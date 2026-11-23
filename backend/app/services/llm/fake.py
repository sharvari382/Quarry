"""Deterministic LLM stand-in for tests and for running the app without an API key.

Tests push scripted responses with `FakeClient.script(...)`. With no script, it
falls back to an "offline mode": profile the first table, then answer with a
notice that no model is configured. That keeps the UI demoable end to end.
"""
from __future__ import annotations

import copy
import re
import threading
from collections import deque

from app.services.llm.base import LLMResponse, ToolCall


class FakeClient:
    provider = "fake"
    _queue: deque[LLMResponse] = deque()
    _lock = threading.Lock()
    calls: list[dict] = []

    @classmethod
    def script(cls, *responses: LLMResponse) -> None:
        with cls._lock:
            cls._queue.extend(responses)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._queue.clear()
            cls.calls.clear()

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> LLMResponse:
        with self._lock:
            self.calls.append({"system": system, "messages": copy.deepcopy(messages)})
            if self._queue:
                return self._queue.popleft()
        return self._offline(system, messages)

    @staticmethod
    def _offline(system: str, messages: list[dict]) -> LLMResponse:
        last = messages[-1]
        already_profiled = isinstance(last["content"], list) and any(
            b.get("type") == "tool_result" for b in last["content"])
        table = (re.findall(r"^TABLE (\w+)", system, re.MULTILINE) or [None])[0]
        if table and not already_profiled:
            return LLMResponse(text="", stop_reason="tool_use",
                               tool_calls=[ToolCall(id="offline-1", name="profile_table", input={"table": table})])
        return LLMResponse(text="", stop_reason="tool_use", tool_calls=[ToolCall(
            id="offline-2", name="final_answer", input={
                "answer": "Running in **offline mode**: no LLM provider is configured, so I can only show a "
                          "profile of your data. Set `LLM_PROVIDER` and an API key in `.env` to ask questions.",
                "reasoning": ["No LLM_PROVIDER configured", "Profiled the first table instead"],
                "follow_ups": [],
            })])
