# CodeCritique

CodeCritique is an AI-assisted local code review tool for Python projects. It combines static analysis, optional local or cloud AI synthesis, saved review history, and a browser demo into one workflow you can run before pushing code.

## Features

- **Integrated linting**: Runs Ruff for style, import, and correctness checks.
- **Type checking**: Runs Mypy for static type analysis.
- **Security auditing**: Runs Bandit for common Python security vulnerabilities.
- **Coverage checks**: Reads Coverage.py data and warns when total coverage falls below the default threshold.
- **Incremental checking**: By default, reviews only changed Python files from the current Git branch.
- **Severity levels**: Buckets findings as `FATAL`, `WARNING`, or `INFO`; fatal issues block the CLI check.
- **Local AI critic**: Uses Ollama with `qwen2.5-coder:7b` to catch logic bugs and design issues static tools can miss.
- **AI enrichment**: Adds plain-English reasoning and concrete suggested fixes to checker findings.
- **AI synthesis**: Produces a prioritized review with a summary, fix-first recommendation, severity groups, and positive observations.
- **Saved reports**: Stores recent review reports locally and lets you list them or chat with a saved report.
- **Performance optimizations**: Runs independent checkers concurrently, chunks AI reviews by function/class, batches AI enrichment, and caches AI responses.
- **Web demo**: Serves a FastAPI + Monaco browser UI where users can paste Python or import a single GitHub file and stream review results.

## Requirements

- Python 3.10, 3.11, or 3.12
- Git, for incremental checks and hook installation
- Optional for local AI: [Ollama](https://ollama.com) with `qwen2.5-coder:7b`
- Optional for web cloud synthesis: an Anthropic API key and the web dependencies

## Installation

Clone the repository and install the CLI:

```bash
git clone https://github.com/adesai-24/CodeCritique.git
cd CodeCritique
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Install development or web extras when needed:

```bash
pip install -e ".[dev]"
pip install -e ".[web]"
```

The package installs both `codecritique` and the legacy `critique` command.

## CLI Usage

Run the default incremental review. AI is enabled by default and skipped automatically if Ollama is not reachable:

```bash
codecritique check
```

Review specific files:

```bash
codecritique check src/app.py tests/test_app.py
```

Scan all Python files in the repository:

```bash
codecritique check --no-incremental
```

Run static analysis only:

```bash
codecritique check --no-ai
```

Install the Git pre-push hook:

```bash
codecritique install-hooks
```

The hook runs `codecritique check --incremental` before every push. Git cancels the push if CodeCritique returns fatal findings. You can still bypass hooks with `git push --no-verify`, but that should be rare.

## Local AI Setup

Install and start Ollama, then pull the default model:

```bash
ollama serve
ollama pull qwen2.5-coder:7b
```

When Ollama is running, the CLI adds three AI stages:

1. The AI critic reviews Python code for semantic bugs.
2. The AI enricher explains checker findings and suggests fixes.
3. The AI synthesizer builds the final prioritized report.

If Ollama is offline, CodeCritique falls back to static analysis and still saves a report.

## Saved Reports And Chat

Each CLI run saves a compact JSON report under:

```text
~/.codecritique/reports
```

Only the 50 most recent reports are kept. List saved reports:

```bash
codecritique list
```

Chat with the latest report:

```bash
codecritique chat --last
```

Chat with a specific report ID:

```bash
codecritique chat rev_abc123
```

Report chat uses local Ollama streaming completions and answers from the saved findings, file paths, line numbers, reasoning, and suggested fixes.

## AI Caching And Performance

CodeCritique caches local AI responses under:

```text
~/.codecritique/cache
```

The cache includes:

- An in-memory cache for the current process.
- A disk cache in `llm_cache.json`.
- A semantic index in `semantic_index.json` for near-duplicate prompts.
- AST-derived cache keys for AI critic chunks, so comment and whitespace-only edits can reuse prior results.

Disable AI caching for one run:

```bash
CODECRITIQUE_AI_CACHE=0 codecritique check
```

Tune concurrency on smaller machines:

```bash
CODECRITIQUE_CHECKER_WORKERS=2 CODECRITIQUE_AI_CRITIC_WORKERS=1 codecritique check
```

Keep the Ollama model loaded for a custom duration:

```bash
CODECRITIQUE_KEEP_ALIVE=30m codecritique check
```

Use `CODECRITIQUE_KEEP_ALIVE=-1` to ask Ollama to keep the model loaded indefinitely.

## Web Demo

The web demo provides a browser-based review flow with:

- Monaco editor for pasted Python.
- Sample clean, bug-prone, security, and type-error snippets.
- GitHub file import for `github.com/.../blob/...`, `raw.githubusercontent.com`, and raw Gist URLs.
- SSE progress events for Ruff, Bandit, Mypy, synthesis, issues, and completion.
- Rate limiting for review and GitHub fetch endpoints.
- AI status detection for Anthropic and Ollama.

Install web dependencies:

```bash
pip install -e ".[web]"
```

Start the server:

```bash
uvicorn web.main:app --reload --port 8000
```

On Windows, you can also run:

```powershell
.\web\start.ps1
```

Then open:

```text
http://localhost:8000
```

The web API exposes:

- `GET /api/health`
- `POST /api/github-file`
- `POST /api/review`

For synthesis, the web app prefers Anthropic when `ANTHROPIC_API_KEY` is set. Otherwise it tries local Ollama. If neither is available, it returns static-analysis results with a fallback summary.

## Configuration

Current defaults:

- Coverage threshold: 80%
- Incremental base: `origin/main`
- Local AI model: `qwen2.5-coder:7b`
- Ollama URL: `http://localhost:11434`
- AI cache: enabled by default
- Saved report limit: 50 reports

CodeCritique does not yet read a project config file. A future version may add `critique.toml` for thresholds, rule exclusions, model settings, and other project-specific options.

## Testing

Run the test suite:

```bash
pytest
```

The tests cover checkers, AI client behavior, enrichment/synthesis, report persistence, Git utilities, and the FastAPI web routes.
