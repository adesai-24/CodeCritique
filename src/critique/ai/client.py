"""
LLMClient — Ollama HTTP API wrapper with multi-layer intelligent caching.

Cache hierarchy (fastest → slowest)
-------------------------------------
1. In-memory dict          — zero I/O; instance-level, lives for the object
                             lifetime; no cross-test contamination.
2. Disk snapshot           — JSON file loaded once per instance, reused until
                             mtime changes on disk.
3. Semantic similarity     — character-trigram Jaccard search over stored
                             user-message fingerprints; catches near-duplicate
                             prompts (same code, different whitespace / minor
                             edits) without a new inference call.

Ollama inference optimisations
--------------------------------
* keep_alive               — model stays loaded in RAM between runs (avoids
                             cold-start reload cost, typically 5-15 s).
* num_keep                 — pins system-prompt tokens in Ollama's KV cache so
                             the shared prefix is never evicted, giving the
                             model an effective "free" prefix on every call
                             that shares the same system prompt.
* Per-system-prompt lock   — requests sharing the same system prompt are
                             serialised so that Ollama processes consecutive
                             calls with identical prefixes, maximising prefix
                             KV-cache reuse between calls.

Thread safety
-------------
All shared state is protected by distinct locks.  Internal helpers that are
always called from within a locked section do NOT re-acquire that same lock
(threading.Lock is not reentrant); they are marked with a leading underscore
and an "_unlocked" suffix to make the convention explicit.
"""

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

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_TIMEOUT = 300
DEFAULT_CACHE_DIR = Path.home() / ".codecritique" / "cache"
AVAILABILITY_CACHE_SECONDS = 30.0

# How long Ollama should keep the model loaded after the last request.
# Override with CODECRITIQUE_KEEP_ALIVE env var (e.g. "-1" = forever).
_DEFAULT_KEEP_ALIVE = os.environ.get("CODECRITIQUE_KEEP_ALIVE", "1h")

# Minimum Jaccard similarity to accept a semantic cache hit.
_SEMANTIC_THRESHOLD = 0.82

# Maximum candidates to scan per system-prompt bucket.
_SEMANTIC_MAX_CANDIDATES = 150

# -------------------------------------------------------------------------
# Module-level shared state (only availability cache and Ollama locks)
# -------------------------------------------------------------------------

_AVAILABILITY_LOCK = threading.Lock()
_AVAILABILITY_CACHE: Dict[str, Tuple[float, bool]] = {}

# Per-system-prompt locks for serialised Ollama access.
# Kept module-level so multiple LLMClient instances (if any) still cooperate.
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
# LLMClient
# -------------------------------------------------------------------------

class LLMClient:
    """Thin wrapper around the Ollama HTTP API with intelligent caching.

    All per-instance cache state (memory dict, disk snapshot, semantic index)
    is stored on the instance so that separate instances with different
    cache_dir paths don't interfere with each other.  This is essential for
    test isolation (each test gets its own tmp_path).
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        cache_dir: Optional[Path] = None,
        use_cache: Optional[bool] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.use_cache = use_cache if use_cache is not None else _cache_enabled_by_env()

        # Layer 1: in-memory cache — instance-level to avoid cross-test pollution.
        self._mem_cache: Dict[str, Any] = {}
        self._mem_lock = threading.Lock()

        # Layer 2: disk snapshot.
        self._disk_snapshot: Optional[Dict[str, Any]] = None
        self._disk_mtime: float = 0.0
        self._disk_lock = threading.Lock()

        # Layer 3: semantic index.
        self._sem_index: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._sem_mtime: float = 0.0
        self._sem_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @property
    def _cache_path(self) -> Path:
        return self.cache_dir / "llm_cache.json"

    @property
    def _sem_path(self) -> Path:
        return self.cache_dir / "semantic_index.json"

    # ------------------------------------------------------------------
    # Disk snapshot — layer 2
    # ------------------------------------------------------------------

    def _load_disk_unlocked(self) -> Dict[str, Any]:
        """Read (or refresh) the disk cache.  Must be called inside _disk_lock."""
        cache_path = self._cache_path
        try:
            mtime = cache_path.stat().st_mtime if cache_path.exists() else 0.0
        except Exception:
            mtime = 0.0
        if self._disk_snapshot is None or mtime != self._disk_mtime:
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
                self._disk_snapshot = data if isinstance(data, dict) else {}
            except Exception:
                self._disk_snapshot = {}
            self._disk_mtime = mtime
        return self._disk_snapshot  # type: ignore[return-value]

    def _write_disk_unlocked(self, cache: Dict[str, Any]) -> None:
        """Atomically write the cache file.  Must be called inside _disk_lock."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=self.cache_dir, encoding="utf-8") as tmp:
            json.dump(cache, tmp)
            tmp_name = tmp.name
        Path(tmp_name).replace(self._cache_path)
        try:
            self._disk_mtime = self._cache_path.stat().st_mtime
        except Exception:
            pass
        self._disk_snapshot = cache

    # ------------------------------------------------------------------
    # Semantic index — layer 3
    # ------------------------------------------------------------------

    def _load_sem_unlocked(self) -> Dict[str, List[Dict[str, str]]]:
        """Read (or refresh) the semantic index.  Must be called inside _sem_lock."""
        path = self._sem_path
        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
        except Exception:
            mtime = 0.0
        if self._sem_index is None or mtime != self._sem_mtime:
            try:
                data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                self._sem_index = data if isinstance(data, dict) else {}
            except Exception:
                self._sem_index = {}
            self._sem_mtime = mtime
        return self._sem_index  # type: ignore[return-value]

    def _write_sem_unlocked(self, index: Dict[str, List[Dict[str, str]]]) -> None:
        """Atomically write the semantic index.  Must be called inside _sem_lock."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._sem_path
        with tempfile.NamedTemporaryFile("w", delete=False, dir=self.cache_dir, encoding="utf-8") as tmp:
            json.dump(index, tmp)
            tmp_name = tmp.name
        Path(tmp_name).replace(path)
        try:
            self._sem_mtime = path.stat().st_mtime
        except Exception:
            pass
        self._sem_index = index

    def _sem_index_add(self, system_hash: str, full_hash: str, user: str) -> None:
        """Register a new cache entry in the semantic index."""
        if not self.use_cache:
            return
        with self._sem_lock:
            index = self._load_sem_unlocked().copy()
            bucket = list(index.get(system_hash, []))
            if not any(e["full_hash"] == full_hash for e in bucket):
                bucket.append({"full_hash": full_hash, "user_sig": _user_sig(user)})
                if len(bucket) > _SEMANTIC_MAX_CANDIDATES:
                    bucket = bucket[-_SEMANTIC_MAX_CANDIDATES:]
            index[system_hash] = bucket
            self._write_sem_unlocked(index)

    def _sem_lookup(self, system_hash: str, user: str) -> Optional[Any]:
        """Return a cached result for a semantically similar prompt, or None."""
        if not self.use_cache:
            return None
        with self._sem_lock:
            bucket = list(self._load_sem_unlocked().get(system_hash, []))

        if not bucket:
            return None

        query_tg = _trigram_set(_user_sig(user))
        best_score = 0.0
        best_hash: Optional[str] = None
        for entry in bucket:
            score = _jaccard(query_tg, _trigram_set(entry.get("user_sig", "")))
            if score > best_score:
                best_score = score
                best_hash = entry["full_hash"]

        if best_score >= _SEMANTIC_THRESHOLD and best_hash is not None:
            with self._disk_lock:
                return self._load_disk_unlocked().get(best_hash)
        return None

    # ------------------------------------------------------------------
    # Public cache interface
    # ------------------------------------------------------------------

    def _cache_key(self, payload: Dict[str, Any]) -> str:
        stable = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(stable.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[Any]:
        if not self.use_cache:
            return None
        with self._mem_lock:
            if key in self._mem_cache:
                return self._mem_cache[key]
        with self._disk_lock:
            value = self._load_disk_unlocked().get(key)
        if value is not None:
            with self._mem_lock:
                self._mem_cache[key] = value
        return value

    def _cache_set(self, key: str, value: Any) -> None:
        if not self.use_cache:
            return
        with self._mem_lock:
            self._mem_cache[key] = value
        with self._disk_lock:
            cache = self._load_disk_unlocked().copy()
            cache[key] = value
            self._write_disk_unlocked(cache)

    # ------------------------------------------------------------------
    # Availability check
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if Ollama is reachable."""
        now = time.monotonic()
        cached = _AVAILABILITY_CACHE.get(self.base_url)
        if cached and now - cached[0] < AVAILABILITY_CACHE_SECONDS:
            return cached[1]
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            available = resp.status_code == 200
        except Exception:
            available = False
        with _AVAILABILITY_LOCK:
            _AVAILABILITY_CACHE[self.base_url] = (now, available)
        return available

    # ------------------------------------------------------------------
    # Ollama options (prefix KV-cache hints)
    # ------------------------------------------------------------------

    def _ollama_options(self, temperature: float, system: str) -> Dict[str, Any]:
        """Build the options dict for every Ollama request.

        num_keep pins system-prompt tokens in Ollama's KV cache so they are
        never evicted when the context window fills up.  Consecutive requests
        that share the same system prompt will reuse those cached KV states
        rather than recomputing attention from scratch.
        """
        return {
            "temperature": temperature,
            "num_keep": _approx_tokens(system),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Plain-text completion.  Raises RuntimeError if Ollama is offline."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": _DEFAULT_KEEP_ALIVE,
            "options": self._ollama_options(temperature, system),
        }
        cache_key = self._cache_key({"kind": "text", "payload": payload})

        cached = self._cache_get(cache_key)
        if isinstance(cached, str):
            return cached

        if not self.is_available():
            raise RuntimeError("Ollama is not running. Start it with: ollama serve")

        system_hash = sha256(system.encode()).hexdigest()
        with _get_system_lock(system_hash):
            cached = self._cache_get(cache_key)
            if isinstance(cached, str):
                return cached
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]

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
            raise RuntimeError("Ollama is not running. Start it with: ollama serve")

        chat_messages = [{"role": "system", "content": system}]
        chat_messages.extend(messages or [])
        chat_messages.append({"role": "user", "content": user})

        payload: Any = {
            "model": self.model,
            "messages": chat_messages,
            "stream": True,
            "keep_alive": _DEFAULT_KEEP_ALIVE,
            "options": self._ollama_options(temperature, system),
        }
        with requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
            stream=True,
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
            default payload hash.  Callers (e.g. AICriticChecker) pass an
            AST-derived hash so that cache hits survive comment / whitespace
            edits that don't change code structure.

        Raises RuntimeError if Ollama is not running.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "keep_alive": _DEFAULT_KEEP_ALIVE,
            "options": self._ollama_options(0.1, system),
        }

        cache_key = cache_key_override or self._cache_key(
            {"kind": "json", "payload": payload, "schema": schema}
        )

        # Layer 1 + 2: exact match.
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        system_hash = sha256(system.encode()).hexdigest()

        # Layer 3: semantic match (only for non-overridden keys; callers that
        # supply cache_key_override have already done semantic normalisation).
        if cache_key_override is None:
            sem_hit = self._sem_lookup(system_hash, user)
            if sem_hit is not None:
                self._cache_set(cache_key, sem_hit)
                return sem_hit

        if not self.is_available():
            raise RuntimeError("Ollama is not running. Start it with: ollama serve")

        with _get_system_lock(system_hash):
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"]
            result = json.loads(raw)

        self._cache_set(cache_key, result)
        if cache_key_override is None:
            self._sem_index_add(system_hash, cache_key, user)
        return result
