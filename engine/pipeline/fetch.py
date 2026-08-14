"""Stage 1: fetch news from every configured source, in parallel.

Each source's spider is resolved through the registry, wrapped with the
configured retry policy, and run in a thread pool. Every item that comes
back is stamped with its subject (from the config, since a spider does
not know where its output will land).
"""
from __future__ import annotations

import inspect
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial

from engine.core.config import AppConfig, SourceConfig
from engine.core.registry import get_spider
from engine.core.retry import retry
from engine.core.type import InfoItem
from engine import spider as _spider  # noqa: F401  (registers spiders)

logger = logging.getLogger(__name__)


def _build_caller(source: SourceConfig, config: AppConfig):
    """Create a zero-arg callable that invokes one source's spider."""
    spider = get_spider(source.spider)
    kwargs: dict = dict(source.kwargs)

    accepts_expired = "expired_after" in inspect.signature(spider).parameters
    if accepts_expired and config.expired_after:
        kwargs["expired_after"] = datetime.strptime(
            config.expired_after, r"%Y/%m/%d %H:%M"
        )

    caller = partial(spider, source.url, **kwargs)
    return retry(
        max_retries=config.retry.max_retries,
        base_delay=config.retry.base_delay,
        factor=config.retry.factor,
        jitter=config.retry.jitter,
    )(caller)


def _safe_call(caller) -> list[InfoItem]:
    """Run one source; a single failure must not kill the whole report."""
    try:
        return caller()
    except Exception as e:  # noqa: BLE001 — per-source tolerance is the point
        logger.error("source failed after retries (%s); skipping it", e)
        return []


def fetch(config: AppConfig, max_workers: int = 4) -> list[InfoItem]:
    enabled = [s for s in config.sources if s.enabled]
    logger.info("fetching %d sources with %d workers", len(enabled), max_workers)

    callers = [_build_caller(s, config) for s in enabled]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda c: _safe_call(c), callers))

    items: list[InfoItem] = []
    for source, batch in zip(enabled, results):
        for item in batch:
            item.subject = source.subject
            item.source = item.source or source.spider
            items.append(item)

    # hard cap per report so the page stays readable
    items = items[: config.max_items_per_source * len(enabled)]
    logger.info("fetched %d items", len(items))
    return items