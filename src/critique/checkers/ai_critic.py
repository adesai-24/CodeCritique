import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from critique.checkers.base import BaseChecker, Issue, Severity
from critique.ai.client import LLMClient
from critique.ai.prompts import CRITIC_SYSTEM
from critique.ai.schemas import CRITIC_SCHEMA

MAX_FILE_CHARS = 30_000
_DEFAULT_AI_CRITIC_WORKERS = 2


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


class AICriticChecker(BaseChecker):
    """
    Semantic code review checker backed by a local LLM.

    Slots into the existing checker pipeline as a peer of Ruff/Bandit/Mypy.
    Catches logic bugs, off-by-one errors, incorrect comparisons, and other
    correctness issues that require understanding intent rather than syntax.

    Safety properties:
      - Skips files larger than MAX_FILE_CHARS to stay within context budget.
      - Wraps each file in try/except so one bad file never aborts the run.
      - Maps "findings" → Issue with code="AI" so the report can distinguish
        AI findings from static-tool findings.
    """

    name = "AI Critic"
    description = "Semantic review via local LLM — catches logic bugs linters miss"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def _review_file(self, file_path: str) -> List[Issue]:
        issues: List[Issue] = []
        if not file_path.endswith(".py"):
            return issues
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            return issues

        if len(source) > MAX_FILE_CHARS:
            return issues

        try:
            result = self.llm.complete_json(
                system=CRITIC_SYSTEM,
                user=(
                    "Review this Python file for logic bugs and correctness issues:\n\n"
                    f"```python\n{source}\n```"
                ),
                schema=CRITIC_SCHEMA,
            )
            for finding in result.get("findings", []):
                try:
                    severity = Severity[finding.get("severity", "WARNING")]
                except KeyError:
                    severity = Severity.WARNING

                issues.append(
                    Issue(
                        file_path=file_path,
                        line=finding.get("line", 1),
                        column=0,
                        message=finding.get("title", "AI finding"),
                        code="AI",
                        severity=severity,
                        reasoning=finding.get("explanation"),
                    )
                )
        except Exception:
            pass

        return issues

    def run(self, files: List[str]) -> List[Issue]:
        py_files = [file_path for file_path in files if file_path.endswith(".py")]
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
