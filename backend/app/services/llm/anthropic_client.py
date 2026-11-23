from __future__ import annotations

import logging

from app.services.llm.base import LLMError, LLMResponse, ToolCall

log = logging.getLogger(__name__)


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        import anthropic

        # The SDK retries 429/5xx with exponential backoff; 3 tries is enough for interactive use.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=3)
        self._errors = anthropic
        self.model = model

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> LLMResponse:
        try:
            resp = self._client.messages.create(
                model=self.model,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                       for t in tools],
                max_tokens=max_tokens,
            )
        except self._errors.RateLimitError as exc:
            raise LLMError("The AI provider is rate limiting us. Please retry in a minute.") from exc
        except self._errors.APIStatusError as exc:
            log.warning("anthropic status error %s", exc.status_code)
            raise LLMError("The AI provider returned an error. Please retry.") from exc
        except self._errors.APIConnectionError as exc:
            raise LLMError("Could not reach the AI provider.") from exc

        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(id=b.id, name=b.name, input=dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return LLMResponse(text=text, tool_calls=calls, stop_reason=resp.stop_reason or "end_turn",
                           input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
