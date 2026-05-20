# CodeCritique — Project Board

## Status Overview

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | AI Bootstrap — LLM client module | ✅ Done |
| Phase 2 | AI Critic Checker — semantic code review | ✅ Done |
| Phase 3 | AI Enricher — reasoning + suggested fixes | ✅ Done |
| Phase 4 | AI Synthesizer + curated report renderer | ✅ Done |
| Phase 5 | Config file (`critique.toml`) support | Planned |
| Phase 6 | Web dashboard integration | Planned |

---

## Phase 1 — AI Bootstrap

Set up the infrastructure for talking to a local LLM via Ollama.

- [x] Add `requests` to `pyproject.toml` dependencies
- [x] Create `src/critique/ai/__init__.py`
- [x] Create `src/critique/ai/client.py` — `LLMClient` wrapping Ollama HTTP API
  - [x] `is_available()` — health check via `GET /api/tags`
  - [x] `complete()` — plain-text chat completion
  - [x] `complete_json()` — structured JSON completion with `format: "json"`
- [x] Create `src/critique/ai/prompts.py` — system prompts for all pipeline stages
- [x] Create `src/critique/ai/schemas.py` — expected JSON shapes for each stage

Branch: `feature/ai-integration`

---

## Phase 2 — AI Critic Checker

Add a new checker that reviews entire files semantically using the LLM.

- [x] Create `src/critique/checkers/ai_critic.py` — `AICriticChecker(BaseChecker)`
  - [x] Skip non-`.py` files and files over 30 000 chars
  - [x] Per-file try/except — one bad file never kills the run
  - [x] Map LLM findings to `Issue(code="AI")` objects
- [x] Wire `AICriticChecker` into `runner.py` (appended when Ollama is reachable)
- [x] Graceful degradation — console warning if Ollama is offline, static-only mode continues

Branch: `feature/ai-integration`

---

## Phase 3 — AI Enricher

Annotate every issue (from any checker) with richer context from the LLM.

- [x] Add `suggested_fix: Optional[str]` field to `Issue` NamedTuple in `base.py`
- [x] Create `src/critique/ai/enricher.py`
  - [x] `AIEnricher.enrich()` — adds `reasoning`, `suggested_fix`, and re-scored `severity`
  - [x] `enrich_issues()` — `ThreadPoolExecutor(4)` for concurrent enrichment
  - [x] Preserves original issue order; fail-open (exceptions return original issue)
  - [x] Rich progress bar during enrichment

Branch: `feature/ai-integration`

---

## Phase 4 — AI Synthesizer + Report Renderer

Replace the raw issue list with a curated, prioritized AI report.

- [x] Create `src/critique/ai/synthesizer.py` — `AISynthesizer`
  - [x] Returns `_CLEAN_RESULT` immediately for zero-issue runs
  - [x] Formats numbered findings list for the LLM
  - [x] Mechanical fallback (bucket by severity) if LLM call fails
- [x] Add `print_ai_report(synth, issues) -> bool` to `src/critique/report.py`
  - [x] Summary panel (cyan border)
  - [x] Fix First priority callout (yellow border)
  - [x] Critical / Warnings / Suggestions sections with reasoning + suggested fix
  - [x] What's Good section (green border)
  - [x] Returns `False` (blocks push) when any critical issue is fatal
- [x] Update `runner.py` — call enricher → synthesizer → `print_ai_report`; fallback to `print_report` on failure
- [x] Add `--no-ai` flag to `src/critique/cli.py`
- [x] Add validation fixture `tests/fixtures/buggy_logic.py` with 3 deliberate bugs
- [x] Update `README.md` with Ollama setup, AI features, `--no-ai` flag, sample output

Branch: `feature/ai-integration`

---

## Phase 5 — Config File Support (Planned)

- [ ] Design `critique.toml` schema (coverage threshold, rule exclusions, model selection)
- [ ] Parse config at startup and pass values to each checker
- [ ] Document config options in README

---

## Phase 6 — Web Dashboard (Planned)

- [ ] Surface AI report output in the React web dashboard
- [ ] Store per-run history (JSON) for trend views
- [ ] Add sparkline charts for coverage and issue counts over time
