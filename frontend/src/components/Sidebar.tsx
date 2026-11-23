import { useRef, useState, type DragEvent } from "react";
import type { Conversation, Dataset } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatNumber, relativeTime } from "../lib/format";
import { Mark } from "../pages/AuthPage";

interface Props {
  datasets: Dataset[];
  conversations: Conversation[];
  activeConversation: Conversation | null;
  inspecting: string | null;
  uploading: boolean;
  onUpload: (files: File[]) => void;
  onLoadSamples: () => void;
  onToggleDataset: (id: string) => void;
  onInspect: (id: string) => void;
  onNewAnalysis: () => void;
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
}

export function Sidebar(p: Props) {
  const { user, logout } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const selected = new Set(p.activeConversation?.dataset_ids ?? []);

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const files = [...e.dataTransfer.files].filter((f) => /\.(csv|tsv|txt)$/i.test(f.name));
    if (files.length) p.onUpload(files);
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <Mark /> Quarry
      </div>

      <button type="button" className="btn btn-primary btn-block" onClick={p.onNewAnalysis}>
        New analysis
      </button>

      <section
        className={`side-section drop ${dragging ? "is-dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <div className="side-head">
          <h2>Data</h2>
          <button type="button" className="link" onClick={() => fileInput.current?.click()} disabled={p.uploading}>
            {p.uploading ? "Uploading" : "Upload CSV"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.tsv,.txt,text/csv"
            multiple
            hidden
            onChange={(e) => {
              const files = [...(e.target.files ?? [])];
              e.target.value = "";
              if (files.length) p.onUpload(files);
            }}
          />
        </div>
        {p.datasets.length === 0 ? (
          <div className="side-empty">
            <p>Drop CSV files here, or</p>
            <button type="button" className="link" onClick={p.onLoadSamples} disabled={p.uploading}>
              load the sample sales data
            </button>
          </div>
        ) : (
          <ul className="dataset-list">
            {p.datasets.map((d) => (
              <li key={d.id} className={p.inspecting === d.id ? "is-inspecting" : undefined}>
                <label className="check" title={p.activeConversation ? "Use in this analysis" : "Start an analysis first"}>
                  <input
                    type="checkbox"
                    checked={selected.has(d.id)}
                    disabled={!p.activeConversation}
                    onChange={() => p.onToggleDataset(d.id)}
                  />
                  <span className="sr-only">Use {d.original_filename} in this analysis</span>
                </label>
                <button type="button" className="dataset-name" onClick={() => p.onInspect(d.id)}>
                  <span>{d.table_name}</span>
                  <span className="muted small">
                    {formatNumber(d.row_count)} rows, {d.column_count} cols
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="side-section grow">
        <div className="side-head">
          <h2>Analyses</h2>
        </div>
        {p.conversations.length === 0 ? (
          <p className="muted small">Your questions and answers are saved here.</p>
        ) : (
          <ul className="conv-list">
            {p.conversations.map((c) => (
              <li key={c.id} className={c.id === p.activeConversation?.id ? "is-active" : undefined}>
                <button type="button" onClick={() => p.onOpenConversation(c.id)}>
                  <span className="conv-title">{c.title}</span>
                  <span className="muted small">{relativeTime(c.updated_at)}</span>
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`Delete ${c.title}`}
                  onClick={() => {
                    if (confirm(`Delete "${c.title}"? This cannot be undone.`)) p.onDeleteConversation(c.id);
                  }}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="side-foot">
        <div>
          <p className="who">{user?.full_name}</p>
          <p className="muted small">{user?.email}</p>
        </div>
        <details className="menu">
          <summary aria-label="Account menu">Account</summary>
          <div className="menu-pop">
            <button type="button" onClick={() => logout()}>
              Sign out
            </button>
            <button type="button" onClick={() => logout(true)}>
              Sign out of all devices
            </button>
          </div>
        </details>
      </footer>
    </aside>
  );
}
