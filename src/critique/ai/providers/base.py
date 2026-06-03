"""
Provider interface shared by every LLM backend.

A provider returns the model's *raw assistant text*.  JSON parsing,
caching, and retries are the client's job — keeping providers this thin makes
them trivial to add and to unit-test with a mocked SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Optional


class ProviderError(RuntimeError):
    """Raised for provider construction / configuration problems."""


class Provider(ABC):
    """Adapter for a single LLM backend."""

    #: Short identifier, e.g. ``"gemini"``.  Used in cache keys so responses
    #: from different backends never collide.
    name: str = "base"

    #: Whether the backend benefits from serialising same-system-prompt calls
    #: to reuse a KV prefix cache (true for local Ollama, false for stateless
    #: cloud HTTP APIs where serialising would only hurt throughput).
    supports_prefix_cache: bool = False

    def __init__(self, model: str, timeout: int = 300):
        self.model = model
        self.timeout = timeout

    # -- availability -------------------------------------------------------
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the backend can currently serve a request.

        For cloud providers this is usually just "is a credential present",
        avoiding a network round-trip on every check.
        """

    def unavailable_message(self) -> str:
        """Human-readable hint shown when :meth:`is_available` is False."""
        return f"The {self.name} provider is not configured."

    # -- generation ---------------------------------------------------------
    @abstractmethod
    def complete_text(self, system: str, user: str, *, temperature: float) -> str:
        """Return a plain-text completion."""

    @abstractmethod
    def complete_json(
        self, system: str, user: str, *, schema: Optional[Dict] = None
    ) -> str:
        """Return a completion as a raw JSON *string* (the client parses it)."""

    @abstractmethod
    def stream(
        self,
        system: str,
        history: List[Dict[str, str]],
        user: str,
        *,
        temperature: float,
    ) -> Iterable[str]:
        """Yield text chunks for an interactive, multi-turn chat."""
