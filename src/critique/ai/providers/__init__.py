"""
Provider registry and factory.

A *provider* is a thin adapter that knows how to talk to one LLM backend
(Gemini, OpenAI, Anthropic, a local Ollama server, a vLLM endpoint, …).  The
caching, semantic-dedup, and KV-prefix machinery lives one layer up in
:class:`critique.ai.client.LLMClient`; providers only implement the raw
round-trip and an availability check.

The Ollama provider is intentionally defined *inside* ``client.py`` (not here)
so its HTTP calls share the same ``requests`` module the client's tests patch.
This factory therefore handles every provider *except* ollama; the client
constructs ``OllamaProvider`` directly.
"""

from __future__ import annotations

from typing import Optional

from critique.config import CritiqueConfig, DEFAULT_MODELS
from critique.ai.providers.base import Provider, ProviderError


def build_provider(
    name: str,
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: int = 300,
    config: Optional[CritiqueConfig] = None,
    api_key: Optional[str] = None,
) -> Provider:
    """Construct a cloud / remote provider by name.

    ``ollama`` is *not* handled here (see module docstring) — calling this with
    ``"ollama"`` raises, which is a programming error in the client.
    """
    name = (name or "").strip().lower()
    resolved_model = model or DEFAULT_MODELS.get(name)

    if name == "gemini":
        from critique.ai.providers.gemini import GeminiProvider
        return GeminiProvider(model=resolved_model, timeout=timeout, api_key=api_key)

    if name in {"openai", "vllm"}:
        # vLLM speaks the OpenAI Chat Completions API, so one adapter covers
        # both; they differ only in default base_url and whether a key is
        # required.
        from critique.ai.providers.openai_compat import OpenAICompatibleProvider
        return OpenAICompatibleProvider(
            model=resolved_model,
            timeout=timeout,
            base_url=base_url,
            api_key=api_key,
            flavor=name,
        )

    if name == "anthropic":
        from critique.ai.providers.anthropic import AnthropicProvider
        return AnthropicProvider(model=resolved_model, timeout=timeout, api_key=api_key)

    raise ProviderError(f"Unknown or non-cloud provider: {name!r}")


__all__ = ["Provider", "ProviderError", "build_provider"]
