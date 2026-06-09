# Changelog

All notable changes to CodeCritique will be documented in this file.

## 0.1.0 - Unreleased

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
- Remove the FastAPI web demo and the unused `web`/`cloud` optional dependencies.
- Remove the legacy embedded HTML report generator.

- Package the CLI as `codecritique` with the legacy `critique` command retained.
- Add GitHub Actions coverage for Python 3.10, 3.11, and 3.12.
- Add repository contribution templates for issues and pull requests.
- Add MIT licensing.
