# Changelog

All notable changes to CodeCritique will be documented in this file.

## 0.2.2 - 2026-06-10

- **Multi-language style learning**: `style learn` now respects the configured
  language setting instead of being hardcoded to Python. C++ projects get
  comment-density and naming-convention analysis; `auto` mode handles mixed
  repos file-by-file.
- **Model management**: `critique config models [provider]` prints a table of
  known models for the active or specified provider, marking the current
  selection. `critique config model <name>` is a dedicated shorthand for
  switching models; `config model none` resets to the provider default.
- **Live model discovery**: `critique config models --fetch` queries the
  provider's API (Gemini, Anthropic, OpenAI/vLLM, Ollama) for its full,
  up-to-date model list. Falls back to the built-in curated list on failure.
- **Project path setup**: new `project_path` config field lets the tool
  remember which directory to review. `check` and `fix` automatically `cd`
  there when no explicit file list is given.
- **Top-level `setup` command**: replaces `config wizard`; auto-adopts the
  current directory as `project_path` and prompts for provider, API key,
  model, and mode in one step.

## 0.2.1 - 2026-06-10

- `codecritique do` can now change settings: a `set_config` action lets plain
  English like "switch to strict mode and only review python files" update
  `provider`, `model`, `language`, `suggestion_mode`, `temperature`,
  `style_learning`, and friends — validated against the known settings and
  their allowed values, and still behind the plan-confirmation prompt.
- API keys are explicitly refused by the assistant; `codecritique config
  set-key <provider>` (hidden input) remains the only way to set them.
- Remove shell tab-completion (the `--install-completion` /
  `--show-completion` options and their documentation); the natural-language
  assistant is the supported discovery path.

## 0.2.0 - 2026-06-09

- Add a natural-language assistant backed by the configured AI provider:
  - `codecritique ask "<question>"` answers capability questions, grounded in
    a manifest generated from the real CLI so it cannot invent commands.
  - `codecritique do "<instruction>"` translates plain English into a plan of
    whitelisted actions (check, fix, format, list_reports, install_hooks),
    shows the plan, and runs it only after confirmation (`--yes` to skip).
- Run ruff, mypy, bandit, and coverage via `python -m` so checks cannot
  silently lose findings when a virtualenv's console-script launchers break
  (e.g. after the venv directory is moved).
- Add `codecritique fix`: applies ruff's safe lint fixes and reformats files
  in place (`--unsafe` opts into behavior-changing fixes).
- Deepen static analysis: curated ruff rule set (bugbear, simplify,
  comprehensions, pyupgrade, complexity) when the project has no ruff config
  of its own; mypy now checks unannotated function bodies.
- Add a Format checker that flags files `ruff format` would rewrite (INFO).
- Make the AI review context-aware and personable: the synthesizer now knows
  the project, branch, and review mode, and addresses the developer directly.
- Add `codecritique check --json` for machine-readable output (AI agents, CI);
  status messages now go to stderr so stdout stays clean.
- Add `AGENTS.md` with the JSON schema and agent usage guide.
- Remove the legacy embedded HTML report generator.

## 0.1.2 - 2026-06-09

- Include `google-genai` in the base install because Gemini is the default
  hosted provider. Users no longer need the `[cloud]` extra for the default AI
  path.
- Update Gemini provider guidance and documentation so the `[cloud]` extra is
  only needed for OpenAI / Anthropic SDK support.

## 0.1.1 - 2026-06-09

- Add configurable language selection under `codecritique config`:
  `auto`, `python`, or `cpp`. The setting controls incremental checks,
  full-repository scans, and explicit file lists without adding a per-run
  `--language` flag.
- Add `CODECRITIQUE_LANGUAGE` for one-off environment overrides.
- Clarify release/tag-based `pipx` upgrade guidance in the documentation.

## 0.1.0 - 2026-06-09

- **Adaptive style learning ("learn as you review")**: opt-in mode where every
  `codecritique check` nudges your saved style profile toward the files it just
  reviewed, so suggestions keep matching your evolving habits. Off by default;
  enable per-run with `check --learn` or persistently with `codecritique style
  auto on`. Updates are EMA-blended (learning rate ≈ 0.15) so a single diff
  can't overtrain or flip established conventions.
- **Removed the web demo**: CodeCritique is now CLI-only. The FastAPI + Monaco
  browser UI (and its `[web]` optional dependencies) has been dropped to keep
  the tool focused on the local, pre-push review workflow.
- **Single-line install**: CodeCritique installs as a standalone CLI with
  `pipx install git+https://github.com/adesai-24/CodeCritique.git` (or `pip
  install git+...`) instead of cloning the repo into your project. The tool
  lives in its own environment, keeping your project repo clean. Added
  `.gitignore` entries so an accidental vendored clone stays invisible; cloning
  is now only needed for contributing.
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
- Add GitHub Actions coverage for Python 3.10, 3.11, and 3.12.
- Add repository contribution templates for issues and pull requests.
- Add MIT licensing.
