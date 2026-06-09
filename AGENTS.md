# CodeCritique — Agent Guide

CodeCritique is a local pre-push quality gate for Python: it runs Ruff (lint),
Mypy (types), Bandit (security), and Coverage, optionally layered with a local
LLM review (Ollama + `qwen2.5-coder:7b`). This file tells AI agents how to call
the tool and how to work on this repo.

## Using the tool (as an agent)

Always prefer `--json`: it prints one JSON object to **stdout** and sends all
progress/status chatter to **stderr**.

```bash
codecritique check --json --no-ai            # fast, deterministic static checks on changed files
codecritique check --json --no-ai path/to/file.py   # specific files
codecritique check --json --no-ai --no-incremental  # full repo scan
codecritique check --json                    # adds local-LLM review (slow; requires `ollama serve`)
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

Other commands: `codecritique list` (saved reports), `codecritique chat --last`
(interactive Q&A about a report; needs Ollama), `codecritique install-hooks`
(git pre-push hook).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CODECRITIQUE_AI_CACHE` | `1` | Set `0` to bypass the LLM response cache |
| `CODECRITIQUE_CHECKER_WORKERS` | `4` | Parallel static checkers |
| `CODECRITIQUE_AI_CRITIC_WORKERS` | `2` | Parallel AI-critic file reviews |
| `CODECRITIQUE_KEEP_ALIVE` | `1h` | How long Ollama keeps the model loaded |

## Working on this repo

Layout:

- `src/critique/cli.py` — Typer CLI (`check`, `fix`, `list`, `chat`, `install-hooks`)
- `src/critique/runner.py` — orchestration: file selection, checker fan-out, fix pipeline, report dispatch
- `src/critique/checkers/` — one checker per file; all implement `BaseChecker.run(files) -> List[Issue]`
- `src/critique/ai/` — Ollama client (with caching), critic prompts/schemas, enricher, synthesizer
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
