"""Shared fixtures. Environment is configured before the app is imported so the
whole suite runs against throwaway SQLite + temp storage + the fake LLM."""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="quarry-tests-")
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{_TMP}/test.db",
    "STORAGE_DIR": f"{_TMP}/blobs",
    "LLM_PROVIDER": "fake",
    "REDIS_URL": "",
    "LOG_LEVEL": "WARNING",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.kv import get_kv  # noqa: E402
from app.services.llm.fake import FakeClient  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"
PASSWORD = "Correct-horse-42"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _isolation():
    kv = get_kv()
    if hasattr(kv, "clear"):
        kv.clear()  # rate limit counters and caches do not leak between tests
    FakeClient.reset()
    yield
    FakeClient.reset()


def make_client() -> TestClient:
    return TestClient(app)


def signup(client: TestClient, email: str | None = None, password: str = PASSWORD) -> dict:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "full_name": "Test User", "password": password})
    assert r.status_code == 201, r.text
    client.headers["x-csrf-token"] = client.cookies.get("quarry_csrf")
    return {"email": email, "password": password, **r.json()}


@pytest.fixture
def client() -> TestClient:
    with make_client() as c:
        yield c


@pytest.fixture
def user_client(client: TestClient) -> TestClient:
    signup(client)
    return client


def upload(client: TestClient, name: str, content: bytes | None = None):
    data = content if content is not None else (SAMPLE_DIR / name).read_bytes()
    return client.post("/api/datasets", files=[("files", (name, data, "text/csv"))])


@pytest.fixture
def sales_dataset(user_client: TestClient) -> dict:
    r = upload(user_client, "sales.csv")
    assert r.status_code == 201, r.text
    return r.json()["datasets"][0]
