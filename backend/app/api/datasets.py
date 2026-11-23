"""Dataset upload, listing, preview, deletion and a direct SQL endpoint."""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, release_connection
from app.deps import authed_user
from app.logging_setup import log_event
from app.models import Dataset, User
from app.observability import UPLOADS
from app.schemas import DatasetOut, PreviewOut, SqlIn, UploadOut
from app.security import rate_limit
from app.services.audit import audit
from app.services.bulkhead import INGEST
from app.services.csv_ingest import CsvValidationError, IngestResult, ingest_csv, table_name_from_filename
from app.services.export import rows_to_csv
from app.services.query_engine import QueryError, run_query
from app.services.sql_guard import UnsafeSqlError
from app.services.storage import get_store, table_cache

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
log = logging.getLogger(__name__)

MAX_FILES_PER_REQUEST = 5


def get_owned_dataset(db: Session, user: User, dataset_id: str) -> Dataset:
    ds = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id))
    if ds is None:
        # 404, not 403: do not confirm that someone else's id exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return ds


def get_owned_datasets(db: Session, user: User, ids: list[str]) -> list[Dataset]:
    if not ids:
        return []
    rows = list(db.scalars(select(Dataset).where(Dataset.id.in_(ids), Dataset.owner_id == user.id)))
    if len(rows) != len(set(ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="One or more datasets were not found")
    return rows


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read in chunks and stop as soon as the cap is exceeded (no unbounded buffering)."""
    chunks, total = [], 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise CsvValidationError(f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _ingest_and_store(raw: bytes, name: str) -> tuple[IngestResult, tuple[str, int]]:
    result = ingest_csv(raw, name)
    return result, get_store().put_table(result.table)


def _unique_table_name(db: Session, user: User, base: str) -> str:
    taken = set(db.scalars(select(Dataset.table_name).where(Dataset.owner_id == user.id)))
    name, n = base, 2
    while name in taken:
        name = f"{base}_{n}"
        n += 1
    return name


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload_datasets(request: Request, files: list[UploadFile] = File(...),
                          user: User = Depends(authed_user), db: Session = Depends(get_db)):
    s = get_settings()
    rate_limit.hit(f"upload:{user.id}", s.uploads_per_user_per_hour, window_seconds=3600)
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"Upload at most {MAX_FILES_PER_REQUEST} files at once.")
    existing = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner_id == user.id)) or 0
    if existing + len(files) > s.max_files_per_user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"You can keep up to {s.max_files_per_user} datasets. Delete some first.")
    release_connection(db)

    # Phase 1: validate, parse and encrypt every file without touching the database,
    # so no transaction is held open during the slow, CPU-bound part.
    parsed: list[tuple[str, bytes, IngestResult, str, int]] = []
    errors: list[str] = []
    for upload in files:
        name = (upload.filename or "upload.csv").replace("\\", "/").split("/")[-1][:255]
        try:
            raw = await _read_capped(upload, s.max_upload_mb * 1024 * 1024)
            # CPU bound: runs off the event loop, and at most a few at a time per process (bulkhead).
            result, (blob_key, size) = await INGEST.run(_ingest_and_store, raw, name)
        except CsvValidationError as exc:
            UPLOADS.labels("rejected").inc()
            errors.append(f"{name}: {exc}")
            continue
        parsed.append((name, raw, result, blob_key, size))

    # Phase 2: one short transaction for all metadata rows.
    created: list[Dataset] = []
    for name, raw, result, blob_key, size in parsed:
        ds = Dataset(
            owner_id=user.id, original_filename=name,
            table_name=_unique_table_name(db, user, table_name_from_filename(name)),
            blob_key=blob_key, sha256=hashlib.sha256(raw).hexdigest(), row_count=result.table.num_rows,
            column_count=result.table.num_columns, size_bytes=size, schema_json=result.schema,
            quality_json=result.quality | {"encoding": result.encoding, "delimiter": result.delimiter},
        )
        db.add(ds)
        db.flush()
        created.append(ds)
        UPLOADS.labels("ok").inc()
        audit(db, "dataset.upload", user.id, rate_limit.client_ip(request), dataset_id=ds.id,
              rows=ds.row_count, filename=name)
        log_event(log, "dataset_uploaded", dataset_id=ds.id, rows=ds.row_count, cols=ds.column_count)

    if errors and not created:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=" ".join(errors))
    # Partial success is allowed: the client shows the errors next to the files that worked.
    return UploadOut(datasets=[DatasetOut.model_validate(d) for d in created], errors=errors)


@router.get("", response_model=list[DatasetOut])
def list_datasets(user: User = Depends(authed_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Dataset).where(Dataset.owner_id == user.id).order_by(Dataset.created_at.desc())))


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    return get_owned_dataset(db, user, dataset_id)


@router.get("/{dataset_id}/preview", response_model=PreviewOut)
def preview_dataset(dataset_id: str, limit: int = 50, user: User = Depends(authed_user),
                    db: Session = Depends(get_db)):
    ds = get_owned_dataset(db, user, dataset_id)
    release_connection(db)
    res = run_query([ds], f'SELECT * FROM "{ds.table_name}"', limit=max(1, min(limit, 200)))
    return PreviewOut(columns=res.columns, rows=res.rows, row_count=ds.row_count)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: str, request: Request, user: User = Depends(authed_user),
                   db: Session = Depends(get_db)):
    ds = get_owned_dataset(db, user, dataset_id)
    get_store().delete(ds.blob_key)
    table_cache.drop(ds.blob_key)
    audit(db, "dataset.delete", user.id, rate_limit.client_ip(request), dataset_id=ds.id)
    db.delete(ds)


@router.post("/query")
def query(body: SqlIn, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    datasets = get_owned_datasets(db, user, body.dataset_ids)
    release_connection(db)
    try:
        return run_query(datasets, body.sql).to_dict()
    except (UnsafeSqlError, QueryError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/query.csv", response_class=PlainTextResponse)
def query_csv(body: SqlIn, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    datasets = get_owned_datasets(db, user, body.dataset_ids)
    release_connection(db)
    try:
        res = run_query(datasets, body.sql)
    except (UnsafeSqlError, QueryError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PlainTextResponse(rows_to_csv(res.columns, res.rows), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="query-result.csv"'})
