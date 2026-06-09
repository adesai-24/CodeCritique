# CodeCritique — Agent Guide

CodeCritique is a local pre-push quality gate for Python and C/C++: it runs
Ruff (lint), Mypy (types), Bandit (security), Coverage, a format check, and
cppcheck for C/C++, optionally layered with an LLM review (Gemini by default;
Ollama, OpenAI, Anthropic, and vLLM are also supported — see `codecritique
config providers`). This file tells AI agents how to call the tool and how to
work on this repo.

## Using the tool (as an agent)

Always prefer `--json`: it prints one JSON object to **stdout** and sends all
progress/status chatter to **stderr**.

```bash
codecritique check --json --no-ai            # fast, deterministic static checks on changed files
codecritique check --json --no-ai path/to/file.py   # specific files
codecritique check --json --no-ai --no-incremental  # full repo scan
codecritique check --json                    # adds the AI review (needs a provider key or Ollama)
codecritique fix [files...]                  # apply safe lint fixes + reformat in place
codecritique fix --unsafe                    # also apply behavior-changing fixes
```

A good agent loop: `fix` first (mechanical cleanup), then `check --json --no-ai`
and resolve the remaining findings yourself.

Exit codes: `0` = passed (no FATAL issues), `1` = failed (FATAL issues found).

JSON shape:

```json
{
  "passed": true,
  "files_checked": ["abs/path/a.py"],
  "issue_count": 1,
  "issues": [
    {
      "file_path": "abs/path/a.py",
      "line": 42,
      "column": 5,
      "message": "...",
      "code": "E999",            // ruff code, bandit test id, "TYPE", "AI", "COV-LOW", "FMT001"
      "severity": "FATAL",       // FATAL | WARNING | INFO
      "reasoning": "...",        // plain-English explanation (AI-enriched when Ollama is up)
      "code_context": ["..."],   // ±3 source lines around the finding
      "suggested_fix": "..."     // present only when AI enrichment ran
    }
  ],
  "synthesis": {
    "summary": "...",
    "fix_first": 0,              // index into issues; -1 if none
    "critical": [0],             // index lists into issues
    "warnings": [],
    "suggestions": [],
    "whats_good": ["..."]
  },
  "report_id": "rev_abc123"      // saved under ~/.codecritique/reports/
}
```

Recommendations:
- Use `--no-ai` in agent loops — you do the reasoning yourself; the LLM pass
  only adds latency. Drop `--no-ai` when the user explicitly wants the local
  AI review.
- Severity is the contract: only `FATAL` blocks (exit 1). `WARNING`/`INFO` pass.
- Incremental mode diffs against `origin/main`; with no changed `.py` files it
  passes immediately.
- Lint depth is environment-aware: when the target project has no ruff config
  (`ruff.toml`, `.ruff.toml`, or `[tool.ruff]` in `pyproject.toml`), checks use
  the curated rule set `E,W,F,B,C4,SIM,UP,C90,RUF`; otherwise the project's own
  config wins. `FMT001` (INFO) means `codecritique fix` would reformat the file.

Other commands: `codecritique ask "<question>"` (plain-English capability
Q&A), `codecritique do "<instruction>" [--yes]` (plain-English request ->
whitelisted action plan -> confirm -> run; actions: check, fix, format,
list_reports, install_hooks), `codecritique format` (AI-driven,
behavior-preserving reformatter with diff preview), `codecritique list`
(saved reports),
`codecritique chat --last` (interactive Q&A about a report; needs an AI
provider), `codecritique config` (provider/key/language/review-mode settings),
`codecritique style` (personal style profiles), `codecritique cache` (AI cache
management), `codecritique install-hooks` (git pre-push hook).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CODECRITIQUE_AI_CACHE` | `1` | Set `0` to bypass the LLM response cache |
| `CODECRITIQUE_CHECKER_WORKERS` | `4` | Parallel static checkers |
| `CODECRITIQUE_AI_CRITIC_WORKERS` | `2` | Parallel AI-critic file reviews |
| `CODECRITIQUE_KEEP_ALIVE` | `1h` | How long Ollama keeps the model loaded |

## Working on this repo

Layout:

- `src/critique/cli.py` — Typer CLI (`check`, `fix`, `format`, `ask`, `do`, `list`, `chat`, `install-hooks`, plus `config`/`cache`/`style` sub-apps)
- `src/critique/assistant.py` — natural-language layer: CLI manifest for `ask`, whitelisted action plans for `do`
- `src/critique/runner.py` — orchestration: file selection, checker fan-out, fix pipeline, report dispatch
- `src/critique/checkers/` — one checker per file; all implement `BaseChecker.run(files) -> List[Issue]`
- `src/critique/ai/` — provider-agnostic LLM client (with caching), providers/, critic prompts/schemas, enricher, synthesizer
- `src/critique/config.py` + `config_cli.py` — persisted settings (provider, model, language, review mode)
- `src/critique/profiles.py` — review modes (severity thresholds, tone) applied to prompts and gating
- `src/critique/languages.py` — supported-extension detection (Python, C/C++)
- `src/critique/report.py` — terminal renderers (basic table + AI review)
- `src/critique/persistence.py` — saved reports in `~/.codecritique/reports/`
- `tests/` — pytest suite; fixtures in `tests/fixtures/`

Conventions:

- `Issue` (a NamedTuple in `checkers/base.py`) is the single data shape passed
  between every stage; extend it rather than inventing parallel structures.
- Checkers and AI stages must fail open: catch exceptions, return what you
  have, never crash a check run.
- Status/progress output goes to the stderr `Console`; stdout is reserved for
  the report or JSON.

Dev commands (Windows host, venv at `.venv`):

```bash
python -m pytest          # run tests
pip install -e .[dev]     # editable install with test deps
```
