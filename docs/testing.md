# Testing

```bash
make test           # backend (pytest) + frontend (tsc + vitest)
make lint           # ruff
make load-test      # locust against a running stack
make eval           # answer accuracy against a real LLM (spends tokens)
```

## Test pyramid

| Layer | Where | What it covers | Count |
|---|---|---|---|
| Unit | `backend/tests/unit/` | CSV parsing edge cases (encodings, delimiters, BOM, malformed rows, leading zeros, reserved names), SQL guard (allowed and 17 blocked patterns), anomaly maths (masking, grouping, sign rule), forecasting, crypto and key rotation, JWT attacks, password policy, bulkheads, LLM adapters | 69 |
| Integration | `backend/tests/integration/` | Full HTTP flows with a scripted LLM: auth lifecycle, multi-file upload, preview, SQL + CSV export, full agent turns with real DuckDB results, self-correction after a failed query, conversation context, answer cache, LLM outage, step limit, offline mode, Markdown export, multi-file joins | 29 |
| Security | `backend/tests/security/` | Auth required everywhere, forged cookies, CSRF, cross-tenant access (IDOR) on every endpoint, SQL reaching other tenants, prompt injection, lockout, refresh reuse, rate limits, upload abuse, path traversal, runaway queries, headers, error leakage | 22 |
| Frontend | `frontend/src/test/` | Formatting, SSE parsing, table sorting, markdown safety (no raw HTML), follow-up wiring, "show working" | 5 |
| Load | `backend/tests/load/locustfile.py` | Realistic user mix through the whole stack with an SLO gate (p95 < 1.5 s, errors < 1 %) | |
| LLM evals | `backend/tests/evals/` | 8 cases from the brief scored against ground truth computed with DuckDB | |

Backend line coverage: **92 %** (CI fails under 80 %). The scripted fake LLM makes every agent test
deterministic and free; the eval harness is where real model behaviour is measured.

## Situations tested

* **Bad input**: empty file, header only, binary file, Excel renamed to .csv, Windows-1252 text,
  semicolon/tab/pipe delimiters, rows with too many fields, 300+ columns, files over the size cap,
  duplicate and reserved column names, IDs with leading zeros, currency strings like `"$1,200.50"`.
* **Model misbehaviour**: invalid SQL (fixed on retry), destructive SQL, file-reading SQL, tool
  loops, provider outage, answer in prose instead of the final tool.
* **Attackers**: other tenants, stolen refresh tokens, missing CSRF, brute force, injection in data.
* **Overload**: see below.

## Load testing results

Run on the development sandbox: **one API instance, 4 gunicorn workers, 2 vCPUs**, Postgres 16,
Redis 7, fake LLM (so we measure our code, not the vendor). 200 concurrent simulated users, each
signing up, uploading the 4,727-row sales file, then browsing, querying and asking questions.

| Iteration | Change | Throughput | p50 | p95 | Max | Failures |
|---|---|---|---|---|---|---|
| 1 | SQLite, 100 users | 19 req/s | 5 ms | 12 s | 67 s | 84 % (`database is locked`) |
| 2 | Postgres + Redis, CSRF fix, 100 users | 53 req/s | 11 ms | 930 ms | 4.3 s | 0 % server errors |
| 3 | 200 users | 43 req/s | 12 ms | 12 s | 92 s | pool exhaustion, worker timeout |
| 4 | DB connection released before DuckDB/parsing; 5 s pool timeout with 503 shedding; **bulkheads** for parsing, hashing and queries | **96 req/s** | **19 ms** | **340 ms** | 13 s | **0.37 %** (all deliberate 503s with `Retry-After`) |

What the load test found and fixed:

1. SQLite cannot take concurrent writers: production uses Postgres (SQLite stays for local dev, now with a busy timeout).
2. Refresh rotated the CSRF token, breaking in-flight requests from other tabs: now kept stable.
3. Requests held a pooled DB connection while doing seconds of CPU work: now released first.
4. Bursts of uploads and sign-ups starved cheap reads and tripped the worker heartbeat: bulkheads cap
   heavy work per process and shed with 503 instead of letting everything slow down.

Remaining slow path: uploads (p95 ~13 s at 200 simultaneous uploads on 2 CPUs). Uploads are
CPU-bound parsing; the next step at real scale is moving ingestion to a background worker queue
(e.g. Celery/RQ/Arq) and returning `202 Accepted` with a status endpoint.

## Scaling the deployment

* **Horizontal**: `docker compose up -d --scale api=6`. nginx re-resolves the service name every 10 s
  and balances by least connections (SSE streams are long-lived, so round robin would pile up).
* **Database connections**: per worker `pool_size=5, max_overflow=3`. Replicas x workers x 8 must stay
  under Postgres `max_connections`; add PgBouncer beyond ~12 workers.
* **Kubernetes**: the same image works unchanged. Use `/healthz` for liveness, `/readyz` for readiness,
  an HPA on CPU, an RWX volume or object storage for blobs, and managed Postgres/Redis.
* **LLM throughput** is usually the real ceiling: provider rate limits, not our CPU. The per-user
  chat limit and daily quota protect the shared API key; the answer cache removes repeat cost.

## LLM evaluation

`make eval` with a real key runs `tests/evals/cases.yaml`: top region, monthly trend chart,
underperforming product, top customers, SQL follow-up, anomaly detection (must flag the planted
2,400 price), forecast, and a prompt-injection attempt. Ground truth is computed with DuckDB at run
time. Results go to `evals_report.json`; exit code is non-zero below an 80 % pass rate, so it can
gate prompt or model changes.
