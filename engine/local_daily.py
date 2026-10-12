"""Fetch, archive and enrich papers in a private local data directory."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.core.config import load_config as load_sources
from engine.local_llm import LLMClient, LLMError, LocalConfig
from engine.pipeline.fetch import fetch
from engine.render.json import rebuild_index
from engine.translate_papers import ARXIV_ID, translate_recent

logger = logging.getLogger(__name__)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def seed_data(root: Path) -> Path:
    data_dir = root / ".local/data"
    if not data_dir.exists():
        # Use the existing archive for the initial local view, then maintain it independently.
        if (root / "data").exists():
            shutil.copytree(root / "data", data_dir)
        else:
            data_dir.mkdir(parents=True)
    return data_dir


def article_key(article: dict) -> str:
    return (article.get("links") or [{}])[0].get("url", "") or article.get("title", "")


def fingerprint(article: dict, config: LocalConfig) -> str:
    value = [article_key(article), article.get("title"), article.get("content"), config.base_url, config.model, config.full_text, 1]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def run_daily(root: Path, config: LocalConfig, progress=lambda message: None) -> dict:
    """Save fetched papers before calling the model; checkpoint each paper separately."""
    config.validate(ready=True)
    data_dir = seed_data(root)
    now = datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    today = now.astimezone(ZoneInfo("Asia/Hong_Kong")).date()
    sources = load_sources(root / "config/source.yaml", root / "config/preference.yaml",
                           use_embed=False, expired_after=(now - timedelta(days=config.lookback_days)).strftime("%Y/%m/%d %H:%M"))
    progress("正在抓取最近的论文，已有译文和学习笔记会复用…")
    items = fetch(sources)
    day_path = data_dir / f"report-{today}.json"
    reports = {path: json.loads(path.read_text(encoding="utf-8")) for path in sorted(data_dir.glob("report-????-??-??.json"), reverse=True)}
    # Carry prior annotations forward when a paper appears in multiple categories or runs.
    known = {}
    for report in reversed(list(reports.values())):
        for article in report.get("articles", []):
            known[article_key(article)] = article
    report = reports.get(day_path, {"articles": []})
    merged = {article_key(article): article for article in report["articles"]}
    for item in items:
        article = item.to_dict()
        key = article_key(article)
        prior = merged.get(key) or known.get(key, {})
        if prior.get("title") == article["title"] and prior.get("content") == article["content"]:
            if key in known and key not in merged:
                continue # Overlapping fetch windows should not re-list old papers as today's discoveries.
            article = {**prior, **article}
        article["tags"] = list(dict.fromkeys([*prior.get("tags", []), *article.get("tags", [])]))
        merged[key] = article
    report.update(generated_at=now.isoformat(), articles=list(merged.values()), count=len(merged))
    report["subjects"] = list(dict.fromkeys(a["subject"] for a in report["articles"]))
    reports[day_path] = report

    def save_reports():
        for path, value in reports.items():
            write_json(path, value)
        write_json(data_dir / "report.json", report)
        rebuild_index(data_dir)

    save_reports()
    pending = {}
    cutoff = today - timedelta(days=config.lookback_days - 1)
    for path in sorted(reports, reverse=True):
        if path.stem.removeprefix("report-") < cutoff.isoformat():
            continue
        for article in reports[path].get("articles", []):
            if article.get("source") == "arxiv" and article.get("title") and article.get("content") and ARXIV_ID.fullmatch(article_key(article)):
                pending.setdefault(article_key(article), article)
    client = LLMClient(config)
    matching = {}
    for archive in reports.values():
        for other in archive.get("articles", []):
            matching.setdefault(fingerprint(other, config), []).append(other)
    completed = failed = attempted = cached = 0
    errors = []
    stop_processing = False
    for article in pending.values():
        digest = fingerprint(article, config)
        checkpoint_path = root / ".local/llm-cache" / f"{digest}.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
        was_cached = checkpoint.get("complete", False)
        if checkpoint.get("complete"):
            cached += 1
        elif stop_processing or attempted >= config.max_papers_per_run:
            continue
        else:
            attempted += 1
            progress(f"正在处理第 {attempted} 篇：{article['title'][:100]}")
            stage = "标题和摘要翻译"
            try:
                if "title_zh" not in checkpoint:
                    checkpoint.update(client.metadata(article))
                    write_json(checkpoint_path, checkpoint)
                # Save title/abstract immediately, even if a later full-text call fails.
                article.update({key: checkpoint[key] for key in ("title_zh", "content_zh")})
                save_reports()
                paper_id = ARXIV_ID.fullmatch(article_key(article)).group(1)
                paper_path = data_dir / "papers" / f"{paper_id}.json"
                full_text_failed = False
                if config.full_text:
                    stage = "全文翻译"
                    progress(f"正在翻译全文：{checkpoint['title_zh']}")
                    _, failures, _ = translate_recent(data_dir, paper_id=paper_id, lookback_days=31, keep_days=31,
                                                      output_dir=data_dir / "papers", max_minutes=120, translator=client,
                                                      translation_profile=digest, today=today)
                    full_text_failed = bool(failures)
                    if full_text_failed and client.last_error:
                        raise client.last_error
                paper = json.loads(paper_path.read_text(encoding="utf-8")) if config.full_text and paper_path.exists() else {}
                blocks = paper.get("blocks", [])
                source = "\n\n".join(block.get("en", "") for block in blocks)
                basis = "full_text" if source and len(blocks) >= 3 else "abstract"
                if not source:
                    source = article["content"]
                if "study" not in checkpoint or checkpoint["study"].get("basis") != basis:
                    stage = "学习笔记"
                    progress(f"正在整理学习笔记：{checkpoint['title_zh']}")
                    study = client.study(article["title"] + "\n\n" + source,
                                         basis="提取的论文全文文本（不含图片）" if basis == "full_text" else "仅标题和摘要，不能声称已经阅读全文")
                    checkpoint["study"] = {**study, "basis": basis, "model": config.model, "generated_at": datetime.now(timezone.utc).isoformat()}
                # Partial / temporary fetch errors stay retryable; confirmed missing HTML uses abstract notes.
                checkpoint["complete"] = not full_text_failed and paper.get("status") != "partial"
                write_json(checkpoint_path, checkpoint)
                if checkpoint["complete"]:
                    completed += 1
                else:
                    failed += 1
                    errors.append({"paper": article_key(article), "stage": "全文翻译", "message": "全文尚未完成，已保存进度；详见本地日志。"})
            except Exception as error:
                # Upstream client exceptions are sanitized; do not expose raw request/response details.
                message = str(error) if isinstance(error, LLMError) else f"处理失败（{type(error).__name__}），已保存进度"
                errors.append({"paper": article_key(article), "stage": stage, "message": message})
                stop_processing = isinstance(error, LLMError) and error.stop_run
                logger.warning("paper processing failed (%s): %s", type(error).__name__, message)
                progress(message)
                failed += 1
        fields = {key: checkpoint[key] for key in ("title_zh", "content_zh", "study") if key in checkpoint}
        for other in matching.get(digest, []):
            other.update(fields)
        if not was_cached:
            save_reports()
    save_reports()
    result = {"fetched": len(items), "completed": completed, "cached": cached, "failed": failed,
              "remaining": max(0, len(pending) - completed - cached), "api_calls": client.calls, "tokens": client.tokens,
              "errors": errors, "stopped_early": stop_processing}
    progress(f"本轮结束：完成 {completed} 篇，复用 {cached} 篇，失败 {failed} 篇，待处理 {result['remaining']} 篇。"
             + (f"最近错误：{errors[-1]['message']}" if errors else "刷新论文列表即可查看。"))
    return result
