"""Provider-neutral LLM interface.

Messages use a block format (text / tool_use / tool_result) close to the
Anthropic wire format; the OpenAI adapter converts to and from it. The agent
never imports a vendor SDK directly, which keeps providers swappable and lets
tests run against a scripted fake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class LLMError(Exception):
    """Raised for provider failures after retries. Message is safe to show users."""


class LLMClient(Protocol):
    provider: str

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> LLMResponse: ...
