"""
Anthropic Claude provider built on the official ``anthropic`` SDK (lazy import).

Claude has no dedicated JSON mode, so :meth:`complete_json` appends a short
instruction and strips any accidental markdown fences before returning the raw
JSON string for the client to parse.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from critique.ai.providers.base import Provider, ProviderError
from critique.secrets_store import get_api_key

DEFAULT_MAX_TOKENS = 2048


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # ```json\n...\n``` → ...
        inner = text.split("```", 2)
        if len(inner) >= 2:
            body = inner[1]
            if body.startswith("json"):
                body = body[4:]
            return body.strip()
    return text


class AnthropicProvider(Provider):
    name = "anthropic"
    supports_prefix_cache = False

    def __init__(self, model: str, timeout: int = 300, api_key: Optional[str] = None):
        super().__init__(model=model, timeout=timeout)
        self._api_key = api_key or get_api_key("anthropic")
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(self.unavailable_message())
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError(
                "The anthropic package is required for the Anthropic provider. "
                "Install it with: pip install 'codecritique[cloud]'"
            ) from exc
        self._client = anthropic.Anthropic(api_key=self._api_key, timeout=self.timeout)
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key)

    def unavailable_message(self) -> str:
        return "No Anthropic API key found. Run: codecritique config set-key anthropic <KEY>"

    def complete_text(self, system: str, user: str, *, temperature: float) -> str:
        client = self._get_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system or "",
            temperature=temperature,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text if resp.content else ""

    def complete_json(self, system: str, user: str, *, schema: Optional[Dict] = None) -> str:
        client = self._get_client()
        json_user = user + "\n\nReturn ONLY a valid JSON object, no prose, no markdown fences."
        resp = client.messages.create(
            model=self.model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system or "",
            temperature=0.1,
            messages=[{"role": "user", "content": json_user}],
        )
        raw = resp.content[0].text if resp.content else "{}"
        return _strip_code_fence(raw)

    def stream(
        self,
        system: str,
        history: List[Dict[str, str]],
        user: str,
        *,
        temperature: float,
    ) -> Iterable[str]:
        client = self._get_client()
        messages = list(history) + [{"role": "user", "content": user}]
        with client.messages.stream(
            model=self.model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system or "",
            temperature=temperature,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text
