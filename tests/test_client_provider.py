"""Tests that LLMClient correctly delegates to a non-Ollama provider."""

import pytest

from critique.ai.client import LLMClient, OllamaProvider, _AVAILABILITY_CACHE


class FakeProvider:
    name = "fake"
    supports_prefix_cache = False
    availability_key = "fake"

    def __init__(self):
        self.model = "fake-model"
        self.json_calls = 0
        self.text_calls = 0
        self.available = True

    def is_available(self):
        return self.available

    def unavailable_message(self):
        return "fake provider unavailable"

    def complete_text(self, system, user, *, temperature):
        self.text_calls += 1
        return f"text:{user}"

    def complete_json(self, system, user, *, schema=None):
        self.json_calls += 1
        return '{"value": 42}'

    def stream(self, system, history, user, *, temperature):
        yield "a"
        yield "b"


@pytest.fixture(autouse=True)
def _clear_availability():
    _AVAILABILITY_CACHE.clear()
    yield
    _AVAILABILITY_CACHE.clear()


@pytest.fixture()
def client(tmp_path):
    c = LLMClient(provider="openai", model="gpt-4o-mini", cache_dir=tmp_path)
    c.provider = FakeProvider()
    return c


def test_default_no_arg_client_uses_config_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("CODECRITIQUE_PROVIDER", raising=False)
    # No config file → default provider is gemini.
    from critique import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.json")
    client = LLMClient(cache_dir=tmp_path)
    assert client.provider_name == "gemini"


def test_explicit_base_url_keeps_ollama_backcompat(tmp_path):
    client = LLMClient(base_url="http://localhost:11434", model="m", cache_dir=tmp_path)
    assert isinstance(client.provider, OllamaProvider)
    assert client.provider_name == "ollama"


def test_complete_json_parses_and_caches(client):
    first = client.complete_json("s", "u")
    second = client.complete_json("s", "u")
    assert first == {"value": 42}
    assert second == {"value": 42}
    # Second call served from cache — provider hit only once.
    assert client.provider.json_calls == 1


def test_complete_text_delegates(client):
    assert client.complete("s", "hello") == "text:hello"


def test_raises_when_provider_unavailable(client):
    client.provider.available = False
    with pytest.raises(RuntimeError, match="fake provider unavailable"):
        client.complete_json("s", "u")


def test_stream_delegates(client):
    assert list(client.complete_stream("s", "u")) == ["a", "b"]
