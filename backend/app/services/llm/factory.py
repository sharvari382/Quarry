from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.llm.base import LLMClient


@lru_cache
def get_llm() -> LLMClient:
    s = get_settings()
    if s.llm_provider == "anthropic" and s.anthropic_api_key:
        from app.services.llm.anthropic_client import AnthropicClient

        return AnthropicClient(s.anthropic_api_key, s.llm_model, s.llm_timeout_seconds)
    if s.llm_provider == "openai" and s.openai_api_key:
        from app.services.llm.openai_client import OpenAIClient

        return OpenAIClient(s.openai_api_key, s.llm_model, s.llm_timeout_seconds, s.openai_base_url)
    from app.services.llm.fake import FakeClient

    return FakeClient()
