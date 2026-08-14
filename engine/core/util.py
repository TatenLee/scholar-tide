"""Small shared helpers: time conversion and HTML -> markdown."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))


def utc_now() -> datetime:
    """Current time as a naive UTC datetime (the pipeline's canonical clock)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_beijing(dt: datetime) -> datetime:
    """Interpret a naive datetime as UTC and shift it to Beijing time (UTC+8)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING)


def struct_time_to_datetime(struct_time) -> datetime:
    """Convert a ``time.struct_time`` from feedparser into a datetime."""
    return datetime(
        year=struct_time.tm_year,
        month=struct_time.tm_mon,
        day=struct_time.tm_mday,
        hour=struct_time.tm_hour,
        minute=struct_time.tm_min,
        second=struct_time.tm_sec,
    )


def html_to_markdown(html: str) -> str:
    """Convert an HTML snippet to markdown.

    Two opinionated tweaks against raw markdownify output:
      1. inline <img> with a base64 source is replaced by a label
      2. <h1..h6> headings become bold text instead of # markers
         (a heading inside a news blurb would break the report outline)
    """
    from markdownify import markdownify as md

    img_pattern = re.compile(
        r'<img\s+[^>]*src=["\']data:image/[^"\']*["\'][^>]*alt=["\']([^"\']*)["\'][^>]*>',
        re.IGNORECASE,
    )
    html = img_pattern.sub(lambda m: f"image: {m.group(1)}", html)

    markdown = md(html, heading_style="ATX")

    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#"):
            lines[i] = f"**{line.lstrip('#').strip()}**"
    return "\n".join(lines)