"""Render the report as a JSON payload for the static frontend.

The frontend (frontend/) fetches ``data/report.json`` (the latest build)
and renders cards. Order of articles is preserved from the rank stage
(personalised within subject).

A daily snapshot is also written as ``report-YYYY-MM-DD.json`` next to the
canonical ``report.json`` (date = build date in Beijing time), and
``index.json`` lists every archived day so the frontend can offer a
history browser. All of these live in the root ``data/`` folder, which
is committed back to the repo and served at the site root.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine.core.type import InfoItem
from engine.core.util import to_beijing


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


def render_json(items: list[InfoItem], generated_at: datetime | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc)
    ordered = order_by_subject(items)
    subjects: list[str] = []
    for item in ordered:
        if item.subject not in subjects:
            subjects.append(item.subject)

    return {
        "generated_at": generated_at.isoformat(),
        "count": len(ordered),
        "subjects": subjects,
        "articles": [item.to_dict() for item in ordered],
    }


def dump_json(items: list[InfoItem], path: Path, generated_at: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(render_json(items, generated_at), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dump_daily(items: list[InfoItem], data_dir: Path, generated_at: datetime) -> Path:
    """Write ``report-YYYY-MM-DD.json`` (date is the build date in Beijing time).

    The archive lives in the root ``data/`` folder alongside the canonical
    ``report.json``, separate from the static assets the frontend ships; it
    is served at the site root and committed back to the repo to accumulate
    over time.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    date_str = to_beijing(generated_at).strftime("%Y-%m-%d")
    path = data_dir / f"report-{date_str}.json"
    dump_json(items, path, generated_at)
    return path


def rebuild_index(data_dir: Path) -> Path:
    """Scan ``report-*.json`` in the data dir and rewrite ``index.json``."""
    days: list[dict] = []
    for path in sorted(data_dir.glob("report-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        days.append(
            {
                "date": path.stem.removeprefix("report-"),
                "count": payload.get("count", len(payload.get("articles", []))),
                "generated_at": payload.get("generated_at", ""),
            }
        )
    days.sort(key=lambda d: d["date"])
    index = {"latest": days[-1]["date"] if days else "", "days": days}
    index_path = data_dir / "index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return index_path
