import type { AnomalyArtifact, Artifact, ProfileArtifact } from "../api/types";
import { formatCell, formatNumber } from "../lib/format";
import { ChartView } from "./ChartView";
import { DataTable } from "./DataTable";

export function ArtifactView({ item, onExportCsv }: { item: Artifact; onExportCsv?: (sql: string, name: string) => void }) {
  switch (item.type) {
    case "chart":
      return <ChartView chart={item} />;
    case "table":
      return (
        <section className="artifact">
          <header className="artifact-head">
            <h4>{item.title}</h4>
            <span className="muted">
              {item.row_count}
              {item.truncated ? "+" : ""} {item.row_count === 1 ? "row" : "rows"}
            </span>
            {onExportCsv && (
              <button type="button" className="link" onClick={() => onExportCsv(item.sql, item.title)}>
                Download CSV
              </button>
            )}
          </header>
          <DataTable columns={item.columns} rows={item.rows} />
        </section>
      );
    case "anomalies":
      return <AnomalyView item={item} />;
    case "profile":
      return <ProfileView item={item} />;
    default:
      return null;
  }
}

function AnomalyView({ item }: { item: AnomalyArtifact }) {
  const labelCols = item.flagged[0] ? Object.keys(item.flagged[0].labels) : [];
  return (
    <section className="artifact anomalies">
      <header className="artifact-head">
        <h4>Unusual values in {item.value_column}</h4>
        <span className="muted">
          {item.n_flagged} of {formatNumber(item.n_values)} flagged
        </span>
      </header>
      {item.flagged.length === 0 ? (
        <p className="muted">Nothing stood out at the current threshold.</p>
      ) : (
        <ol className="flag-list">
          {item.flagged.slice(0, 12).map((f) => (
            <li key={f.row}>
              <span className={`flag-dir ${f.direction}`} aria-label={f.direction === "above" ? "High" : "Low"}>
                {f.direction === "above" ? "High" : "Low"}
              </span>
              <div>
                <p className="flag-reason">{f.reason}</p>
                {labelCols.length > 0 && (
                  <p className="flag-labels">
                    {labelCols.map((c) => (
                      <span key={c}>
                        {c}: <strong>{formatCell(f.labels[c])}</strong>
                      </span>
                    ))}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
      <p className="method-note">
        Method: {item.method.replace(/_/g, " ").replace("+", ", ")}. Values more than 3.5 robust standard deviations from
        the median are flagged; the median and MAD are used so the outliers cannot hide themselves by inflating the spread.
      </p>
    </section>
  );
}

function ProfileView({ item }: { item: ProfileArtifact }) {
  return (
    <section className="artifact">
      <header className="artifact-head">
        <h4>Profile of {item.table}</h4>
        <span className="muted">{formatNumber(item.rows)} rows</span>
      </header>
      <DataTable
        columns={["column", "type", "missing", "distinct", "min", "median", "max"]}
        rows={item.columns.map((c) => [
          c.column,
          c.dtype,
          c.nulls,
          c.distinct,
          c.min ?? "",
          c.median ?? "",
          c.max ?? "",
        ])}
        maxRows={20}
      />
    </section>
  );
}
