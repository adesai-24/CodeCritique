# CodeCritique

CodeCritique is an AI-assisted local code review tool. It combines static
analysis, optional local or cloud AI synthesis, saved review history, and a
pre-push CLI workflow you run **before** you push code.

It reviews **Python** and **C/C++** out of the box.

---

## Contents

1. [What it does](#1-what-it-does)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [Quick start](#4-quick-start)
5. [CLI commands](#5-cli-commands)
6. [AI providers & API keys](#6-ai-providers--api-keys)
7. [Review modes & project context](#7-review-modes--project-context)
8. [Formatting code for review](#8-formatting-code-for-review)
9. [Style learning](#9-style-learning)
10. [Saved reports & chat](#10-saved-reports--chat)
11. [Caching & performance](#11-caching--performance)
12. [Where to tweak the AI](#12-where-to-tweak-the-ai)
13. [Configuration reference](#13-configuration-reference)

---

## 1. What it does

- **Multi-language review** — Python and C/C++ (`.c`, `.cc`, `.cpp`, `.cxx`,
  `.h`, `.hpp`, …). File selection detects the language automatically.
- **Configurable language choice** — `auto` detects Python and C/C++ by
  extension, or set `python` / `cpp` under config to narrow reviews.
- **In-depth static analysis** — Ruff with a curated rule set (likely bugs,
  simplifiable code, outdated idioms, complexity), Mypy (types, including
  unannotated function bodies), Bandit (security), and a format check for
  Python; `cppcheck` (memory safety, leaks, null derefs) for C/C++. Projects
  with their own ruff config keep their settings.
- **Auto-fix** — `codecritique fix` applies ruff's safe lint fixes and
  reformats files in place; `--unsafe` opts into behavior-changing rewrites.
- **Coverage check** — reads Coverage.py data and warns below the threshold.
- **AI critic** — an LLM catches logic bugs, edge cases, and design issues the
  static tools miss.
- **AI enrichment & synthesis** — adds plain-English reasoning plus a concrete
  fix to every finding, then produces a prioritized "fix this first" report.
- **Incremental by default** — reviews only the files changed on your current
  branch; fatal findings block a push via the Git pre-push hook.
- **Pluggable AI** — Gemini (free default), Ollama (local), OpenAI, Anthropic,
  or a self-hosted vLLM endpoint. Switch with one command.
- **Saved reports + chat** — every run is saved locally; list past reports or
  chat with one to dig into findings.
- **Agent-ready output** — `check --json` emits one machine-readable JSON
  object on stdout with clean stream separation and `0`/`1` exit codes; see
  [AGENTS.md](AGENTS.md).

---

## 2. Requirements

| Need | For |
|------|-----|
| **Python 3.10 / 3.11 / 3.12** | Required — CodeCritique itself runs on Python |
| **Git** | Required — incremental checks and the pre-push hook |
| **cppcheck** | Only if you review **C/C++** |
| **An AI provider key** *(or Ollama)* | Only if you want the AI stages (free Gemini tier works) |

Reviewing C/C++ does **not** require you to write Python — CodeCritique is just
the tool; your project can be in any language it supports.

---

## 3. Installation

Installation has **two parts**: install the tool once (Part A), then do the
one-time setup for **your** language (Part B). Do A, then the B that matches you.

### Part A — install CodeCritique (everyone)

CodeCritique is a **standalone CLI**, not something you clone into your project.
Install it once with a single line and it lives in its own environment — your
project repo stays clean.

**Recommended — isolated global install with [pipx](https://pipx.pypa.io):**

```bash
pipx install "git+https://github.com/adesai-24/CodeCritique.git@v0.1.2"
```

pipx puts the `codecritique` command on your PATH in its own private
environment, so it never touches your project's dependencies.

Upgrade to a newer release tag by replacing `v0.1.2` with the release you want:

```bash
pipx uninstall codecritique
pipx install "git+https://github.com/adesai-24/CodeCritique.git@v0.1.2"
```

**Or — into an existing virtual environment with pip:**

```bash
pip install "git+https://github.com/adesai-24/CodeCritique.git@v0.1.2"
```

Either way you get two equivalent commands: `codecritique` (and the legacy
alias `critique`). Verify:

```bash
codecritique --help
```

> **Contributing?** Only then do you need a clone:
> ```bash
> git clone https://github.com/adesai-24/CodeCritique.git
> cd CodeCritique && python -m venv .venv
> source .venv/bin/activate        # Windows: .venv\Scripts\activate
> pip install -e ".[dev]"
> ```

### Part B — set up for your language

**If you write Python** — you're done. Ruff, Mypy, and Bandit ship with the
install. Skip ahead to [Quick start](#4-quick-start).

**If you write C/C++** — also install `cppcheck`, the external static analyzer
(it is not a Python package):

```bash
sudo apt-get install cppcheck      # Debian/Ubuntu
brew install cppcheck              # macOS
choco install cppcheck             # Windows
```

> If `cppcheck` is missing, CodeCritique simply skips that one checker — the AI
> critic still reviews your C/C++ and nothing crashes.

### Optional extras

Gemini support is included in the base install because Gemini is the default
hosted provider. Add extras only if you want OpenAI or Anthropic SDK support
(here with pipx; for a plain venv use
`pip install "codecritique[cloud] @ git+https://github.com/adesai-24/CodeCritique.git@v0.1.2"`):

```bash
pipx install "codecritique[cloud] @ git+https://github.com/adesai-24/CodeCritique.git@v0.1.2"  # OpenAI / Anthropic SDKs
```

From a clone you can use the shorthand `pip install -e ".[cloud]"` or
`".[dev]"`.

To use the AI stages, add a provider key next — see
[AI providers & API keys](#6-ai-providers--api-keys). Without a key (and without
Ollama running), the AI stages are skipped automatically and you still get full
static analysis.

---

## 4. Quick start

```bash
# 1. (optional) add a free Gemini key to turn on the AI stages
codecritique config set-key gemini          # prompts; input is hidden

# 2. review the files you changed on this branch
codecritique check

# 3. make CodeCritique run automatically before every push
codecritique install-hooks
```

That's it. `codecritique check` runs static analysis + AI review on your
changed files and prints a prioritized report. The pre-push hook runs the same
check and blocks the push if there are fatal findings (bypass with
`git push --no-verify` if you must).

---

## 5. CLI commands

```bash
codecritique check                       # review changed files on this branch
codecritique check src/app.py main.cpp   # review specific files
codecritique check --no-incremental      # review the whole repo
codecritique check --no-ai               # static analysis only
codecritique check --json                # machine-readable JSON output (AI agents, CI)
codecritique check --learn               # also adapt your style profile (see §9)

codecritique fix                         # apply ruff's safe lint fixes + reformat in place
codecritique fix --unsafe                # also apply behavior-changing fixes
codecritique install-hooks               # install the Git pre-push hook
codecritique format                      # reshape code for review (see §8)

codecritique config languages            # list language choices
codecritique config language cpp         # review only C/C++ files
codecritique list                        # list saved reports
codecritique chat --last                 # chat with the most recent report
codecritique chat rev_abc123             # chat with a specific report

codecritique config show                 # show current configuration
codecritique cache stats                 # AI cache size / entries
```

Findings are bucketed as `FATAL`, `WARNING`, or `INFO`. Only `FATAL` blocks a
push by default (see [Review modes](#7-review-modes--project-context) to change
that). There is no per-run `--language` option; set the default once with
`codecritique config language auto|python|cpp`.

Python linting is in-depth by default: when your project has no ruff
configuration of its own, checks use a curated rule set covering likely bugs
(`bugbear`), simplifiable code, outdated idioms, comprehension rewrites, and
complexity limits — and mypy analyzes unannotated function bodies too. If your
project does configure ruff, CodeCritique respects your settings instead.

`check --json` prints one JSON object to stdout (issues, severities, reasoning,
suggested fixes, synthesis) and routes status messages to stderr, with exit
code `0`/`1` — built for AI agents and CI. See [AGENTS.md](AGENTS.md) for the
schema and agent usage guide.

`fix` is the deterministic cleanup: ruff's safe autofixes plus `ruff format`,
applied in place to changed files. `format` (§8) is the AI counterpart that
reshapes code for review.

---

## 6. AI providers & API keys

CodeCritique's AI pipeline is **provider-agnostic**. It defaults to Google
**Gemini** (generous free tier); switch backends any time.

| Provider | Default model | Needs a key? | Notes |
|----------|---------------|--------------|-------|
| `gemini` | `gemini-2.0-flash` | yes (free) | Default. Free key: <https://aistudio.google.com/apikey> |
| `ollama` | `qwen2.5-coder:7b` | no | Fully local; needs the Ollama server (below) |
| `openai` | `gpt-4o-mini` | yes | Hosted OpenAI |
| `anthropic` | `claude-3-5-haiku-latest` | yes | Hosted Claude |
| `vllm` | `Qwen/Qwen2.5-Coder-7B-Instruct` | optional | Self-hosted, OpenAI-compatible |

Gemini support ships in the base install. OpenAI and Anthropic need the extra
SDKs — install with the `[cloud]` extra (see [Optional extras](#optional-extras)).

### Configure a provider and key

```bash
codecritique config providers          # list supported providers
codecritique config show               # show what's active
codecritique config languages          # list language choices
codecritique config language cpp       # auto, python, or cpp

codecritique config set-key gemini     # set a key (input hidden)
codecritique config set provider openai
codecritique config set-key openai sk-...

# point at a local vLLM server (no key required)
codecritique config set provider vllm
codecritique config set base_url http://localhost:8000/v1
```

### How keys are kept safe

- Stored in `~/.codecritique/secrets.env` with `0600` (owner-only) permissions —
  never in your repo. That path is git-ignored.
- Masked (`AIza…q7Yk`) whenever displayed.
- You can skip on-disk storage entirely with an env var
  (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …), which takes
  precedence over the file. This is the recommended approach for CI.

### Local AI with Ollama (no key, fully offline)

```bash
ollama serve
ollama pull qwen2.5-coder:7b
codecritique config set provider ollama
```

With Ollama running, the three AI stages — critic, enricher, synthesizer —
activate automatically. If it's offline, CodeCritique falls back to static
analysis and still saves a report.

---

## 7. Review modes & project context

A **mode** tunes the AI's tone and focus, which findings surface, and which
severities block a push — without touching the checkers.

```bash
codecritique config modes              # list modes
codecritique config mode strict        # switch mode
```

| Mode | Focus | Reports ≥ | Blocks push ≥ |
|------|-------|-----------|---------------|
| `balanced` (default) | Pragmatic; real problems only | INFO | FATAL |
| `strict` | Zero-tolerance; flags everything | INFO | **WARNING** |
| `lenient` | Real bugs only; hides nitpicks | WARNING | FATAL |
| `security` | Vulnerabilities & unsafe patterns | INFO | FATAL |
| `mentor` | Detailed, teaching tone | INFO | **NEVER** |
| `concise` | One-line findings & fixes | INFO | FATAL |

**Project context** tells the reviewer about your stack so suggestions fit (and
it becomes part of the AI cache key, so updating it produces fresh reviews):

```bash
codecritique config context "Async FastAPI service; prefer pydantic models."
codecritique config set custom_instructions "We avoid global state; flag it."
codecritique config wizard             # guided interactive setup
```

---

## 8. Formatting code for review

`codecritique format` reshapes code into a clean, consistent layout —
consistent spacing, column-aligned declarations, and a documenting comment
above every function — **without changing behavior**. Works for Python and
C/C++.

```bash
codecritique format                 # preview a diff for changed files
codecritique format src/main.cpp    # format a specific file
codecritique format --in-place      # apply changes (originals saved as *.bak)
codecritique format --in-place --no-backup
codecritique format --no-incremental
```

It previews a unified diff and applies nothing by default. This step is
intentionally **format-only** — it never fixes bugs, renames things, or alters
logic.

For deterministic, tool-based cleanup of Python (no AI involved), use
`codecritique fix` instead: it applies ruff's safe lint fixes and `ruff format`
directly to disk (see [CLI commands](#5-cli-commands)). A good workflow is
`fix` for the mechanical issues, then `format` if you want the AI's
review-ready restyling on top.

---

## 9. Style learning

CodeCritique can learn *your* coding habits and tailor suggested fixes so they
read like something you'd write.

```bash
codecritique style enable        # turn it on
codecritique style learn         # analyze your code (defaults to current dir)
codecritique style show          # see what was learned (and adaptive state)
codecritique style disable       # turn it off (keeps the profile)
```

**How it works (no fine-tuning, nothing leaves your machine):** `style learn`
statically analyzes your existing Python — quote style, type-hint/docstring
coverage, f-string usage, naming case, typical function length and line width —
and saves a small JSON profile at `~/.codecritique/style_profile.json`. When
enabled, a concise summary is injected into the reviewer's context so its fixes
match your conventions. Re-run `style learn` whenever your conventions evolve.

### Learn as you review (adaptive, optional)

Instead of re-running `style learn` by hand, let the profile keep adapting on
its own — every `codecritique check` learns a little from the files it just
reviewed:

```bash
codecritique style auto on       # learn a little from every check (persistent)
codecritique style auto off      # stop
codecritique check --learn       # learn just for this one run
codecritique check --no-learn    # skip learning for this one run
```

**Won't it overtrain?** No — that's the whole point of making it optional and
gradual. It's **off by default**, and when on, each run only *nudges* the
profile using an exponential moving average (learning rate ≈ 0.15). A single
odd diff can't flip your established conventions; the profile drifts slowly
toward your real, current habits over many reviews. Counters accumulate so
`style show` reflects everything seen over time. (Learning analyzes Python; C/C++
files in a run are skipped for the profile.)

---

## 10. Saved reports & chat

Every CLI run saves a compact JSON report under `~/.codecritique/reports` (only
the 50 most recent are kept).

```bash
codecritique list                # list saved reports
codecritique chat --last         # chat with the most recent
codecritique chat rev_abc123     # chat with a specific report
```

Report chat uses local Ollama streaming and answers from the saved findings —
file paths, line numbers, reasoning, and suggested fixes.

---

## 11. Caching & performance

CodeCritique caches AI responses under `~/.codecritique/cache` (in-memory +
`llm_cache.json` on disk + a semantic index for near-duplicate prompts, with
AST-derived keys so comment/whitespace-only edits reuse prior results).

```bash
codecritique cache stats         # size, entry count, semantic buckets
codecritique cache clear         # force fresh inference next run
CODECRITIQUE_AI_CACHE=0 codecritique check   # disable caching for one run
```

**Tuning knobs** (only applied when set):

```bash
# concurrency on smaller machines
CODECRITIQUE_CHECKER_WORKERS=2 \
CODECRITIQUE_AI_CRITIC_WORKERS=1 \
CODECRITIQUE_AI_CHUNK_WORKERS=4 \
codecritique check

# Ollama runtime
CODECRITIQUE_NUM_PREDICT=1024 \  # cap generated tokens (speed)
CODECRITIQUE_NUM_CTX=8192 \      # context window
CODECRITIQUE_NUM_GPU=99 \        # GPU-offloaded layers
CODECRITIQUE_KEEP_ALIVE=30m \    # keep the model loaded (-1 = forever)
codecritique check
```

**Fastest local setup:** for big speedups over Ollama on the same hardware, run
a [vLLM](https://docs.vllm.ai) server (continuous batching + paged KV cache,
plus guided JSON decoding) and point CodeCritique at it:

```bash
codecritique config set provider vllm
codecritique config set base_url http://localhost:8000/v1
```

---

## 12. Where to tweak the AI

Everything that shapes the reviewer lives in **one place: `~/.codecritique/`**
(your home directory). There is no separate "skill file" system — you steer the
AI through config values and the prompt templates below. Relocate the whole
directory by setting `CODECRITIQUE_HOME=/some/path`.

| Path | What it controls | How to edit |
|------|------------------|-------------|
| `~/.codecritique/config.json` | Provider, model, review **mode**, **project context**, **custom instructions**, style/adaptive toggles | `codecritique config ...` (preferred) or edit the JSON |
| `~/.codecritique/style_profile.json` | Your learned coding style injected into reviews | `codecritique style learn` / `style auto` (or edit the JSON) |
| `~/.codecritique/secrets.env` | API keys (`0600`, git-ignored) | `codecritique config set-key <provider>` |
| `~/.codecritique/reports/` | Saved review reports (JSON) | `codecritique list` / `chat` |
| `~/.codecritique/cache/` | AI response cache | `codecritique cache stats` / `clear` |

**The two knobs you'll use most** — natural-language context the AI sees on
every review:

```bash
codecritique config context "Async FastAPI service; prefer pydantic models."
codecritique config set custom_instructions "We avoid global state; flag it."
codecritique config show          # see everything that's currently set
```

**Prompt templates (advanced).** The actual system prompts for each AI stage —
critic, enricher, formatter, synthesizer — live in the installed package at
`critique/ai/prompts.py` (`CRITIC_SYSTEM`, `ENRICHER_SYSTEM`,
`BATCH_ENRICHER_SYSTEM`, `FORMATTER_SYSTEM`, `SYNTHESIZER_SYSTEM`). Find the file
on your machine with:

```bash
python -c "import critique.ai.prompts as p; print(p.__file__)"
```

Editing those changes the AI's base behavior for everyone using that install —
prefer `config context` / `custom_instructions` for project-specific tweaks, and
reserve prompt edits for a contributor clone.

---

## 13. Configuration reference

**Defaults:**

- Coverage threshold: 80%
- Incremental base: `origin/main`
- Lint rules: curated ruff set `E,W,F,B,C4,SIM,UP,C90,RUF` when the project has
  no ruff config of its own (`ruff.toml`, `.ruff.toml`, or `[tool.ruff]` in
  `pyproject.toml`); otherwise the project's configuration is respected
- Default provider/model: `gemini` / `gemini-2.0-flash`
- Language choice: `auto` (review all supported Python and C/C++ files)
- Local model: `qwen2.5-coder:7b`; Ollama URL: `http://localhost:11434`
- AI cache: enabled
- Saved report limit: 50
- Style learning / adaptive ("learn as you review"): both off

Configuration lives in `~/.codecritique/config.json` (managed via
`codecritique config`). Environment overrides take highest precedence — handy
for CI:

| Variable | Effect |
|----------|--------|
| `CODECRITIQUE_PROVIDER` | Override the active provider |
| `CODECRITIQUE_MODEL` | Override the model |
| `CODECRITIQUE_BASE_URL` | Override the endpoint (ollama / vllm / openai-compatible) |
| `CODECRITIQUE_LANGUAGE` | Override language choice (`auto`, `python`, `cpp`) |
| `CODECRITIQUE_TEMPERATURE` | Override sampling temperature |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Provider API keys (preferred for CI) |

CodeCritique does not yet read a per-project config file. A future version may
add `critique.toml` for thresholds, rule exclusions, and model settings.
</content>
</invoke>
