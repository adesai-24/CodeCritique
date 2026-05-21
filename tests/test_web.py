import pytest

from web import main


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
