# CodeCritique

CodeCritique is an AI-assisted local code review tool for Python projects. It combines static analysis, optional local or cloud AI synthesis, saved review history, and a browser demo into one workflow you can run before pushing code.

It supports **Python** and **C/C++** out of the box.

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
- **Multi-language**: Reviews **Python** and **C/C++** (`.c`, `.cc`, `.cpp`, `.cxx`, `.h`, `.hpp`, …). File selection (incremental and full-scan) detects supported languages automatically.
- **Integrated Linting**: Uses `Ruff` for Python style and error checking.
- **Type Checking**: Uses `Mypy` for static type analysis.
- **Security Auditing**: Uses `Bandit` to find common security vulnerabilities.
- **C/C++ Static Analysis**: Uses `cppcheck` to catch memory-safety and correctness issues (buffer overruns, null dereferences, leaks). Optional — skipped cleanly if `cppcheck` isn't installed.
- **Coverage Reports**: Checks test coverage using `Coverage.py`.
- **Code Formatter** *(new)*: `codecritique format` agentically reshapes code for review — consistent spacing, column-aligned declarations, and a documenting comment above every function — **without changing behaviour**.
- **Incremental Checking**: Optionally checks only the files that have changed in your current branch.
- **Severity Levels**: Categorizes issues into "Fatal" (blocks pushes) and "Warnings" (actionable feedback).
- **AI Critic** *(new)*: Reviews each file with an LLM to catch logic bugs, edge cases, and design issues that static tools miss.
- **Pluggable AI Providers** *(new)*: Use Google **Gemini** (the free default), local **Ollama**, **OpenAI**, **Anthropic**, or a self-hosted **vLLM** endpoint — switch with one command. API keys are stored in a permission-locked, git-ignored secrets file (never in the repo).
- **AI Enricher** *(new)*: Runs concurrently to add plain-English reasoning and a concrete suggested fix to every issue found by any checker.
- **AI Synthesizer + Report** *(new)*: Produces a curated summary — a "fix first" priority call, grouped critical/warning/suggestion buckets, and a "what's good" section — instead of a raw issue list.
- **AI Response Cache** *(new)*: Reuses prior AI critic, enrichment, and synthesis responses for identical prompts so repeated checks of unchanged code return much faster after the first run.
- **Parallel Analysis** *(new)*: Runs independent static checkers concurrently and reviews multiple AI critic files with bounded concurrency.

## AI Providers & API Keys

CodeCritique's AI pipeline is **provider-agnostic**. By default it uses Google
**Gemini**, because Google offers a generous free API tier — but you can switch
to any supported backend at any time.

| Provider    | Default model                    | Needs a key? | Notes |
|-------------|----------------------------------|--------------|-------|
| `gemini`    | `gemini-2.0-flash`               | yes (free)   | Default. Get a free key at <https://aistudio.google.com/apikey> |
| `ollama`    | `qwen2.5-coder:7b`               | no           | Fully local; requires the Ollama server (see below) |
| `openai`    | `gpt-4o-mini`                    | yes          | Hosted OpenAI |
| `anthropic` | `claude-3-5-haiku-latest`        | yes          | Hosted Claude |
| `vllm`      | `Qwen/Qwen2.5-Coder-7B-Instruct` | optional     | Self-hosted, OpenAI-compatible endpoint |

Install the cloud SDKs (only needed for `gemini`/`openai`/`anthropic`/`vllm`):

```bash
pip install -e '.[cloud]'
```

### Configuring a provider and key

```bash
# See what's supported and what's currently configured
codecritique config providers
codecritique config show

# Use the free Gemini default — just add your key
codecritique config set-key gemini            # prompts; input is hidden
# ...or non-interactively:
codecritique config set-key gemini AIza...

# Switch providers
codecritique config set provider openai
codecritique config set-key openai sk-...

# Point at a local vLLM server (no key required)
codecritique config set provider vllm
codecritique config set base_url http://localhost:8000/v1
```

### How keys are kept safe

- Keys are stored in `~/.codecritique/secrets.env` with **`0600`** permissions
  (owner-only) — **never** in the repository.
- That path is **git-ignored** and the `.env` format is recognised by common
  secret scanners.
- Keys are **masked** (`AIza…q7Yk`) whenever they are displayed.
- You can skip on-disk storage entirely by exporting an environment variable
  (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …), which always
  takes precedence over the secrets file. This is the recommended approach for
  CI.

If the selected provider has no key (or Ollama isn't running), the AI stages are
skipped automatically and CodeCritique falls back to static analysis — no crash.

## Prerequisites

### cppcheck (optional — only for C/C++ static analysis)

C/C++ static analysis is powered by [`cppcheck`](https://cppcheck.sourceforge.io/),
an external tool (not a Python package). Install it with your system package
manager:

```bash
# Debian/Ubuntu
sudo apt-get install cppcheck
# macOS
brew install cppcheck
# Windows
choco install cppcheck
```

If `cppcheck` isn't installed, CodeCritique simply skips that checker — the AI
critic still reviews your C/C++ files, and Python checks are unaffected.

### Ollama (optional — only for the local `ollama` provider)

The local AI path requires [Ollama](https://ollama.com) running with the `qwen2.5-coder:7b` model pulled.

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
### Code Formatting (review-ready layout)

`codecritique format` rewrites your code into a clean, consistent layout so it's
easy to read in review — **without changing what the code does**. It applies
proper spacing, aligns consecutive declarations/assignments into vertical
columns (the "straight-line" look), and adds a short documenting comment above
every function. It works for both Python and C/C++.

```bash
codecritique format                 # preview a diff for changed files
codecritique format src/main.cpp    # format a specific file
codecritique format --in-place      # apply the changes (originals saved as *.bak)
codecritique format --in-place --no-backup
codecritique format --no-incremental   # consider all supported files in the repo
```

By default it **previews a unified diff** and applies nothing. Pass
`--in-place` to write the changes back (the original is copied to `<file>.bak`
unless you add `--no-backup`). Like the reviewer, it uses your configured AI
provider and the shared response cache, so re-formatting unchanged code is fast.

> This step is intentionally **format-only** — it never fixes bugs, renames
> things, or alters logic. Auto-suggested fixes for technical errors are a
> separate, upcoming feature.

### Review Modes (suggestion profiles)

CodeCritique can review in different "moods". A **mode** tunes the AI's tone and
focus, which findings are surfaced, and which severities block a push — without
changing the checkers themselves.

```bash
codecritique config modes          # list modes and what they do
codecritique config mode strict    # switch mode
```

| Mode | Focus | Reports ≥ | Blocks push ≥ |
|------|-------|-----------|---------------|
| `balanced` (default) | Pragmatic; real problems only | INFO | FATAL |
| `strict` | Zero-tolerance; flags everything | INFO | **WARNING** |
| `lenient` | Real bugs only; hides nitpicks | WARNING | FATAL |
| `security` | Vulnerabilities & unsafe patterns | INFO | FATAL |
| `mentor` | Detailed, teaching tone | INFO | **NEVER** |
| `concise` | One-line findings & fixes | INFO | FATAL |

**Project context** lets you tell the reviewer about your codebase so its
suggestions match your stack — and it becomes part of the AI cache key, so
updating it produces fresh reviews:

```bash
codecritique config context "Async FastAPI service; prefer pydantic models."
codecritique config set custom_instructions "We avoid global state; flag it."
```

Prefer a guided setup? Run the interactive wizard:

```bash
codecritique config wizard
```

### Style Learning (personalised suggestions)

CodeCritique can learn *your* coding habits and tailor its suggested fixes so
they read like something you'd write — instead of generic advice.

```bash
codecritique style enable        # turn it on
codecritique style learn         # analyse your code (defaults to the current dir)
codecritique style show          # see what was learned
codecritique style disable       # turn it off (keeps the profile)
```

**How it works (no fine-tuning, nothing leaves your machine):** `style learn`
statically analyses your existing Python — quote style, type-hint and docstring
coverage, f-string usage, naming case, typical function length and line width —
and saves a small JSON profile at `~/.codecritique/style_profile.json`. When
enabled, a concise summary of that profile is injected into the AI reviewer's
context (a form of in-context conditioning), so its fixes match your conventions.

Example of what gets learned and injected:

```
- Prefer double quotes for strings.
- Use snake_case for function and variable names.
- Include type hints on function parameters and return values.
- Use f-strings for string formatting.
- Keep functions around 20 lines, matching the existing style.
```

Re-run `codecritique style learn` whenever your conventions evolve.

### Git Hooks

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
Inspect or clear the cache:

```bash
codecritique cache stats   # size, entry count, semantic buckets
codecritique cache clear   # force fresh inference next run
```

### Performance tuning

CodeCritique applies several optimizations automatically and exposes knobs for
the rest:

- **Adaptive concurrency** — Ollama reviews a file's functions serially to keep
  its prefix KV-cache warm; stateless backends (Gemini/OpenAI/**vLLM**) review
  them **in parallel** instead.
- **vLLM guided decoding** — when using a vLLM endpoint, JSON responses are
  generated with `guided_json` schema constraints (faster + always parseable).
- **Bounded generation** — responses are capped (`num_predict`, default 2048)
  so the model never rambles.

Ollama runtime knobs (only sent when you set them):

```bash
CODECRITIQUE_NUM_PREDICT=1024 \  # cap generated tokens (speed)
CODECRITIQUE_NUM_CTX=8192 \      # context window
CODECRITIQUE_NUM_GPU=99 \        # layers offloaded to the GPU
CODECRITIQUE_NUM_THREAD=8 \      # CPU threads
codecritique check
```

You can also tune concurrency when a machine has limited CPU or memory:

```bash
CODECRITIQUE_CHECKER_WORKERS=2 \
CODECRITIQUE_AI_CRITIC_WORKERS=1 \
CODECRITIQUE_AI_CHUNK_WORKERS=4 \
codecritique check
```

**Fastest local setup:** for big speedups over Ollama on the same hardware, run
a [vLLM](https://docs.vllm.ai) server (continuous batching + paged KV cache) and
point CodeCritique at it:

```bash
codecritique config set provider vllm
codecritique config set base_url http://localhost:8000/v1
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

- **Coverage**: Hardcoded threshold of 80%.
- **Linter**: Uses the default Ruff configuration.
- **Incremental Mode**: Compares current branch changes against `origin/main`.
- **AI Provider/Model**: Managed via `codecritique config` (stored in `~/.codecritique/config.json`). Defaults to `gemini` / `gemini-2.0-flash`.

Environment overrides (highest precedence) are available for scripting and CI:

| Variable | Effect |
|----------|--------|
| `CODECRITIQUE_PROVIDER` | Override the active provider |
| `CODECRITIQUE_MODEL`    | Override the model |
| `CODECRITIQUE_BASE_URL` | Override the endpoint (ollama / vllm / openai-compatible) |
| `CODECRITIQUE_TEMPERATURE` | Override sampling temperature |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Provider API keys (preferred for CI) |

Future versions will support a per-project `critique.toml` for custom thresholds and rule exclusions.
