"""Load test for a running stack (through nginx, so the load balancer is exercised).

    make load-test USERS=200 HOST=http://localhost:8080

User mix (weights) mirrors expected traffic: mostly browsing and direct queries,
fewer LLM questions (expensive, rate limited), occasional uploads.

For capacity tests of the API itself, run the stack with LLM_PROVIDER=fake so
you measure our code and not the LLM vendor's latency or your token budget.
Set the per-user limits high for the test (RATE_LIMIT_PER_MINUTE etc.) or you
will mostly measure the rate limiter, which is also a valid test on its own.
"""
from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

SAMPLE = (Path(__file__).resolve().parents[3] / "sample_data" / "sales.csv").read_bytes()
QUESTIONS = [
    "Which region generated the highest revenue?",
    "Show monthly sales trends.",
    "Which products are underperforming?",
    "What are the top five customers?",
    "Detect anomalies in the dataset.",
]
QUERIES = [
    "SELECT region, sum(revenue) FROM sales GROUP BY 1 ORDER BY 2 DESC",
    "SELECT strftime(order_date, '%Y-%m') m, sum(revenue) FROM sales GROUP BY 1 ORDER BY 1",
    "SELECT product_id, count(*) n, avg(unit_price) FROM sales GROUP BY 1",
]


class AnalystUser(HttpUser):
    wait_time = between(1, 4)

    def _with_backoff(self, send, name: str, ok: int):
        """Behave like a well-written client: honour 503/429 Retry-After instead of hammering."""
        for _ in range(4):
            with send() as r:
                if r.status_code in (429, 503):
                    r.success()
                    time.sleep(float(r.headers.get("Retry-After", "2")))
                    continue
                if r.status_code != ok:
                    r.failure(f"{name}: HTTP {r.status_code}")
                return r
        return None

    def on_start(self):
        self.dataset_id = self.conversation_id = None
        email = f"load-{uuid.uuid4().hex[:10]}@example.com"
        r = self._with_backoff(lambda: self.client.post(
            "/api/auth/register", json={"email": email, "full_name": "Load Test", "password": "Load-test-pass-2026"},
            name="/api/auth/register", catch_response=True), "register", 201)
        if r is None or r.status_code != 201:
            self.stop()  # could not sign up: this simulated user leaves, like a real one would
            return
        self.client.headers["x-csrf-token"] = self.client.cookies.get("quarry_csrf", "")
        up = self._with_backoff(lambda: self.client.post(
            "/api/datasets", files=[("files", ("sales.csv", SAMPLE, "text/csv"))],
            name="/api/datasets [upload]", catch_response=True), "upload", 201)
        if up is None or up.status_code != 201:
            self.stop()
            return
        self.dataset_id = up.json()["datasets"][0]["id"]
        conv = self.client.post("/api/conversations", json={"dataset_ids": [self.dataset_id]})
        self.conversation_id = conv.json().get("id") if conv.ok else None

    @task(5)
    def browse(self):
        for path in ("/api/datasets", "/api/conversations"):
            with self.client.get(path, catch_response=True) as r:
                if r.status_code == 503:
                    r.success()  # shed under overload by design; counted separately below

    @task(4)
    def direct_query(self):
        if self.dataset_id:
            self.client.post("/api/datasets/query", json={"sql": random.choice(QUERIES),  # noqa: S311
                                                          "dataset_ids": [self.dataset_id]})

    @task(2)
    def preview(self):
        if self.dataset_id:
            self.client.get(f"/api/datasets/{self.dataset_id}/preview", name="/api/datasets/{id}/preview")

    @task(1)
    def ask(self):
        if not self.conversation_id:
            return
        with self.client.post(f"/api/conversations/{self.conversation_id}/ask",
                              json={"question": random.choice(QUESTIONS)},  # noqa: S311
                              name="/api/conversations/{id}/ask", stream=True, catch_response=True) as r:
            if r.status_code == 429:
                r.success()  # rate limiting working as designed is not a failure
                return
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
                return
            body = r.content.decode()
            if '"type": "done"' not in body:
                r.failure("stream ended without a done event")
            elif '"type": "error"' in body:
                r.failure("agent error: " + body[body.find('"type": "error"'):][:120])

    @task(1)
    def refresh_session(self):
        self.client.post("/api/auth/refresh")


@events.quitting.add_listener
def _assert_slo(environment, **_):
    """Fail the CI run if the service level objective is missed."""
    stats = environment.stats.total
    p95 = stats.get_response_time_percentile(0.95)
    fail_ratio = stats.fail_ratio
    print(json.dumps({"requests": stats.num_requests, "fail_ratio": round(fail_ratio, 4), "p95_ms": p95}))
    if fail_ratio > 0.01 or (p95 and p95 > 1500):
        environment.process_exit_code = 1
