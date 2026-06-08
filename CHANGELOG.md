# Changelog

All notable changes to CodeCritique will be documented in this file.

## 0.1.0 - Unreleased

- **Single-line install**: CodeCritique installs as a standalone CLI with
  `pipx install git+https://github.com/adesai-24/CodeCritique.git` (or `pip
  install git+...`) instead of cloning the repo into your project. The tool
  lives in its own environment, keeping your project repo clean. Added
  `.gitignore` entries so an accidental vendored clone stays invisible; cloning
  is now only needed for contributing or running the web demo.
- **C/C++ support**: review `.c`/`.cpp`/`.h`/`.hpp` (and related) files. The AI
  critic understands C/C++ idioms and pitfalls, and a new `cppcheck`-backed
  static checker flags memory-safety and correctness issues. Both incremental
  (git diff) and full-scan modes now pick up C/C++ files automatically. The
  static `cppcheck` tool is optional — if it isn't installed, that checker is
  skipped and the rest of the pipeline still runs.
- **`codecritique format`**: an agentic, behaviour-preserving formatter that
  reshapes code for review — consistent spacing, column-aligned declarations,
  and a documenting comment above every function. Previews a diff by default;
  apply with `--in-place` (originals are backed up to `<file>.bak`). Works for
  both Python and C/C++.
- Centralised language detection in `critique.languages` so supported file
  types live in one place.
- Package the CLI as `codecritique` with the legacy `critique` command retained.
- Add the core `check` command with incremental Git-aware file selection, specific-file checks, full-repository scans, and `--no-ai` static-only mode.
- Add Ruff, Mypy, Bandit, and Coverage.py checkers with severity-based reporting.
- Add Git pre-push hook installation via `codecritique install-hooks`.
- Add optional Ollama-powered AI review using `qwen2.5-coder:7b`, including the AI critic, AI enrichment, and synthesized priority reports.
- Add graceful static-analysis fallback when Ollama or AI report generation is unavailable.
- Add saved review reports under `~/.codecritique/reports`, report pruning, `codecritique list`, and `codecritique chat` for follow-up questions about saved reports.
- Add local AI caching under `~/.codecritique/cache`, including in-memory reuse, disk snapshots, semantic similarity lookup, AST-derived critic cache keys, and Ollama keep-alive/prefix-cache options.
- Add checker and AI critic concurrency controls through `CODECRITIQUE_CHECKER_WORKERS` and `CODECRITIQUE_AI_CRITIC_WORKERS`.
- Add batched AI enrichment with per-issue fallback and canned enrichment for simple formatting findings.
- Add a FastAPI web demo with Monaco editor, sample snippets, streamed SSE review progress, static checker execution, AI synthesis, health checks, rate limiting, and GitHub/raw Gist file import.
- Add optional Anthropic synthesis support in the web demo when `ANTHROPIC_API_KEY` is configured.
- Add GitHub Actions coverage for Python 3.10, 3.11, and 3.12.
- Add repository contribution templates for issues and pull requests.
- Add MIT licensing.
