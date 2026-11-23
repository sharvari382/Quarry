"""The analysis agent: an LLM tool-calling loop that streams progress events.

Event types (sent to the browser over Server-Sent Events):
  step      a tool started            {id, tool, label, input}
  step_end  a tool finished           {id, ok, elapsed_ms, error?}
  artifact  chart / table / anomalies / profile to render
  answer    the final structured answer
  error     a user-safe error message
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.config import get_settings
from app.logging_setup import log_event
from app.models import Dataset, Message
from app.observability import LLM_CALLS, LLM_TOKENS, TOOL_CALLS
from app.security.rate_limit import enforce_daily_llm_quota
from app.services.kv import get_kv
from app.services.llm.base import LLMClient, LLMError
from app.services.prompts import PROMPT_VERSION, build_system_prompt
from app.services.tools import TOOLS, ToolExecutor

log = logging.getLogger(__name__)

_LABELS = {
    "run_sql": "Querying data",
    "create_chart": "Building chart",
    "detect_anomalies": "Scanning for anomalies",
    "profile_table": "Profiling table",
    "forecast": "Forecasting",
}


@dataclass
class TurnResult:
    answer: str = ""
    artifacts: dict = field(default_factory=lambda: {
        "steps": [], "items": [], "sql": [], "reasoning": [], "pandas_code": None, "follow_ups": []})
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0})


def history_to_messages(history: list[Message], limit: int) -> list[dict]:
    """Replay prior turns as plain text. Tool traces are not replayed (token cost);
    the SQL behind each earlier answer is, so follow-ups like "now by month" or
    "show me the SQL for that" have what they need."""
    msgs: list[dict] = []
    for m in history[-limit:]:
        if m.role == "user":
            msgs.append({"role": "user", "content": m.content})
        else:
            text = m.content
            sqls = (m.artifacts or {}).get("sql") or []
            if sqls:
                text += "\n\n[SQL used for this answer]\n" + "\n;\n".join(sqls[-3:])
            msgs.append({"role": "assistant", "content": text})
    # Providers require alternating roles starting with user; drop leading assistant turns.
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def _answer_cache_key(datasets: list[Dataset], question: str, model: str) -> str:
    h = hashlib.sha256(f"{PROMPT_VERSION}|{model}|{' '.join(question.lower().split())}".encode())
    for d in sorted(datasets, key=lambda d: d.table_name):
        h.update(d.sha256.encode())
    return "ans:" + h.hexdigest()


class Agent:
    def __init__(self, llm: LLMClient, datasets: list[Dataset], user_id: str) -> None:
        self.llm = llm
        self.datasets = datasets
        self.user_id = user_id
        self.tools = ToolExecutor(datasets)
        self.settings = get_settings()

    def run(self, question: str, history: list[Message], result: TurnResult) -> Iterator[dict]:
        s = self.settings
        model_name = getattr(self.llm, "model", self.llm.provider)
        cache_key = _answer_cache_key(self.datasets, question, model_name)
        kv = get_kv()

        # Only first questions are cacheable: later ones depend on conversation context.
        if not history and (cached := kv.get(cache_key)):
            data = json.loads(cached)
            result.answer, result.artifacts = data["answer"], data["artifacts"]
            result.artifacts["cached"] = True
            for item in result.artifacts["items"]:
                yield {"type": "artifact", "artifact": item}
            yield {"type": "answer", **self._answer_payload(result)}
            return

        system = build_system_prompt(self.datasets)
        messages = history_to_messages(history, s.history_messages) + [{"role": "user", "content": question}]
        step_no = 0

        for _ in range(s.llm_max_tool_steps + 1):
            enforce_daily_llm_quota(self.user_id)
            started = time.perf_counter()
            try:
                resp = self.llm.complete(system, messages, TOOLS, s.llm_max_tokens)
                LLM_CALLS.labels(self.llm.provider, "ok").inc()
            except LLMError as exc:
                LLM_CALLS.labels(self.llm.provider, "error").inc()
                yield {"type": "error", "message": str(exc)}
                return
            result.usage["llm_calls"] += 1
            result.usage["input_tokens"] += resp.input_tokens
            result.usage["output_tokens"] += resp.output_tokens
            LLM_TOKENS.labels(self.llm.provider, "input").inc(resp.input_tokens)
            LLM_TOKENS.labels(self.llm.provider, "output").inc(resp.output_tokens)
            log_event(log, "llm_call", provider=self.llm.provider, tools=[t.name for t in resp.tool_calls],
                      ms=int((time.perf_counter() - started) * 1000), in_tok=resp.input_tokens,
                      out_tok=resp.output_tokens)

            if not resp.tool_calls:
                # Model answered in prose without calling final_answer: accept it.
                result.answer = resp.text.strip() or "I could not produce an answer for that question."
                yield {"type": "answer", **self._answer_payload(result)}
                return

            assistant_blocks: list[dict] = []
            if resp.text:
                assistant_blocks.append({"type": "text", "text": resp.text})
            tool_results: list[dict] = []
            final = None

            for call in resp.tool_calls:
                assistant_blocks.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.input})
                if call.name == "final_answer":
                    final = self.tools.execute("final_answer", call.input).final
                    tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": "ok"})
                    continue

                step_no += 1
                step_id = f"s{step_no}"
                yield {"type": "step", "id": step_id, "tool": call.name,
                       "label": _LABELS.get(call.name, call.name), "input": _short_input(call.input)}
                t0 = time.perf_counter()
                outcome = self.tools.execute(call.name, call.input)
                elapsed = int((time.perf_counter() - t0) * 1000)
                TOOL_CALLS.labels(call.name, "error" if outcome.is_error else "ok").inc()

                step = {"id": step_id, "tool": call.name, "label": _LABELS.get(call.name, call.name),
                        "input": _short_input(call.input), "ok": not outcome.is_error, "elapsed_ms": elapsed}
                if outcome.is_error:
                    step["error"] = outcome.model_content
                result.artifacts["steps"].append(step)
                result.artifacts["sql"].extend(outcome.sql)
                yield {"type": "step_end", **step}
                if outcome.ui:
                    outcome.ui["id"] = step_id
                    result.artifacts["items"].append(outcome.ui)
                    yield {"type": "artifact", "artifact": outcome.ui}
                tool_results.append({"type": "tool_result", "tool_use_id": call.id,
                                     "content": outcome.model_content, "is_error": outcome.is_error})

            if final is not None:
                result.answer = final["answer"]
                result.artifacts["reasoning"] = final["reasoning"]
                result.artifacts["pandas_code"] = final["pandas_code"]
                result.artifacts["follow_ups"] = final["follow_ups"]
                if final["sql"]:
                    result.artifacts["final_sql"] = final["sql"]
                yield {"type": "answer", **self._answer_payload(result)}
                if not history and not any(not st["ok"] for st in result.artifacts["steps"]):
                    kv.set(cache_key, json.dumps({"answer": result.answer, "artifacts": result.artifacts},
                                                 default=str).encode(), 3600)
                return

            messages.append({"role": "assistant", "content": assistant_blocks})
            messages.append({"role": "user", "content": tool_results})

        result.answer = ("I hit the step limit before reaching a confident answer. The intermediate results "
                         "are shown above; try a narrower question.")
        yield {"type": "answer", **self._answer_payload(result)}

    @staticmethod
    def _answer_payload(result: TurnResult) -> dict:
        a = result.artifacts
        return {"answer": result.answer, "reasoning": a.get("reasoning", []), "sql": a.get("final_sql"),
                "pandas_code": a.get("pandas_code"), "follow_ups": a.get("follow_ups", []),
                "cached": a.get("cached", False)}


def _short_input(args: dict) -> dict:
    return {k: (v if not isinstance(v, str) or len(v) < 600 else v[:600] + "...") for k, v in args.items()}
