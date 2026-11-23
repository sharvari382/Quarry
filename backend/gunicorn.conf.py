"""Gunicorn process manager settings for the API container.

Workers: CPU bound work (pandas, DuckDB) plus long-lived SSE streams. Uvicorn
workers handle the async parts; each worker also has a thread pool for sync
endpoints. Scale out with more containers behind nginx rather than huge workers.
"""
import multiprocessing
import os
import shutil

bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.getenv("WEB_CONCURRENCY", min(4, multiprocessing.cpu_count() * 2)))
timeout = 120  # an analysis turn can take a while (several LLM calls)
graceful_timeout = 30  # finish in-flight requests on deploy/scale-down
keepalive = 5
max_requests = 2000  # recycle workers to cap memory growth from pandas/arrow
max_requests_jitter = 200
accesslog = None  # the app writes structured access logs itself
forwarded_allow_ips = "*"  # only nginx can reach us (internal network)

_prom_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR")


def on_starting(server):
    if _prom_dir:
        shutil.rmtree(_prom_dir, ignore_errors=True)
        os.makedirs(_prom_dir, exist_ok=True)


def child_exit(server, worker):
    if _prom_dir:
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(worker.pid)
