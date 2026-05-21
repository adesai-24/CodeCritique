# Changelog

All notable changes to CodeCritique will be documented in this file.

## 0.1.0 - Unreleased

### Added
- Package the CLI as `codecritique` with the legacy `critique` command retained.
- GitHub Actions CI matrix covering Python 3.10, 3.11, and 3.12.
- Repository contribution templates for issues and pull requests.
- MIT license.
- Web demo (`web/`) — FastAPI backend that streams review results via SSE, with a
  single-page Monaco-editor frontend (no build step).
- `POST /api/github-file` endpoint — fetch any GitHub-hosted source file by URL
  directly into the web demo editor.
- Rate limiting on `/api/review` (10/hour) and `/api/github-file` (20/hour) via `slowapi`.
- AI synthesis in the web server falls back automatically:
  Anthropic (if `ANTHROPIC_API_KEY` is set) → Ollama → static-only.
- Integration test suite for the web server (`tests/test_web.py`).
