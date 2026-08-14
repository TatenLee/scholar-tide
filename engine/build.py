"""High-level orchestration: run the whole pipeline in one call.

    fetch  ->  embed (optional)  ->  rank (optional)  ->  render

Kept deliberately thin: every stage lives in engine/pipeline/*
so the flow reads top to bottom like a recipe.
"""
from __future__ import annotations

import logging
from pathlib import Path

from engine.core.config import AppConfig
from engine.pipeline.embed import EmbeddingClient
from engine.pipeline.fetch import fetch
from engine.pipeline.rank import compute_projection, score_and_sort_by_subject
from engine.render.json import dump_json
from engine.render.markdown import render_markdown

logger = logging.getLogger(__name__)


def build(
    config: AppConfig,
    *,
    markdown_path: Path = Path("output.md"),
    json_path: Path = Path("frontend/data/report.json"),
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

    markdown_path.write_text(render_markdown(items), encoding="utf-8")
    dump_json(items, json_path)

    logger.info("wrote %s and %s", markdown_path, json_path)
    return {"items": items, "projection": projection}