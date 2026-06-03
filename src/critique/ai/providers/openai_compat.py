"""
OpenAI and OpenAI-compatible provider (covers OpenAI itself and vLLM).

vLLM exposes the OpenAI Chat Completions API, so the same adapter serves both;
they differ only in the default ``base_url`` and whether an API key is required.
The ``openai`` SDK is imported lazily.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from critique.ai.providers.base import Provider, ProviderError
from critique.secrets_store import get_api_key

# Default endpoint for a locally-served vLLM OpenAI-compatible server.
DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"


class OpenAICompatibleProvider(Provider):
    supports_prefix_cache = False

    def __init__(
        self,
        model: str,
        timeout: int = 300,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        flavor: str = "openai",
    ):
        super().__init__(model=model, timeout=timeout)
        self.flavor = flavor
        self.name = flavor  # "openai" or "vllm" — distinguishes cache entries
        self.base_url = base_url or (DEFAULT_VLLM_BASE_URL if flavor == "vllm" else None)
        self._api_key = api_key or get_api_key(flavor)
        # vLLM commonly runs unauthenticated; the SDK still wants *some* key.
        if flavor == "vllm" and not self._api_key:
            self._api_key = "EMPTY"
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(self.unavailable_message())
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError(
                "The openai package is required for this provider. "
                "Install it with: pip install 'codecritique[cloud]'"
            ) from exc
        kwargs: Dict = {"api_key": self._api_key, "timeout": self.timeout}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def is_available(self) -> bool:
        # vLLM is "available" if a base_url is configured (key optional);
        # hosted OpenAI requires a real key.
        if self.flavor == "vllm":
            return bool(self.base_url)
        return bool(self._api_key)

    def unavailable_message(self) -> str:
        if self.flavor == "vllm":
            return (
                "No vLLM endpoint configured. Start a server and set: "
                "codecritique config set base_url http://localhost:8000/v1"
            )
        return (
            "No OpenAI API key found. Run: codecritique config set-key openai <KEY>"
        )

    def _messages(self, system: str, user: str, history: Optional[List[Dict[str, str]]] = None):
        msgs: List[Dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(history or [])
        msgs.append({"role": "user", "content": user})
        return msgs

    def complete_text(self, system: str, user: str, *, temperature: float) -> str:
        client = self._get_client()
        resp = client.chat.completions.create(
            model=self.model,
            messages=self._messages(system, user),
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""

    def complete_json(self, system: str, user: str, *, schema: Optional[Dict] = None) -> str:
        client = self._get_client()
        resp = client.chat.completions.create(
            model=self.model,
            messages=self._messages(system, user),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or "{}"

    def stream(
        self,
        system: str,
        history: List[Dict[str, str]],
        user: str,
        *,
        temperature: float,
    ) -> Iterable[str]:
        client = self._get_client()
        stream = client.chat.completions.create(
            model=self.model,
            messages=self._messages(system, user, history),
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
