"""arXiv spider: fetch recent papers per category through the official API.

Registered name: ``arxiv``.

Config example (config/source.yaml):
    - spider: arxiv
      url: cs.CV            # arxiv category (or a list URL)
      subject: paper
"""
from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any

import feedparser
import requests

from engine.core.registry import register
from engine.core.type import InfoItem, Link
from engine.core.util import struct_time_to_datetime, utc_now


def _paper_links(arxiv_number: str) -> list[Link]:
    """Every paper gets four useful views; no need to re-type them per spider."""
    return [
        Link("arxiv", f"https://arxiv.org/abs/{arxiv_number}"),
        Link("html", f"https://arxiv.org/html/{arxiv_number}"),
        Link("pdf", f"https://arxiv.org/pdf/{arxiv_number}"),
        Link("papers.cool", f"https://papers.cool/arxiv/{arxiv_number}"),
    ]


def _convert_entry(entry: Any, cat: str) -> InfoItem:
    return InfoItem(
        title=entry["title"].replace("\n", " "),
        content=entry["summary"],
        published_at=struct_time_to_datetime(entry["published_parsed"])
        if "published_parsed" in entry
        else utc_now(),
        links=_paper_links(entry["link"].split("/")[-1]),
        source="arxiv",
        tags=[cat],
    )


@register("arxiv")
def get_info(
    url: str,
    expired_after: datetime | None = None,
    timeout: float | None = None,
) -> list[InfoItem]:
    """Fetch recent papers from arXiv by category.

    :param url: arxiv category id (e.g. "cs.CV") or list-page URL.
    :param expired_after: only keep papers published after this time.
    :param timeout: per-request timeout; the retry decorator may inject it.
    """
    if "/" in url:
        cat = url.split("/")[4]
    else:
        cat = url

    timeout = timeout or 60.0
    now = utc_now()
    expired_str = expired_after.strftime(r"%Y%m%d%H%M") if expired_after else "197001010000"
    now_str = now.strftime(r"%Y%m%d%H%M")

    page_size = 1000
    entries: list[dict] = []
    for page in range(20):  # hard cap of 20k papers per run
        start = page * page_size
        query = (
            f"https://export.arxiv.org/api/query"
            f"?search_query=cat:{cat}+AND+submittedDate:[{expired_str}+TO+{now_str}]"
            f"&sortBy=lastUpdatedDate&sortOrder=descending"
            f"&start={start}&max_results={page_size}"
        )
        data = requests.get(query, timeout=timeout).content.decode("utf-8")
        parsed = feedparser.parse(data)
        if not parsed["entries"]:
            break
        entries.extend(parsed["entries"])
        time.sleep(random.random() * 5 + 1)  # be gentle with export.arxiv.org

    return [_convert_entry(e, cat) for e in entries]