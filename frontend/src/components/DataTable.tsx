import { useMemo, useState } from "react";
import { formatCell } from "../lib/format";

interface Props {
  columns: string[];
  rows: unknown[][];
  maxRows?: number;
  highlightRows?: Set<number>;
}

/** Sortable table. Numeric columns are right-aligned with tabular figures. */
export function DataTable({ columns, rows, maxRows = 12, highlightRows }: Props) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const [expanded, setExpanded] = useState(false);

  const numeric = useMemo(
    () => columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] === null || typeof r[i] === "number")),
    [columns, rows],
  );

  const indexed = useMemo(() => {
    const list = rows.map((r, i) => ({ r, i }));
    if (!sort) return list;
    return [...list].sort((a, b) => {
      const x = a.r[sort.col];
      const y = b.r[sort.col];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * sort.dir;
    });
  }, [rows, sort]);

  const visible = expanded ? indexed : indexed.slice(0, maxRows);

  function toggleSort(col: number) {
    setSort((s) => (s?.col === col ? (s.dir === -1 ? null : { col, dir: -1 }) : { col, dir: 1 }));
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={c + i} className={numeric[i] ? "num" : undefined} aria-sort={
                sort?.col === i ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                <button type="button" onClick={() => toggleSort(i)}>
                  {c}
                  <span className="sort-ind" aria-hidden="true">
                    {sort?.col === i ? (sort.dir === 1 ? "▲" : "▼") : ""}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map(({ r, i }) => (
            <tr key={i} className={highlightRows?.has(i) ? "flag" : undefined}>
              {r.map((v, j) => (
                <td key={j} className={numeric[j] ? "num" : undefined}>
                  {formatCell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && (
        <button type="button" className="link table-more" onClick={() => setExpanded((e) => !e)}>
          {expanded ? "Show fewer rows" : `Show all ${rows.length} rows`}
        </button>
      )}
    </div>
  );
}
