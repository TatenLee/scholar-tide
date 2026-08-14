"""Render the report as a JSON payload for the static frontend.

The frontend (frontend/) fetches this file and renders cards. Order of
articles is preserved from the rank stage (personalised within subject).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.core.type import InfoItem


def order_by_subject(items: list[InfoItem]) -> list[InfoItem]:
    """Group by subject (first-appearance order), sort within group by score."""
    seen: list[str] = []
    for item in items:
        if item.subject not in seen:
            seen.append(item.subject)
    ordered: list[InfoItem] = []
    for subject in seen:
        group = [i for i in items if i.subject == subject]
        group.sort(key=lambda i: i.score, reverse=True)
        ordered.extend(group)
    return ordered


def render_json(items: list[InfoItem]) -> dict:
    ordered = order_by_subject(items)
    subjects: list[str] = []
    for item in ordered:
        if item.subject not in subjects:
            subjects.append(item.subject)

    return {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "count": len(ordered),
        "subjects": subjects,
        "articles": [item.to_dict() for item in ordered],
    }


def dump_json(items: list[InfoItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(render_json(items), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )