"""Database engine and session management (SQLAlchemy 2.x, sync).

Sync SQLAlchemy is used on purpose: FastAPI runs sync dependencies in a thread
pool, and the heavy work (DuckDB, pandas) is CPU bound anyway.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        return engine
    # Pool is per worker process: 3 replicas x 4 workers x (5 + 3) = 96 connections,
    # just under Postgres' default max_connections=100. Scale these together, or put
    # PgBouncer in front once you add more replicas.
    # pool_timeout is short on purpose: under overload it is better to shed load with a
    # fast 503 (see main.py) than to queue requests for 30 s and time out everywhere.
    return create_engine(url, pool_size=5, max_overflow=3, pool_timeout=5, pool_pre_ping=True, pool_recycle=1800)


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def release_connection(db: Session) -> None:
    """Return the pooled connection before slow, DB-free work (DuckDB, parsing).

    Loaded ORM objects stay usable (expire_on_commit=False). If the request later
    touches the database again, the session simply checks out a new connection."""
    db.commit()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
