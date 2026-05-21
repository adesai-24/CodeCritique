"""
LLM provider abstraction layer.

Defines the LLMProvider protocol and concrete implementations for:
  - OllamaProvider  (local, free)
  - AnthropicProvider (cloud, requires ANTHROPIC_API_KEY)
  - OpenAIProvider    (cloud, requires OPENAI_API_KEY)

Use get_llm_provider(config) to obtain the correct provider.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional, runtime_checkable, Protocol

from critique.config import Config


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMProvider(Protocol):
    """Minimal interface every provider must implement."""

    def is_available(self) -> bool: ...

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str: ...

    def complete_json(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Any: ...

    def complete_stream(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.2,
    ) -> Iterable[str]: ...


# ---------------------------------------------------------------------------
# Ollama provider (wraps the existing LLMClient)
# ---------------------------------------------------------------------------

class OllamaProvider:
    """Local Ollama backend — the default provider."""

    def __init__(self, base_url: str, model: str, timeout: int = 300):
        from critique.ai.client import LLMClient
        self._client = LLMClient(base_url=base_url, model=model, timeout=timeout)

    def is_available(self) -> bool:
        return self._client.is_available()

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        return self._client.complete(system, user, temperature)

    def complete_json(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return self._client.complete_json(system, user, schema)

    def complete_stream(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.2,
    ) -> Iterable[str]:
        return self._client.complete_stream(system, user, messages, temperature)


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

# Approximate cost per token (USD) for cost-guard estimation.
# Values are per-input-token; output is typically 3–5× more expensive but
# we use a conservative flat rate as a guard, not an invoice.
_ANTHROPIC_COST_PER_TOKEN: Dict[str, float] = {
    "claude-haiku-4-5-20251001": 0.00000025,
    "claude-sonnet-4-6": 0.000003,
    "claude-opus-4-7": 0.000015,
}
_ANTHROPIC_DEFAULT_COST_PER_TOKEN = 0.000003  # sonnet-class default


class AnthropicProvider:
    """Cloud provider via the Anthropic Python SDK."""

    MAX_COST_PER_RUN = 0.50  # USD — hard reject above this

    def __init__(self, model: str, api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._cost_per_token = _ANTHROPIC_COST_PER_TOKEN.get(
            model, _ANTHROPIC_DEFAULT_COST_PER_TOKEN
        )
        self._session_cost: float = 0.0

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _check_cost(self, prompt: str) -> None:
        """Rough token estimate; reject if projected cost would exceed the cap."""
        estimated_tokens = len(prompt) // 4  # ~4 chars per token
        estimated_cost = estimated_tokens * self._cost_per_token
        if self._session_cost + estimated_cost > self.MAX_COST_PER_RUN:
            raise RuntimeError(
                f"Estimated run cost ${self._session_cost + estimated_cost:.3f} "
                f"exceeds the ${self.MAX_COST_PER_RUN:.2f} cap. "
                "Reduce input size or raise the limit in your config."
            )

    def _record_usage(self, input_tokens: int, output_tokens: int) -> float:
        cost = (input_tokens + output_tokens * 3) * self._cost_per_token
        self._session_cost += cost
        return cost

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        self._check_cost(system + user)
        client = anthropic.Anthropic(api_key=self._api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=2048,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        cost = self._record_usage(msg.usage.input_tokens, msg.usage.output_tokens)
        _print_cost(cost)
        return msg.content[0].text

    def complete_json(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Any:
        # Anthropic doesn't have a native JSON mode; ask the model directly.
        json_system = system + "\n\nRespond ONLY with valid JSON. No markdown, no commentary."
        raw = self.complete(json_system, user, temperature=0.1)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)

    def complete_stream(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.2,
    ) -> Iterable[str]:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        self._check_cost(system + user)
        client = anthropic.Anthropic(api_key=self._api_key)
        chat_messages = list(messages or [])
        chat_messages.append({"role": "user", "content": user})

        with client.messages.stream(
            model=self.model,
            max_tokens=2048,
            temperature=temperature,
            system=system,
            messages=chat_messages,
        ) as stream:
            for text in stream.text_stream:
                yield text

        usage = stream.get_final_message().usage
        cost = self._record_usage(usage.input_tokens, usage.output_tokens)
        _print_cost(cost)


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

_OPENAI_COST_PER_TOKEN: Dict[str, float] = {
    "gpt-4o-mini": 0.00000015,
    "gpt-4o": 0.0000025,
    "gpt-4-turbo": 0.00001,
}
_OPENAI_DEFAULT_COST_PER_TOKEN = 0.0000025


class OpenAIProvider:
    """Cloud provider via the OpenAI Python SDK."""

    MAX_COST_PER_RUN = 0.50

    def __init__(self, model: str, api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._cost_per_token = _OPENAI_COST_PER_TOKEN.get(
            model, _OPENAI_DEFAULT_COST_PER_TOKEN
        )
        self._session_cost: float = 0.0

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _check_cost(self, prompt: str) -> None:
        estimated_tokens = len(prompt) // 4
        estimated_cost = estimated_tokens * self._cost_per_token
        if self._session_cost + estimated_cost > self.MAX_COST_PER_RUN:
            raise RuntimeError(
                f"Estimated run cost ${self._session_cost + estimated_cost:.3f} "
                f"exceeds the ${self.MAX_COST_PER_RUN:.2f} cap."
            )

    def _record_usage(self, input_tokens: int, output_tokens: int) -> float:
        cost = (input_tokens + output_tokens * 3) * self._cost_per_token
        self._session_cost += cost
        return cost

    def _build_messages(
        self,
        system: str,
        user: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        msgs = [{"role": "system", "content": system}]
        msgs.extend(history or [])
        msgs.append({"role": "user", "content": user})
        return msgs

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )
        self._check_cost(system + user)
        client = OpenAI(api_key=self._api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=self._build_messages(system, user),
            temperature=temperature,
        )
        usage = response.usage
        cost = self._record_usage(usage.prompt_tokens, usage.completion_tokens)
        _print_cost(cost)
        return response.choices[0].message.content or ""

    def complete_json(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Any:
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )
        self._check_cost(system + user)
        client = OpenAI(api_key=self._api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=self._build_messages(system, user),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        usage = response.usage
        cost = self._record_usage(usage.prompt_tokens, usage.completion_tokens)
        _print_cost(cost)
        raw = response.choices[0].message.content or "{}"
        return json.loads(raw)

    def complete_stream(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.2,
    ) -> Iterable[str]:
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )
        self._check_cost(system + user)
        client = OpenAI(api_key=self._api_key)
        stream = client.chat.completions.create(
            model=self.model,
            messages=self._build_messages(system, user, messages),
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm_provider(config: Config) -> LLMProvider:
    """
    Return the appropriate LLMProvider based on the active config.

    Falls back to OllamaProvider when the requested cloud provider has no API key.
    """
    provider = config.provider.lower()

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            return AnthropicProvider(model=config.model, api_key=key)
        raise RuntimeError(
            "provider = 'anthropic' but ANTHROPIC_API_KEY is not set. "
            "Export it or switch provider to 'ollama'."
        )

    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            return OpenAIProvider(model=config.model, api_key=key)
        raise RuntimeError(
            "provider = 'openai' but OPENAI_API_KEY is not set. "
            "Export it or switch provider to 'ollama'."
        )

    # Default: Ollama
    return OllamaProvider(
        base_url=config.ollama.base_url,
        model=config.model,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_cost(cost: float) -> None:
    """Print per-call cost estimate to stderr when using a cloud provider."""
    import sys
    print(f"[cloud] estimated cost this call: ${cost:.5f}", file=sys.stderr)
