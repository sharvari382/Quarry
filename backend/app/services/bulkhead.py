"""Bulkheads: cap how many CPU-heavy jobs run at once in one worker process.

Load testing showed that a burst of uploads (pandas parsing) and sign-ups
(Argon2 hashing) starved cheap requests: 40 threads fighting over two cores
made *every* endpoint slow and eventually tripped the worker heartbeat.
With a small fixed number of slots per process, heavy work queues briefly
and then fails fast with 503 + Retry-After, while reads stay quick.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import TypeVar

import anyio
from fastapi import HTTPException, status

T = TypeVar("T")

_CPUS = os.cpu_count() or 2


def _busy() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="The service is busy. Please retry in a moment.", headers={"Retry-After": "3"})


class Bulkhead:
    def __init__(self, name: str, slots: int, wait_seconds: float) -> None:
        self.name = name
        self.wait = wait_seconds
        self._sem = threading.BoundedSemaphore(slots)

    @contextmanager
    def slot(self):
        """For sync code (already running in a worker thread)."""
        if not self._sem.acquire(timeout=self.wait):
            raise _busy()
        try:
            yield
        finally:
            self._sem.release()

    async def run(self, fn: Callable[..., T], *args) -> T:
        """For async endpoints: wait for a slot in a thread, then run fn in a thread."""
        acquired = await anyio.to_thread.run_sync(lambda: self._sem.acquire(timeout=self.wait))
        if not acquired:
            raise _busy()
        try:
            return await anyio.to_thread.run_sync(fn, *args)
        finally:
            self._sem.release()


INGEST = Bulkhead("ingest", slots=max(1, _CPUS // 2), wait_seconds=20)
PASSWORD_HASH = Bulkhead("password_hash", slots=_CPUS, wait_seconds=10)
QUERY = Bulkhead("query", slots=_CPUS * 2, wait_seconds=10)
