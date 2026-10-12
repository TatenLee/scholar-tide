import json
import logging
import stat
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from engine.core.type import InfoItem, Link
from engine.local_daily import run_daily, write_json
from engine.local_llm import LLMClient, LLMError, LocalConfig, load_config, save_config
from engine.local_server import LocalService, ZONE, make_handler
from engine.local_logging import configure_logging


def config(**kwargs):
    return LocalConfig(base_url="http://localhost:11434/v1", model="test-model", **kwargs)


def study():
    return {"overview": "研究概述", "problem": "研究问题", "method": "核心方法", "evidence": "实验依据",
            "limitations": "需要核查的局限", "learning": ["如何复现？"]}


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "config/source.yaml").write_text("sources: []\n")
        (self.root / "config/preference.yaml").write_text("{}\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_private_config_and_validation(self):
        path = self.root / "config/llm.local.yaml"
        save_config(path, config(access_token="test-secret"))
        loaded = load_config(path)
        self.assertEqual(loaded.access_token, "test-secret")
        self.assertNotIn("test-secret", repr(loaded))
        self.assertNotIn("access_token", loaded.public())
        self.assertTrue(loaded.public()["has_token"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(ValueError):
            LocalConfig(base_url="https://user:pass@example.com/v1").validate()
        with self.assertRaises(ValueError):
            config(daily_time="25:00").validate()

    def test_transport_does_not_log_provider_secrets(self):
        client = LLMClient(config(access_token="test-secret"))
        reply = Mock(status_code=200)
        reply.json.return_value = {"choices": [{"message": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}], "usage": {"total_tokens": 12}}
        client.session.post = Mock(return_value=reply)
        self.assertEqual(client.json("instruction", "source"), {"answer": "ok"})
        args, kwargs = client.session.post.call_args
        self.assertEqual(args[0], "http://localhost:11434/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(client.tokens, 12)
        reply.status_code = 401
        reply.text = "test-secret reflected by upstream"
        with self.assertRaises(LLMError) as caught:
            client.json("instruction", "source")
        self.assertNotIn("test-secret", str(caught.exception))

    def test_paragraph_batching_preserves_alignment_and_checks_count(self):
        client = LLMClient(config())
        batches = []
        def answer(instruction, texts):
            batches.append(texts)
            return {"translations": ["中" + text for text in texts]}
        client.json = answer
        translated = client.translate_many(["first", "second", "x" * 4100])
        self.assertEqual(batches[0], ["first", "second"])
        self.assertEqual(len(translated), 3)
        self.assertEqual(translated[2][0], "中" + "x" * 4000 + "中" + "x" * 100)
        client.json = lambda *args: {"translations": []}
        with self.assertRaises(LLMError):
            client.translate_many(["first"])

    def test_provider_error_is_visible_redacted_and_restriction_not_retried(self):
        client = LLMClient(config(access_token="private-secret"))
        reply = Mock(status_code=500)
        reply.json.return_value = {"error": {"type": "internal_error", "message": "当前仅允许官方CodeX客户端使用 private-secret Bearer other-secret"}}
        client.session.post = Mock(return_value=reply)
        with self.assertLogs("engine.local_llm", level="INFO") as logs, self.assertRaises(LLMError) as caught:
            client.json("instruction", "private paper text")
        self.assertTrue(caught.exception.stop_run)
        self.assertEqual(client.session.post.call_count, 1)
        self.assertIn("当前仅允许官方CodeX客户端使用", str(caught.exception))
        self.assertIn("HTTP 500", str(caught.exception))
        output = str(caught.exception) + str(logs.output)
        for secret in ("private-secret", "other-secret", "private paper text"):
            self.assertNotIn(secret, output)
        reply.status_code = 502
        reply.json.side_effect = ValueError
        with self.assertRaises(LLMError):
            client.json("instruction", "source", test=True)
        self.assertEqual(client.session.post.call_count, 2)

    def test_file_logs_redact_tracebacks_and_remain_private_after_rotation(self):
        save_config(self.root / "config/llm.local.yaml", config(access_token="private-secret"))
        root_logger = logging.getLogger()
        old_handlers, old_level = list(root_logger.handlers), root_logger.level
        old_formatters = [handler.formatter for handler in old_handlers]
        path = configure_logging(self.root)
        handler = root_logger.handlers[-1]
        try:
            try:
                raise RuntimeError("echo private-secret Bearer another-secret")
            except RuntimeError:
                logging.getLogger("engine.local_llm").exception("diagnostic")
            handler.doRollover()
            logging.getLogger("engine.local_llm").warning("second private-secret")
            for log in path.parent.glob("service.log*"):
                text = log.read_text()
                self.assertNotIn("private-secret", text)
                self.assertNotIn("another-secret", text)
                self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
        finally:
            root_logger.removeHandler(handler)
            handler.close()
            root_logger.setLevel(old_level)
            for old, formatter in zip(old_handlers, old_formatters):
                old.setFormatter(formatter)

    def test_test_operation_surfaces_error_without_fetch_publish_or_schedule(self):
        service = LocalService(self.root)
        save_config(service.config_path, config(enabled=True, auto_publish=True))
        with patch.object(LLMClient, "json", side_effect=LLMError("HTTP 500: 客户端限制")), patch("engine.local_server.run_daily") as daily, patch("engine.publish_local.publish_local") as publish:
            self.assertTrue(service.start_run(test_only=True))
            deadline = time.monotonic() + 5
            while service.status["running"] and time.monotonic() < deadline:
                time.sleep(0.01)
            service.worker.join(timeout=5)
            self.assertFalse(service.status["running"])
            self.assertEqual(service.status["error"], "HTTP 500: 客户端限制")
            self.assertFalse(service.schedule_path.exists())
            daily.assert_not_called()
            publish.assert_not_called()

    def test_daily_stops_on_bad_credentials_and_publication_preserves_error(self):
        items = [InfoItem(f"Paper {n}", "Abstract", datetime.now(timezone.utc),
                         [Link("arxiv", f"https://arxiv.org/abs/2610.0000{n}v1")], source="arxiv", subject="paper") for n in (1, 2)]
        with patch("engine.local_daily.fetch", return_value=items), patch.object(LLMClient, "metadata", side_effect=LLMError("HTTP 401: invalid key", stop_run=True)) as metadata:
            result = run_daily(self.root, config())
            self.assertEqual(metadata.call_count, 1)
            self.assertEqual(result["remaining"], 2)
            self.assertTrue(result["stopped_early"])
            self.assertEqual(result["errors"][0]["stage"], "标题和摘要翻译")
        service = LocalService(self.root)
        save_config(service.config_path, config(auto_publish=True))
        def publish(root, *, tokens, progress):
            progress("没有完成的笔记可发布")
            return {"notes": 0}
        with patch("engine.local_server.run_daily", return_value=result), patch("engine.publish_local.publish_local", side_effect=publish):
            service.start_run()
            deadline = time.monotonic() + 5
            while service.status["running"] and time.monotonic() < deadline:
                time.sleep(0.01)
            service.worker.join(timeout=5)
            self.assertFalse(service.status["running"])
            self.assertIn("HTTP 401", service.status["message"])
            self.assertEqual(service.status["outcome"], "partial")

    def test_daily_preserves_fetch_and_resumes_after_summary_failure(self):
        item = InfoItem("A paper", "An abstract", datetime.now(timezone.utc),
                        [Link("arxiv", "https://arxiv.org/abs/2610.00001v1")], source="arxiv", subject="paper")
        html = '<article class="ltx_document"><section class="ltx_section"><h2 class="ltx_title_section">Introduction</h2><div class="ltx_para">A method with evidence.</div></section></article>'
        response = Mock(status_code=200, text=html)
        metadata_calls = []
        fail_summary = [True]
        def model(client, instruction, source):
            if "title_zh" in instruction:
                metadata_calls.append(source)
                return {"title_zh": "论文标题", "content_zh": "中文摘要"}
            if "translations" in instruction:
                return {"translations": ["译文：" + text for text in source]}
            if fail_summary[0]:
                fail_summary[0] = False
                raise LLMError("temporary failure")
            return study()
        with patch("engine.local_daily.fetch", return_value=[item, item]), patch.object(LLMClient, "json", model), patch("requests.Session.get", return_value=response) as download:
            first = run_daily(self.root, config())
            self.assertEqual(first["failed"], 1)
            report_path = self.root / ".local/data/report.json"
            first_report = json.loads(report_path.read_text())
            self.assertEqual(first_report["count"], 1)
            self.assertEqual(first_report["articles"][0]["title_zh"], "论文标题")
            second = run_daily(self.root, config())
            self.assertEqual(second["completed"], 1)
            self.assertEqual(len(metadata_calls), 1)
            self.assertEqual(download.call_count, 1)
            paper = json.loads((self.root / ".local/data/papers/2610.00001v1.json").read_text())
            self.assertEqual(paper["status"], "complete")
            self.assertTrue(any(block.get("translation_engine") == "llm:test-model" for block in paper["blocks"]))
            final = json.loads(report_path.read_text())["articles"][0]
            self.assertEqual(final["study"]["basis"], "full_text")
            third = run_daily(self.root, config())
            self.assertEqual(third["cached"], 1)
            self.assertEqual(third["completed"], 0)
            changed = run_daily(self.root, replace(config(), model="another-model"))
            self.assertEqual(changed["completed"], 1)
            refreshed = json.loads((self.root / ".local/data/papers/2610.00001v1.json").read_text())
            self.assertTrue(all(block.get("translation_engine") == "llm:another-model" for block in refreshed["blocks"]))
            self.assertEqual(download.call_count, 1)

    def test_limit_keeps_a_queue_and_completed_papers_do_not_consume_limit(self):
        items = [InfoItem(f"Paper {number}", "Abstract", datetime.now(timezone.utc),
                          [Link("arxiv", f"https://arxiv.org/abs/2610.0000{number}v1")], source="arxiv", subject="paper") for number in (1, 2)]
        with patch("engine.local_daily.fetch", return_value=items), patch.object(LLMClient, "metadata", return_value={"title_zh": "标题", "content_zh": "摘要"}), patch.object(LLMClient, "study", return_value=study()):
            first = run_daily(self.root, config(full_text=False, max_papers_per_run=1))
            self.assertEqual((first["completed"], first["remaining"]), (1, 1))
            second = run_daily(self.root, config(full_text=False, max_papers_per_run=1))
            self.assertEqual((second["completed"], second["cached"], second["remaining"]), (1, 1, 0))

    def test_long_summary_includes_end_of_paper(self):
        client = LLMClient(config())
        sources = []
        def answer(instruction, source):
            sources.append(source)
            return study()
        client.json = answer
        client.study("A" * 12000 + "B" * 12000 + "THE_END", basis="full text")
        self.assertIn("THE_END", sources)
        self.assertTrue(any(isinstance(source, list) and len(source) == 3 for source in sources))

    def test_abstract_basis_and_no_rediscovery_of_old_papers(self):
        item = InfoItem("Earlier paper", "Abstract only", datetime.now(timezone.utc),
                        [Link("arxiv", "https://arxiv.org/abs/2610.00002v1")], source="arxiv", subject="paper")
        yesterday = datetime.now(ZONE).date() - timedelta(days=1)
        write_json(self.root / "data" / f"report-{yesterday}.json", {"articles": [item.to_dict()]})
        with patch("engine.local_daily.fetch", return_value=[item]), patch.object(LLMClient, "metadata", return_value={"title_zh": "旧论文", "content_zh": "摘要"}), patch.object(LLMClient, "study", return_value=study()), patch("engine.local_daily.translate_recent") as full:
            result = run_daily(self.root, config(full_text=False))
            self.assertEqual(result["completed"], 1)
            self.assertFalse(full.called)
            latest = json.loads((self.root / ".local/data/report.json").read_text())
            self.assertEqual(latest["count"], 0)
            prior = json.loads((self.root / ".local/data" / f"report-{yesterday}.json").read_text())
            self.assertEqual(prior["articles"][0]["study"]["basis"], "abstract")

    def test_http_config_is_masked_and_posts_are_protected(self):
        service = LocalService(self.root)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            data = requests.get(url + "/api/local/config", timeout=5).json()
            payload = {"access_token": "private-token", "model": "test-model", "base_url": "https://example.com/v1"}
            self.assertEqual(requests.post(url + "/api/local/config", json=payload, timeout=5).status_code, 403)
            headers = {"X-Scholar-Token": data["csrf_token"]}
            response = requests.post(url + "/api/local/config", json=payload, headers=headers, timeout=5)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("private-token", response.text)
            self.assertNotIn("private-token", requests.get(url + "/api/local/config", timeout=5).text)
            self.assertEqual(requests.get(url + "/config/llm.local.yaml", timeout=5).status_code, 404)
            self.assertEqual(requests.get(url + "/api/local/config", headers={"Host": "evil.example"}, timeout=5).status_code, 403)
            self.assertEqual(requests.post(url + "/api/local/config", json={}, headers={**headers, "Origin": "https://evil.example"}, timeout=5).status_code, 403)
            requests.post(url + "/api/local/config", json={"access_token": ""}, headers=headers, timeout=5)
            self.assertEqual(service.config().access_token, "private-token")
        finally:
            server.shutdown()
            server.server_close()

    def test_schedule_runs_once_per_day_and_catches_up(self):
        service = LocalService(self.root)
        save_config(service.config_path, config(enabled=True))
        with patch.object(service, "start_run", return_value=True) as start:
            service.schedule_tick(datetime(2026, 10, 12, 13, 29, tzinfo=ZONE))
            self.assertEqual(start.call_count, 0)
            service.schedule_tick(datetime(2026, 10, 12, 15, 0, tzinfo=ZONE))
            service.schedule_tick(datetime(2026, 10, 12, 18, 0, tzinfo=ZONE))
            self.assertEqual(start.call_count, 1)
            service.schedule_tick(datetime(2026, 10, 13, 15, 0, tzinfo=ZONE))
            self.assertEqual(start.call_count, 2)


if __name__ == "__main__":
    unittest.main()
