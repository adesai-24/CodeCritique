"""
LLMClient — Ollama HTTP API wrapper with multi-layer intelligent caching.

Cache hierarchy (fastest → slowest)
-------------------------------------
1. In-memory dict          — zero I/O; lives for the process lifetime.
2. Disk snapshot           — JSON file loaded once, reused until mtime changes.
3. Semantic similarity     — character-trigram Jaccard search over the disk
                             cache; catches near-duplicate prompts (same code,
                             different whitespace / minor edits).

Ollama inference optimisations
--------------------------------
* keep_alive               — model stays loaded in RAM between runs (avoids
                             cold-start reload cost, typically 5-15 s).
* num_keep                 — pins system-prompt tokens in Ollama's KV cache so
                             the shared prefix is never evicted, giving the
                             model an effective "free" prefix on every call
                             that shares the same system prompt.
* Per-system-prompt lock   — when multiple threads call the model with the
                             same system prompt, they are serialised. Ollama
                             detects identical prefixes in consecutive requests
                             and skips recomputing attention for those tokens
                             (prefix KV-cache reuse). Interleaving different
                             system prompts would flush that prefix from the
                             KV cache between calls.
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
# Set CODECRITIQUE_KEEP_ALIVE="-1" to keep it loaded forever.
_DEFAULT_KEEP_ALIVE = os.environ.get("CODECRITIQUE_KEEP_ALIVE", "1h")

# Minimum Jaccard similarity to accept a semantic cache hit.
# Conservative: code semantics matter, so we require high structural overlap.
_SEMANTIC_THRESHOLD = 0.82

# Maximum number of candidates to scan per system-prompt bucket in the
# semantic index.  Keeps the similarity search O(1) in practice.
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

# Layer 3 — semantic index: system_hash → list of {full_hash, user_sig}
# Stored in a separate JSON file next to the main cache.
_SEM_INDEX: Optional[Dict[str, List[Dict[str, str]]]] = None
_SEM_INDEX_MTIME: float = 0.0
_SEM_INDEX_LOCK = threading.RLock()

# Per-system-prompt locks for serialised Ollama access (prefix KV-cache reuse).
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
    """Compact fingerprint of a user message for semantic comparison.

    We store only the first 800 normalised characters to keep the index small
    while still capturing enough of the prompt for reliable similarity scoring.
    """
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
    """Thin wrapper around the Ollama HTTP API with intelligent caching."""

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
        """Register a new cache entry in the semantic index."""
        if not self.use_cache:
            return
        with _SEM_INDEX_LOCK:
            index = self._load_sem_index().copy()
            bucket = list(index.get(system_hash, []))
            # Avoid duplicate entries for the same full_hash.
            if not any(e["full_hash"] == full_hash for e in bucket):
                bucket.append({"full_hash": full_hash, "user_sig": _user_sig(user)})
                # Cap bucket size to keep searches bounded.
                if len(bucket) > _SEMANTIC_MAX_CANDIDATES:
                    bucket = bucket[-_SEMANTIC_MAX_CANDIDATES:]
            index[system_hash] = bucket
            self._write_sem_index(index)

    def _sem_cache_lookup(self, system_hash: str, user: str) -> Optional[Any]:
        """Search for a semantically similar cached result.

        Computes character-trigram Jaccard similarity between the incoming
        user message and every stored signature in the same system-prompt
        bucket.  Returns the cached result for the best match if it exceeds
        _SEMANTIC_THRESHOLD, otherwise None.
        """
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
            # Fetch the actual result from the main cache.
            with _CACHE_LOCK:
                result = self._load_disk_snapshot().get(best_hash)
            return result
        return None

    # ------------------------------------------------------------------
    # Public cache interface
    # ------------------------------------------------------------------

    def _cache_key(self, payload: Dict[str, Any]) -> str:
        stable = json.dumps(
            {"cache_dir": str(self.cache_dir), "payload": payload},
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
    # Availability check
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
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
    # Internal: build Ollama options with prefix-cache hints
    # ------------------------------------------------------------------

    def _ollama_options(self, temperature: float, system: str) -> Dict[str, Any]:
        """Return the options dict to include in every Ollama request.

        num_keep pins the system-prompt tokens at the start of Ollama's KV
        cache so they are never evicted when the context window fills up.
        This is the application-side knob for prefix caching: consecutive
        requests that share the same system prompt will reuse those KV states
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

        # Layer 1 + 2: exact match.
        cached = self._cache_get(cache_key)
        if isinstance(cached, str):
            return cached

        if not self.is_available():
            raise RuntimeError("Ollama is not running. Start it with: ollama serve")

        system_hash = sha256(system.encode()).hexdigest()
        with _get_system_lock(system_hash):
            # Re-check after acquiring the lock (another thread may have just run).
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
            full payload hash.  Callers (e.g. AICriticChecker) can pass an
            AST-derived hash so that cache hits survive comment / whitespace
            edits that don't change code structure.  The actual request to
            Ollama always contains the original user text.

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

        # Layer 3: semantic match (only on true cache misses; skip for overridden
        # keys because the caller already performed semantic normalisation).
        if cache_key_override is None:
            sem_hit = self._sem_cache_lookup(system_hash, user)
            if sem_hit is not None:
                # Warm the exact-match cache so subsequent identical calls are O(1).
                self._cache_set(cache_key, sem_hit)
                return sem_hit

        if not self.is_available():
            raise RuntimeError("Ollama is not running. Start it with: ollama serve")

        with _get_system_lock(system_hash):
            # Re-check after acquiring the lock.
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"]
            result = json.loads(raw)

        self._cache_set(cache_key, result)
        # Register in semantic index only for regular (non-overridden) keys.
        if cache_key_override is None:
            self._sem_index_add(system_hash, cache_key, user)
        return result
