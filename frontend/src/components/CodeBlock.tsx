import { useState, type ReactElement } from "react";

const SQL_KEYWORDS =
  /\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|LIMIT|JOIN|LEFT JOIN|INNER JOIN|ON|USING|AS|AND|OR|NOT|IN|WITH|CASE|WHEN|THEN|ELSE|END|DESC|ASC|HAVING|DISTINCT|OVER|PARTITION BY|UNION ALL|BETWEEN|IS|NULL)\b/gi;

/** Light syntax tinting for SQL: keywords only. Output is built from text nodes, never innerHTML. */
function tintSql(code: string) {
  const parts: (string | ReactElement)[] = [];
  let last = 0;
  for (const m of code.matchAll(SQL_KEYWORDS)) {
    if (m.index! > last) parts.push(code.slice(last, m.index));
    parts.push(
      <span key={m.index} className="kw">
        {m[0]}
      </span>,
    );
    last = m.index! + m[0].length;
  }
  parts.push(code.slice(last));
  return parts;
}

export function CodeBlock({ code, language }: { code: string; language: "sql" | "python" }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  }
  return (
    <div className="code">
      <div className="code-bar">
        <span>{language === "sql" ? "SQL" : "pandas"}</span>
        <button type="button" className="link" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        <code>{language === "sql" ? tintSql(code) : code}</code>
      </pre>
    </div>
  );
}
