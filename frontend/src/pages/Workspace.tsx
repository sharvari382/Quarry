import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Conversation, ConversationDetail, Dataset, Step } from "../api/types";
import { AnswerBlock, type TurnView } from "../components/AnswerBlock";
import { Composer } from "../components/Composer";
import { DatasetPanel } from "../components/DatasetPanel";
import { Sidebar } from "../components/Sidebar";

const STARTERS = [
  "Which region generated the highest revenue?",
  "Show monthly sales trends.",
  "Which products are underperforming?",
  "What are the top five customers?",
  "Detect anomalies in the dataset.",
  "Forecast revenue for the next six months.",
];

function toTurns(detail: ConversationDetail): TurnView[] {
  const turns: TurnView[] = [];
  for (const m of detail.messages) {
    if (m.role === "user") {
      turns.push({ key: m.id, question: m.content, steps: [], items: [], live: false });
    } else if (turns.length) {
      const t = turns[turns.length - 1];
      const a = m.artifacts ?? {};
      Object.assign(t, {
        steps: a.steps ?? [],
        items: a.items ?? [],
        answer: a.failed && !m.content ? undefined : m.content,
        error: a.failed ? "This answer did not complete. Ask again to retry." : undefined,
        reasoning: a.reasoning,
        sql: a.final_sql,
        pandas: a.pandas_code,
        followUps: a.follow_ups,
        cached: a.cached,
      });
    }
  }
  return turns;
}

export function Workspace() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<Conversation | null>(null);
  const [turns, setTurns] = useState<TurnView[]>([]);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [prefill, setPrefill] = useState<{ text: string; n: number }>();
  const abortRef = useRef<AbortController | null>(null);
  const threadEnd = useRef<HTMLDivElement>(null);

  const showError = (e: unknown) => setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });

  const refreshLists = useCallback(async () => {
    const [d, c] = await Promise.all([api.datasets(), api.conversations()]);
    setDatasets(d);
    setConversations(c);
    return { d, c };
  }, []);

  useEffect(() => {
    refreshLists().catch(showError);
  }, [refreshLists]);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const activeDatasets = useMemo(
    () => datasets.filter((d) => active?.dataset_ids.includes(d.id)),
    [datasets, active],
  );

  async function openConversation(id: string) {
    if (busy) return;
    try {
      const detail = await api.conversation(id);
      setActive(detail);
      setTurns(toTurns(detail));
    } catch (e) {
      showError(e);
    }
  }

  async function newAnalysis(datasetIds = datasets.map((d) => d.id)) {
    if (busy) return null;
    const conv = await api.createConversation(datasetIds.slice(0, 10));
    setActive(conv);
    setTurns([]);
    setConversations((cs) => [conv, ...cs]);
    return conv;
  }

  async function toggleDataset(id: string) {
    if (!active) return;
    const ids = active.dataset_ids.includes(id)
      ? active.dataset_ids.filter((x) => x !== id)
      : [...active.dataset_ids, id];
    try {
      setActive(await api.updateConversation(active.id, { dataset_ids: ids }));
    } catch (e) {
      showError(e);
    }
  }

  async function upload(files: File[]) {
    setUploading(true);
    setNotice(null);
    try {
      const res = await api.upload(files);
      if (res.errors.length) setNotice({ kind: "error", text: res.errors.join(" ") });
      else
        setNotice({
          kind: "info",
          text: `Added ${res.datasets.map((d) => d.table_name).join(", ")}. Ask a question below.`,
        });
      const { d } = await refreshLists();
      const newIds = res.datasets.map((x) => x.id);
      if (active) setActive(await api.updateConversation(active.id, { dataset_ids: [...active.dataset_ids, ...newIds].slice(0, 10) }));
      else if (d.length) await newAnalysis(d.map((x) => x.id));
      if (res.datasets.length === 1) setInspecting(res.datasets[0].id);
    } catch (e) {
      showError(e);
    } finally {
      setUploading(false);
    }
  }

  async function loadSamples() {
    try {
      const files = await Promise.all(
        ["sales.csv", "customers.csv", "products.csv"].map(async (name) => {
          const r = await fetch(`/samples/${name}`);
          if (!r.ok) throw new Error("Sample data is not available in this build.");
          return new File([await r.blob()], name, { type: "text/csv" });
        }),
      );
      await upload(files);
    } catch (e) {
      showError(e);
    }
  }

  async function deleteDataset(id: string) {
    try {
      await api.deleteDataset(id);
      setInspecting(null);
      await refreshLists();
      if (active) setActive({ ...active, dataset_ids: active.dataset_ids.filter((x) => x !== id) });
    } catch (e) {
      showError(e);
    }
  }

  async function deleteConversation(id: string) {
    try {
      await api.deleteConversation(id);
      setConversations((cs) => cs.filter((c) => c.id !== id));
      if (active?.id === id) {
        setActive(null);
        setTurns([]);
      }
    } catch (e) {
      showError(e);
    }
  }

  function patchLive(fn: (t: TurnView) => TurnView) {
    setTurns((ts) => (ts.length ? [...ts.slice(0, -1), fn(ts[ts.length - 1])] : ts));
  }

  async function ask(question: string) {
    setNotice(null);
    let conv = active;
    try {
      if (!conv) conv = await newAnalysis();
      if (!conv) return;
    } catch (e) {
      showError(e);
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setTurns((ts) => [...ts, { key: `live-${Date.now()}`, question, steps: [], items: [], live: true }]);

    try {
      for await (const ev of api.ask(conv.id, question, controller.signal)) {
        switch (ev.type) {
          case "step":
            patchLive((t) => ({ ...t, steps: [...t.steps, ev as Step] }));
            break;
          case "step_end":
            patchLive((t) => ({ ...t, steps: t.steps.map((s) => (s.id === ev.id ? { ...s, ...ev } : s)) }));
            break;
          case "artifact":
            patchLive((t) => ({ ...t, items: [...t.items, ev.artifact] }));
            break;
          case "answer":
            patchLive((t) => ({
              ...t,
              answer: ev.answer,
              reasoning: ev.reasoning,
              sql: ev.sql,
              pandas: ev.pandas_code,
              followUps: ev.follow_ups,
              cached: ev.cached,
            }));
            break;
          case "error":
            patchLive((t) => ({ ...t, error: ev.message }));
            break;
        }
      }
    } catch (e) {
      if (controller.signal.aborted) patchLive((t) => ({ ...t, error: "Stopped." }));
      else patchLive((t) => ({ ...t, error: e instanceof Error ? e.message : "Connection lost." }));
    } finally {
      patchLive((t) => ({ ...t, live: false }));
      setBusy(false);
      abortRef.current = null;
      api.conversations().then(setConversations).catch(() => {});
      if (conv) api.conversation(conv.id).then((d) => setActive(d)).catch(() => {});
    }
  }

  const inspected = datasets.find((d) => d.id === inspecting) ?? null;
  const noData = datasets.length === 0;
  const canAsk = !noData && (!active || active.dataset_ids.length > 0);

  return (
    <div className={`workspace ${inspected ? "with-panel" : ""}`}>
      <Sidebar
        datasets={datasets}
        conversations={conversations}
        activeConversation={active}
        inspecting={inspecting}
        uploading={uploading}
        onUpload={upload}
        onLoadSamples={loadSamples}
        onToggleDataset={toggleDataset}
        onInspect={(id) => setInspecting((cur) => (cur === id ? null : id))}
        onNewAnalysis={() => newAnalysis().catch(showError)}
        onOpenConversation={openConversation}
        onDeleteConversation={deleteConversation}
      />

      <main className="main">
        <header className="main-head">
          <div className="main-title">
            <h1>{active?.title ?? "New analysis"}</h1>
            {activeDatasets.length > 0 && (
              <p className="muted small">
                Using {activeDatasets.map((d) => d.table_name).join(", ")}
              </p>
            )}
          </div>
          {active && turns.length > 0 && (
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => api.exportReport(active.id, active.title).catch(showError)}
            >
              Export report
            </button>
          )}
        </header>

        {notice && (
          <div className={`notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
            <span>{notice.text}</span>
            <button type="button" className="icon-btn" onClick={() => setNotice(null)} aria-label="Dismiss">
              ×
            </button>
          </div>
        )}

        <div className="thread">
          {turns.length === 0 ? (
            <div className="empty">
              {noData ? (
                <>
                  <h2>Start with a CSV</h2>
                  <p>
                    Upload one or more exports from your sales, finance or operations tools. Quarry reads the columns,
                    checks the data quality, and keeps the file encrypted.
                  </p>
                  <div className="empty-actions">
                    <button type="button" className="btn btn-primary" onClick={loadSamples} disabled={uploading}>
                      {uploading ? "Loading" : "Try the sample sales data"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <h2>What do you want to know?</h2>
                  <p>Ask in plain English. Every answer shows the query it ran, so you can check the numbers.</p>
                  <div className="starters">
                    {STARTERS.map((s) => (
                      <button key={s} type="button" className="chip" onClick={() => setPrefill({ text: s, n: Date.now() })}>
                        {s}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : (
            turns.map((t) => (
              <AnswerBlock
                key={t.key}
                turn={t}
                onFollowUp={(q) => ask(q)}
                onExportCsv={(sql, name) =>
                  active && api.exportCsv(sql, active.dataset_ids, name).catch(showError)
                }
              />
            ))
          )}
          <div ref={threadEnd} />
        </div>

        <Composer
          disabled={!canAsk}
          busy={busy}
          prefill={prefill}
          placeholder={
            noData
              ? "Upload a CSV to start asking questions"
              : active && active.dataset_ids.length === 0
                ? "Tick at least one dataset on the left"
                : "Ask about your data, e.g. which products are underperforming?"
          }
          onSubmit={ask}
          onStop={() => abortRef.current?.abort()}
        />
      </main>

      {inspected && (
        <DatasetPanel dataset={inspected} onClose={() => setInspecting(null)} onDelete={deleteDataset} />
      )}
    </div>
  );
}
