"""Integration tests for the FastAPI web server (web/main.py)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Bootstrap src/ onto path so the web module can import critique.*
_src = str(Path(__file__).parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))
import main  # noqa: E402

client = TestClient(main.app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the in-memory rate-limit counters before every test."""
    main.limiter._storage.reset()
    yield


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_has_expected_keys(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert "ai" in data
        assert "anthropic" in data["ai"]
        assert "ollama" in data["ai"]

    def test_health_ai_values_are_bools(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert isinstance(data["ai"]["anthropic"], bool)
        assert isinstance(data["ai"]["ollama"], bool)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestIndexRoute:
    def test_root_serves_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<title>CodeCritique</title>" in resp.text

    def test_root_contains_run_review_button(self):
        resp = client.get("/")
        assert "Run Review" in resp.text


# ---------------------------------------------------------------------------
# POST /api/review  (static-only — no AI calls)
# ---------------------------------------------------------------------------

_CLEAN_CODE = 'def add(a: int, b: int) -> int:\n    return a + b\n'
_BUGGY_CODE = (
    "import subprocess\n"
    "import os\n"
    "\n"
    "def run(cmd):\n"
    "    subprocess.run(cmd, shell=True)\n"
)


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE stream into list of (event, data) dicts."""
    events = []
    current_event = "message"
    for line in text.splitlines():
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            payload = line[5:].strip()
            try:
                events.append({"event": current_event, "data": json.loads(payload)})
            except json.JSONDecodeError:
                pass
            current_event = "message"
    return events


class TestReviewEndpoint:
    def _review(self, code: str, filename: str = "main.py") -> list[dict]:
        resp = client.post(
            "/api/review",
            json={"code": code, "filename": filename, "language": "python"},
        )
        assert resp.status_code == 200
        return _parse_sse(resp.text)

    def test_review_returns_sse_stream(self):
        resp = client.post(
            "/api/review",
            json={"code": _CLEAN_CODE, "filename": "main.py"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_review_emits_complete_event(self):
        events = self._review(_CLEAN_CODE)
        event_types = [e["event"] for e in events]
        assert "complete" in event_types

    def test_review_emits_issues_event(self):
        events = self._review(_BUGGY_CODE)
        event_types = [e["event"] for e in events]
        assert "issues" in event_types

    def test_review_complete_has_totals(self):
        events = self._review(_BUGGY_CODE)
        complete = next(e["data"] for e in events if e["event"] == "complete")
        assert "total" in complete
        assert "fatal" in complete
        assert "warnings" in complete
        assert "info" in complete
        assert "passed" in complete

    def test_clean_code_passes(self):
        events = self._review(_CLEAN_CODE)
        complete = next(e["data"] for e in events if e["event"] == "complete")
        assert complete["passed"] is True

    def test_buggy_code_finds_issues(self):
        events = self._review(_BUGGY_CODE)
        issues_event = next(e["data"] for e in events if e["event"] == "issues")
        assert len(issues_event) > 0

    def test_issues_have_required_fields(self):
        events = self._review(_BUGGY_CODE)
        issues_event = next(e["data"] for e in events if e["event"] == "issues")
        for issue in issues_event:
            assert "severity" in issue
            assert "message" in issue
            assert "line" in issue
            assert "file" in issue

    def test_filename_patched_in_issues(self):
        events = self._review(_BUGGY_CODE, filename="mymodule.py")
        issues_event = next(e["data"] for e in events if e["event"] == "issues")
        for issue in issues_event:
            assert issue["file"] == "mymodule.py"

    def test_checker_done_events_emitted_for_all_checkers(self):
        events = self._review(_BUGGY_CODE)
        done_checkers = {
            e["data"]["checker"] for e in events if e["event"] == "checker_done"
        }
        assert "Lint (Ruff)" in done_checkers
        assert "Security (Bandit)" in done_checkers
        assert "Types (Mypy)" in done_checkers

    def test_empty_code_still_completes(self):
        events = self._review("# empty\n")
        event_types = [e["event"] for e in events]
        assert "complete" in event_types

    def test_status_events_emitted(self):
        events = self._review(_CLEAN_CODE)
        status_events = [e for e in events if e["event"] == "status"]
        assert len(status_events) > 0


# ---------------------------------------------------------------------------
# GitHub file utilities
# ---------------------------------------------------------------------------

def test_github_blob_url_maps_to_raw_file():
    raw_url, filename = main._github_raw_url(
        "https://github.com/adesai-24/CodeCritique/blob/main/web/main.py"
    )

    assert raw_url == "https://raw.githubusercontent.com/adesai-24/CodeCritique/main/web/main.py"
    assert filename == "main.py"


def test_github_raw_url_is_accepted():
    url = "https://raw.githubusercontent.com/adesai-24/CodeCritique/main/web/main.py"

    assert main._github_raw_url(url) == (url, "main.py")


def test_non_github_url_is_rejected():
    with pytest.raises(ValueError, match="GitHub"):
        main._github_raw_url("https://example.com/main.py")


def test_fetch_github_file_rejects_large_files(monkeypatch):
    class Response:
        content = b"x" * (main.MAX_REMOTE_BYTES + 1)
        headers = {"content-type": "text/plain"}
        encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(ValueError, match="too large"):
        main.fetch_github_file("https://raw.githubusercontent.com/a/b/main/file.py")


def test_fetch_github_file_returns_code(monkeypatch):
    class Response:
        content = b"print('hello')\n"
        headers = {"content-type": "text/plain; charset=utf-8"}
        encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: Response())

    result = main.fetch_github_file("https://raw.githubusercontent.com/a/b/main/file.py")

    assert result["filename"] == "file.py"
    assert result["language"] == "python"
    assert result["code"] == "print('hello')\n"
