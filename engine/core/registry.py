"""A registry of spider functions, keyed by a short name.

This replaces the old design where `config/source.yaml` stored a string
f-string path (e.g. `infiv.spiders.arxiv.get_info`) that was loaded by
reflection at runtime. A registry is:

  * type safe  - every registered entry is a real python object
  * jumpable   - IDEs can resolve the symbol
  * fail-fast  - a typo in config throws a NameError at startup,
                 not a silent AttributeError halfway through a run
"""
from __future__ import annotations

from typing import Callable, TypeAlias

from engine.core.type import InfoItem

SpiderFunc: TypeAlias = Callable[..., list[InfoItem]]

_registry: dict[str, SpiderFunc] = {}


def register(name: str) -> Callable[[SpiderFunc], SpiderFunc]:
    """Decorator: register a spider function under `name`."""

    def decorator(func: SpiderFunc) -> SpiderFunc:
        _registry[name] = func
        return func

    return decorator


def get_spider(name: str) -> SpiderFunc:
    if name not in _registry:
        raise NameError(
            f"unknown spider {name!r}; registered spiders: "
            + ", ".join(sorted(_registry))
        )
    return _registry[name]


def list_spiders() -> list[str]:
    return sorted(_registry)