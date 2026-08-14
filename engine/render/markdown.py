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

from datetime import datetime

from engine.core.type import InfoItem


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
    lines.append(item.published_at.strftime(r"%Y/%m/%d %H:%M") + " UTC")
    lines.append("")
    lines.append(item.content)
    return "\n".join(lines)


def render_markdown(items: list[InfoItem], generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.utcnow()
    header = [
        "# Daily News",
        f"Generated at {generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
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