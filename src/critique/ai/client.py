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

Cache files (all under ~/.codecritique/cache/ via paths.py)
-------------------------------------------------------------
  inference.json   — LLM response cache (exact-match results)
  semantic.json    — per-system-prompt fingerprint index for layer 3

Ollama inference optimisations
--------------------------------
* keep_alive        — model stays loaded between runs; avoids the 5-15 s
                      cold-start reload cost. Default "1h", set
                      CODECRITIQUE_KEEP_ALIVE="-1" to keep it forever.

* num_keep          — pins system-prompt tokens in Ollama's KV cache so
                      the shared prefix is never evicted when the context
                      window fills up. Consecutive calls with the same
                      system prompt reuse those cached KV states.

* num_ctx           — context window sized dynamically to the actual
                      prompt length (next power of 2, 1.5× safety margin,
                      capped at CODECRITIQUE_NUM_CTX, default 8 192).
                      For a 7B model the default 32 K context wastes up
                      to 1.8 GB of VRAM on KV cache; right-sizing this to
                      the actual prompt footprint frees that VRAM for the
                      model weights and active KV states.

* num_gpu           — number of model layers to offload to the GPU.
                      Default 99 (= all layers). Forces every transformer
                      block onto VRAM so no weight reads cross the PCIe
                      bus. Override with CODECRITIQUE_NUM_GPU.

* num_batch         — token batch size used during the prompt-processing
                      (prefill) phase. Larger batches amortise the kernel
                      launch overhead and saturate GPU SIMD units better.
                      Default 512. Override with CODECRITIQUE_NUM_BATCH.

* Per-system-prompt lock — requests sharing the same system prompt are
                      serialised so Ollama always processes a run of
                      identical prefixes consecutively, maximising prefix
                      KV-cache reuse.

Flash Attention (requires action outside this codebase)
--------------------------------------------------------
Ollama uses llama.cpp internally. Flash Attention is supported but must be
enabled at server startup via an environment variable, not via the API:

    OLLAMA_FLASH_ATTENTION=1 ollama serve

On an RTX 5060 (or any CUDA GPU) this reduces the memory bandwidth demand
of the attention computation and meaningfully shortens prefill time for
longer prompts. Set it in your shell profile or systemd unit.

Thread safety
-------------
All shared state is protected by distinct locks. Internal helpers always
called from within a locked section are suffixed _unlocked and must NOT
re-acquire that same lock (threading.Lock is not reentrant).
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

from critique.paths import CACHE_DIR

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_TIMEOUT = 300
AVAILABILITY_CACHE_SECONDS = 30.0

# ── Ollama inference knobs (all overridable via env vars) ─────────────────────
_KEEP_ALIVE   = os.environ.get("CODECRITIQUE_KEEP_ALIVE", "1h")
_NUM_GPU      = int(os.environ.get("CODECRITIQUE_NUM_GPU",   "99"))
_NUM_BATCH    = int(os.environ.get("CODECRITIQUE_NUM_BATCH", "512"))
# Hard ceiling for dynamic num_ctx; user can raise if they analyse very large
# files. Keeping this at 8 192 limits KV-cache VRAM to ~450 MB for a 7B model.
_MAX_CTX      = int(os.environ.get("CODECRITIQUE_NUM_CTX",  "8192"))
# Tokens budgeted for the model's JSON response on top of the prompt.
_RESPONSE_RESERVE = 512

# ── Semantic cache knobs ──────────────────────────────────────────────────────
_SEMANTIC_THRESHOLD     = 0.82
_SEMANTIC_MAX_CANDIDATES = 150

# ── Module-level shared state (availability + Ollama serialisation locks) ────
_AVAILABILITY_LOCK:  threading.Lock               = threading.Lock()
_AVAILABILITY_CACHE: Dict[str, Tuple[float, bool]] = {}

_SYSTEM_LOCKS:      Dict[str, threading.Lock] = {}
_SYSTEM_LOCKS_LOCK: threading.Lock            = threading.Lock()


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _cache_enabled_by_env() -> bool:
    return os.environ.get("CODECRITIQUE_AI_CACHE", "1").lower() not in {
        "0", "false", "no", "off"
    }


def _approx_tokens(text: str) -> int:
    """~1.3 tokens per whitespace-delimited word (conservative estimate)."""
    return max(1, int(len(text.split()) * 1.3))


def _next_pow2(n: int) -> int:
    """Smallest power of 2 that is ≥ n."""
    p = 1
    while p < n:
        p <<= 1
    return p


def _normalize_text(text: str) -> str:
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
    """First 800 chars of normalised user message — compact similarity key."""
    return _normalize_text(user)[:800]


def _get_system_lock(system_hash: str) -> threading.Lock:
    with _SYSTEM_LOCKS_LOCK:
        if system_hash not in _SYSTEM_LOCKS:
            _SYSTEM_LOCKS[system_hash] = threading.Lock()
        return _SYSTEM_LOCKS[system_hash]


def _migrate_legacy_cache(cache_dir: Path) -> None:
    """Rename old cache filenames to the current names (one-time, silent)."""
    renames = [
        ("llm_cache.json",     "inference.json"),
        ("semantic_index.json", "semantic.json"),
    ]
    for old_name, new_name in renames:
        old = cache_dir / old_name
        new = cache_dir / new_name
        if old.exists() and not new.exists():
            try:
                old.rename(new)
            except Exception:
                pass


# ── LLMClient ─────────────────────────────────────────────────────────────────

class LLMClient:
    """Ollama HTTP API wrapper with three-layer caching and GPU tuning.

    All per-instance cache state lives on the instance so that separate
    instances (e.g. per-test tmp_path) are fully isolated.
    """

    def __init__(
        self,
        base_url:  str            = OLLAMA_BASE_URL,
        model:     str            = DEFAULT_MODEL,
        timeout:   int            = DEFAULT_TIMEOUT,
        cache_dir: Optional[Path] = None,
        use_cache: Optional[bool] = None,
    ):
        self.base_url  = base_url.rstrip("/")
        self.model     = model
        self.timeout   = timeout
        self.cache_dir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
        self.use_cache = use_cache if use_cache is not None else _cache_enabled_by_env()

        _migrate_legacy_cache(self.cache_dir)

        # Layer 1 — in-memory dict
        self._mem_cache: Dict[str, Any] = {}
        self._mem_lock = threading.Lock()

        # Layer 2 — disk snapshot
        self._disk_snapshot: Optional[Dict[str, Any]] = None
        self._disk_mtime: float = 0.0
        self._disk_lock = threading.Lock()

        # Layer 3 — semantic index
        self._sem_index: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._sem_mtime: float = 0.0
        self._sem_lock = threading.Lock()

    # ── Path helpers ──────────────────────────────────────────────────────────

    @property
    def _cache_path(self) -> Path:
        return self.cache_dir / "inference.json"

    @property
    def _sem_path(self) -> Path:
        return self.cache_dir / "semantic.json"

    # ── Disk snapshot (layer 2) ───────────────────────────────────────────────

    def _load_disk_unlocked(self) -> Dict[str, Any]:
        """Refresh + return disk cache. Caller must hold _disk_lock."""
        p = self._cache_path
        try:
            mtime = p.stat().st_mtime if p.exists() else 0.0
        except Exception:
            mtime = 0.0
        if self._disk_snapshot is None or mtime != self._disk_mtime:
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                self._disk_snapshot = data if isinstance(data, dict) else {}
            except Exception:
                self._disk_snapshot = {}
            self._disk_mtime = mtime
        return self._disk_snapshot  # type: ignore[return-value]

    def _write_disk_unlocked(self, cache: Dict[str, Any]) -> None:
        """Atomically persist cache. Caller must hold _disk_lock."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", delete=False, dir=self.cache_dir, encoding="utf-8"
        ) as tmp:
            json.dump(cache, tmp)
            tmp_name = tmp.name
        Path(tmp_name).replace(self._cache_path)
        try:
            self._disk_mtime = self._cache_path.stat().st_mtime
        except Exception:
            pass
        self._disk_snapshot = cache

    # ── Semantic index (layer 3) ──────────────────────────────────────────────

    def _load_sem_unlocked(self) -> Dict[str, List[Dict[str, str]]]:
        """Refresh + return semantic index. Caller must hold _sem_lock."""
        p = self._sem_path
        try:
            mtime = p.stat().st_mtime if p.exists() else 0.0
        except Exception:
            mtime = 0.0
        if self._sem_index is None or mtime != self._sem_mtime:
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                self._sem_index = data if isinstance(data, dict) else {}
            except Exception:
                self._sem_index = {}
            self._sem_mtime = mtime
        return self._sem_index  # type: ignore[return-value]

    def _write_sem_unlocked(self, index: Dict[str, List[Dict[str, str]]]) -> None:
        """Atomically persist semantic index. Caller must hold _sem_lock."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        p = self._sem_path
        with tempfile.NamedTemporaryFile(
            "w", delete=False, dir=self.cache_dir, encoding="utf-8"
        ) as tmp:
            json.dump(index, tmp)
            tmp_name = tmp.name
        Path(tmp_name).replace(p)
        try:
            self._sem_mtime = p.stat().st_mtime
        except Exception:
            pass
        self._sem_index = index

    def _sem_index_add(self, system_hash: str, full_hash: str, user: str) -> None:
        if not self.use_cache:
            return
        with self._sem_lock:
            index  = self._load_sem_unlocked().copy()
            bucket = list(index.get(system_hash, []))
            if not any(e["full_hash"] == full_hash for e in bucket):
                bucket.append({"full_hash": full_hash, "user_sig": _user_sig(user)})
                if len(bucket) > _SEMANTIC_MAX_CANDIDATES:
                    bucket = bucket[-_SEMANTIC_MAX_CANDIDATES:]
            index[system_hash] = bucket
            self._write_sem_unlocked(index)

    def _sem_lookup(self, system_hash: str, user: str) -> Optional[Any]:
        if not self.use_cache:
            return None
        with self._sem_lock:
            bucket = list(self._load_sem_unlocked().get(system_hash, []))
        if not bucket:
            return None
        query_tg   = _trigram_set(_user_sig(user))
        best_score = 0.0
        best_hash: Optional[str] = None
        for entry in bucket:
            score = _jaccard(query_tg, _trigram_set(entry.get("user_sig", "")))
            if score > best_score:
                best_score = score
                best_hash  = entry["full_hash"]
        if best_score >= _SEMANTIC_THRESHOLD and best_hash is not None:
            with self._disk_lock:
                return self._load_disk_unlocked().get(best_hash)
        return None

    # ── Cache interface ───────────────────────────────────────────────────────

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

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        now    = time.monotonic()
        cached = _AVAILABILITY_CACHE.get(self.base_url)
        if cached and now - cached[0] < AVAILABILITY_CACHE_SECONDS:
            return cached[1]
        try:
            resp      = requests.get(f"{self.base_url}/api/tags", timeout=5)
            available = resp.status_code == 200
        except Exception:
            available = False
        with _AVAILABILITY_LOCK:
            _AVAILABILITY_CACHE[self.base_url] = (now, available)
        return available

    # ── Ollama request options ────────────────────────────────────────────────

    def _ollama_options(
        self,
        temperature: float,
        system: str,
        user: str = "",
    ) -> Dict[str, Any]:
        """Build the options dict sent with every Ollama request.

        num_ctx is sized dynamically: we estimate the token count of the
        actual system + user content, apply a 1.5× safety margin, round up
        to the next power of 2, then clamp to [2048, _MAX_CTX].

        This avoids allocating the model's full 32 K KV cache (≈1.8 GB for
        a 7B model) when our prompt is only 2-4 K tokens, freeing that VRAM
        for weight caching and active states.
        """
        estimated = _approx_tokens(system) + _approx_tokens(user) + _RESPONSE_RESERVE
        num_ctx   = min(max(_next_pow2(int(estimated * 1.5)), 2048), _MAX_CTX)
        return {
            "temperature": temperature,
            "num_keep":    _approx_tokens(system),  # pin system-prompt KV entries
            "num_ctx":     num_ctx,
            "num_gpu":     _NUM_GPU,
            "num_batch":   _NUM_BATCH,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Plain-text completion. Raises RuntimeError if Ollama is offline."""
        payload: Dict[str, Any] = {
            "model":      self.model,
            "messages":   [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream":     False,
            "keep_alive": _KEEP_ALIVE,
            "options":    self._ollama_options(temperature, system, user),
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
            resp    = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]

        self._cache_set(cache_key, content)
        self._sem_index_add(system_hash, cache_key, user)
        return content

    def complete_stream(
        self,
        system:      str,
        user:        str,
        messages:    Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.2,
    ) -> Iterable[str]:
        """Streaming completion for interactive chat. Not cached."""
        if not self.is_available():
            raise RuntimeError("Ollama is not running. Start it with: ollama serve")

        chat_messages = [{"role": "system", "content": system}]
        chat_messages.extend(messages or [])
        chat_messages.append({"role": "user", "content": user})

        payload: Any = {
            "model":      self.model,
            "messages":   chat_messages,
            "stream":     True,
            "keep_alive": _KEEP_ALIVE,
            "options":    self._ollama_options(temperature, system, user),
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
                data  = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done"):
                    break

    def complete_json(
        self,
        system:             str,
        user:               str,
        schema:             Optional[Dict[str, Any]] = None,
        cache_key_override: Optional[str]            = None,
    ) -> Any:
        """JSON-mode completion.

        cache_key_override
            When set, this hash is used as the cache key instead of the
            full payload hash. AICriticChecker passes an AST-derived hash
            so cache hits survive comment/whitespace edits.

        Raises RuntimeError if Ollama is not running.
        """
        payload: Dict[str, Any] = {
            "model":      self.model,
            "messages":   [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream":     False,
            "format":     "json",
            "keep_alive": _KEEP_ALIVE,
            "options":    self._ollama_options(0.1, system, user),
        }

        cache_key = cache_key_override or self._cache_key(
            {"kind": "json", "payload": payload, "schema": schema}
        )

        # Layer 1 + 2: exact match
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        system_hash = sha256(system.encode()).hexdigest()

        # Layer 3: semantic match (skip when caller provided their own key)
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
            resp = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            raw    = resp.json()["message"]["content"]
            result = json.loads(raw)

        self._cache_set(cache_key, result)
        if cache_key_override is None:
            self._sem_index_add(system_hash, cache_key, user)
        return result
