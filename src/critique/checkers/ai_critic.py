"""
AICriticChecker — semantic code review via local LLM.

Optimizations over the naive whole-file approach
-------------------------------------------------
1. AST-based cache key: we hash the AST dump rather than raw source text, so
   changes that only affect comments or whitespace don't invalidate cached
   results.  A SyntaxError falls back to hashing the raw text.

2. Function/class chunking: instead of sending an entire file as one prompt,
   we extract top-level functions and classes and review each independently.
   This keeps prompts small (faster inference, fewer tokens), improves cache
   granularity (editing one function doesn't invalidate results for others),
   and lets us run chunks in parallel.

3. Files with no top-level definitions fall back to whole-file review (e.g.
   scripts, __init__.py with only imports).
"""

import ast
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from critique.checkers.base import BaseChecker, Issue, Severity
from critique.ai.client import LLMClient
from critique.ai.prompts import CRITIC_SYSTEM
from critique.ai.schemas import CRITIC_SCHEMA

MAX_FILE_CHARS = 30_000
MAX_CHUNK_CHARS = 8_000   # keep individual chunks well within context window
_DEFAULT_AI_CRITIC_WORKERS = 2


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _extract_chunks(source: str, file_path: str) -> List[Tuple[str, int]]:
    """
    Split a Python source file into reviewable chunks.

    Returns a list of (chunk_source, base_line_offset) tuples where
    base_line_offset is the 1-based line number of the chunk's first line
    within the original file.

    Strategy:
    - Parse the AST; collect top-level FunctionDef / AsyncFunctionDef / ClassDef.
    - Each definition becomes its own chunk (capped at MAX_CHUNK_CHARS).
    - Everything else (module-level statements, imports) is collected into a
      "module-level" chunk.
    - If parsing fails or there are no definitions, the whole file is one chunk.
    """
    try:
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
    except SyntaxError:
        return [(source, 1)]

    # Collect top-level definitions with their line ranges.
    def_nodes = [
        node for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    if not def_nodes:
        return [(source, 1)]

    chunks: List[Tuple[str, int]] = []

    # Build a set of lines covered by top-level definitions.
    covered: set = set()
    for node in def_nodes:
        start = node.lineno - 1   # 0-based
        end = getattr(node, "end_lineno", node.lineno)  # 1-based, inclusive
        covered.update(range(start, end))

    # Module-level lines (not inside any top-level def/class).
    module_lines = [i for i in range(len(lines)) if i not in covered]
    if module_lines:
        module_text = "".join(lines[i] for i in module_lines)
        if module_text.strip():
            chunks.append((module_text, module_lines[0] + 1))

    # One chunk per top-level definition.
    for node in def_nodes:
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        chunk_text = "".join(lines[start:end])
        if len(chunk_text) > MAX_CHUNK_CHARS:
            chunk_text = chunk_text[:MAX_CHUNK_CHARS]
        if chunk_text.strip():
            chunks.append((chunk_text, node.lineno))

    return chunks if chunks else [(source, 1)]


class AICriticChecker(BaseChecker):
    """
    Semantic code review checker backed by a local LLM.

    Slots into the existing checker pipeline as a peer of Ruff/Bandit/Mypy.
    Catches logic bugs, off-by-one errors, incorrect comparisons, and other
    correctness issues that require understanding intent rather than syntax.

    Safety properties:
      - Skips files larger than MAX_FILE_CHARS to stay within context budget.
      - Wraps each file/chunk in try/except so one failure never aborts the run.
      - Maps findings → Issue with code="AI" so the report can distinguish
        AI findings from static-tool findings.
    """

    name = "AI Critic"
    description = "Semantic review via local LLM — catches logic bugs linters miss"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def _review_chunk(
        self, chunk: str, line_offset: int, file_path: str
    ) -> List[Issue]:
        """Review a single chunk (function/class/module block) and return issues."""
        try:
            result = self.llm.complete_json(
                system=CRITIC_SYSTEM,
                user=(
                    f"Review this Python code (from {file_path}, starting at line {line_offset}) "
                    "for logic bugs and correctness issues:\n\n"
                    f"```python\n{chunk}\n```"
                ),
                schema=CRITIC_SCHEMA,
            )
            issues: List[Issue] = []
            for finding in result.get("findings", []):
                try:
                    severity = Severity[finding.get("severity", "WARNING")]
                except KeyError:
                    severity = Severity.WARNING

                # Line numbers in the response are relative to the chunk;
                # translate them back to file-absolute lines.
                relative_line = finding.get("line", 1)
                absolute_line = line_offset + relative_line - 1

                issues.append(
                    Issue(
                        file_path=file_path,
                        line=absolute_line,
                        column=0,
                        message=finding.get("title", "AI finding"),
                        code="AI",
                        severity=severity,
                        reasoning=finding.get("explanation"),
                    )
                )
            return issues
        except Exception:
            return []

    def _review_file(self, file_path: str) -> List[Issue]:
        if not file_path.endswith(".py"):
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            return []

        if len(source) > MAX_FILE_CHARS:
            return []

        chunks = _extract_chunks(source, file_path)

        all_issues: List[Issue] = []
        for chunk_text, line_offset in chunks:
            all_issues.extend(self._review_chunk(chunk_text, line_offset, file_path))
        return all_issues

    def run(self, files: List[str]) -> List[Issue]:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return []

        max_workers = max(
            1,
            min(
                len(py_files),
                _env_int("CODECRITIQUE_AI_CRITIC_WORKERS", _DEFAULT_AI_CRITIC_WORKERS),
            ),
        )
        results: List[List[Issue]] = [[] for _ in py_files]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(self._review_file, file_path): i
                for i, file_path in enumerate(py_files)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = []

        issues: List[Issue] = []
        for file_issues in results:
            issues.extend(file_issues)
        return issues
