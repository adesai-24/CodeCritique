# Changelog

All notable changes to CodeCritique will be documented in this file.

## 0.1.0 - Unreleased

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
- Add GitHub Actions coverage for Python 3.10, 3.11, and 3.12.
- Add repository contribution templates for issues and pull requests.
- Add MIT licensing.
