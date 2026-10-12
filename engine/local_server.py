"""Loopback-only settings, live data serving and the daily local scheduler."""
from __future__ import annotations

import fcntl
import json
import logging
import mimetypes
import secrets
import threading
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from engine.local_daily import run_daily, seed_data, write_json
from engine.local_llm import LocalConfig, load_config, save_config

logger = logging.getLogger(__name__)
ZONE = ZoneInfo("Asia/Hong_Kong")


class LocalService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.config_path = self.root / "config/llm.local.yaml"
        if not self.config_path.exists():
            save_config(self.config_path, LocalConfig())
        self.data_dir = seed_data(self.root)
        self.status_path = self.root / ".local/status.json"
        self.schedule_path = self.root / ".local/schedule.json"
        self.guard = threading.Lock()
        self.stop = threading.Event()
        self.status = {"running": False, "message": "填写并保存配置后，可立即运行或开启每日定时。"}
        if self.status_path.exists():
            self.status.update(json.loads(self.status_path.read_text(encoding="utf-8")))
            if self.status.get("running"):
                self.status.update(running=False, message="上次任务中途退出；再次运行会复用已保存的进度。")

    def config(self):
        return load_config(self.config_path)

    def progress(self, message):
        self.status["message"] = message
        write_json(self.status_path, self.status)
        logger.info(message)

    def start_run(self, *, publish_only=False):
        config = self.config()
        config.validate(ready=not publish_only)
        with self.guard:
            if self.status["running"]:
                return False
            lock = (self.root / ".local/run.lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                raise ValueError("另一个本地进程正在运行任务，请等待其完成") from None
            self.status = {"running": True, "operation": "publish" if publish_only else "daily", "started_at": datetime.now(ZONE).isoformat(), "message": "任务已开始"}
            write_json(self.status_path, self.status)
            now = datetime.now(ZONE)
            if not publish_only and config.enabled and now.strftime("%H:%M") >= config.daily_time:
                # A manual run after today's deadline also satisfies today's scheduled run.
                write_json(self.schedule_path, {"last_attempt": now.strftime("%Y-%m-%d")})

        def work():
            from engine.publish_local import PublishError, publish_local
            try:
                if not publish_only:
                    result = run_daily(self.root, config, self.progress)
                    self.status.update(result=result, outcome="partial" if result["failed"] or result["remaining"] else "complete")
                if publish_only or config.auto_publish:
                    published = publish_local(self.root, tokens=(config.token, config.access_token), progress=self.progress)
                    self.status["publication"] = published
                    if publish_only:
                        self.status["outcome"] = "complete"
            except PublishError as error:
                self.status.update(outcome="publish_failed", message=str(error))
            except Exception as error:
                self.status.update(outcome="failed", message=f"任务未完成（{type(error).__name__}），已保存的数据会在下次运行时复用。")
                logger.error("local daily job failed (%s)", type(error).__name__)
            finally:
                self.status.update(running=False, finished_at=datetime.now(ZONE).isoformat())
                write_json(self.status_path, self.status)
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()

        worker = threading.Thread(target=work, daemon=True, name="local-daily")
        worker.start()
        return True

    def schedule_tick(self, now: datetime):
        config = self.config()
        if not config.enabled or self.status["running"]:
            return
        last = json.loads(self.schedule_path.read_text()) if self.schedule_path.exists() else {}
        day = now.strftime("%Y-%m-%d")
        if now.strftime("%H:%M") >= config.daily_time and last.get("last_attempt", "") < day:
            if self.start_run():
                write_json(self.schedule_path, {"last_attempt": day})

    def scheduler(self):
        while not self.stop.is_set():
            try:
                self.schedule_tick(datetime.now(ZONE))
            except (ValueError, TypeError, OSError):
                logger.warning("local schedule could not start; check local configuration")
            self.stop.wait(5)


def make_handler(service: LocalService):
    csrf_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def reply(self, code, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "仅允许本机访问"})
            route = unquote(urlsplit(self.path).path)
            if route == "/api/local/config":
                try:
                    return self.reply(200, {"config": service.config().public(), "status": service.status, "csrf_token": csrf_token})
                except (ValueError, TypeError):
                    return self.reply(400, {"error": "本地 YAML 配置无效，请检查 config/llm.local.yaml"})
            if route.startswith("/api/"):
                return self.reply(404, {"error": "未找到接口"})
            root = service.data_dir if route.startswith("/data/") else service.root / "frontend"
            relative = route.removeprefix("/data/") if route.startswith("/data/") else route.lstrip("/") or "index.html"
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or path.suffix not in {".html", ".js", ".css", ".json", ".svg", ".png", ".ico"} or not path.is_file():
                return self.reply(404, {"error": "未找到文件"})
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self.valid_host() or self.headers.get("X-Scholar-Token") != csrf_token:
                return self.reply(403, {"error": "请从本地设置页面操作"})
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return self.reply(403, {"error": "不接受跨站请求"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 16384:
                    raise ValueError("请求内容过长")
                payload = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/api/local/config":
                    current = asdict(service.config())
                    if not isinstance(payload, dict) or set(payload) - set(current) - {"clear_token"}:
                        raise ValueError("配置字段无效")
                    # Blank means keep the saved key. Clearing requires an explicit choice.
                    if payload.pop("clear_token", False):
                        current["access_token"] = ""
                    if not payload.get("access_token"):
                        payload.pop("access_token", None)
                    current.update(payload)
                    updated = LocalConfig(**current)
                    save_config(service.config_path, updated)
                    return self.reply(200, {"config": updated.public()})
                if self.path == "/api/local/run":
                    started = service.start_run()
                    return self.reply(202 if started else 200, {"started": started, "status": service.status})
                if self.path == "/api/local/publish":
                    started = service.start_run(publish_only=True)
                    return self.reply(202 if started else 200, {"started": started, "status": service.status})
                return self.reply(404, {"error": "未找到接口"})
            except (ValueError, TypeError):
                return self.reply(400, {"error": "请检查接口地址、模型、Token、时间和数量；启用定时前须填写有效配置。"})

        def log_message(self, format, *args):
            # Never log arbitrary URLs that could contain a token entered by mistake.
            pass

    return Handler


def serve_local(root: Path, port: int):
    service = LocalService(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(service))
    threading.Thread(target=service.scheduler, daemon=True, name="local-scheduler").start()
    print(f"本地设置：http://127.0.0.1:{port}/local-settings.html", flush=True)
    print("每日定时采用香港时间；请保持此进程运行。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop.set()
        server.server_close()
