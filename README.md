# CodeCritique

CodeCritique is a local development tool designed to evaluate your code before you push it to a GitHub repository. It acts as a final check to ensure code quality by integrating static analysis tools and a local AI reviewer into a single, unified feedback loop.

## Features

- **Integrated Linting**: Uses `Ruff` for style and error checking.
- **Type Checking**: Uses `Mypy` for static type analysis.
- **Security Auditing**: Uses `Bandit` to find common security vulnerabilities.
- **Coverage Reports**: Checks test coverage using `Coverage.py`.
- **Incremental Checking**: Optionally checks only the files that have changed in your current branch.
- **Severity Levels**: Categorizes issues into "Fatal" (blocks pushes) and "Warnings" (actionable feedback).
- **AI Critic** *(new)*: Reviews each file with a local LLM (`qwen2.5-coder:7b` via Ollama) to catch logic bugs, edge cases, and design issues that static tools miss.
- **AI Enricher** *(new)*: Runs concurrently to add plain-English reasoning and a concrete suggested fix to every issue found by any checker.
- **AI Synthesizer + Report** *(new)*: Produces a curated summary — a "fix first" priority call, grouped critical/warning/suggestion buckets, and a "what's good" section — instead of a raw issue list.

## Prerequisites

### Ollama (required for AI features)

The AI pipeline requires [Ollama](https://ollama.com) running locally with the `qwen2.5-coder:7b` model pulled.

1. **Install Ollama** — download from [ollama.com](https://ollama.com) or via the installer for your platform.

2. **Start the Ollama server**:

   ```bash
   ollama serve
   ```

3. **Pull the model** (one-time, ~4 GB download):

   ```bash
   ollama pull qwen2.5-coder:7b
   ```

If Ollama is not running when you invoke `critique`, the AI stages are skipped automatically and the tool falls back to the standard static-analysis report — no crash, no manual flag needed.

## Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/adesai-24/CodeCritique.git
   cd CodeCritique
   ```

2. **Set up a virtual environment**:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install CodeCritique**:
   ```bash
   pip install -e .
   ```

Supported Python versions: 3.10 through 3.12.

## Web Demo

A browser-based demo is included in `web/`. It accepts pasted code and streams results live — no local install required for the reviewer.

### Running the web server locally

1. **Install web dependencies**:

   ```bash
   pip install -e ".[web]"
   # Optional: add cloud AI synthesis
   pip install -e ".[web,cloud]"
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

2. **Start the server** (from the repo root):

   ```bash
   uvicorn web.main:app --reload --port 8000
   # Or on Windows:
   .\web\start.ps1
   ```

3. **Open** `http://localhost:8000` in your browser.

The demo runs the same Ruff, Bandit, and Mypy pipeline as the CLI. If `ANTHROPIC_API_KEY` is set it uses Claude for synthesis; otherwise it falls back to Ollama, then static-only mode.

You can also load a file directly from GitHub using the "Fetch from GitHub" button — paste any `github.com/.../blob/...` file URL.

## Usage

### Manual Check

Run the critique on only your modified files (AI enabled by default):

```bash
codecritique check
```

Run on specific files:

```bash
codecritique check path/to/file.py
```

Run a full scan of all Python files in the repository:

```bash
codecritique check --no-incremental
```

Run with AI features disabled (static analysis only, no Ollama required):

```bash
codecritique check --no-ai
```

### AI Report Output

When Ollama is running, `critique check` produces a curated AI report instead of a raw issue list:

```
+-------------------------- CodeCritique AI Review ---------------------------+
| Found 3 issue(s). Review the list below.                                    |
+-----------------------------------------------------------------------------+

+-------------------------------- !! Priority --------------------------------+
| Fix First: src/app.py:42 - Unhandled None return                            |
+-----------------------------------------------------------------------------+

------------------------------------------------------------
  CRITICAL - Must Fix
------------------------------------------------------------

  Unhandled None return  (AI)
  src/app.py:42
  get_user() can return None when the user is not found, but the caller
  dereferences the result without checking.
  Fix: Add `if user is None: return` before line 43.

BLOCKED: Fix 2 critical issue(s) before pushing.
```

Each issue includes:
- **Source** — which checker flagged it (`AI`, `ruff`, `bandit`, etc.)
- **Reasoning** — plain-English explanation from the AI Enricher
- **Suggested fix** — a concrete, actionable recommendation
- **Code context** — the relevant lines from the file

### Git Hooks

To automate this tool, install it as a Git `pre-push` hook. This prevents pushing if any fatal issues are found.

```bash
codecritique install-hooks
```

## Git Hooks Explained

The `install-hooks` command creates a script in `.git/hooks/pre-push`.

Each time you run `git push`, your computer automatically runs `critique check --incremental` first. If the tool finds critical issues (like a syntax error or security hole), it returns a failure code to Git, which cancels your push. This ensures that only high-quality, verified code reaches your remote repository.

When Ollama is running, the pre-push hook also runs the full AI pipeline. If Ollama is offline, the hook falls back to static-analysis-only mode without any extra configuration.

## Configuration

Currently, the tool uses default configurations for the underlying tools:

- **Coverage**: Hardcoded threshold of 80%.
- **Linter**: Uses the default Ruff configuration.
- **Incremental Mode**: Compares current branch changes against `origin/main`.
- **AI Model**: `qwen2.5-coder:7b` via Ollama at `http://localhost:11434`. Override via environment variable or by editing `src/critique/ai/client.py`.

Future versions will support a `critique.toml` file for custom thresholds, rule exclusions, and model selection.
