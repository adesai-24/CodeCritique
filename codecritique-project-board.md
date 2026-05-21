# CodeCritique — Project Board

> Universal checklist for taking CodeCritique from current state → shipped AI-first product.
> Check off tasks as they're done. Phases are roughly sequential but can overlap.

---

## Status at a Glance

| Phase | Status | Description |
|---|---|---|
| 0 | ✅ Done | Core CLI + static analysis foundation |
| 1 | ⏳ Not Started | AI bootstrap (local LLM client) |
| 2 | ⏳ Not Started | AI Critic — semantic review checker |
| 3 | ⏳ Not Started | AI Enricher — upgrade existing findings |
| 4 | ⏳ Not Started | AI Synthesizer + new report renderer |
| 5 | ⏳ Not Started | Chat mode + report persistence |
| 6 | ⏳ Not Started | Config system + cloud provider fallback |
| 7 | ⏳ Not Started | Test suite |
| 8 | ⏳ Not Started | CI/CD + packaging |
| 9 | ⏳ Not Started | Web demo / hosted version |
| 10 | ⏳ Not Started | Docs, polish, recruiter showcase |

Legend: ✅ Done · 🚧 In Progress · ⏳ Not Started

---

## Phase 0 — Foundation ✅

> Core CLI + static analysis. This is what's already built.

**Goal:** A working CLI that runs static analyzers on changed files and reports findings.

### Project setup
- [x] Python package structure (`critique/`)
- [x] Typer-based CLI entry point (`cli.py`)
- [x] `pyproject.toml` / installable package
- [x] Pre-push hook installer (`install_pre_push_hook`)

### Core types & abstractions
- [x] `BaseChecker` abstract class
- [x] `Issue` NamedTuple (file, line, column, message, code, severity, reasoning, code_context)
- [x] `Severity` enum (FATAL / WARNING / INFO)

### Static analysis checkers
- [x] `RuffChecker` — lint
- [x] `BanditChecker` — security
- [x] `MypyChecker` — types
- [x] `CoverageChecker` — test coverage

### Runner
- [x] `scan_files()` orchestrating all checkers
- [x] `extract_code_context()` for surrounding code snippets
- [x] `run_all_checks()` end-to-end flow
- [x] Rich progress indicators

### Git integration
- [x] `get_changed_files()` via `git diff --name-only`
- [x] Incremental mode (changed files only)
- [x] Custom file targeting via CLI args
- [x] Pre-push hook generation + installation

### Reporting (v1)
- [x] Basic `print_report()` (assumed present, not in uploaded files)
- [x] Exit code 0/1 based on severity

**Definition of done:** ✅ `critique check` runs on a repo, finds issues from 4 tools, prints them, exits with proper code.

---

## Phase 1 — AI Bootstrap ⏳

> Get a local LLM responding to your code. ~1 hour.

**Goal:** Smoke test that an LLM call works from inside the codebase.

### Local model setup
- [ ] Install Ollama (`brew install ollama` or download)
- [ ] Run `ollama serve` (or set up as background daemon)
- [ ] Pick a model based on RAM and pull it
  - [ ] `qwen2.5-coder:7b` (16GB+ RAM, recommended default)
  - [ ] `qwen2.5-coder:14b` (32GB+ RAM, better quality)
  - [ ] OR `deepseek-coder-v2:16b` (alternative)
- [ ] Verify with CLI: `ollama run <model> "say hi"` returns a response

### LLM client module
- [ ] Create `critique/ai/__init__.py`
- [ ] Create `critique/ai/client.py` with `LLMClient` class
- [ ] Implement `complete(system, user, temperature)` method
- [ ] Implement `complete_json(system, user, schema)` method using Ollama's `format` param
- [ ] Add timeout handling (120s default)
- [ ] Add health check method (`is_available()` → `GET /api/tags`)

### Smoke test
- [ ] REPL test: instantiate `LLMClient`, run `complete()` with a basic prompt
- [ ] REPL test: `complete_json()` returns valid parsed dict
- [ ] Test failure case: Ollama not running → clear error, not a crash

**Definition of done:** From a Python REPL inside the project, `LLMClient().complete(system=..., user=...)` returns a coherent string.

---

## Phase 2 — AI Critic Checker ⏳

> A new `BaseChecker` that uses the LLM for semantic review.

**Goal:** Drop AI into the existing checker pipeline as a peer of Ruff/Bandit/Mypy.

### Prompts & schemas
- [ ] Create `critique/ai/prompts.py`
- [ ] Write `CRITIC_SYSTEM` prompt (with "don't invent issues" guard)
- [ ] Create `critique/ai/schemas.py`
- [ ] Define `CRITIC_SCHEMA` JSON schema (findings array with line/title/explanation/severity)

### Checker implementation
- [ ] Create `critique/checkers/ai_critic.py`
- [ ] `AICriticChecker(BaseChecker)` class
- [ ] Iterates files, reads content, calls `LLMClient.complete_json()`
- [ ] Maps each finding to an `Issue` with `code="AI"`
- [ ] Skips files >30k chars (token budget)
- [ ] Try/except around each file — one bad file doesn't kill the whole run

### Wire into runner
- [ ] Import `AICriticChecker` and `LLMClient` in `runner.py`
- [ ] Instantiate `LLMClient` once at the top of `scan_files()`
- [ ] Add `AICriticChecker(llm)` to the checkers list
- [ ] Progress label shows AI activity ("Running AI Critic...")

### Validation
- [ ] Create a test file with a deliberate logic bug (off-by-one, wrong comparison) that linters won't catch
- [ ] Run `critique check --no-incremental` on it
- [ ] Verify AI Critic flags it
- [ ] Run on clean code — verify AI doesn't invent issues (empty findings)
- [ ] Time the run — note baseline latency

**Definition of done:** AI Critic catches at least one logic bug that Ruff/Bandit/Mypy miss, on a real test file.

---

## Phase 3 — AI Enricher ⏳

> Upgrade existing linter findings with code-specific reasoning + suggested fixes.

**Goal:** Replace generic "Type mismatch found." reasoning with specific, helpful explanations.

### Schema & prompt
- [ ] `ENRICHER_SYSTEM` prompt in `critique/ai/prompts.py`
- [ ] `ENRICHMENT_SCHEMA` in `critique/ai/schemas.py` (reasoning, suggested_fix, real_severity)

### Model extension
- [ ] Add `suggested_fix: Optional[str] = None` field to `Issue` in `base.py`
- [ ] Confirm NamedTuple backward compat (no existing code breaks)

### Enricher implementation
- [ ] Create `critique/ai/enricher.py`
- [ ] `AIEnricher` class with `enrich(issue) -> Issue`
- [ ] Format prompt with tool, file, line, message, code context
- [ ] Parse response, return `issue._replace(reasoning=..., suggested_fix=...)`
- [ ] Fail-open: any exception returns the original issue unchanged

### Concurrency
- [ ] Wrap enrichment in `ThreadPoolExecutor(max_workers=4)`
- [ ] `enrich_issues(issues, llm) -> List[Issue]` helper in `runner.py`
- [ ] Handle Ctrl-C gracefully (cancel pending futures)
- [ ] Rich progress shows N/M enrichments complete

### Wire into runner
- [ ] Call `enrich_issues()` after `scan_files()`, before report
- [ ] Guard behind the `--ai` flag (default on)

**Definition of done:** Every linter finding shows a code-specific reasoning sentence and a concrete suggested fix, not the hardcoded generic string.

---

## Phase 4 — Synthesizer + New Report ⏳

> The user-facing brain. Turns a flat list of findings into a curated review.

**Goal:** Output looks like a senior engineer wrote it, not like a lint dump.

### Schema & prompt
- [ ] `SYNTHESIZER_SYSTEM` prompt in `prompts.py`
- [ ] `SYNTH_SCHEMA` in `schemas.py` (summary, fix_first, critical[], warnings[], suggestions[], whats_good[])

### Synthesizer implementation
- [ ] Create `critique/ai/synthesizer.py`
- [ ] `AISynthesizer.synthesize(issues) -> dict`
- [ ] Format issues as numbered list for the prompt
- [ ] Handle empty issues case (return clean "no issues" structure)

### Report renderer
- [ ] Add `print_ai_report(synth_output, issues)` to `report.py`
- [ ] Top: summary panel (Rich `Panel`)
- [ ] Fix First callout (yellow/red bordered panel) — pulls from `fix_first` index
- [ ] Critical section — red header, each issue with file:line, reasoning, suggested_fix as `Syntax` block
- [ ] Warnings section — yellow header
- [ ] Suggestions section — blue header
- [ ] What's Good section — green panel at the bottom
- [ ] Exit code logic: FATAL/critical → 1, otherwise 0

### Runner integration
- [ ] Update `run_all_checks()` to call synthesizer + new report when `ai=True`
- [ ] Keep old `print_report()` accessible via `--no-ai` flag

### Visual QA
- [ ] Screenshot the report on a repo with all 3 severity types
- [ ] Screenshot the report on clean code (should still feel encouraging, not empty)
- [ ] Compare side-by-side with the old raw output

**Definition of done:** Running `critique check` on a real repo produces a curated, prioritized, kind-toned review with a Fix First callout — not a flat dump.

---

## Phase 5 — Chat Mode + Persistence ⏳

> Follow-up Q&A on the last review.

**Goal:** After a review, run `critique chat --last` and ask questions about findings.

### Persistence
- [ ] Create `~/.codecritique/reports/` directory on first run
- [ ] After each run, save `{timestamp}.json` with synth output + raw issues
- [ ] Limit to last 50 reports (auto-delete oldest)
- [ ] Add `critique list` subcommand to show recent reports
- [ ] Each report gets a short ID (e.g. `rev_abc123`)

### Chat subcommand
- [ ] Add `chat` command to `cli.py`
- [ ] `critique chat <id>` loads that report
- [ ] `critique chat --last` loads most recent
- [ ] In-terminal REPL loop using `prompt_toolkit` or simple `input()`
- [ ] `exit`/`quit`/Ctrl-D ends the session

### LLM streaming
- [ ] Add `complete_stream(system, user, messages)` to `LLMClient` (yields chunks)
- [ ] Use Ollama's streaming endpoint (`stream=True`)
- [ ] Rich renders chunks as they arrive

### Chat context
- [ ] System prompt: "You just reviewed this code. Answer follow-ups."
- [ ] Pass full synth output + raw issues + conversation history each turn
- [ ] Cap conversation history at last 10 exchanges (token budget)

**Definition of done:** Run a review, then run `critique chat --last`, ask "expand on finding 3" and get a streamed coherent response that references the actual code.

---

## Phase 6 — Config + Cloud Fallback ⏳

> Make the tool configurable. Support cloud LLMs as a backup.

**Goal:** Real users (and recruiters) can tweak behavior without editing source.

### Config file
- [ ] Define `~/.codecritique/config.toml` schema
  - [ ] `provider` (ollama / anthropic / openai)
  - [ ] `model` (per provider)
  - [ ] `ollama.base_url`
  - [ ] `severity_overrides` (map code → severity)
  - [ ] `skip_checkers` (list)
  - [ ] `max_file_chars`
- [ ] Load with `tomllib` (Python 3.11+) at startup
- [ ] Sensible defaults if file doesn't exist
- [ ] `critique init-config` writes a starter file

### Provider abstraction
- [ ] Define `LLMProvider` protocol/ABC
- [ ] `OllamaProvider` (current `LLMClient`)
- [ ] `AnthropicProvider` (uses `anthropic` SDK + `ANTHROPIC_API_KEY`)
- [ ] `OpenAIProvider` (uses `openai` SDK + `OPENAI_API_KEY`)
- [ ] Factory: `get_llm_client(config) -> LLMProvider`
- [ ] All providers support `complete_json()` + `complete_stream()`

### Per-checker enable/disable
- [ ] CLI flags: `--skip ruff --skip ai-critic` etc.
- [ ] Config equivalent
- [ ] `critique check --ai-only` runs only AI Critic, skips static tools

### Cost / rate guard (for cloud providers)
- [ ] Token counting before send (use `tiktoken` for OpenAI, anthropic SDK helper)
- [ ] Reject if estimated cost > $0.50/run with a clear error
- [ ] Display cost estimate per run when using cloud provider

**Definition of done:** Switch from local to cloud with one env var or config change. Cost is visible when using cloud.

---

## Phase 7 — Tests ⏳

> Make this robust enough that you'd actually use it in CI.

**Goal:** Confidence to refactor + something to show recruiters.

### Unit tests
- [ ] `tests/test_checkers.py` — each checker on a fixture file
- [ ] `tests/test_git_utils.py` — mock `git diff` output
- [ ] `tests/test_ai_client.py` — mock Ollama HTTP responses
- [ ] `tests/test_enricher.py` — mock LLM, verify fail-open behavior
- [ ] `tests/test_synthesizer.py` — verify schema-conforming output handling
- [ ] `tests/test_runner.py` — end-to-end with `--no-ai` (no LLM dependency)

### Integration tests
- [ ] `tests/integration/test_full_run.py` — runs real Ollama if available, skips if not
- [ ] Fixture repos with known-bad code (logic bugs, security holes, type errors)
- [ ] Assertions on which findings AI Critic catches

### Coverage
- [ ] `pytest --cov=critique --cov-report=html`
- [ ] Aim for >80% on core modules (runner, checkers, ai/*)
- [ ] Note: don't game the metric — focus tests on logic-heavy paths

### Fixtures
- [ ] `tests/fixtures/clean_code.py` — should produce zero findings
- [ ] `tests/fixtures/buggy_logic.py` — off-by-one, wrong operators
- [ ] `tests/fixtures/security_holes.py` — SQL injection, hardcoded secrets
- [ ] `tests/fixtures/type_errors.py` — Mypy bait

**Definition of done:** `pytest` runs clean, coverage report exists, AI tests can be skipped when Ollama isn't running.

---

## Phase 8 — CI/CD + Packaging ⏳

> Make installation one command. Run tests on every push.

**Goal:** `pip install codecritique` works, and PRs run tests automatically.

### Packaging
- [ ] Finalize `pyproject.toml` (name, version, deps, entry points, console_scripts)
- [ ] Entry point: `codecritique = critique.cli:app`
- [ ] Pin minimum versions of `ruff`, `bandit`, `mypy`, `coverage`
- [ ] Add `requests`, `rich`, `typer`, `pydantic` (or whatever else is used)
- [ ] Optional deps: `anthropic`, `openai` as extras (`pip install codecritique[cloud]`)
- [ ] Test install in a fresh venv: `pip install -e .` then `codecritique check`

### GitHub repo hygiene
- [ ] `.gitignore` (Python defaults + `~/.codecritique/` if accidentally local)
- [ ] `LICENSE` (MIT recommended)
- [ ] `CHANGELOG.md`
- [ ] Issue templates (`bug_report.md`, `feature_request.md`)
- [ ] PR template

### GitHub Actions
- [ ] `.github/workflows/test.yml` — pytest on push/PR
- [ ] Run lint on own codebase as a self-test: `codecritique check --no-ai`
- [ ] Matrix: Python 3.10, 3.11, 3.12
- [ ] Cache dependencies for speed

### Release
- [ ] Tag v0.1.0
- [ ] Publish to PyPI (or TestPyPI first)
- [ ] GitHub Release with notes

**Definition of done:** Fresh machine + `pip install codecritique` → works immediately. PRs show green CI.

---

## Phase 9 — Web Demo / Hosted Version ⏳

> Optional but high-leverage for the recruiter pitch.

**Goal:** A URL the recruiter can click without installing anything.

### Backend
- [ ] FastAPI wrapper around `critique` functions
- [ ] `POST /api/review` — accept code (paste) or GitHub URL
- [ ] Streams synth output as SSE
- [ ] Uses cloud provider (Anthropic) for hosted version — local Ollama isn't reachable from the cloud
- [ ] Rate limiting (`slowapi`, 10 reviews/hour/IP)

### Frontend
- [ ] Single-page React + Vite app
- [ ] Code editor (Monaco) for paste mode
- [ ] GitHub URL input for repo/PR mode
- [ ] Live-streaming report display (mirrors CLI Rich layout)
- [ ] Apply-fix buttons that show the diff
- [ ] Dark mode

### Deployment
- [ ] Backend: Fly.io or Railway
- [ ] Frontend: Vercel (or serve static from backend)
- [ ] Custom domain (optional, ~$12/yr)
- [ ] Environment secrets: `ANTHROPIC_API_KEY` on the host
- [ ] Hard daily spend cap on cloud calls

### Demo readiness
- [ ] Land-page tagline + description
- [ ] Sample code prefilled so click-to-demo works in 5 seconds
- [ ] Link back to GitHub repo

**Definition of done:** Public URL that runs a full review on pasted code in <30 seconds.

### Phase 9 — Format Exploration

A web app isn't the only way to ship this. Quick honest take on each option:

| Format | Effort | Recruiter impact | Verdict |
|---|---|---|---|
| **Web app** (current plan) | 1–2 days | High — clickable URL | ✅ Best primary |
| **VS Code extension** | 2–3 days | High — devs live here | ✅ Strong second |
| **Desktop GUI** (Tauri) | 2–3 days | Medium — looks polished | 🤷 Optional |
| **Menu bar app** | 1 day | Low — too niche | ⏭️ Skip |
| **Mobile app** | 1+ week | Low — wrong use case | ❌ Don't |

**Web app** stays the primary recommendation because the recruiter can click one link. Zero friction.

**VS Code extension** is the most natural "app" form for a code review tool. Devs already live in the editor, and showing findings inline (squiggles, hover tooltips, code actions) is how real review tools work. If you have appetite for a second format, this is it — and you can reuse 90% of your existing CLI code by spawning it as a subprocess.

**Desktop GUI via Tauri** would wrap the CLI in a native-feeling app with a real UI. Looks impressive, but it's mostly cosmetic since the CLI already does the work. Skip unless you want the visual polish.

**Mobile app** doesn't make sense — nobody's running pre-push hooks from their phone. Don't waste cycles here.

### Recommended sequence

1. Ship the web app first (Phase 9 main plan)
2. If you have time after the recruiter pitch lands, build the VS Code extension as a follow-up — it's the strongest "I went further" signal
3. Mention both in the README and recruiter pitch as a roadmap, even if only #1 is built

---

## Phase 10 — Docs, Polish, Showcase ⏳

> The last 10% that makes everything before it matter.

**Goal:** Anyone landing on the repo immediately gets what this is and wants to try it.

### README
- [ ] Hero section: tagline + one screenshot of the AI report
- [ ] 30-second elevator pitch paragraph
- [ ] Install instructions (`pip install codecritique` + `ollama pull qwen2.5-coder:7b`)
- [ ] Quick start: 3 commands to first review
- [ ] Architecture diagram (the ASCII one from the guide is fine)
- [ ] "Why local LLM" section — the privacy/cost/offline pitch
- [ ] Feature list with checkmarks
- [ ] Configuration table
- [ ] Contributing section
- [ ] License

### Demo media
- [ ] 60-second screen recording or asciinema of `critique check` end-to-end
- [ ] Follow-up showing `critique chat --last`
- [ ] Host on the README (asciinema embed or video link)

### Code docs
- [ ] Docstrings on public functions (`run_all_checks`, `LLMClient.*`, `AIEnricher.enrich`, etc.)
- [ ] `ARCHITECTURE.md` — the full design doc (lift from this project's guide)
- [ ] `DECISIONS.md` — log of major technical decisions with rationale

### Recruiter package
- [ ] Pinned tweet / LinkedIn post with 30-second video + repo link
- [ ] Tailored email to Replit recruiter linking repo + demo
- [ ] Resume update with the project
- [ ] Talking points doc (cheat sheet for interview prep)

### Bonus polish
- [ ] Custom shell completions (`critique --install-completion`)
- [ ] Helpful error messages (Ollama not running → "Run `ollama serve`")
- [ ] First-run wizard: `critique init` walks through setup

**Definition of done:** A stranger on GitHub understands the project in 30 seconds, can install it in 2 minutes, can see it work in 5 minutes.

---

## Phase 11 — Stretch Goals ⏳

> Optional features. Pick 1–2 based on remaining time + ROI.

- [ ] **`critique fix`** — apply suggested fixes interactively with confirmation
- [ ] **`critique describe`** — generate PR description from `git diff`
- [ ] **JS/TS support** — add ESLint + JS-flavored AI Critic
- [ ] **Inline annotations** — render code with comments overlaid (Rich Markdown)
- [ ] **VS Code extension** — show CodeCritique findings inline in the editor
- [ ] **Slack/Discord bot** — `/critique <pr-url>` posts a review in-channel
- [ ] **Custom rules** — let users add YAML files defining checks
- [ ] **Diff-mode for AI Critic** — only review changed hunks, not whole files

---

## Cross-Cutting Concerns

These aren't phases; they touch everything. Check as you address.

### Quality
- [ ] All AI calls fail-open (errors return original/empty, never crash pipeline)
- [ ] Ollama unreachable → clear error message + graceful degrade to no-AI mode
- [ ] Token budgets enforced (file size caps, conversation history caps)
- [ ] Logging: structured logs at `~/.codecritique/logs/` (gated behind `--debug`)

### Security
- [ ] No API keys committed (`.gitignore`, env vars only)
- [ ] Cloud requests strip identifiable info (file paths → relative)
- [ ] User can opt out of any cloud calls via config
- [ ] No telemetry without explicit opt-in

### Performance
- [ ] Parallelize enrichment (ThreadPoolExecutor, 4 workers)
- [ ] Skip AI on files >30k chars
- [ ] Cache by file SHA → AI Critic findings (avoid re-reviewing unchanged files)
- [ ] Profile a real run — note where the time goes, document in DECISIONS.md

### UX
- [ ] Rich progress bars during long operations
- [ ] Clear "Fix First" callout always visible at top of report
- [ ] What's Good section never empty (default to something positive on clean code)
- [ ] Keyboard interrupts always handled gracefully

---

## Final Mile — Pre-Release Checklist

Run through right before tagging v0.1.0 / sharing with the recruiter.

- [ ] Fresh-machine install test passes
- [ ] CI green on main branch
- [ ] README screenshot is current
- [ ] Demo video links work
- [ ] All examples in README actually run
- [ ] No `print()` debug statements left
- [ ] No `TODO` / `FIXME` in user-facing flows
- [ ] CHANGELOG entry for v0.1.0
- [ ] Recruiter email drafted with repo link, demo link, talking points

---

*This is a living checklist. Mark items as you go. When a phase is fully checked, update the status table at the top.*
