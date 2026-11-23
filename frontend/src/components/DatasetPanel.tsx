import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Dataset } from "../api/types";
import { formatBytes, formatCell, formatNumber, TYPE_LABEL } from "../lib/format";
import { DataTable } from "./DataTable";

interface Props {
  dataset: Dataset;
  onClose: () => void;
  onDelete: (id: string) => void;
}

export function DatasetPanel({ dataset, onClose, onDelete }: Props) {
  const [tab, setTab] = useState<"columns" | "quality" | "preview">("columns");
  const [preview, setPreview] = useState<{ columns: string[]; rows: unknown[][] } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    if (tab !== "preview") return;
    let cancelled = false;
    api
      .preview(dataset.id)
      .then((p) => !cancelled && setPreview(p))
      .catch((e) => !cancelled && setPreviewError(e.message));
    return () => {
      cancelled = true;
    };
  }, [dataset.id, tab]);

  const q = dataset.quality;
  const warnings = q.issues.filter((i) => i.severity === "warning").length;

  return (
    <aside className="panel" aria-label={`Details for ${dataset.original_filename}`}>
      <header className="panel-head">
        <div>
          <h3>{dataset.table_name}</h3>
          <p className="muted small">
            {dataset.original_filename}, {formatNumber(dataset.row_count)} rows, {formatBytes(dataset.size_bytes)} encrypted
          </p>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close details">
          ×
        </button>
      </header>

      <div className="tabs" role="tablist">
        {(["columns", "quality", "preview"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>
            {t === "columns" ? "Columns" : t === "quality" ? `Quality ${q.score}` : "Preview"}
          </button>
        ))}
      </div>

      <div className="panel-body">
        {tab === "columns" && (
          <ul className="col-list">
            {dataset.columns.map((c) => (
              <li key={c.name}>
                <div className="col-row">
                  <code>{c.name}</code>
                  <span className={`type type-${c.type}`}>{TYPE_LABEL[c.type] ?? c.type}</span>
                </div>
                <p className="muted small">
                  {c.original_name !== c.name && <>from “{c.original_name}”. </>}
                  {formatNumber(c.distinct)} distinct
                  {c.nulls > 0 && <>, {formatNumber(c.nulls)} missing</>}
                  {c.min !== undefined && (
                    <>
                      , {formatCell(c.min)} to {formatCell(c.max)}
                    </>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}

        {tab === "quality" && (
          <div className="quality">
            <p>
              {q.issues.length === 0
                ? "No problems found: no missing values, duplicates or malformed rows."
                : `${q.issues.length} ${q.issues.length === 1 ? "finding" : "findings"}${warnings ? `, ${warnings} worth fixing` : ""}.`}
            </p>
            <ul className="issue-list">
              {q.issues.map((i, n) => (
                <li key={n} className={i.severity}>
                  {i.column && <code>{i.column}</code>} {i.issue}
                </li>
              ))}
            </ul>
          </div>
        )}

        {tab === "preview" &&
          (previewError ? (
            <p className="form-error">{previewError}</p>
          ) : preview ? (
            <DataTable columns={preview.columns} rows={preview.rows} maxRows={25} />
          ) : (
            <p className="muted">Loading first rows</p>
          ))}
      </div>

      <footer className="panel-foot">
        <button
          type="button"
          className="btn btn-danger-quiet"
          onClick={() => {
            if (confirm(`Delete ${dataset.original_filename}? Analyses that use it will no longer be able to query it.`))
              onDelete(dataset.id);
          }}
        >
          Delete dataset
        </button>
      </footer>
    </aside>
  );
}
