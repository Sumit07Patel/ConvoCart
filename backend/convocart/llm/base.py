"""Provider-neutral model interface. Messages use the OpenAI chat format, which Groq, OpenRouter,
Gemini's OpenAI-compatible endpoint and Ollama all accept."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict | str  # str when the model produced invalid JSON


@dataclass
class ModelReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0


class ChatModel(Protocol):
    name: str

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             tool_choice: str | dict | None = None) -> ModelReply: ...


class ModelError(Exception):
    """Raised when the provider fails after retries (quota, network, bad response)."""
