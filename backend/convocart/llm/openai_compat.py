"""One client for every hosted or local provider that speaks the OpenAI chat-completions API.

Choose with LLM_PROVIDER. Default model names are starting points only: free-tier models and
limits change often, so check each provider's current list and set LLM_MODEL.
"""
from __future__ import annotations

import json
import random
import time

import httpx

from .base import ModelError, ModelReply, ToolCall

PROVIDERS: dict[str, dict] = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.3-70b-instruct:free"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash"},
    # Ollama: data never leaves the machine. Needs a model with tool calling, e.g. qwen2.5:7b-instruct.
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b-instruct"},
}


class OpenAICompatModel:
    def __init__(self, provider: str, model: str = "", api_key: str = "", base_url: str = "",
                 timeout_s: float = 60, max_retries: int = 3, client: httpx.Client | None = None):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider}")
        preset = PROVIDERS[provider]
        self.provider = provider
        self.model = model or preset["model"]
        self.base_url = (base_url or preset["base_url"]).rstrip("/")
        self.api_key = api_key or ("ollama" if provider == "ollama" else "")
        if not self.api_key:
            raise ValueError(f"LLM_API_KEY is required for {provider}")
        self.max_retries = max_retries
        self.client = client or httpx.Client(timeout=timeout_s)
        self.name = f"{provider}:{self.model}"

    def chat(self, messages, tools=None, tool_choice=None) -> ModelReply:
        body: dict = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.provider == "openrouter":
            headers["X-Title"] = "ConvoCart"
        last_err = ""
        for attempt in range(self.max_retries + 1):
            t0 = time.perf_counter()
            wait = min(8.0, (2 ** attempt) + random.random())
            try:
                r = self.client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as e:
                last_err = f"network: {e}"
            else:
                if r.status_code == 200:
                    return self._parse(r.json(), (time.perf_counter() - t0) * 1000)
                last_err = f"HTTP {r.status_code}: {r.text[:500]}"
                if r.status_code not in (408, 429, 500, 502, 503, 504):
                    break
                retry_after = r.headers.get("retry-after")
                if retry_after and retry_after.replace(".", "").isdigit():
                    if float(retry_after) > 30:
                        break  # daily quota hit; do not sit and wait
                    wait = float(retry_after) + random.random()  # per-minute limit: wait exactly as told
            if attempt < self.max_retries:
                time.sleep(wait)
        raise ModelError(f"{self.name} failed: {last_err}")

    def _parse(self, data: dict, latency_ms: float) -> ModelReply:
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise ModelError(f"unexpected response: {str(data)[:300]}") from e
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                args = raw  # passed back to the tool runner, which reports invalid_arguments
            calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args))
        return ModelReply(content=msg.get("content") or "", tool_calls=calls, model=data.get("model", self.model),
                          usage=data.get("usage") or {}, latency_ms=latency_ms)
