"""OpenAI (or any OpenAI-compatible endpoint: Azure, vLLM, Ollama) adapter."""
from __future__ import annotations

import json
import logging

from app.services.llm.base import LLMError, LLMResponse, ToolCall

log = logging.getLogger(__name__)


def _to_openai(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        texts = [b["text"] for b in content if b["type"] == "text"]
        tool_uses = [b for b in content if b["type"] == "tool_use"]
        tool_results = [b for b in content if b["type"] == "tool_result"]
        if m["role"] == "assistant":
            msg: dict = {"role": "assistant", "content": "\n".join(texts) or None}
            if tool_uses:
                msg["tool_calls"] = [{"id": b["id"], "type": "function",
                                      "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                                     for b in tool_uses]
            out.append(msg)
        else:
            for r in tool_results:
                out.append({"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]})
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    return out


class OpenAIClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str, timeout: float, base_url: str | None = None) -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=3)
        self._errors = openai
        self.model = model

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> LLMResponse:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=_to_openai(system, messages),
                tools=[{"type": "function", "function": t} for t in tools],
                max_completion_tokens=max_tokens,
            )
        except self._errors.RateLimitError as exc:
            raise LLMError("The AI provider is rate limiting us. Please retry in a minute.") from exc
        except self._errors.APIStatusError as exc:
            # Log the provider's own message server side (never sent to the browser) so
            # misconfiguration (bad key, unknown model, unsupported parameter) is diagnosable.
            log.warning("openai status error %s: %s", exc.status_code, str(exc.message)[:500])
            raise LLMError("The AI provider returned an error. Please retry.") from exc
        except self._errors.APIConnectionError as exc:
            raise LLMError("Could not reach the AI provider.") from exc

        choice = resp.choices[0]
        calls = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))
        usage = resp.usage
        return LLMResponse(text=choice.message.content or "", tool_calls=calls,
                           stop_reason="tool_use" if calls else "end_turn",
                           input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                           output_tokens=getattr(usage, "completion_tokens", 0) or 0)
