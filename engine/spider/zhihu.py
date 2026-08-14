"""Zhihu spider: needs a login cookie. Optional; keep it enabled only
if you actually want a feed section, otherwise leave it out of config.
Registered name: ``zhihu``.
"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime
from typing import Any

import bs4
import requests

from engine.core.registry import register
from engine.core.type import InfoItem, Link
from engine.core.util import html_to_markdown, utc_now

_COOKIE_ENV = "ZHIHU_COOKIE"
MAX_CONTENT_LEN = 5000


def _headers() -> dict[str, str]:
    cookie = os.environ.get(_COOKIE_ENV)
    if not cookie:
        raise RuntimeError(
            f"{_COOKIE_ENV} not set; log in to zhihu, copy document.cookie, "
            "and export it as an env var / GH secret."
        )
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Cookie": cookie,
    }


def _clip(text: str) -> str:
    return text[:MAX_CONTENT_LEN] + "..." if len(text) > MAX_CONTENT_LEN else text


def _extract_question(content: bytes, url: str) -> InfoItem:
    soup = bs4.BeautifulSoup(content, "html.parser")
    title = soup.select_one("h1.QuestionHeader-title")
    answer = soup.select_one("div.RichContent")
    return InfoItem(
        title=title.text.strip() if title else url,
        content=_clip(html_to_markdown(answer.prettify())) if answer else "",
        published_at=utc_now(),
        links=[Link("zhihu", url)],
        source="zhihu",
    )


def _extract_article(content: bytes, url: str) -> InfoItem:
    soup = bs4.BeautifulSoup(content, "html.parser")
    title = soup.select_one("h1.Post-Title")
    body = soup.select_one("div.Post-RichTextContainer")
    return InfoItem(
        title=title.text.strip() if title else url,
        content=_clip(html_to_markdown(body.prettify())) if body else "",
        published_at=utc_now(),
        links=[Link("zhihu", url)],
        source="zhihu",
    )


def _parse_card(card: bs4.Tag) -> InfoItem:
    title_tag = card.select_one('a[data-za-detail-view-element_name="Title"]')
    title = title_tag.text.strip()
    url = f"https:{title_tag.attrs['href']}"
    summary = card.select_one("div.RichContent-inner")
    summary = html_to_markdown(summary.prettify()).strip().rstrip("…\n \n\n\n 阅读全文\n \n \u200b")
    return InfoItem(
        title=title,
        content=summary + "...",
        published_at=utc_now(),
        links=[Link("zhihu", url)],
        source="zhihu",
    )


@register("zhihu")
def get_info(url: str, max_items: int = 10, timeout: float | None = None) -> list[InfoItem]:
    """Scrape the zhihu home timeline (recommendation feed)."""
    timeout = timeout or 5.0
    cards: list[bs4.Tag] = []
    while len(cards) < max_items:
        resp = requests.get(url, headers=_headers(), timeout=timeout)
        resp.raise_for_status()
        soup = bs4.BeautifulSoup(resp.content, "html.parser")
        cards += soup.select("div.ContentItem")
        time.sleep(random.uniform(0.5, 1.5))

    return [_parse_card(c) for c in cards[:max_items]]