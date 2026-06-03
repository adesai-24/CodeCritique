"""
LLMClient — provider-agnostic LLM wrapper with multi-layer intelligent caching.

Architecture
------------
``LLMClient`` owns the *caching* and *prompt-dedup* machinery; a pluggable
**provider** owns the raw round-trip to one backend (Ollama, Gemini, OpenAI,
Anthropic, vLLM, …).  The default provider is chosen from the user's config
(:mod:`critique.config`), defaulting to Gemini's free tier.  Constructing
``LLMClient(base_url=..., model=...)`` with no explicit provider keeps the
historical behaviour of targeting a local Ollama server.

The Ollama provider is defined in *this* module (rather than under
``ai/providers/``) so its HTTP calls go through the module-level ``requests``
object that the client's unit tests patch.

Cache hierarchy (fastest → slowest)
-------------------------------------
1. In-memory dict          — zero I/O; lives for the process lifetime.
2. Disk snapshot           — JSON file loaded once, reused until mtime changes.
3. Semantic similarity     — character-trigram Jaccard search over the disk
                             cache; catches near-duplicate prompts (same code,
                             different whitespace / minor edits).

Ollama inference optimisations (no-ops for stateless cloud providers)
---------------------------------------------------------------------
* keep_alive / num_keep    — keep the model + system-prompt KV states warm.
* Per-system-prompt lock   — serialise same-prefix calls so Ollama reuses the
                             prefix KV cache instead of recomputing attention.
"""

import contextlib
import json
import os
import re
import requests
import tempfile
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from critique.config import load_config

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_TIMEOUT = 300
DEFAULT_CACHE_DIR = Path.home() / ".codecritique" / "cache"
AVAILABILITY_CACHE_SECONDS = 30.0

# How long Ollama should keep the model loaded after the last request.
# Set CODECRITIQUE_KEEP_ALIVE="-1" to keep it loaded forever.
_DEFAULT_KEEP_ALIVE = os.environ.get("CODECRITIQUE_KEEP_ALIVE", "1h")

# Minimum Jaccard similarity to accept a semantic cache hit.
_SEMANTIC_THRESHOLD = 0.82

# Maximum number of candidates to scan per system-prompt bucket.
_SEMANTIC_MAX_CANDIDATES = 150

# -------------------------------------------------------------------------
# Module-level shared state
# -------------------------------------------------------------------------

_CACHE_LOCK = threading.Lock()
_AVAILABILITY_LOCK = threading.Lock()
_AVAILABILITY_CACHE: Dict[str, Tuple[float, bool]] = {}

# Layer 1 — in-memory result cache.
_MEM_CACHE: Dict[str, Any] = {}
_MEM_CACHE_LOCK = threading.Lock()

# Layer 2 — disk snapshot (re-read only when mtime changes).
_DISK_SNAPSHOT: Optional[Dict[str, Any]] = None
_DISK_SNAPSHOT_MTIME: float = 0.0
_DISK_SNAPSHOT_LOCK = threading.Lock()

# Layer 3 — semantic index: system_hash → list of {full_hash, user_sig}.
_SEM_INDEX: Optional[Dict[str, List[Dict[str, str]]]] = None
_SEM_INDEX_MTIME: float = 0.0
_SEM_INDEX_LOCK = threading.RLock()

# Per-system-prompt locks for serialised access (prefix KV-cache reuse).
_SYSTEM_LOCKS: Dict[str, threading.Lock] = {}
_SYSTEM_LOCKS_LOCK = threading.Lock()


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _cache_enabled_by_env() -> bool:
    value = os.environ.get("CODECRITIQUE_AI_CACHE", "1").lower()
    return value not in {"0", "false", "no", "off"}


def _approx_tokens(text: str) -> int:
    """Rough token estimate: ~1.3 tokens per whitespace-delimited word."""
    return max(1, int(len(text.split()) * 1.3))


def _normalize_text(text: str) -> str:
    """Lowercase + collapse all non-alphanumeric chars to spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", text.lower())).strip()


def _trigram_set(text: str) -> frozenset:
    n = 3
    return frozenset(text[i : i + n] for i in range(max(0, len(text) - n + 1)))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _user_sig(user: str) -> str:
    """Compact fingerprint of a user message for semantic comparison."""
    return _normalize_text(user)[:800]


def _get_system_lock(system_hash: str) -> threading.Lock:
    """Return (or create) the serialisation lock for a system prompt."""
    with _SYSTEM_LOCKS_LOCK:
        if system_hash not in _SYSTEM_LOCKS:
            _SYSTEM_LOCKS[system_hash] = threading.Lock()
        return _SYSTEM_LOCKS[system_hash]


# -------------------------------------------------------------------------
# OllamaProvider — default local backend (kept in-module for test patching)
# -------------------------------------------------------------------------

class OllamaProvider:
    """Talks to a local Ollama HTTP server.

    Implements the same surface as :class:`critique.ai.providers.base.Provider`
    but lives here so ``requests`` resolves to this module's import (which the
    tests patch).  Returns *raw assistant text*; the client parses JSON.
    """

    name = "ollama"
    supports_prefix_cache = True

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def availability_key(self) -> str:
        return self.base_url

    def unavailable_message(self) -> str:
        return "Ollama is not running. Start it with: ollama serve"

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _options(self, temperature: float, system: str) -> Dict[str, Any]:
        # num_keep pins the system-prompt tokens at the front of the KV cache so
        # consecutive same-prefix requests reuse them instead of recomputing.
        return {"temperature": temperature, "num_keep": _approx_tokens(system)}

    def complete_text(self, system: str, user: str, *, temperature: float) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": _DEFAULT_KEEP_ALIVE,
            "options": self._options(temperature, system),
        }
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def complete_json(self, system: str, user: str, *, schema: Optional[Dict] = None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "keep_alive": _DEFAULT_KEEP_ALIVE,
            "options": self._options(0.1, system),
        }
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def stream(
        self,
        system: str,
        history: List[Dict[str, str]],
        user: str,
        *,
        temperature: float,
    ) -> Iterable[str]:
        chat_messages = [{"role": "system", "content": system}]
        chat_messages.extend(history or [])
        chat_messages.append({"role": "user", "content": user})
        payload: Any = {
            "model": self.model,
            "messages": chat_messages,
            "stream": True,
            "keep_alive": _DEFAULT_KEEP_ALIVE,
            "options": self._options(temperature, system),
        }
        with requests.post(
            f"{self.base_url}/api/chat", json=payload, timeout=self.timeout, stream=True
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done"):
                    break


# -------------------------------------------------------------------------
# Provider resolution
# -------------------------------------------------------------------------

def _resolve_provider(
    provider: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
    timeout: int,
    config,
):
    """Pick and construct the backend provider.

    Back-compat rule: if a caller passes ``base_url``/``model`` but no explicit
    ``provider`` (and none is set in the environment), assume the historical
    Ollama target.  Otherwise fall back to the configured provider (Gemini by
    default).
    """
    env_provider = os.environ.get("CODECRITIQUE_PROVIDER")
    name = provider or env_provider
    if name is None:
        if base_url is not None or model is not None:
            name = "ollama"
        else:
            name = config.provider
    name = name.strip().lower()

    # If the chosen provider matches the configured one, honour the configured
    # model; otherwise (e.g. an explicit one-off provider) use the provider's
    # own default.
    configured_model = config.resolved_model() if config.provider == name else None

    if name == "ollama":
        return OllamaProvider(
            base_url=base_url or config.base_url or OLLAMA_BASE_URL,
            model=model or configured_model or DEFAULT_MODEL,
            timeout=timeout,
        )

    # Cloud / remote providers built by the registry.
    from critique.ai.providers import build_provider

    return build_provider(
        name,
        model=model or configured_model,
        base_url=base_url or config.base_url,
        timeout=timeout,
        config=config,
    )


# -------------------------------------------------------------------------
# LLMClient
# -------------------------------------------------------------------------

class LLMClient:
    """Provider-agnostic LLM wrapper with intelligent caching."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        cache_dir: Optional[Path] = None,
        use_cache: Optional[bool] = None,
        provider: Optional[str] = None,
        config: Optional[Any] = None,
    ):
        cfg = config if config is not None else load_config()
        self.config = cfg
        self.provider = _resolve_provider(provider, base_url, model, timeout, cfg)
        # Expose a few attributes for back-compat with existing call sites/tests.
        self.model = self.provider.model
        self.base_url = getattr(self.provider, "base_url", None)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.use_cache = use_cache if use_cache is not None else _cache_enabled_by_env()

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", "unknown")

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @property
    def _cache_path(self) -> Path:
        return self.cache_dir / "llm_cache.json"

    @property
    def _sem_index_path(self) -> Path:
        return self.cache_dir / "semantic_index.json"

    # ------------------------------------------------------------------
    # System-prompt lock (only meaningful for prefix-cache providers)
    # ------------------------------------------------------------------

    def _maybe_system_lock(self, system: str):
        if getattr(self.provider, "supports_prefix_cache", False):
            return _get_system_lock(sha256(system.encode()).hexdigest())
        return contextlib.nullcontext()

    # ------------------------------------------------------------------
    # Disk snapshot (layer 2)
    # ------------------------------------------------------------------

    def _load_disk_snapshot(self) -> Dict[str, Any]:
        global _DISK_SNAPSHOT, _DISK_SNAPSHOT_MTIME
        cache_path = self._cache_path
        with _DISK_SNAPSHOT_LOCK:
            try:
                mtime = cache_path.stat().st_mtime if cache_path.exists() else 0.0
            except Exception:
                mtime = 0.0
            if _DISK_SNAPSHOT is None or mtime != _DISK_SNAPSHOT_MTIME:
                try:
                    data = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
                    _DISK_SNAPSHOT = data if isinstance(data, dict) else {}
                except Exception:
                    _DISK_SNAPSHOT = {}
                _DISK_SNAPSHOT_MTIME = mtime
            return _DISK_SNAPSHOT  # type: ignore[return-value]

    def _write_disk(self, cache: Dict[str, Any]) -> None:
        global _DISK_SNAPSHOT, _DISK_SNAPSHOT_MTIME
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=self.cache_dir, encoding="utf-8") as tmp:
            json.dump(cache, tmp)
            tmp_path = Path(tmp.name)
        tmp_path.replace(self._cache_path)
        try:
            _DISK_SNAPSHOT_MTIME = self._cache_path.stat().st_mtime
        except Exception:
            pass
        _DISK_SNAPSHOT = cache

    # ------------------------------------------------------------------
    # Semantic index (layer 3)
    # ------------------------------------------------------------------

    def _load_sem_index(self) -> Dict[str, List[Dict[str, str]]]:
        global _SEM_INDEX, _SEM_INDEX_MTIME
        path = self._sem_index_path
        with _SEM_INDEX_LOCK:
            try:
                mtime = path.stat().st_mtime if path.exists() else 0.0
            except Exception:
                mtime = 0.0
            if _SEM_INDEX is None or mtime != _SEM_INDEX_MTIME:
                try:
                    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                    _SEM_INDEX = data if isinstance(data, dict) else {}
                except Exception:
                    _SEM_INDEX = {}
                _SEM_INDEX_MTIME = mtime
            return _SEM_INDEX  # type: ignore[return-value]

    def _write_sem_index(self, index: Dict[str, List[Dict[str, str]]]) -> None:
        global _SEM_INDEX, _SEM_INDEX_MTIME
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._sem_index_path
        with tempfile.NamedTemporaryFile("w", delete=False, dir=self.cache_dir, encoding="utf-8") as tmp:
            json.dump(index, tmp)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
        try:
            _SEM_INDEX_MTIME = path.stat().st_mtime
        except Exception:
            pass
        _SEM_INDEX = index

    def _sem_index_add(self, system_hash: str, full_hash: str, user: str) -> None:
        if not self.use_cache:
            return
        with _SEM_INDEX_LOCK:
            index = self._load_sem_index().copy()
            bucket = list(index.get(system_hash, []))
            if not any(e["full_hash"] == full_hash for e in bucket):
                bucket.append({"full_hash": full_hash, "user_sig": _user_sig(user)})
                if len(bucket) > _SEMANTIC_MAX_CANDIDATES:
                    bucket = bucket[-_SEMANTIC_MAX_CANDIDATES:]
            index[system_hash] = bucket
            self._write_sem_index(index)

    def _sem_cache_lookup(self, system_hash: str, user: str) -> Optional[Any]:
        if not self.use_cache:
            return None
        with _SEM_INDEX_LOCK:
            index = self._load_sem_index()
            bucket = index.get(system_hash, [])

        if not bucket:
            return None

        query_sig = _user_sig(user)
        query_tg = _trigram_set(query_sig)
        best_score = 0.0
        best_hash: Optional[str] = None

        for entry in bucket:
            stored_tg = _trigram_set(entry.get("user_sig", ""))
            score = _jaccard(query_tg, stored_tg)
            if score > best_score:
                best_score = score
                best_hash = entry["full_hash"]

        if best_score >= _SEMANTIC_THRESHOLD and best_hash is not None:
            with _CACHE_LOCK:
                return self._load_disk_snapshot().get(best_hash)
        return None

    # ------------------------------------------------------------------
    # Cache key + get/set
    # ------------------------------------------------------------------

    def _cache_key(
        self,
        kind: str,
        system: str,
        user: str,
        *,
        schema: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
    ) -> str:
        stable = json.dumps(
            {
                "cache_dir": str(self.cache_dir),
                "provider": self.provider_name,
                "model": self.model,
                "kind": kind,
                "system": system,
                "user": user,
                "schema": schema,
                "temperature": temperature,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(stable.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[Any]:
        if not self.use_cache:
            return None
        with _MEM_CACHE_LOCK:
            if key in _MEM_CACHE:
                return _MEM_CACHE[key]
        with _CACHE_LOCK:
            value = self._load_disk_snapshot().get(key)
        if value is not None:
            with _MEM_CACHE_LOCK:
                _MEM_CACHE[key] = value
        return value

    def _cache_set(self, key: str, value: Any) -> None:
        if not self.use_cache:
            return
        with _MEM_CACHE_LOCK:
            _MEM_CACHE[key] = value
        with _CACHE_LOCK:
            cache = self._load_disk_snapshot().copy()
            cache[key] = value
            self._write_disk(cache)

    # ------------------------------------------------------------------
    # Availability check (30s cached, delegated to the provider)
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        key = getattr(self.provider, "availability_key", self.provider_name)
        now = time.monotonic()
        cached = _AVAILABILITY_CACHE.get(key)
        if cached and now - cached[0] < AVAILABILITY_CACHE_SECONDS:
            return cached[1]
        available = self.provider.is_available()
        with _AVAILABILITY_LOCK:
            _AVAILABILITY_CACHE[key] = (now, available)
        return available

    def unavailable_message(self) -> str:
        return self.provider.unavailable_message()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Plain-text completion.  Raises RuntimeError if the backend is offline."""
        cache_key = self._cache_key("text", system, user, temperature=temperature)

        cached = self._cache_get(cache_key)
        if isinstance(cached, str):
            return cached

        if not self.is_available():
            raise RuntimeError(self.provider.unavailable_message())

        system_hash = sha256(system.encode()).hexdigest()
        with self._maybe_system_lock(system):
            cached = self._cache_get(cache_key)
            if isinstance(cached, str):
                return cached
            content = self.provider.complete_text(system, user, temperature=temperature)

        self._cache_set(cache_key, content)
        self._sem_index_add(system_hash, cache_key, user)
        return content

    def complete_stream(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.2,
    ) -> Iterable[str]:
        """Streaming completion for interactive chat.  Not cached."""
        if not self.is_available():
            raise RuntimeError(self.provider.unavailable_message())
        yield from self.provider.stream(system, messages or [], user, temperature=temperature)

    def complete_json(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
        cache_key_override: Optional[str] = None,
    ) -> Any:
        """JSON-mode completion.

        cache_key_override
            When provided, this hash is used as the cache key instead of the
            normalised payload hash.  Callers (e.g. AICriticChecker) pass an
            AST-derived hash so cache hits survive comment / whitespace edits.

        Raises RuntimeError if the backend is offline.
        """
        cache_key = cache_key_override or self._cache_key("json", system, user, schema=schema)

        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        system_hash = sha256(system.encode()).hexdigest()

        # Layer 3: semantic match (skip for overridden keys — the caller already
        # normalised them).
        if cache_key_override is None:
            sem_hit = self._sem_cache_lookup(system_hash, user)
            if sem_hit is not None:
                self._cache_set(cache_key, sem_hit)
                return sem_hit

        if not self.is_available():
            raise RuntimeError(self.provider.unavailable_message())

        with self._maybe_system_lock(system):
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
            raw = self.provider.complete_json(system, user, schema=schema)
            result = json.loads(raw)

        self._cache_set(cache_key, result)
        if cache_key_override is None:
            self._sem_index_add(system_hash, cache_key, user)
        return result
