"""Small key/value abstraction over Redis, with an in-process fallback.

Redis is what makes the API stateless across replicas: rate limit counters,
login lockouts and the query cache are shared by every instance behind the
load balancer. The in-memory store exists for local dev and tests only; with
more than one replica it would let each instance keep its own counters.
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache
from typing import Protocol

from app.config import get_settings


class KV(Protocol):
    def incr(self, key: str, ttl_seconds: int) -> int: ...
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...
    def delete(self, key: str) -> None: ...
    def ttl(self, key: str) -> int: ...
    def ping(self) -> bool: ...


class MemoryKV:
    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, float]] = {}
        self._lock = threading.Lock()

    def _alive(self, key: str) -> tuple[bytes, float] | None:
        item = self._data.get(key)
        if item and item[1] < time.monotonic():
            self._data.pop(key, None)
            return None
        return item

    def incr(self, key: str, ttl_seconds: int) -> int:
        with self._lock:
            item = self._alive(key)
            if item is None:
                self._data[key] = (b"1", time.monotonic() + ttl_seconds)
                return 1
            value = int(item[0]) + 1
            self._data[key] = (str(value).encode(), item[1])
            return value

    def get(self, key: str) -> bytes | None:
        with self._lock:
            item = self._alive(key)
            return item[0] if item else None

    def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        with self._lock:
            if len(self._data) > 10_000:  # crude bound so tests and dev cannot grow it forever
                self._data.clear()
            self._data[key] = (value, time.monotonic() + ttl_seconds)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def ttl(self, key: str) -> int:
        with self._lock:
            item = self._alive(key)
            return max(0, int(item[1] - time.monotonic())) if item else 0

    def ping(self) -> bool:
        return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class RedisKV:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2, health_check_interval=30)

    def incr(self, key: str, ttl_seconds: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds, nx=True)  # set TTL only on first hit (fixed window)
        value, _ = pipe.execute()
        return int(value)

    def get(self, key: str) -> bytes | None:
        return self._r.get(key)

    def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        self._r.set(key, value, ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def ttl(self, key: str) -> int:
        return max(0, int(self._r.ttl(key)))

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


@lru_cache
def get_kv() -> KV:
    url = get_settings().redis_url
    return RedisKV(url) if url else MemoryKV()
