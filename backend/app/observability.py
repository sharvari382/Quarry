"""Prometheus metrics. Works under gunicorn with several workers when
PROMETHEUS_MULTIPROC_DIR is set (see gunicorn.conf.py)."""
from __future__ import annotations

import os

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter("quarry_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("quarry_http_request_seconds", "HTTP latency", ["method", "route"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
LLM_CALLS = Counter("quarry_llm_calls_total", "LLM API calls", ["provider", "outcome"])
LLM_TOKENS = Counter("quarry_llm_tokens_total", "LLM tokens", ["provider", "kind"])
TOOL_CALLS = Counter("quarry_tool_calls_total", "Agent tool calls", ["tool", "outcome"])
QUERY_SECONDS = Histogram("quarry_query_seconds", "DuckDB query time",
                          buckets=(0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10))
UPLOADS = Counter("quarry_uploads_total", "CSV uploads", ["outcome"])


def render_metrics() -> tuple[bytes, str]:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST
