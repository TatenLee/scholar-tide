"""Generic RSS spider: parse any RSS/Atom feed (incl. RSSHub).
Registered name: ``rss``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import feedparser
import requests

from engine.core.registry import register
from engine.core.type import InfoItem, Link
from engine.core.util import html_to_markdown, struct_time_to_datetime, utc_now


@register("rss")
def get_info(
    url: str,
    html_summary: bool = False,
    timeout: float | None = None,
) -> list[InfoItem]:
    """Fetch entries from an RSS/Atom feed.

    :param url: feed URL (RSSHub endpoint or any other RSS site).
    :param html_summary: if True the entry summary is HTML (convert to md);
        otherwise it is plain text already.
    """
    timeout = timeout or 60.0
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)  # type: Any

    entries: list[InfoItem] = []
    for entry in parsed.get("entries", []):
        if html_summary:
            content = html_to_markdown(entry.get("summary", ""))
        else:
            content = entry.get("summary", "")
        links = [Link("src", entry.get("link", url))]
        if parsed.get("feed", {}).get("link"):
            links.append(Link("feed", parsed["feed"]["link"]))

        published_parsed = entry.get("published_parsed")
        entries.append(
            InfoItem(
                title=entry.get("title", ""),
                content=content,
                published_at=struct_time_to_datetime(published_parsed)
                if published_parsed
                else utc_now(),
                links=links,
                source="rss",
            )
        )
    return entries