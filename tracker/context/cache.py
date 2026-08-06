"""In-memory TTL cache decorator for context resolvers."""

import time
from functools import wraps
from typing import Any, Callable, Dict, Tuple, TypeVar

T = TypeVar("T")


def ttl_cache(ttl_seconds: float) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """In-memory TTL cache for pure functions. Arguments must be hashable.

    Cached values expire after `ttl_seconds`. The cache is never pruned on access, so callers
    that run for a long time with many unique arguments can grow unbounded. A `cache_clear`
    method is attached to the wrapper for tests and rare resets.
    """
    def decorator(func: Callable[..., T]) -> Callable[[Callable[..., T]], Callable[..., T]]:
        cache: Dict[Tuple[Any, ...], Tuple[T, float]] = {}

        @wraps(func)
        def wrapper(*args: Any) -> T:
            now = time.monotonic()
            key = args
            if key in cache:
                value, timestamp = cache[key]
                if now - timestamp < ttl_seconds:
                    return value
            value = func(*args)
            cache[key] = (value, now)
            return value

        def cache_clear() -> None:
            cache.clear()

        wrapper.cache_clear = cache_clear
        return wrapper

    return decorator
