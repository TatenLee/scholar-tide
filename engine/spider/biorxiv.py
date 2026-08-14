"""bioRxiv spider: list a collection page and expand each paper's abstract.

Registered name: ``biorxiv``.
"""
from __future__ import annotations

import random
import re
import time
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from engine.core.registry import register
from engine.core.type import InfoItem, Link
from engine.core.util import html_to_markdown, utc_now

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}


def _parse_posted_date(text: str) -> datetime:
    match = re.search(
        r"(?i)(january|february|march|april|may|june|july|august|september"
        r"|october|november|december) (\d{1,2}), (\d{4})",
        text,
    )
    if not match:
        return utc_now()
    month, day, year = match.groups()
    return datetime(int(year), _MONTHS[month.lower()], int(day), 23, 59, 59)


def _extract_article(
    url: str, expired_after: datetime | None, timeout: float
) -> InfoItem | None:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    abstract_el = soup.select_one("#abstract-1")
    abstract = html_to_markdown(abstract_el.prettify()).strip() if abstract_el else ""

    date_el = soup.select_one(
        "#block-system-main .sidebar-right-wrapper"
        " .panel-pane.pane-1 div:last-child"
    )
    published_at = _parse_posted_date(date_el.text if date_el else "")

    if expired_after and published_at <= expired_after:
        return None

    return InfoItem(
        title="",
        content=abstract,
        published_at=published_at,
        links=[Link("biorxiv", url), Link("pdf", f"{url}.full.pdf")],
        source="biorxiv",
    )


@register("biorxiv")
def get_info(
    url: str,
    expired_after: datetime | None = None,
    max_items: int = 100,
    request_timeout: float = 60.0,
    timeout: float | None = None,
) -> list[InfoItem]:
    """Fetch the newest papers of a bioRxiv collection.

    :param url: collection page, e.g. https://www.biorxiv.org/collection/biochemistry
    :param expired_after: stop paginating once papers fall older than this.
    """
    timeout = timeout or request_timeout
    results: list[InfoItem] = []
    page = 0
    while len(results) < max_items:
        page_url = f"{url}?page={page}"
        resp = requests.get(page_url, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        cards = soup.select("div.highwire-article-citation.highwire-citation-type-highwire-article")
        if not cards:
            break

        for card in cards:
            title = card.select_one("span.highwire-cite-title")
            title_link = card.select_one("a.highwire-cite-linked-title")
            if title is None or title_link is None:
                continue

            start = time.time()
            item = _extract_article(
                f"https://www.biorxiv.org{title_link['href']}", expired_after, timeout
            )
            elapsed = time.time() - start
            if item is None:
                break  # reached papers older than the cutoff
            item.title = title.text.strip()
            results.append(item)

            sleep = max(0.0, timeout - elapsed) * random.uniform(0.1, 0.7)
            time.sleep(sleep)

        page += 1

    return results[:max_items]