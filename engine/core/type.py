"""Core data model shared across the whole pipeline.

Every spider returns a list of InfoItem. Every downstream stage
(fetch -> embed -> rank -> render) only speaks this one type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Link:
    """A single clickable link attached to a news item."""

    label: str
    url: str


@dataclass
class InfoItem:
    """One atomic piece of news (a paper, an article, a video...)."""

    title: str
    content: str  # markdown body
    published_at: datetime
    links: list[Link] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    subject: str = "unclassified"  # assigned by config, not by the spider
    source: str = ""  # which spider produced it (e.g. "arxiv")
    score: float = 0.0  # personalised ranking score, set by the rank stage

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "published_at": self.published_at.replace(
                tzinfo=timezone.utc
            ).isoformat(),
            "links": [{"label": l.label, "url": l.url} for l in self.links],
            "tags": self.tags,
            "subject": self.subject,
            "source": self.source,
            "score": round(self.score, 4),
        }