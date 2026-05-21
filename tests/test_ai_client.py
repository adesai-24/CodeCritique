"""Tests for LLMClient — all HTTP calls are mocked so Ollama is not required."""

import json
import pytest
from unittest.mock import MagicMock, patch

from critique.ai.client import LLMClient


@pytest.fixture()
def client():
    return LLMClient(base_url="http://localhost:11434", model="test-model", timeout=10)


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

def test_is_available_returns_true_when_server_ok(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("critique.ai.client.requests.get", return_value=mock_resp):
        assert client.is_available() is True


def test_is_available_returns_false_on_connection_error(client):
    with patch("critique.ai.client.requests.get", side_effect=ConnectionError()):
        assert client.is_available() is False


def test_is_available_returns_false_on_non_200(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    with patch("critique.ai.client.requests.get", return_value=mock_resp):
        assert client.is_available() is False


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

def test_complete_returns_content_string(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "hello world"}}
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp):
        result = client.complete(system="sys", user="usr")
    assert result == "hello world"


def test_complete_raises_when_ollama_offline(client):
    with patch.object(client, "is_available", return_value=False):
        with pytest.raises(RuntimeError, match="Ollama is not running"):
            client.complete(system="sys", user="usr")


def test_complete_sends_correct_payload(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "ok"}}
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp) as mock_post:
        client.complete(system="system-prompt", user="user-prompt", temperature=0.5)

    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"]
    assert payload["model"] == "test-model"
    assert payload["messages"][0] == {"role": "system", "content": "system-prompt"}
    assert payload["messages"][1] == {"role": "user", "content": "user-prompt"}
    assert payload["options"]["temperature"] == 0.5


# ---------------------------------------------------------------------------
# complete_json
# ---------------------------------------------------------------------------

def test_complete_json_parses_response(client):
    data = {"findings": [{"line": 5, "title": "bug"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": json.dumps(data)}}
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp):
        result = client.complete_json(system="s", user="u")
    assert result == data


def test_complete_json_raises_when_offline(client):
    with patch.object(client, "is_available", return_value=False):
        with pytest.raises(RuntimeError):
            client.complete_json(system="s", user="u")


def test_complete_json_sets_format_json_in_payload(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "{}"}}
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp) as mock_post:
        client.complete_json(system="s", user="u")

    payload = mock_post.call_args[1]["json"]
    assert payload.get("format") == "json"


# ---------------------------------------------------------------------------
# complete_stream
# ---------------------------------------------------------------------------

def _make_stream_response(chunks):
    """Build a mock streaming response from a list of content chunks."""
    lines = []
    for chunk in chunks:
        lines.append(json.dumps({"message": {"content": chunk}, "done": False}))
    lines.append(json.dumps({"message": {"content": ""}, "done": True}))

    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.iter_lines.return_value = lines
    return mock_resp


def test_complete_stream_yields_chunks(client):
    mock_resp = _make_stream_response(["hello", " world"])
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp):
        result = list(client.complete_stream(system="s", user="u"))
    assert result == ["hello", " world"]


def test_complete_stream_raises_when_offline(client):
    with patch.object(client, "is_available", return_value=False):
        with pytest.raises(RuntimeError):
            list(client.complete_stream(system="s", user="u"))


def test_complete_stream_includes_prior_messages(client):
    mock_resp = _make_stream_response(["ok"])
    prior = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "reply"}]
    with patch.object(client, "is_available", return_value=True), \
         patch("critique.ai.client.requests.post", return_value=mock_resp) as mock_post:
        list(client.complete_stream(system="sys", user="new", messages=prior))

    msgs = mock_post.call_args[1]["json"]["messages"]
    # system, prev user, assistant reply, new user
    assert len(msgs) == 4
    assert msgs[1] == prior[0]
    assert msgs[3] == {"role": "user", "content": "new"}
