"""Pretranslate recent arXiv HTML papers for the static bilingual reader."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

from engine.translate_archive import _argos_translator
from engine.translation_api import ApiFirstTranslator

logger = logging.getLogger(__name__)
ARXIV_ID = re.compile(r"^https://arxiv\.org/abs/([\w.\-]+)$")
SKIP_CLASSES = {"ltx_bibliography", "ltx_authors", "ltx_acknowledgements"}


def _write_json(path: Path, payload: dict) -> None:
    """Keep a usable checkpoint if a runner stops during a later write."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def extract_blocks(markup: str, abstract_zh: str = "", abstract_en: str = "") -> list[dict[str, str]]:
    article = BeautifulSoup(markup, "html.parser").select_one("article.ltx_document")
    if not article:
        return []
    blocks = []
    if abstract_zh:
        if not abstract_en:
            abstract = article.select_one(".ltx_abstract")
            if abstract:
                abstract_en = re.sub(r"^Abstract\s*", "", " ".join(abstract.stripped_strings), flags=re.I).strip()
        blocks.extend([
            {"type": "heading", "en": "Abstract", "zh": "摘要"},
            {"type": "paragraph", "en": abstract_en, "zh": abstract_zh},
        ])
    else:
        abstract = article.select_one(".ltx_abstract")
        if abstract:
            text = " ".join(abstract.stripped_strings)
            text = re.sub(r"^Abstract\s*", "", text, flags=re.I).strip()
            if text:
                blocks.extend([{"type": "heading", "text": "Abstract"}, {"type": "paragraph", "text": text}])

    for node in article.select(".ltx_title_section, .ltx_title_subsection, .ltx_title_subsubsection, .ltx_title_appendix, .ltx_caption, .ltx_para"):
        if any(SKIP_CLASSES.intersection(parent.get("class", [])) for parent in node.parents if isinstance(parent, Tag)):
            continue
        is_paragraph = "ltx_para" in node.get("class", [])
        if is_paragraph and any("ltx_caption" in parent.get("class", []) for parent in node.parents if isinstance(parent, Tag)):
            continue
        if is_paragraph and not any({"ltx_section", "ltx_appendix"}.intersection(parent.get("class", [])) for parent in node.parents if isinstance(parent, Tag)):
            continue
        text = " ".join(node.stripped_strings)
        if len(text) > 2:
            blocks.append({"type": "paragraph" if is_paragraph or "ltx_caption" in node.get("class", []) else "heading", "text": text})
    return blocks


def recent_articles(data_dir: Path, days: int) -> list[tuple[str, dict]]:
    reports = sorted(data_dir.glob("report-????-??-??.json"), reverse=True)[:days]
    seen = set()
    articles = []
    for path in reports:
        archive_date = path.stem.removeprefix("report-")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for article in payload.get("articles", []):
            if article.get("source") != "arxiv":
                continue
            link = (article.get("links") or [{}])[0].get("url", "")
            match = ARXIV_ID.fullmatch(link)
            if match and match.group(1) not in seen:
                seen.add(match.group(1))
                articles.append((archive_date, article))
    return articles


def prune(papers_dir: Path, *, keep_days: int, max_bytes: int, today: date) -> int:
    cutoff = today - timedelta(days=keep_days - 1)
    files = []
    removed = 0
    for path in papers_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            paper_date = date.fromisoformat(payload["archive_date"])
        except (OSError, ValueError, KeyError):
            paper_date = date.min
        if paper_date < cutoff:
            path.unlink()
            removed += 1
        else:
            files.append((paper_date, path))
    total = sum(path.stat().st_size for _, path in files)
    for _, path in sorted(files):
        if total <= max_bytes:
            break
        size = path.stat().st_size
        path.unlink()
        total -= size
        removed += 1
    return removed


def translate_recent(
    data_dir: Path,
    *,
    paper_id: str | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
    output_dir: Path | None = None,
    lookback_days: int = 21,
    keep_days: int = 21,
    max_megabytes: int = 256,
    max_minutes: int = 300,
    limit: int | None = None,
    translator=None,
    fetch_html=None,
    request_delay: float = 3.0,
    today: date | None = None,
) -> tuple[int, int, int]:
    """Return translated, failed, and pruned counts. Save each finished paper immediately."""
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("shard index must be between 0 and shard count - 1")
    papers_dir = data_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    target_dir = output_dir or papers_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    pruned = 0 if output_dir else prune(papers_dir, keep_days=keep_days, max_bytes=max_megabytes * 1024 * 1024, today=today)
    cutoff = today - timedelta(days=keep_days - 1)
    articles = [(d, a) for d, a in recent_articles(data_dir, lookback_days) if date.fromisoformat(d) >= cutoff]
    if paper_id:
        articles = [(d, a) for d, a in articles if ARXIV_ID.fullmatch(a["links"][0]["url"]).group(1) == paper_id]
        if not articles:
            raise ValueError(f"arXiv ID {paper_id} was not found in the recent reports")
    articles = [
        (d, a) for d, a in articles
        if int(hashlib.sha256(ARXIV_ID.fullmatch(a["links"][0]["url"]).group(1).encode()).hexdigest(), 16) % shard_count == shard_index
    ]
    if limit is not None:
        articles = articles[:limit]
    pending = []
    for archive_date, article in articles:
        paper_id = ARXIV_ID.fullmatch(article["links"][0]["url"]).group(1)
        path = target_dir / f"{paper_id}.json"
        existing_path = path if path.exists() else papers_dir / f"{paper_id}.json"
        checkpoint = None
        if existing_path.exists():
            payload = json.loads(existing_path.read_text(encoding="utf-8"))
            if payload.get("archive_date", "") < archive_date:
                payload["archive_date"] = archive_date
                _write_json(path, payload)
            state = payload.get("status")
            if state == "partial":
                checkpoint = payload
            elif state != "unavailable":
                continue
            elif date.fromisoformat(payload.get("checked_at", "0001-01-01")) > today - timedelta(days=7):
                continue
        pending.append((archive_date, article, paper_id, path, checkpoint))
    if not pending:
        return 0, 0, pruned
    if translator is None:
        translator = ApiFirstTranslator.from_environment(
            lambda: _argos_translator(Path.home() / ".cache/scholar-tide/models")
        )
    session = requests.Session()
    session.headers.update({"User-Agent": "ScholarTide/1.0 (+https://github.com/TatenLee/scholar-tide)"})
    fetch_html = fetch_html or (lambda paper_id: session.get(f"https://arxiv.org/html/{paper_id}", timeout=30))
    started = time.monotonic()
    last_fetch = 0.0
    translated = failed = 0
    for index, (archive_date, article, paper_id, path, checkpoint) in enumerate(pending, 1):
        if time.monotonic() - started >= max_minutes * 60:
            logger.info("time budget reached; %d papers remain", len(pending) - index + 1)
            break
        blocks = []
        try:
            if checkpoint and isinstance(checkpoint.get("blocks"), list) and len(checkpoint["blocks"]) >= 3 and all(block.get("en") for block in checkpoint["blocks"]):
                blocks = checkpoint["blocks"]
                logger.info("resuming %s at %d/%d blocks", paper_id, sum(bool(block.get("zh")) for block in blocks), len(blocks))
            else:
                delay = request_delay - (time.monotonic() - last_fetch)
                if delay > 0:
                    time.sleep(delay)
                last_fetch = time.monotonic()
                response = fetch_html(paper_id)
                if response.status_code == 404:
                    _write_json(path, {"id": paper_id, "archive_date": archive_date, "status": "unavailable", "checked_at": today.isoformat()})
                    logger.info("HTML unavailable for %s", paper_id)
                    continue
                response.raise_for_status()
                blocks = extract_blocks(response.text, article.get("content_zh", ""), article.get("content", ""))
                if len(blocks) < 3:
                    _write_json(path, {"id": paper_id, "archive_date": archive_date, "status": "unavailable", "checked_at": today.isoformat()})
                    logger.info("HTML body unavailable for %s", paper_id)
                    continue
                for block in blocks:
                    if "text" in block:
                        block["en"] = block.pop("text")
                if any(not block.get("en") for block in blocks):
                    raise ValueError("empty English source block")
            payload = {
                "id": paper_id,
                "archive_date": archive_date,
                "source_url": f"https://arxiv.org/html/{paper_id}",
                "status": "partial",
                "blocks": blocks,
            }
            _write_json(path, payload)
            budget_reached = False
            for block_number, block in enumerate(blocks, 1):
                if block.get("zh"):
                    continue
                if time.monotonic() - started >= max_minutes * 60:
                    budget_reached = True
                    break
                batch_indices = [block_number - 1]
                batch_chars = len(block["en"])
                for next_index in range(block_number, len(blocks)):
                    next_block = blocks[next_index]
                    if next_block.get("zh") or len(batch_indices) >= 12 or batch_chars + len(next_block["en"]) > 4_000:
                        break
                    batch_indices.append(next_index)
                    batch_chars += len(next_block["en"])
                texts = [blocks[block_index]["en"] for block_index in batch_indices]
                if hasattr(translator, "translate_many"):
                    results = translator.translate_many(texts)
                else:
                    results = [(translator(text), "local") for text in texts]
                if len(results) != len(batch_indices) or any(not result[0] for result in results):
                    raise ValueError("incomplete translation batch")
                for block_index, (translated_text, engine) in zip(batch_indices, results):
                    blocks[block_index]["zh"] = translated_text
                    blocks[block_index]["translation_engine"] = engine
                _write_json(path, payload)
                if (block_number + len(batch_indices) - 1) // 20 > (block_number - 1) // 20:
                    logger.info("%s: translated %d/%d blocks", paper_id, block_number + len(batch_indices) - 1, len(blocks))
            if budget_reached:
                _write_json(path, payload)
                logger.info("time budget reached during %s at %d/%d blocks", paper_id, sum(bool(block.get("zh")) for block in blocks), len(blocks))
                break
            payload["status"] = "complete"
            _write_json(path, payload)
            translated += 1
            logger.info("translated %d/%d: %s (%d blocks)", index, len(pending), paper_id, len(blocks))
        except Exception:
            if blocks and all(block.get("en") for block in blocks):
                _write_json(path, {"id": paper_id, "archive_date": archive_date, "source_url": f"https://arxiv.org/html/{paper_id}", "status": "partial", "blocks": blocks})
            failed += 1
            logger.exception("could not translate full paper %s", paper_id)
    if not output_dir:
        pruned += prune(papers_dir, keep_days=keep_days, max_bytes=max_megabytes * 1024 * 1024, today=today)
    return translated, failed, pruned


def main() -> None:
    parser = argparse.ArgumentParser(description="Nightly full-paper translation")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--id", dest="paper_id", help="Translate a single arXiv ID immediately")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, help="Write only new papers here for a parallel job")
    parser.add_argument("--lookback-days", type=int, default=21)
    parser.add_argument("--keep-days", type=int, default=21)
    parser.add_argument("--max-megabytes", type=int, default=256)
    parser.add_argument("--max-minutes", type=int, default=300)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    count, failures, pruned = translate_recent(**vars(args))
    logger.info("full papers: translated %d, failed %d, pruned %d", count, failures, pruned)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
