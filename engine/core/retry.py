"""Generic retry decorator with exponential backoff and jitter.

Unlike the original build.py version, this one makes no assumption about
the wrapped function's return type. It is safe to wrap a spider (returns
list[InfoItem]) or an embedding call (returns a vector).

Optional behaviour: if the wrapped function declares a ``timeout``
keyword argument with default ``None``, the computed backoff delay is
passed in *as* the timeout instead of sleeping. This lets blocking HTTP
calls act as their own timer so parallel workers stay bounded.
"""
from __future__ import annotations

import functools
import inspect
import logging
import random
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _name_of(func: Callable[..., Any]) -> str:
    """Best-effort human-readable name; handles functools.partial too."""
    for candidate in (func, getattr(func, "func", None)):
        if candidate is None:
            continue
        name = getattr(candidate, "__name__", None)
        if name:
            return name
    return type(func).__name__


def retry(
    max_retries: int = 3,
    base_delay: float = 10.0,
    factor: float = 2.0,
    jitter: bool = True,
    on: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Retry ``func`` with exponential backoff.

    - On final failure the last exception is re-raised (the caller may
      decide whether that is fatal).
    - If ``func`` accepts a ``timeout`` keyword (default None) the
      backoff delay is handed to it instead of sleeping.
    """

    def decorator(func: F) -> F:
        signature = inspect.signature(func)
        accepts_timeout = (
            "timeout" in signature.parameters
            and signature.parameters["timeout"].default is None
        )

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: BaseException | None = None
            for attempt in range(max_retries):
                delay = base_delay * (factor**attempt)
                if jitter:
                    delay += random.uniform(0, 1)
                try:
                    if accepts_timeout:
                        return func(*args, **{**kwargs, "timeout": delay})
                    return func(*args, **kwargs)
                except on as e:
                    last_error = e
                    remaining = max_retries - attempt - 1
                    logger.warning(
                        "%s failed (%s); %d retries left",
                        _name_of(func),
                        e,
                        remaining,
                    )
                    if remaining <= 0:
                        raise
                    if not accepts_timeout:
                        time.sleep(delay)
            raise last_error  # unreachable, satisfies type checkers

        return wrapper  # type: ignore[return-value]

    return decorator