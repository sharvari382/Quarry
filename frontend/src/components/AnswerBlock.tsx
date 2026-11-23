import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Artifact, Step } from "../api/types";
import { ArtifactView } from "./ArtifactView";
import { CodeBlock } from "./CodeBlock";
import { StepTrail } from "./StepTrail";

export interface TurnView {
  key: string;
  question: string;
  steps: Step[];
  items: Artifact[];
  answer?: string;
  reasoning?: string[];
  sql?: string | null;
  pandas?: string | null;
  followUps?: string[];
  error?: string;
  cached?: boolean;
  live: boolean;
}

interface Props {
  turn: TurnView;
  onFollowUp: (q: string) => void;
  onExportCsv: (sql: string, name: string) => void;
}

export function AnswerBlock({ turn, onFollowUp, onExportCsv }: Props) {
  // Show charts first, then anomaly/profile findings, then tables: the order a reader scans in.
  const order = { chart: 0, anomalies: 1, profile: 2, table: 3 } as const;
  const items = [...turn.items].sort((a, b) => order[a.type] - order[b.type]);
  const tables = items.filter((i) => i.type === "table");
  const others = items.filter((i) => i.type !== "table");

  return (
    <article className="turn">
      <p className="question">{turn.question}</p>
      <div className="answer">
        <StepTrail steps={turn.steps} live={turn.live} />

        {turn.error && (
          <p className="answer-error" role="alert">
            {turn.error}
          </p>
        )}

        {turn.answer && (
          <div className="prose">
            {/* react-markdown renders to React elements and ignores raw HTML: model output cannot inject markup. */}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.answer}</ReactMarkdown>
          </div>
        )}

        {others.map((item) => (
          <ArtifactView key={item.id} item={item} />
        ))}

        {tables.length > 0 && (
          <details className="evidence" open={tables.length === 1 && others.length === 0}>
            <summary>
              {tables.length === 1 ? "Result table" : `${tables.length} result tables`}
            </summary>
            {tables.map((item) => (
              <ArtifactView key={item.id} item={item} onExportCsv={onExportCsv} />
            ))}
          </details>
        )}

        {!turn.live && (turn.reasoning?.length || turn.sql || turn.pandas) && (
          <details className="evidence">
            <summary>How this was worked out</summary>
            {turn.reasoning && turn.reasoning.length > 0 && (
              <ol className="reasoning">
                {turn.reasoning.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ol>
            )}
            {turn.sql && <CodeBlock code={turn.sql} language="sql" />}
            {turn.pandas && <CodeBlock code={turn.pandas} language="python" />}
          </details>
        )}

        {!turn.live && turn.followUps && turn.followUps.length > 0 && (
          <div className="follow-ups">
            {turn.followUps.map((f) => (
              <button key={f} type="button" className="chip" onClick={() => onFollowUp(f)}>
                {f}
              </button>
            ))}
          </div>
        )}
        {turn.cached && <p className="muted small">Answered from cache: same question on the same data.</p>}
      </div>
    </article>
  );
}
