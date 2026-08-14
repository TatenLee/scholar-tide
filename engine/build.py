"""High-level orchestration: run the whole pipeline in one call.

    fetch  ->  embed (optional)  ->  rank (optional)  ->  render

Kept deliberately thin: every stage lives in engine/pipeline/*
so the flow reads top to bottom like a recipe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from engine.core.config import AppConfig
from engine.pipeline.embed import EmbeddingClient
from engine.pipeline.fetch import fetch
from engine.pipeline.rank import compute_projection, score_and_sort_by_subject
from engine.render.json import dump_daily, dump_json, rebuild_index
from engine.render.markdown import render_markdown

logger = logging.getLogger(__name__)


def build(
    config: AppConfig,
    *,
    markdown_path: Path = Path("output.md"),
    data_dir: Path = Path("data"),
    max_workers: int = 4,
) -> dict:
    items = fetch(config, max_workers=max_workers)

    projection = None
    if config.embedding.use_embed:
        client = EmbeddingClient(
            model=config.embedding.model,
            dimensions=config.embedding.dimensions,
            api_key=config.embedding.api_key,
            base_url=config.embedding.base_url,
        )
        projection = compute_projection(client, config.embedding)
        score_and_sort_by_subject(items, projection, client)
        logger.info("re-ranked %d items by personal preference", len(items))
    else:
        logger.info("embedding disabled (use --use-embed to personalise)")

    generated_at = datetime.now(timezone.utc)
    markdown_path.write_text(
        render_markdown(items, generated_at=generated_at), encoding="utf-8"
    )
    dump_json(items, data_dir / "report.json", generated_at)
    dump_daily(items, data_dir, generated_at)
    rebuild_index(data_dir)

    logger.info(
        "wrote %s and data in %s", markdown_path, data_dir
    )
    return {"items": items, "projection": projection}