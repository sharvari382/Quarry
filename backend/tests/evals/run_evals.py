"""Evaluate answer quality against a real LLM.

    ANTHROPIC_API_KEY=... LLM_PROVIDER=anthropic python -m tests.evals.run_evals

Runs every case in cases.yaml through the full HTTP stack in-process, checks the
result against ground truth computed directly with DuckDB, and writes
evals_report.json. Exit code is non-zero if the pass rate is below the bar,
so this can gate prompt or model changes in CI (as a manual/nightly job,
since it spends tokens).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import yaml

_tmp = tempfile.mkdtemp(prefix="quarry-evals-")
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/evals.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/blobs"
os.environ.setdefault("REDIS_URL", "")
os.environ["CHAT_RATE_LIMIT_PER_MINUTE"] = "1000"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

HERE = Path(__file__).parent
SAMPLES = HERE.parents[2] / "sample_data"
PASS_BAR = float(os.environ.get("EVAL_PASS_BAR", "0.8"))


def ground_truth(sql: str) -> str:
    con = duckdb.connect()
    for name in ("sales", "customers", "products"):
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{SAMPLES / (name + '.csv')}')")
    return str(con.execute(sql).fetchone()[0])


def parse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def main() -> int:
    if os.environ.get("LLM_PROVIDER", "fake") == "fake":
        print("Set LLM_PROVIDER and an API key: evals against the fake model are meaningless.")
        return 2
    Base.metadata.create_all(engine)
    cases = yaml.safe_load((HERE / "cases.yaml").read_text())
    client = TestClient(app)
    client.post("/api/auth/register", json={"email": "evals@example.com", "full_name": "Evals",
                                            "password": "Evals-pass-2026"})
    client.headers["x-csrf-token"] = client.cookies["quarry_csrf"]
    files = [("files", (n, (SAMPLES / n).read_bytes(), "text/csv")) for n in ("sales.csv", "customers.csv", "products.csv")]
    ids = [d["id"] for d in client.post("/api/datasets", files=files).json()["datasets"]]

    conversations: dict[str, str] = {}
    results = []
    for case in cases:
        conv = conversations.get(case.get("follows", "")) or client.post(
            "/api/conversations", json={"dataset_ids": ids}).json()["id"]
        conversations[case["id"]] = conv
        t0 = time.perf_counter()
        events = parse_events(client.post(f"/api/conversations/{conv}/ask", json={"question": case["question"]}).text)
        elapsed = time.perf_counter() - t0
        answer = next((e for e in events if e["type"] == "answer"), {})
        text = (answer.get("answer") or "")
        blob = (text + " " + (answer.get("sql") or "")).lower()
        tools = {e["tool"] for e in events if e["type"] == "step"}
        artifacts = [e["artifact"] for e in events if e["type"] == "artifact"]
        failures = []

        if any(e["type"] == "error" for e in events):
            failures.append("agent error")
        if q := case.get("answer_contains_sql"):
            truth = ground_truth(q)
            if truth.lower() not in text.lower():
                failures.append(f"expected '{truth}' in answer")
        for t in case.get("tools", []):
            if t not in tools:
                failures.append(f"tool {t} not used")
        if types := case.get("chart"):
            if not any(a["type"] == "chart" and a["chart_type"] in types for a in artifacts):
                failures.append(f"no {types} chart")
        if v := case.get("flags_value"):
            if not any(a["type"] == "anomalies" and any(abs(f["value"] - v) < 1e-6 for f in a["flagged"])
                       for a in artifacts):
                failures.append(f"anomaly {v} not flagged")
        for word in case.get("answer_or_sql_contains", []):
            if word.lower() not in blob:
                failures.append(f"'{word}' missing")
        for bad in case.get("must_not_contain", []):
            if bad.lower() in text.lower():
                failures.append(f"contains '{bad}'")

        results.append({"id": case["id"], "passed": not failures, "failures": failures,
                        "seconds": round(elapsed, 1), "tools": sorted(tools)})
        mark = "PASS" if not failures else "FAIL"
        print(f"{mark}  {case['id']:<26} {elapsed:5.1f}s  {', '.join(failures)}")

    rate = sum(r["passed"] for r in results) / len(results)
    (HERE / "evals_report.json").write_text(json.dumps({"pass_rate": rate, "results": results}, indent=2))
    print(f"\npass rate {rate:.0%} (bar {PASS_BAR:.0%})")
    return 0 if rate >= PASS_BAR else 1


if __name__ == "__main__":
    sys.exit(main())
