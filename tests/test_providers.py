"""
Tests for the provider abstraction.

The cloud SDKs (google-genai, openai, anthropic) are stubbed via sys.modules so
these tests run without the real packages and without any network access.
"""

import sys
import types

import pytest

from critique.ai.providers import build_provider, ProviderError


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_build_unknown_provider_raises():
    with pytest.raises(ProviderError):
        build_provider("does-not-exist")


def test_build_gemini_provider_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Point the secrets store at an empty temp file so no real key leaks in.
    from critique import secrets_store
    monkeypatch.setattr(secrets_store, "SECRETS_PATH", "/nonexistent/secrets.env")
    provider = build_provider("gemini", api_key=None)
    assert provider.name == "gemini"
    assert provider.is_available() is False
    assert "API key" in provider.unavailable_message()


def test_build_openai_provider_available_with_key():
    provider = build_provider("openai", api_key="sk-test")
    assert provider.name == "openai"
    assert provider.is_available() is True


def test_vllm_provider_available_with_base_url():
    provider = build_provider("vllm", base_url="http://localhost:8000/v1")
    assert provider.name == "vllm"
    assert provider.is_available() is True  # key optional for vLLM


def test_vllm_uses_default_base_url():
    provider = build_provider("vllm")
    assert provider.base_url == "http://localhost:8000/v1"


# ---------------------------------------------------------------------------
# Gemini provider with a stubbed SDK
# ---------------------------------------------------------------------------

@pytest.fixture()
def stub_genai(monkeypatch):
    """Install a fake `google.genai` module that records calls."""
    calls = {}

    class FakeResponse:
        def __init__(self, text):
            self.text = text

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls["model"] = model
            calls["contents"] = contents
            calls["config"] = config
            return FakeResponse('{"ok": true}')

    class FakeClient:
        def __init__(self, api_key):
            calls["api_key"] = api_key
            self.models = FakeModels()

    class FakeTypes:
        @staticmethod
        def GenerateContentConfig(**kwargs):
            return kwargs

    genai_mod = types.ModuleType("google.genai")
    genai_mod.Client = FakeClient
    types_mod = types.ModuleType("google.genai.types")
    types_mod.GenerateContentConfig = FakeTypes.GenerateContentConfig
    google_mod = types.ModuleType("google")
    google_mod.genai = genai_mod

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    return calls


def test_gemini_complete_json_returns_raw_text(stub_genai):
    provider = build_provider("gemini", api_key="key-123", model="gemini-2.0-flash")
    raw = provider.complete_json("system prompt", "user prompt")
    assert raw == '{"ok": true}'
    assert stub_genai["api_key"] == "key-123"
    assert stub_genai["model"] == "gemini-2.0-flash"
    # JSON mode should request application/json.
    assert stub_genai["config"]["response_mime_type"] == "application/json"


def test_gemini_complete_text_passes_temperature(stub_genai):
    provider = build_provider("gemini", api_key="key", model="gemini-2.0-flash")
    provider.complete_text("sys", "usr", temperature=0.4)
    assert stub_genai["config"]["temperature"] == 0.4
    assert stub_genai["config"]["response_mime_type"] == "text/plain"
