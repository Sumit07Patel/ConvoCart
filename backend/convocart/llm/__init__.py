"""Swappable model wrapper: pick the provider with LLM_PROVIDER, nothing else changes."""
from __future__ import annotations

from ..config import Settings, get_settings
from .base import ChatModel, ModelError, ModelReply, ToolCall  # noqa: F401


def get_model(settings: Settings | None = None) -> ChatModel:
    st = settings or get_settings()
    if st.llm_provider == "scripted":
        from .scripted import ScriptedModel
        return ScriptedModel()
    from .openai_compat import OpenAICompatModel
    return OpenAICompatModel(st.llm_provider, model=st.llm_model, api_key=st.llm_api_key,
                             base_url=st.llm_base_url, timeout_s=st.llm_timeout_s)
