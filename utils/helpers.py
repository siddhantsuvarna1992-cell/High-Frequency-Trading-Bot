"""Async utility functions: retry decorator and rate limiter."""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

from utils.logging import get_logger

log = get_logger("helpers")


def async_retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Decorator that retries an async function on exception with exponential backoff."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc = None
            current_delay = delay
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_retries:
                        log.warning(
                            f"{func.__name__} attempt {attempt}/{max_retries} "
                            f"failed: {e}. Retrying in {current_delay:.1f}s..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        log.error(f"{func.__name__} failed after {max_retries} attempts: {e}")
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


class RateLimiter:
    """Token-bucket rate limiter for order submission."""

    def __init__(self, max_per_second: int = 5):
        self._max = max_per_second
        self._tokens = float(max_per_second)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._max, self._tokens + elapsed * self._max)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._max
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


def ms_to_str(timestamp_ms: int) -> str:
    """Convert millisecond timestamp to human-readable string."""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
