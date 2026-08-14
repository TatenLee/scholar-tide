"""Bilibili spider: needs a login cookie. Optional.
Registered name: ``bilibili``.
"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime

import bs4
import requests

from engine.core.registry import register
from engine.core.type import InfoItem, Link
from engine.core.util import html_to_markdown

_COOKIE_ENV = "BILIBILI_COOKIE"


def _headers() -> dict[str, str]:
    cookie = os.environ.get(_COOKIE_ENV)
    if not cookie:
        raise RuntimeError(
            f"{_COOKIE_ENV} not set; log in to bilibili, copy document.cookie, "
            "and export it as an env var / GH secret."
        )
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Cookie": cookie,
    }


def _extract_video(url: str, timeout: float) -> InfoItem:
    resp = requests.get(url, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    soup = bs4.BeautifulSoup(resp.content, "html.parser")

    title = soup.select_one("h1.video-title").text.strip()
    author = soup.select_one('a[class~="up-name"]').text.strip()
    published = soup.select_one("div.pubdate-ip-text").text.strip()
    desc = soup.select_one("span.desc-info-text")
    desc = html_to_markdown(desc.prettify()) if desc else ""

    return InfoItem(
        title=title,
        content=f"{author} posted at {published}\n\n{desc}",
        published_at=datetime.now(),
        links=[Link("bilibili", url)],
        source="bilibili",
    )


@register("bilibili")
def get_info(url: str, max_items: int = 10, timeout: float | None = None) -> list[InfoItem]:
    """Scrape the bilibili home page recommendation grid and expand videos."""
    timeout = timeout or 10.0
    links: list[str] = []
    while len(links) < max_items:
        resp = requests.get(url, headers=_headers(), timeout=timeout)
        resp.raise_for_status()
        soup = bs4.BeautifulSoup(resp.content, "html.parser")
        for node in soup.select("h3.bili-video-card__info--tit a"):
            href = node.attrs.get("href", "")
            if href.startswith("https://www.bilibili.com/video/"):
                links.append(href)
        time.sleep(random.uniform(0.5, 1.5))

    results = [_extract_video(v, timeout) for v in links[:max_items]]
    return results