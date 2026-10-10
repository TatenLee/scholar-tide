"""Pretranslate the latest arXiv titles and abstracts for the static site.

This runs in GitHub Actions after the daily build. The translation model runs on
the Actions runner; no API key or translation service is exposed in the site.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

from engine.core.util import to_beijing
from engine.render.json import rebuild_index

logger = logging.getLogger(__name__)
MODEL_URL = "https://argos-net.com/v1/translate-en_zh-1_9.argosmodel"
MODEL_FILENAME = "translate-en_zh-1_9.argosmodel"
MODEL_SHA256 = "433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(article: dict) -> tuple[str, str, str]:
    links = article.get("links") or []
    url = links[0].get("url", "") if links else ""
    return url, article.get("title", ""), article.get("content", "")


def _existing_translations(data_dir: Path) -> dict[tuple[str, str, str], tuple[str, str]]:
    cache = {}
    for path in data_dir.glob("report-????-??-??.json"):
        try:
            articles = json.loads(path.read_text(encoding="utf-8")).get("articles", [])
        except (OSError, ValueError):
            continue
        for article in articles:
            if article.get("title_zh") and article.get("content_zh"):
                cache[_key(article)] = article["title_zh"], article["content_zh"]
    return cache


def _argos_translator(model_dir: Path) -> Callable[[str], str]:
    from argostranslate import package, translate

    installed = any(
        item.from_code == "en" and item.to_code == "zh"
        for item in package.get_installed_packages()
    )
    if not installed:
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / MODEL_FILENAME
        if not model_path.exists():
            logger.info("downloading English-Chinese model to %s", model_path)
            temporary = model_path.with_suffix(".part")
            request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "ScholarTide/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(model_path)
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise ValueError("offline translation model checksum mismatch")
        package.install_from_path(model_path)
    english = next(lang for lang in translate.get_installed_languages() if lang.code == "en")
    chinese = next(lang for lang in translate.get_installed_languages() if lang.code == "zh")
    return english.get_translation(chinese).translate


def translate_latest(
    data_dir: Path,
    translator: Callable[[str], str] | None = None,
    *,
    limit: int | None = None,
) -> tuple[int, int]:
    latest_path = data_dir / "report.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(payload["generated_at"])
    daily_path = data_dir / f"report-{to_beijing(generated_at):%Y-%m-%d}.json"
    cache = _existing_translations(data_dir)
    pending = [
        article for article in payload.get("articles", [])
        if article.get("source") == "arxiv" and article.get("title") and article.get("content")
    ]
    if limit is not None:
        pending = pending[:limit]
    translated_count = 0
    failures = 0
    if translator is None and any(_key(article) not in cache for article in pending):
        translator = _argos_translator(Path.home() / ".cache/scholar-tide/models")

    for index, article in enumerate(pending, 1):
        prior = cache.get(_key(article))
        if prior:
            article["title_zh"], article["content_zh"] = prior
            continue
        try:
            assert translator is not None
            title_zh = translator(article["title"])
            content_zh = translator(article["content"])
            if not title_zh or not content_zh:
                raise ValueError("empty translation")
            article["title_zh"] = title_zh
            article["content_zh"] = content_zh
            cache[_key(article)] = title_zh, content_zh
            translated_count += 1
            logger.info("translated %d/%d: %s", index, len(pending), article["title"][:80])
        except Exception:
            failures += 1
            logger.exception("could not translate %s", article["title"][:80])

    _write_json(latest_path, payload)
    _write_json(daily_path, payload)
    rebuild_index(data_dir)
    return translated_count, failures


def backfill_history(
    data_dir: Path,
    translator: Callable[[str], str] | None = None,
    *,
    limit: int = 200,
) -> tuple[int, int]:
    """Translate a bounded batch of older reports, newest first."""
    cache = _existing_translations(data_dir)
    count = failures = 0
    latest_date = ""
    latest_path = data_dir / "report.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest_date = f'report-{to_beijing(datetime.fromisoformat(latest["generated_at"])):%Y-%m-%d}.json'

    for path in sorted(data_dir.glob("report-????-??-??.json"), reverse=True):
        payload = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for article in payload.get("articles", []):
            if article.get("source") != "arxiv" or not article.get("title") or not article.get("content"):
                continue
            key = _key(article)
            prior = cache.get(key)
            if prior:
                if (article.get("title_zh"), article.get("content_zh")) != prior:
                    article["title_zh"], article["content_zh"] = prior
                    changed = True
                continue
            if count >= limit:
                continue
            try:
                if translator is None:
                    translator = _argos_translator(Path.home() / ".cache/scholar-tide/models")
                translated = translator(article["title"]), translator(article["content"])
                if not all(translated):
                    raise ValueError("empty translation")
                article["title_zh"], article["content_zh"] = translated
                cache[key] = translated
                count += 1
                changed = True
            except Exception:
                failures += 1
                logger.exception("could not translate %s", article["title"][:80])
        if changed:
            _write_json(path, payload)
            if path.name == latest_date:
                _write_json(latest_path, payload)
        if count >= limit:
            break
    rebuild_index(data_dir)
    return count, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Pretranslate the latest arXiv report")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--limit", type=int, default=None, help="Only translate the first N papers")
    parser.add_argument("--backfill", action="store_true", help="Translate older daily reports newest first")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.backfill:
        count, failures = backfill_history(args.data_dir, limit=args.limit if args.limit is not None else 200)
    else:
        count, failures = translate_latest(args.data_dir, limit=args.limit)
    logger.info("translated %d new papers; %d failed", count, failures)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
