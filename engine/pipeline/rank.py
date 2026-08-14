"""Stage 3: personalised re-ranking by an embedding projection vector.

Idea (kept from the original project):
    projection p = mean(embed(likes)) - mean(embed(dislikes))
    score(item)  = dot(embed(item.title), p)

Items are then sorted *within each subject* by descending score, so the
things closest to your stated taste surface to the top while the report
still stays organised by subject.

The projection vector can also be precomputed to a JSON file
(preference.yaml -> rank.proj_embedding_json), which skips all live
embedding API calls for the likes/dislikes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from engine.core.config import EmbeddingConfig

logger = logging.getLogger(__name__)


def load_projection(path: str) -> list[float]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data["embedding"]
    return [float(x) for x in data]


def compute_projection(
    client, config: EmbeddingConfig
) -> list[float] | None:
    """Return the projection vector, preferring a cached JSON when given."""
    if config.proj_embedding_path:
        return load_projection(config.proj_embedding_path)

    likes, dislikes = config.likes, config.dislikes
    if not likes and not dislikes:
        logger.warning("no likes/dislikes configured; skipping re-ranking")
        return None

    dim = config.dimensions
    if likes:
        pos = client.mean(client.embed_texts(likes), dim)
    else:
        pos = [0.0] * dim
    if dislikes:
        neg = client.mean(client.embed_texts(dislikes), dim)
    else:
        neg = [0.0] * dim

    proj = [p - n for p, n in zip(pos, neg)]
    logger.info("computed projection vector from %d likes / %d dislikes",
                len(likes), len(dislikes))
    return proj


def score_and_sort_by_subject(
    items,
    projection: list[float] | None,
    client,
) -> None:
    """Mutate items with score, then sort each subject group by score.

    All titles are embedded in one batched call, then scored by
    dot(item_embedding, projection).
    """
    if projection is None:
        return

    vectors = client.embed_texts([item.title for item in items])
    for item, vector in zip(items, vectors):
        item.score = client.dot(vector, projection)

    by_subject: dict[str, list] = {}
    for item in items:
        by_subject.setdefault(item.subject, []).append(item)
    for group in by_subject.values():
        group.sort(key=lambda i: i.score, reverse=True)