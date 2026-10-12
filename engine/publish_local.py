"""Publish only completed paper results, using an isolated temporary checkout."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from engine.local_daily import article_key, write_json
from engine.render.json import rebuild_index
from engine.translate_papers import ARXIV_ID

ARTICLE_FIELDS = ("title", "content", "published_at", "links", "tags", "subject", "source", "score", "title_zh", "content_zh")
STUDY_FIELDS = ("overview", "problem", "method", "evidence", "limitations", "learning", "basis", "model", "generated_at")


class PublishError(RuntimeError):
    pass


def identity(article: dict) -> tuple:
    return article_key(article), article.get("title", ""), article.get("content", "")


def collect_results(data_dir: Path) -> dict:
    results = {}
    for path in sorted(data_dir.glob("report-????-??-??.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        for article in report.get("articles", []):
            if article.get("source") != "arxiv" or not ARXIV_ID.fullmatch(article_key(article)):
                continue
            if not article.get("title_zh") or not article.get("content_zh") or not article.get("study", {}).get("overview"):
                continue
            clean = {field: article[field] for field in ARTICLE_FIELDS if field in article}
            clean["study"] = {field: article["study"][field] for field in STUDY_FIELDS if field in article["study"]}
            key = identity(article)
            prior = results.get(key)
            if prior and prior["article"]["study"].get("generated_at", "") > clean["study"].get("generated_at", ""):
                continue
            results[key] = {"article": clean, "date": path.stem.removeprefix("report-"), "generated_at": report.get("generated_at", "")}
    return results


def merge_results(data_dir: Path, local_data: Path, results: dict) -> dict:
    """Merge by versioned arXiv URL and source text; preserve every other cloud article."""
    reports = {path: json.loads(path.read_text(encoding="utf-8")) for path in data_dir.glob("report-????-??-??.json")}
    found = set()
    for report in reports.values():
        for article in report.get("articles", []):
            key = identity(article)
            if key in results:
                found.add(key)
                local = results[key]["article"]
                if article.get("study", {}).get("generated_at", "") <= local["study"].get("generated_at", ""):
                    article.update({field: local[field] for field in ("title_zh", "content_zh", "study")})
    for key, item in results.items():
        if key not in found:
            path = data_dir / f"report-{item['date']}.json"
            report = reports.setdefault(path, {"generated_at": item["generated_at"], "articles": []})
            report["articles"].append(item["article"])
    for path, report in reports.items():
        report["count"] = len(report["articles"])
        report["subjects"] = list(dict.fromkeys(a.get("subject", "paper") for a in report["articles"]))
        write_json(path, report)
    if reports:
        write_json(data_dir / "report.json", reports[max(reports)])
    papers = 0
    for item in results.values():
        paper_id = ARXIV_ID.fullmatch(article_key(item["article"])).group(1)
        path = local_data / "papers" / f"{paper_id}.json"
        if not path.exists():
            continue
        paper = json.loads(path.read_text(encoding="utf-8"))
        if paper.get("status") != "complete" or paper.get("id") != paper_id:
            continue
        blocks = paper.get("blocks", [])
        if not blocks or not all(block.get("en") and block.get("zh") for block in blocks):
            continue
        if not any(str(block.get("translation_engine", "")).startswith("llm:") for block in blocks):
            continue
        published_at = item["article"]["study"].get("generated_at", "")
        target = data_dir / "papers" / f"{paper_id}.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("local_study_at", "") > published_at:
                continue
        clean = {
            "id": paper_id, "archive_date": item["date"], "status": "complete",
            "source_url": f"https://arxiv.org/html/{paper_id}", "published_from": "local-llm",
            "local_study_at": published_at,
            "blocks": [{key: block[key] for key in ("type", "en", "zh", "translation_engine") if key in block} for block in blocks],
        }
        write_json(target, clean)
        papers += 1
    rebuild_index(data_dir)
    return {"notes": len(results), "full_papers": papers}


def git(root: Path, *args: str, check=True) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3")
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise PublishError("GitHub 同步超时或 Git 不可用，本地结果仍已保留") from None
    if check and result.returncode:
        # Do not expose remote URLs or credential-helper output to the browser/logs.
        raise PublishError("GitHub 同步失败，请检查网络、origin 地址和本机 Git 的推送权限")
    return result


def publish_local(root: Path, *, tokens=(), progress=lambda message: None) -> dict:
    local_data = root / ".local/data"
    results = collect_results(local_data)
    if not results:
        progress("还没有完成的大模型学习笔记；完成一次本地任务后即可发布。")
        return {"notes": 0, "full_papers": 0, "changed": False}
    worktree = None
    with tempfile.TemporaryDirectory(prefix="publish-", dir=root / ".local") as temporary:
        checkout = Path(temporary) / "checkout"
        try:
            for attempt in range(3):
                progress("正在同步 GitHub，并合并本地译文与学习笔记…")
                git(root, "fetch", "origin", "main")
                if worktree is None:
                    git(root, "worktree", "add", "--detach", str(checkout), "origin/main")
                    worktree = checkout
                else:
                    # Only our disposable checkout is reset. User files and local results are untouched.
                    git(checkout, "reset", "--hard", "origin/main")
                counts = merge_results(checkout / "data", local_data, results)
                git(checkout, "add", "--", "data")
                names = git(checkout, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
                names = [name for name in names if name]
                for name in names:
                    if not name.startswith("data/") or not name.endswith(".json"):
                        raise PublishError("发布包含非论文文件，已停止")
                    content = (checkout / name).read_text(encoding="utf-8")
                    if any(token and token in content for token in tokens):
                        raise PublishError("检测到发布内容包含访问令牌，已停止；请检查模型输出")
                if not names:
                    progress("GitHub 已有这些译文与笔记，无需重复上传。")
                    return {**counts, "changed": False}
                git(checkout, "-c", "user.name=Scholar Tide", "-c", "user.email=scholar-tide@users.noreply.github.com",
                    "commit", "-m", "build: publish local LLM translations and study notes")
                pushed = git(checkout, "push", "origin", "HEAD:main", check=False)
                if pushed.returncode == 0:
                    commit = git(checkout, "rev-parse", "HEAD").stdout.strip()
                    progress(f"已发布 {counts['notes']} 篇学习笔记、{counts['full_papers']} 篇全文译文。GitHub Pages 部署完成后，手机即可访问。")
                    return {**counts, "changed": True, "commit": commit}
                progress(f"远端可能有新提交，正在重新合并（{attempt + 1}/3）…")
            raise PublishError("推送未成功，本地结果已保留；请检查权限或稍后再次发布")
        finally:
            if worktree is not None:
                git(root, "worktree", "remove", "--force", str(worktree), check=False)
