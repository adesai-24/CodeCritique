# CodeCritique

CodeCritique is a local development tool designed to evaluate your code before you push it to a GitHub repository. It acts as a final check to ensure code quality by integrating static analysis tools and a local AI reviewer into a single, unified feedback loop.

## Features

- **Integrated Linting**: Uses `Ruff` for style and error checking.
- **Type Checking**: Uses `Mypy` for static type analysis.
- **Security Auditing**: Uses `Bandit` to find common security vulnerabilities.
- **Coverage Reports**: Checks test coverage using `Coverage.py`.
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

### Ollama (optional — only for the local `ollama` provider)

The local AI path requires [Ollama](https://ollama.com) running with the `qwen2.5-coder:7b` model pulled.

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
   git clone https://github.com/yourusername/CodeCritique.git
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

### Git Hooks

To automate this tool, install it as a Git `pre-push` hook. This prevents pushing if any fatal issues are found.

```bash
codecritique install-hooks
```

## Git Hooks Explained

The `install-hooks` command creates a script in `.git/hooks/pre-push`.

Each time you run `git push`, your computer automatically runs `critique check --incremental` first. If the tool finds critical issues (like a syntax error or security hole), it returns a failure code to Git, which cancels your push. This ensures that only high-quality, verified code reaches your remote repository.

When Ollama is running, the pre-push hook also runs the full AI pipeline. If Ollama is offline, the hook falls back to static-analysis-only mode without any extra configuration.

## AI Caching

AI reviews are slower than static checks because the model has to read the prompt, process code context, generate structured JSON, and return it over the local Ollama API. CodeCritique caches deterministic AI responses under `~/.codecritique/cache/llm_cache.json`, keyed by the model, prompt, schema, and generation options.

That means the first AI review of a file or finding can still take a while, but repeated checks of unchanged code can reuse the cached critic, enrichment, and synthesis output instead of calling the model again. If the code, prompt, model, or schema changes, CodeCritique automatically misses the cache and asks the model for a fresh result.

To force fresh AI responses for a run, disable the cache:

```bash
CODECRITIQUE_AI_CACHE=0 codecritique check
```

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

## Configuration

Currently, the tool uses default configurations for the underlying tools:

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
