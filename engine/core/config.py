"""Declarative configuration models, loaded from YAML files.

The config lives in two files:

  config/source.yaml      what to fetch and how to fetch it
  config/preference.yaml  the reader's personal taste (for re-ranking)

Keeping them separate means you can change "what kind of news I see"
without touching the plumbing, and vice versa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class SourceConfig:
    """One entry in `sources`. Points at a registered spider by name."""

    spider: str  # name registered in engine.spider.registry
    subject: str = "unclassified"
    url: str = ""
    kwargs: dict = field(default_factory=dict)
    enabled: bool = True


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 10.0
    factor: float = 2.0
    jitter: bool = True


@dataclass
class EmbeddingConfig:
    """Settings for the optional personalisation stage."""

    use_embed: bool = False
    model: str = "text-embedding-v4"
    dimensions: int = 2048
    base_url: Optional[str] = None  # env OPENAI_BASE_URL wins if set
    api_key: Optional[str] = None  # env OPENAI_API_KEY wins if set
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    # path to a pre-computed projection vector -> skip live API calls
    proj_embedding_path: Optional[str] = None


@dataclass
class AppConfig:
    sources: list[SourceConfig]
    retry: RetryConfig = field(default_factory=RetryConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    max_items_per_source: int = 200
    expired_after: Optional[str] = None  # "%Y/%m/%d %H:%M" filter cutoff (UTC)


def _load_settings(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_sources(cfg: dict) -> list[SourceConfig]:
    sources = []
    for raw in cfg.get("sources") or []:
        sources.append(
            SourceConfig(
                spider=raw["spider"],
                subject=raw.get("subject", "unclassified"),
                url=str(raw.get("url", "")),
                kwargs=dict(raw.get("kwargs", {}) or {}),
                enabled=raw.get("enabled", True),
            )
        )
    return sources


def _parse_retry(cfg: dict) -> RetryConfig:
    raw = cfg.get("retry") or {}
    return RetryConfig(
        max_retries=raw.get("max_retries", 3),
        base_delay=raw.get("base_delay", 10.0),
        factor=raw.get("factor", 2.0),
        jitter=raw.get("jitter", True),
    )


def _parse_embedding(cfg: dict, prefs: dict) -> EmbeddingConfig:
    raw = cfg.get("embedding") or {}
    prefs_rank = prefs.get("rank") or {}
    return EmbeddingConfig(
        use_embed=bool(raw.get("use_embed", False)),
        model=raw.get("model", "text-embedding-v4"),
        dimensions=raw.get("dimensions", 2048),
        base_url=raw.get("base_url"),
        api_key=raw.get("api_key"),
        likes=list(prefs_rank.get("likes", [])),
        dislikes=list(prefs_rank.get("dislikes", [])),
        proj_embedding_path=prefs_rank.get("proj_embedding_json"),
    )


def load_config(
    sources_path: Path,
    preferences_path: Path,
    *,
    use_embed: bool | None = None,
    expired_after: str | None = None,
) -> AppConfig:
    sources_cfg = _load_settings(sources_path)
    prefs_cfg = _load_settings(preferences_path)

    embedding = _parse_embedding(sources_cfg, prefs_cfg)
    if use_embed is not None:
        embedding.use_embed = use_embed

    return AppConfig(
        sources=_parse_sources(sources_cfg),
        retry=_parse_retry(sources_cfg),
        embedding=embedding,
        max_items_per_source=sources_cfg.get("max_items_per_source", 200),
        expired_after=expired_after,
    )