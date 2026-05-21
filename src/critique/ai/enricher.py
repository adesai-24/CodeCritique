"""
AIEnricher — upgrades raw linter findings with code-specific reasoning and fixes.

Each Issue goes through the LLM individually so the explanation is specific to
the actual code, not a generic rephrasing of the tool message. Enrichment runs
concurrently (ThreadPoolExecutor, 4 workers) to keep wall-clock time reasonable.

Fail-open contract: any exception on a single issue returns the original issue
unchanged. One bad enrichment never kills the full pipeline.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from typing import Any

from critique.checkers.base import Issue, Severity
from critique.ai.prompts import ENRICHER_SYSTEM
from critique.ai.schemas import ENRICHMENT_SCHEMA

console = Console()

_MAX_WORKERS = 4


class AIEnricher:
    def __init__(self, llm: Any):
        self.llm = llm

    def enrich(self, issue: Issue) -> Issue:
        """
        Return a new Issue with AI-generated reasoning and suggested_fix.
        Returns the original issue unchanged if anything goes wrong.
        """
        try:
            context_str = "".join(issue.code_context) if issue.code_context else ""
            user_msg = (
                f"Tool: {issue.code}\n"
                f"File: {issue.file_path}\n"
                f"Line: {issue.line}\n"
                f"Message: {issue.message}\n\n"
                f"Code context:\n```python\n{context_str}\n```\n\n"
                "Explain why this is a problem in THIS specific code and provide a concrete fix."
            )
            result = self.llm.complete_json(
                system=ENRICHER_SYSTEM,
                user=user_msg,
                schema=ENRICHMENT_SCHEMA,
            )
            new_severity = issue.severity
            try:
                new_severity = Severity[result.get("real_severity", issue.severity.value)]
            except KeyError:
                pass

            return issue._replace(
                reasoning=result.get("reasoning", issue.reasoning),
                suggested_fix=result.get("suggested_fix"),
                severity=new_severity,
            )
        except Exception:
            return issue


def enrich_issues(issues: List[Issue], llm: Any) -> List[Issue]:
    """
    Enrich all issues concurrently, returning results in original order.

    Handles KeyboardInterrupt by cancelling pending work and returning
    whatever has completed so far (plus originals for the rest).
    """
    if not issues:
        return issues

    enricher = AIEnricher(llm)
    enriched: List[Issue] = [None] * len(issues)  # type: ignore[list-item]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("Enriching findings with AI...", total=len(issues))

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_to_idx = {
                executor.submit(enricher.enrich, issue): i
                for i, issue in enumerate(issues)
            }
            try:
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        enriched[idx] = future.result()
                    except Exception:
                        enriched[idx] = issues[idx]
                    progress.advance(task)
            except KeyboardInterrupt:
                executor.shutdown(wait=False, cancel_futures=True)

    return [e if e is not None else issues[i] for i, e in enumerate(enriched)]
