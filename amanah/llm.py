"""Free LLM backends.

- ollama  : local, free, private (default). e.g. `ollama pull qwen2.5:7b`
- openai  : any OpenAI-compatible API (Groq free tier, Azure OpenAI, OpenAI...)
- none    : no LLM; agents fall back to deterministic templates

Every agent works with `none`, so tests and CI never need a model or a key.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

import httpx

PROVIDER = os.getenv("AMANAH_LLM", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OPENAI_BASE = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    ok: bool


class LLM:
    def __init__(self, provider: str | None = None):
        self.provider = (provider or PROVIDER).lower()
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = self._probe()
        return self._available

    def _probe(self) -> bool:
        if self.provider == "none":
            return False
        if self.provider == "openai":
            return bool(OPENAI_KEY)
        try:
            return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    @property
    def model(self) -> str:
        return {"ollama": OLLAMA_MODEL, "openai": OPENAI_MODEL}.get(self.provider, "template")

    def chat(self, system: str, user: str, temperature: float = 0.1, json_mode: bool = False) -> LLMResult:
        if not self.available:
            return LLMResult("", "none", "template", 0, False)
        t0 = time.perf_counter()
        try:
            if self.provider == "ollama":
                body = {"model": OLLAMA_MODEL, "stream": False, "options": {"temperature": temperature},
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
                if json_mode:
                    body["format"] = "json"
                r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=180)
                r.raise_for_status()
                text = r.json()["message"]["content"]
            else:
                body = {"model": OPENAI_MODEL, "temperature": temperature,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                r = httpx.post(f"{OPENAI_BASE}/chat/completions", json=body, timeout=120,
                               headers={"Authorization": f"Bearer {OPENAI_KEY}"})
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
            return LLMResult(text, self.provider, self.model, int((time.perf_counter() - t0) * 1000), True)
        except (httpx.HTTPError, KeyError, ValueError):
            return LLMResult("", self.provider, self.model, int((time.perf_counter() - t0) * 1000), False)

    def chat_json(self, system: str, user: str) -> tuple[dict | None, LLMResult]:
        res = self.chat(system, user, json_mode=True)
        if not res.ok:
            return None, res
        match = re.search(r"\{.*\}", res.text, re.S)
        try:
            return (json.loads(match.group(0)) if match else None), res
        except json.JSONDecodeError:
            return None, res


_default: LLM | None = None


def get_llm() -> LLM:
    global _default
    if _default is None:
        _default = LLM()
    return _default


def set_llm(llm: LLM) -> None:
    global _default
    _default = llm
