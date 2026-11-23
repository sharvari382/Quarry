import { useState } from "react";
import type { Step } from "../api/types";

/**
 * The "working" of an answer: every tool call the analyst made, in order, with
 * timing and the exact query. Collapsed to one line by default; this is what
 * lets a reader check the number instead of trusting it.
 */
export function StepTrail({ steps, live }: { steps: Step[]; live: boolean }) {
  const [open, setOpen] = useState(false);
  if (steps.length === 0 && !live) return null;
  const failed = steps.filter((s) => s.ok === false).length;
  const total = steps.reduce((sum, s) => sum + (s.elapsed_ms ?? 0), 0);
  const current = steps.find((s) => s.ok === undefined);

  return (
    <div className={`trail ${live ? "is-live" : ""}`}>
      <button type="button" className="trail-summary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="trail-dots" aria-hidden="true">
          {steps.map((s) => (
            <i key={s.id} className={s.ok === false ? "bad" : s.ok ? "ok" : "run"} />
          ))}
        </span>
        <span>
          {live && current
            ? `${current.label}...`
            : live
              ? "Thinking..."
              : `${steps.length} ${steps.length === 1 ? "step" : "steps"} in ${(total / 1000).toFixed(1)}s` +
                (failed ? `, ${failed} retried` : "")}
        </span>
        <span className="trail-toggle">{open ? "Hide working" : "Show working"}</span>
      </button>
      {open && (
        <ol className="trail-list">
          {steps.map((s) => (
            <li key={s.id} className={s.ok === false ? "bad" : undefined}>
              <div className="trail-row">
                <span className="trail-label">{s.label}</span>
                {typeof s.input.purpose === "string" && <span className="muted">{s.input.purpose}</span>}
                {s.elapsed_ms !== undefined && <span className="trail-ms">{s.elapsed_ms} ms</span>}
              </div>
              {typeof s.input.sql === "string" && <pre className="trail-sql">{s.input.sql}</pre>}
              {s.error && <p className="trail-error">{s.error}</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
