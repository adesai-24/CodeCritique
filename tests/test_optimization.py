"""Tests for inference-optimization features (branch 3)."""

import pytest
from unittest.mock import MagicMock, patch

from critique.ai import client as llm_client
from critique.ai.client import LLMClient, _AVAILABILITY_CACHE
from critique.ai.providers import build_provider


@pytest.fixture(autouse=True)
def _clear(tmp_path):
    _AVAILABILITY_CACHE.clear()
    llm_client.reset_cache_stats()
    yield
    _AVAILABILITY_CACHE.clear()


# ---------------------------------------------------------------------------
# Ollama performance options
# ---------------------------------------------------------------------------

def test_default_num_predict_is_applied(monkeypatch):
    monkeypatch.delenv("CODECRITIQUE_NUM_PREDICT", raising=False)
    opts = llm_client._ollama_perf_options()
    assert opts["num_predict"] == llm_client._DEFAULT_NUM_PREDICT


def test_num_predict_env_override(monkeypatch):
    monkeypatch.setenv("CODECRITIQUE_NUM_PREDICT", "512")
    assert llm_client._ollama_perf_options()["num_predict"] == 512


def test_perf_knobs_only_present_when_set(monkeypatch):
    monkeypatch.delenv("CODECRITIQUE_NUM_CTX", raising=False)
    assert "num_ctx" not in llm_client._ollama_perf_options()
    monkeypatch.setenv("CODECRITIQUE_NUM_CTX", "8192")
    assert llm_client._ollama_perf_options()["num_ctx"] == 8192


def test_perf_options_flow_into_ollama_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("CODECRITIQUE_NUM_PREDICT", "256")
    client = LLMClient(base_url="http://localhost:11434", model="m", cache_dir=tmp_path)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "ok"}}
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp) as mock_post:
        client.complete(system="s", user="u")
    options = mock_post.call_args[1]["json"]["options"]
    assert options["num_predict"] == 256


# ---------------------------------------------------------------------------
# Cache instrumentation
# ---------------------------------------------------------------------------

def test_cache_stats_track_hits_and_misses(tmp_path):
    client = LLMClient(base_url="http://localhost:11434", model="m", cache_dir=tmp_path)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "hello"}}
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp):
        client.complete(system="s", user="u")  # miss
        client.complete(system="s", user="u")  # hit
    stats = llm_client.cache_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 1


def test_cache_info_and_clear(tmp_path):
    client = LLMClient(base_url="http://localhost:11434", model="m", cache_dir=tmp_path)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "x"}}
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp):
        client.complete(system="s", user="u")
    info = llm_client.cache_info(tmp_path)
    assert info["entries"] >= 1
    removed = llm_client.clear_cache(tmp_path)
    assert removed >= 1
    assert llm_client.cache_info(tmp_path)["entries"] == 0


# ---------------------------------------------------------------------------
# Prefix-cache capability flag
# ---------------------------------------------------------------------------

def test_ollama_supports_prefix_cache(tmp_path):
    client = LLMClient(base_url="http://localhost:11434", model="m", cache_dir=tmp_path)
    assert client.supports_prefix_cache is True


def test_cloud_provider_no_prefix_cache(tmp_path):
    client = LLMClient(provider="openai", model="gpt-4o-mini", cache_dir=tmp_path)
    assert client.supports_prefix_cache is False


# ---------------------------------------------------------------------------
# vLLM guided JSON decoding
# ---------------------------------------------------------------------------

def test_vllm_complete_json_uses_guided_json():
    provider = build_provider("vllm", base_url="http://localhost:8000/v1")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"ok": 1}'))]
    )
    with patch.object(provider, "_get_client", return_value=fake_client):
        out = provider.complete_json("s", "u", schema={"type": "object"})
    assert out == '{"ok": 1}'
    kwargs = fake_client.chat.completions.create.call_args[1]
    assert kwargs["extra_body"]["guided_json"] == {"type": "object"}


def test_openai_complete_json_no_guided_json():
    provider = build_provider("openai", api_key="sk-test")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="{}"))]
    )
    with patch.object(provider, "_get_client", return_value=fake_client):
        provider.complete_json("s", "u", schema={"type": "object"})
    kwargs = fake_client.chat.completions.create.call_args[1]
    assert "extra_body" not in kwargs


# ---------------------------------------------------------------------------
# Concurrent chunk review for stateless backends
# ---------------------------------------------------------------------------

class _FakeLLM:
    supports_prefix_cache = False

    def complete_json(self, system, user, schema=None, cache_key_override=None):
        # One finding per reviewed chunk; line 1 relative to the chunk.
        return {"findings": [{"line": 1, "title": "issue", "explanation": "x", "severity": "WARNING"}]}


def test_ai_critic_reviews_all_chunks_concurrently(tmp_path):
    from critique.checkers.ai_critic import AICriticChecker

    src = (
        "def alpha():\n    return 1\n\n\n"
        "def beta():\n    return 2\n"
    )
    f = tmp_path / "mod.py"
    f.write_text(src, encoding="utf-8")

    checker = AICriticChecker(_FakeLLM())
    issues = checker.run([str(f)])
    # Two top-level functions → two chunks → two findings.
    assert len(issues) == 2
    assert all(i.code == "AI" for i in issues)
