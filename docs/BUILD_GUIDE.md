# Build guide: every file, in the order to create it

This is the order the project was built in. Each step leaves something you can run or test, so
you never write a lot of code before checking it works.

## Step 0. Repository skeleton

| File | Purpose |
|---|---|
| `.gitignore` | Keeps `.env`, virtualenvs, `node_modules`, build output and local data out of git |
| `.env.example` | Every setting the stack needs, with comments. Copied to `.env` (never committed) |
| `Makefile` | Short commands: `make up`, `make test`, `make secrets`, `make load-test`, `make eval` |
| `scripts/generate_sample_data.py` | Deterministic sample business data with planted anomalies |
| `sample_data/*.csv` | Output of the script: `sales`, `customers`, `products` |

Check: `python3 scripts/generate_sample_data.py` writes three CSVs.

## Step 1. Backend foundation

| File | Purpose |
|---|---|
| `backend/requirements.txt`, `requirements-dev.txt` | Pinned runtime and test dependencies |
| `backend/pyproject.toml`, `pytest.ini` | Ruff lint rules (incl. security rules), pytest and coverage config |
| `backend/app/config.py` | All settings from env vars; refuses to boot in production with dev secrets |
| `backend/app/logging_setup.py` | JSON logs with request id and user id; redacts secrets |
| `backend/app/db.py` | SQLAlchemy engine, session per request, pool sizing, `release_connection` |
| `backend/app/models.py` | Tables: users, refresh_tokens, datasets, conversations, messages, audit_log |
| `backend/alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial_schema.py` | Database migrations (Postgres in production) |

Check: `alembic upgrade head` creates the tables.

## Step 2. Security primitives

| File | Purpose |
|---|---|
| `app/security/passwords.py` | Argon2id hashing, password policy, timing-equalising dummy hash |
| `app/security/tokens.py` | Access JWT, opaque refresh tokens (hashed), cookie names |
| `app/security/crypto.py` | Fernet encryption at rest with key rotation |
| `app/services/kv.py` | Redis or in-memory store for counters and caches |
| `app/security/rate_limit.py` | Per-user/IP rate limits, login lockout, daily LLM quota |
| `app/services/bulkhead.py` | Caps concurrent CPU-heavy work; sheds load with 503 |
| `tests/unit/test_security_primitives.py`, `test_bulkhead.py` | Proves the above, including JWT `alg=none` and tampering |

## Step 3. Data layer

| File | Purpose |
|---|---|
| `app/services/csv_ingest.py` | Validate, detect encoding/delimiter, type columns, sanitise names, quality report |
| `app/services/storage.py` | Encrypted Parquet blob store + bounded cache of decrypted tables |
| `app/services/sql_guard.py` | Allows exactly one read-only SELECT; blocks file, network and admin SQL |
| `app/services/query_engine.py` | Sandboxed DuckDB per query, timeout watchdog, result cache |
| `app/services/analytics.py` | Anomaly detection, table profiling, forecasting |
| `tests/unit/test_csv_ingest.py`, `test_sql_guard.py`, `test_analytics.py` | Edge cases for all of the above |

Check: `pytest tests/unit`.

## Step 4. The AI agent

| File | Purpose |
|---|---|
| `app/services/llm/base.py` | Provider-neutral message and tool-call types |
| `app/services/llm/anthropic_client.py`, `openai_client.py` | Vendor adapters with retries and safe error messages |
| `app/services/llm/fake.py` | Scripted model for tests; offline mode without a key |
| `app/services/llm/factory.py` | Picks the provider from settings |
| `app/services/prompts.py` | Versioned system prompt built from the dataset schemas |
| `app/services/tools.py` | Tool schemas for the model and their executors |
| `app/services/agent.py` | Tool-calling loop, streaming events, conversation history, answer cache |
| `app/services/export.py` | Markdown report, CSV export with formula-injection escaping |
| `tests/unit/test_llm_adapters.py` | Message format conversion, history building |

## Step 5. HTTP API

| File | Purpose |
|---|---|
| `app/schemas.py` | Request/response models with strict size limits |
| `app/deps.py` | Current user from cookie, CSRF check, per-user rate limit |
| `app/services/audit.py` | Audit log helper |
| `app/api/auth.py` | Register, login, refresh with rotation and reuse detection, logout, change password |
| `app/api/datasets.py` | Upload, list, preview, delete, direct SQL, CSV download |
| `app/api/conversations.py` | Analyses CRUD, the streaming `ask` endpoint, report export |
| `app/api/health.py` | `/healthz`, `/readyz`, `/metrics` |
| `app/observability.py` | Prometheus counters and histograms |
| `app/middleware.py` | Request id, access log, metrics, security headers (SSE-safe) |
| `app/main.py` | App factory, error handlers, 503 load shedding |
| `tests/conftest.py` | Isolated test environment and helpers |
| `tests/integration/*.py`, `tests/security/test_access_control.py` | Full flows and attack scenarios |

Check: `uvicorn app.main:app --reload` and open `http://localhost:8000/api/docs`; `pytest` passes.

## Step 6. Frontend

| File | Purpose |
|---|---|
| `frontend/package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `public/favicon.svg` | Project setup; dev server proxies `/api` |
| `frontend/scripts/copy-samples.mjs` | Makes "Try the sample sales data" work |
| `src/api/types.ts` | Types matching the API |
| `src/api/client.ts` | Fetch wrapper: cookies, CSRF header, silent refresh, SSE reader, downloads |
| `src/auth/AuthContext.tsx` | Session state, login/register/logout |
| `src/lib/format.ts` | Number, date and size formatting |
| `src/pages/AuthPage.tsx` | Sign in / create account |
| `src/pages/Workspace.tsx` | Main screen: state, upload, ask, streaming updates |
| `src/components/Sidebar.tsx` | Datasets (drag and drop), analyses, account menu |
| `src/components/DatasetPanel.tsx` | Columns, data quality, preview, delete |
| `src/components/AnswerBlock.tsx` | One question and its answer, evidence and follow-ups |
| `src/components/StepTrail.tsx` | "Show working": every tool call with timing and SQL |
| `src/components/ArtifactView.tsx` | Renders tables, anomalies and profiles |
| `src/components/ChartView.tsx` | All chart types, including forecast band |
| `src/components/DataTable.tsx` | Sortable, number-aligned table |
| `src/components/CodeBlock.tsx` | SQL/pandas with copy button |
| `src/components/Composer.tsx` | Question box (Enter to send, Shift+Enter for newline) |
| `src/styles.css` | The whole visual system |
| `src/main.tsx`, `src/App.tsx` | Entry point and auth gate |
| `src/test/*.ts(x)` | Component and utility tests |

Check: `npm run dev`, `npm test`, `npm run build`.

## Step 7. Deployment and scaling

| File | Purpose |
|---|---|
| `backend/gunicorn.conf.py` | Worker count, timeouts, worker recycling, multi-process metrics |
| `backend/Dockerfile`, `backend/.dockerignore` | Multi-stage, non-root API image with healthcheck |
| `frontend/Dockerfile`, `frontend/.dockerignore`, `.dockerignore` | Builds the SPA into the nginx image |
| `nginx/nginx.conf`, `nginx/proxy_common.conf` | Static files, CSP, per-IP limits, least-conn load balancing, SSE streaming |
| `docker-compose.yml` | Postgres, Redis, migrations job, 3 API replicas, nginx, optional Prometheus |
| `ops/prometheus.yml` | Scrapes every replica via DNS discovery |

Check: `make secrets`, fill `.env`, `docker compose up -d --build`, open `http://localhost:8080`.

## Step 8. Quality gates

| File | Purpose |
|---|---|
| `backend/tests/load/locustfile.py` | Load test with an SLO gate |
| `backend/tests/evals/cases.yaml`, `run_evals.py` | LLM accuracy against DuckDB ground truth |
| `.github/workflows/ci.yml` | Lint, tests with 80 % coverage gate, dependency audit, image build, stack smoke test |

## Step 9. Documentation

`README.md`, `docs/architecture.md`, `docs/security.md`, `docs/testing.md`, `docs/screenshots/`,
and this file.
