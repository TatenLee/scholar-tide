"""Stage 2: text -> embedding vectors through an OpenAI-compatible API.

`openai` and `numpy` are optional dependencies; this module is only
imported when the user asks for personalisation (``--use-embed``), so a
plain fetch+build run needs none of them. Vector math is plain python
lists to avoid the numpy dependency entirely.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from engine.core.retry import retry

logger = logging.getLogger(__name__)

Vector = list[float]


class EmbeddingClient:
    """Thin wrapper around the OpenAI-compatible embedding endpoint."""

    def __init__(
        self,
        model: str = "text-embedding-v4",
        dimensions: int = 2048,
        api_key: str | None = None,
        base_url: str | None = None,
        max_workers: int = 8,
    ):
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set; cannot compute embeddings. "
                "Either set the key or drop --use-embed."
            )
        from openai import OpenAI

        self._model = model
        self._dimensions = dimensions
        self._max_workers = max_workers
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def _embed_one(self, text: str) -> Vector:
        resp = self._client.embeddings.create(
            model=self._model, dimensions=self._dimensions, input=text
        )
        return [float(x) for x in resp.data[0].embedding]

    def embed_texts(self, texts: list[str]) -> list[Vector]:
        guarded = [
            retry(max_retries=3, base_delay=60 / 1200, factor=2, jitter=True)(
                lambda t=text: self._embed_one(t)
            )
            for text in texts
        ]
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            return list(pool.map(lambda f: f(), guarded))

    @staticmethod
    def dot(a: Vector, b: Vector) -> float:
        return sum(x * y for x, y in zip(a, b))

    @staticmethod
    def mean(vectors: list[Vector], dim: int) -> Vector:
        size = len(vectors)
        if size == 0:
            return [0.0] * dim
        return [sum(v[i] for v in vectors) / size for i in range(dim)]