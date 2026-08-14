"""Render a report as Markdown (for GitHub issues / plain-text readers).

The outline structure:

    # Daily News
    generated ...
    ## <subject>
    ### <title>
    [link](url) ...
    time
    content
"""
from __future__ import annotations

from datetime import datetime, timezone

from engine.core.type import InfoItem
from engine.core.util import to_beijing


def _render_links(item: InfoItem) -> str:
    parts = []
    for link in item.links:
        parts.append(f"[{link.label}]({link.url})")
    return " ".join(parts)


def _render_item(item: InfoItem) -> str:
    lines = [f"### {item.title}", ""]
    if item.links:
        lines.append(_render_links(item))
        lines.append("")
    lines.append(to_beijing(item.published_at).strftime(r"%Y/%m/%d %H:%M") + " CST")
    lines.append("")
    lines.append(item.content)
    return "\n".join(lines)


def render_markdown(items: list[InfoItem], generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).replace(tzinfo=None)
    beijing = to_beijing(generated_at)
    header = [
        "# Daily News",
        f"Generated at {beijing.strftime('%Y-%m-%d %H:%M:%S')} CST (UTC+8)",
        f"{len(items)} news from your selected sources.",
    ]

    ordered = sorted(items, key=lambda i: i.subject)
    sections: list[str] = [*header]
    current_subject: str | None = None
    for item in ordered:
        if item.subject != current_subject:
            current_subject = item.subject
            sections.append(f"## {item.subject}")
        sections.append(_render_item(item))

    return "\n\n".join(sections)