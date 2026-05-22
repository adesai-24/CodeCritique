import json
import os
import requests
import tempfile
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_TIMEOUT = 300  # qwen2.5-coder:7b can be slow on CPU; 5 min is safe
DEFAULT_CACHE_DIR = Path.home() / ".codecritique" / "cache"
AVAILABILITY_CACHE_SECONDS = 30.0

_CACHE_LOCK = threading.Lock()
_AVAILABILITY_LOCK = threading.Lock()
_AVAILABILITY_CACHE: Dict[str, Tuple[float, bool]] = {}

# In-memory cache: avoids all disk I/O on repeated queries within the same process.
# Keyed by the same sha256 hash used for disk cache. No eviction — typical runs
# touch far fewer than 1 000 unique prompts.
_MEM_CACHE: Dict[str, Any] = {}
_MEM_CACHE_LOCK = threading.Lock()

# Disk-cache snapshot: we load the JSON file once and reuse it until the file
# is modified on disk.  This cuts repeated disk reads when many threads call
# _cache_get concurrently.
_DISK_SNAPSHOT: Optional[Dict[str, Any]] = None
_DISK_SNAPSHOT_MTIME: float = 0.0
_DISK_SNAPSHOT_LOCK = threading.Lock()


def _cache_enabled_by_env() -> bool:
    value = os.environ.get("CODECRITIQUE_AI_CACHE", "1").lower()
    return value not in {"0", "false", "no", "off"}


class LLMClient:
    """
    Thin wrapper around the Ollama HTTP API.

    Supports plain-text completion and structured JSON completion.
    Fails with a clear RuntimeError (not a crash) when Ollama is offline.

    Two-level cache:
      1. In-memory dict  — instant, no I/O, lives for the process lifetime.
      2. Disk JSON file  — survives across runs, loaded lazily and shared via
         a snapshot that is only re-read when the file changes on disk.
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

    @property
    def _cache_path(self) -> Path:
        return self.cache_dir / "llm_cache.json"

    def _cache_key(self, payload: Dict[str, Any]) -> str:
        stable_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(stable_payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Disk snapshot helpers
    # ------------------------------------------------------------------

    def _load_disk_snapshot(self) -> Dict[str, Any]:
        """Return the disk cache, using a process-level snapshot to avoid
        repeated file reads. The snapshot is invalidated when the file's
        mtime changes."""
        global _DISK_SNAPSHOT, _DISK_SNAPSHOT_MTIME
        cache_path = self._cache_path
        with _DISK_SNAPSHOT_LOCK:
            try:
                mtime = cache_path.stat().st_mtime if cache_path.exists() else 0.0
            except Exception:
                mtime = 0.0

            if _DISK_SNAPSHOT is None or mtime != _DISK_SNAPSHOT_MTIME:
                try:
                    if cache_path.exists():
                        data = json.loads(cache_path.read_text(encoding="utf-8"))
                        _DISK_SNAPSHOT = data if isinstance(data, dict) else {}
                    else:
                        _DISK_SNAPSHOT = {}
                except Exception:
                    _DISK_SNAPSHOT = {}
                _DISK_SNAPSHOT_MTIME = mtime

            return _DISK_SNAPSHOT  # type: ignore[return-value]

    def _write_disk(self, cache: Dict[str, Any]) -> None:
        global _DISK_SNAPSHOT, _DISK_SNAPSHOT_MTIME
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=self.cache_dir,
            encoding="utf-8",
        ) as tmp:
            json.dump(cache, tmp)
            tmp_path = Path(tmp.name)
        tmp_path.replace(self._cache_path)
        # Update snapshot so subsequent reads in this process stay hot.
        try:
            _DISK_SNAPSHOT_MTIME = self._cache_path.stat().st_mtime
        except Exception:
            pass
        _DISK_SNAPSHOT = cache

    # ------------------------------------------------------------------
    # Public cache interface
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[Any]:
        if not self.use_cache:
            return None

        # 1. Check in-memory cache (no lock needed for dict reads in CPython,
        #    but use one to be safe across platforms).
        with _MEM_CACHE_LOCK:
            if key in _MEM_CACHE:
                return _MEM_CACHE[key]

        # 2. Fall back to disk snapshot.
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

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        """
        Send a chat completion request and return the assistant's reply as a string.

        Raises RuntimeError if Ollama is not running.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        cache_key = self._cache_key({"kind": "text", "payload": payload})
        cached = self._cache_get(cache_key)
        if isinstance(cached, str):
            return cached

        if not self.is_available():
            raise RuntimeError(
                "Ollama is not running. Start it with: ollama serve"
            )

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        self._cache_set(cache_key, content)
        return content

    def complete_stream(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.2,
    ) -> Iterable[str]:
        """
        Send a streaming chat completion request and yield content chunks.

        `messages` should contain prior conversation turns. The current user
        message is appended after that history.
        """
        if not self.is_available():
            raise RuntimeError(
                "Ollama is not running. Start it with: ollama serve"
            )

        chat_messages = [{"role": "system", "content": system}]
        chat_messages.extend(messages or [])
        chat_messages.append({"role": "user", "content": user})

        payload: Any = {
            "model": self.model,
            "messages": chat_messages,
            "stream": True,
            "options": {"temperature": temperature},
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
    ) -> Any:
        """
        Send a chat completion request with JSON mode enabled.

        Returns the parsed Python object. The caller is responsible for
        validating the shape — this method only guarantees valid JSON.

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
            "options": {"temperature": 0.1},
        }
        cache_key = self._cache_key(
            {"kind": "json", "payload": payload, "schema": schema}
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        if not self.is_available():
            raise RuntimeError(
                "Ollama is not running. Start it with: ollama serve"
            )

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        result = json.loads(raw)
        self._cache_set(cache_key, result)
        return result
