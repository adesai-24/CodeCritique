"""
Google Gemini provider (default, free tier) built on the official
``google-genai`` SDK.

Gemini is CodeCritique's default hosted provider, so ``google-genai`` is part of
the base install rather than an optional extra.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from critique.ai.providers.base import Provider, ProviderError
from critique.secrets_store import get_api_key


class GeminiProvider(Provider):
    name = "gemini"
    supports_prefix_cache = False

    def __init__(self, model: str, timeout: int = 300, api_key: Optional[str] = None):
        super().__init__(model=model, timeout=timeout)
        self._api_key = api_key or get_api_key("gemini")
        self._client = None  # lazily constructed

    # -- internals ----------------------------------------------------------
    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(self.unavailable_message())
        try:
            from google import genai  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError(
                "The google-genai package is missing from this install. "
                "Reinstall CodeCritique from the latest release."
            ) from exc
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key)

    def unavailable_message(self) -> str:
        return (
            "No Gemini API key found. Get a free key at "
            "https://aistudio.google.com/apikey and run: "
            "codecritique config set-key gemini <KEY>"
        )

    def _gen_config(self, *, temperature: float, system: str, json_mode: bool):
        from google.genai import types  # type: ignore

        return types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else "text/plain",
        )

    # -- generation ---------------------------------------------------------
    def complete_text(self, system: str, user: str, *, temperature: float) -> str:
        client = self._get_client()
        resp = client.models.generate_content(
            model=self.model,
            contents=user,
            config=self._gen_config(temperature=temperature, system=system, json_mode=False),
        )
        return resp.text or ""

    def complete_json(self, system: str, user: str, *, schema: Optional[Dict] = None) -> str:
        client = self._get_client()
        resp = client.models.generate_content(
            model=self.model,
            contents=user,
            config=self._gen_config(temperature=0.1, system=system, json_mode=True),
        )
        return resp.text or "{}"

    def stream(
        self,
        system: str,
        history: List[Dict[str, str]],
        user: str,
        *,
        temperature: float,
    ) -> Iterable[str]:
        from google.genai import types  # type: ignore

        client = self._get_client()
        # Map our role/content history to Gemini "contents". Gemini uses
        # "model" instead of "assistant".
        contents = []
        for msg in history:
            role = "model" if msg.get("role") == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=msg.get("content", ""))])
            )
        contents.append(types.Content(role="user", parts=[types.Part(text=user)]))

        stream = client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=self._gen_config(temperature=temperature, system=system, json_mode=False),
        )
        for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text
