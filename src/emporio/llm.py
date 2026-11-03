"""LLM provider configuration.

A single OpenAI-compatible client covers many providers by changing only the
base URL: Gemini (default), OpenAI, Groq, OpenRouter, a local Ollama, etc.
The API key comes from the UI (kept in session memory only) or from `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

PROVIDER_PRESETS = {
    "Gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_url": "https://platform.openai.com/api-keys",
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_url": "https://console.groq.com/keys",
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.5-flash",
        "key_url": "https://openrouter.ai/keys",
    },
    "Ollama (local)": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "key_url": None,  # no key needed; any value works
    },
}
DEFAULT_PROVIDER = "Gemini"


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float = 0.2

    @classmethod
    def from_env(cls) -> "LLMConfig":
        load_dotenv()
        preset = PROVIDER_PRESETS[DEFAULT_PROVIDER]
        return cls(
            base_url=os.getenv("LLM_BASE_URL") or preset["base_url"],
            model=os.getenv("LLM_MODEL") or preset["model"],
            api_key=os.getenv("LLM_API_KEY", ""),
        )

    def client(self) -> OpenAI:
        # Local servers such as Ollama ignore the key, but the SDK requires one.
        return OpenAI(base_url=self.base_url, api_key=self.api_key or "not-needed", max_retries=2)
