from typing import List

from critique.checkers.base import BaseChecker, Issue, Severity
from critique.ai.client import LLMClient
from critique.ai.prompts import CRITIC_SYSTEM
from critique.ai.schemas import CRITIC_SCHEMA

MAX_FILE_CHARS = 30_000


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

    def run(self, files: List[str]) -> List[Issue]:
        issues: List[Issue] = []
        for file_path in files:
            if not file_path.endswith(".py"):
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()
            except Exception:
                continue

            if len(source) > MAX_FILE_CHARS:
                continue

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
                continue

        return issues
