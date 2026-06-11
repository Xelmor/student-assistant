from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def consume(self, key: str, *, limit: int, window_seconds: int) -> int | None:
        now = monotonic()
        cutoff = now - window_seconds

        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()

            if len(attempts) >= limit:
                retry_after = max(1, int(window_seconds - (now - attempts[0])))
                return retry_after

            attempts.append(now)
            return None

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._attempts.clear()
            else:
                self._attempts.pop(key, None)


auth_rate_limiter = InMemoryRateLimiter()


def rate_limit_key(request: Request, scope: str, discriminator: str = '') -> str:
    client_host = request.client.host if request.client else 'unknown'
    return f'{scope}:{client_host}:{discriminator.strip().lower()}'


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
    discriminator: str = '',
) -> str:
    key = rate_limit_key(request, scope, discriminator)
    retry_after = auth_rate_limiter.consume(key, limit=limit, window_seconds=window_seconds)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail='Слишком много попыток. Повтори запрос позже.',
            headers={'Retry-After': str(retry_after)},
        )
    return key
