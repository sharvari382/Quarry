import threading

import anyio
import pytest
from fastapi import HTTPException

from app.services.bulkhead import Bulkhead


def test_sync_slot_sheds_load_when_full():
    b = Bulkhead("t", slots=1, wait_seconds=0.05)
    started, release = threading.Event(), threading.Event()

    def hold():
        with b.slot():
            started.set()
            release.wait(2)

    t = threading.Thread(target=hold)
    t.start()
    started.wait(1)
    with pytest.raises(HTTPException) as exc:
        with b.slot():
            pass
    assert exc.value.status_code == 503 and exc.value.headers["Retry-After"]
    release.set()
    t.join()
    with b.slot():  # free again
        pass


def test_async_run_returns_result():
    b = Bulkhead("t", slots=2, wait_seconds=1)
    assert anyio.run(b.run, lambda x: x * 2, 21) == 42
