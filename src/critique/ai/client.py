import json
import requests
from typing import Any, Dict, Iterable, List, Optional

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_TIMEOUT = 300  # qwen2.5-coder:7b can be slow on CPU; 5 min is safe


class LLMClient:
    """
    Thin wrapper around the Ollama HTTP API.

    Supports plain-text completion and structured JSON completion.
    Fails with a clear RuntimeError (not a crash) when Ollama is offline.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        """Return True if Ollama is reachable."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        """
        Send a chat completion request and return the assistant's reply as a string.

        Raises RuntimeError if Ollama is not running.
        """
        if not self.is_available():
            raise RuntimeError(
                "Ollama is not running. Start it with: ollama serve"
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

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

        payload = {
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
        if not self.is_available():
            raise RuntimeError(
                "Ollama is not running. Start it with: ollama serve"
            )
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
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        return json.loads(raw)
