"""
AIEnricher — upgrades raw linter findings with code-specific reasoning and fixes.

Optimization strategy
---------------------
1. Trivial-filter: pure formatting issues (whitespace, line length, blank lines)
   get a lightweight canned enrichment and are never sent to the LLM.

2. Batch call: all remaining issues are sent in ONE LLM request that returns an
   "enrichments" array aligned by index.  This cuts N LLM round-trips to 1 and
   is the single biggest speed-up for large codebases.

3. Per-issue fallback: if the batch call fails (malformed JSON, wrong length,
   model unavailable), we fall back to the original per-issue concurrent approach
   so the pipeline never silently drops enrichments.

Fail-open contract: any exception at any stage returns the original issue unchanged.
One bad enrichment never kills the full pipeline.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from critique.checkers.base import Issue, Severity
from critique.ai.client import LLMClient
from critique.ai.prompts import BATCH_ENRICHER_SYSTEM, ENRICHER_SYSTEM
from critique.ai.schemas import BATCH_ENRICHMENT_SCHEMA, ENRICHMENT_SCHEMA

console = Console()

_MAX_WORKERS = 4

# Ruff rule codes whose meaning is fully captured by the tool message.
# These don't benefit from LLM enrichment; we give them a canned explanation
# and skip the model call entirely.
_TRIVIAL_CODES: Set[str] = {
    # whitespace / blank lines
    "E101", "E111", "E114", "E116", "E117",
    "E121", "E122", "E123", "E124", "E125", "E126", "E127", "E128", "E129", "E131",
    "E133",
    "W191", "W291", "W292", "W293", "W391",
    "E301", "E302", "E303", "E304", "E305", "E306",
    # line length
    "E501",
    # imports ordering (isort)
    "I001", "I002",
    # unused import (already obvious)
    "F401",
    # trailing comma
    "COM812", "COM818",
}

_TRIVIAL_REASONING = "This is a formatting / style issue; fix it to keep the codebase consistent."
_TRIVIAL_FIX = "Run `ruff check --fix` to auto-correct this."


def _is_trivial(issue: Issue) -> bool:
    return issue.code in _TRIVIAL_CODES


def _canned_enrichment(issue: Issue) -> Issue:
    return issue._replace(
        reasoning=_TRIVIAL_REASONING,
        suggested_fix=_TRIVIAL_FIX,
    )


def _format_issue_for_batch(idx: int, issue: Issue) -> str:
    context_str = "".join(issue.code_context) if issue.code_context else "(no context)"
    return (
        f"Issue {idx}:\n"
        f"  Tool: {issue.code}\n"
        f"  File: {issue.file_path}\n"
        f"  Line: {issue.line}\n"
        f"  Message: {issue.message}\n"
        f"  Code context:\n"
        f"```python\n{context_str}\n```"
    )


def _enrich_batch(issues: List[Issue], llm: LLMClient) -> Optional[List[Issue]]:
    """
    Send all issues in a single LLM call.  Returns a fully-enriched list aligned
    with the input, or None if the call fails / produces a malformed response.
    """
    if not issues:
        return []

    user_msg = (
        f"Enrich the following {len(issues)} code issue(s).\n\n"
        + "\n\n".join(_format_issue_for_batch(i, iss) for i, iss in enumerate(issues))
    )

    try:
        result = llm.complete_json(
            system=BATCH_ENRICHER_SYSTEM,
            user=user_msg,
            schema=BATCH_ENRICHMENT_SCHEMA,
        )
        enrichments = result.get("enrichments", [])
        if len(enrichments) != len(issues):
            return None  # malformed — fall back to per-issue mode

        enriched: List[Issue] = []
        for issue, enr in zip(issues, enrichments):
            new_severity = issue.severity
            try:
                new_severity = Severity[enr.get("real_severity", issue.severity.name)]
            except KeyError:
                pass
            enriched.append(
                issue._replace(
                    reasoning=enr.get("reasoning", issue.reasoning),
                    suggested_fix=enr.get("suggested_fix"),
                    severity=new_severity,
                )
            )
        return enriched
    except Exception:
        return None


class AIEnricher:
    """Fallback per-issue enricher used when the batch call fails."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def enrich(self, issue: Issue) -> Issue:
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


def _enrich_per_issue_fallback(
    issues: List[Issue], llm: LLMClient, progress_callback=None
) -> List[Issue]:
    """Concurrent per-issue enrichment used as a fallback."""
    enricher = AIEnricher(llm)
    enriched: List[Issue] = [None] * len(issues)  # type: ignore[list-item]

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
                if progress_callback:
                    progress_callback()
        except KeyboardInterrupt:
            executor.shutdown(wait=False, cancel_futures=True)

    return [e if e is not None else issues[i] for i, e in enumerate(enriched)]


def enrich_issues(issues: List[Issue], llm: LLMClient) -> List[Issue]:
    """
    Enrich all issues as fast as possible:

    1. Trivial formatting issues get a canned explanation (no LLM call).
    2. Non-trivial issues are sent to the LLM in ONE batch request.
    3. If the batch response is malformed, fall back to per-issue concurrent mode.

    Returns results in original order.  Never raises.
    """
    if not issues:
        return issues

    # Separate trivial from non-trivial.
    trivial_indices: List[int] = []
    nontrivial_indices: List[int] = []
    for i, iss in enumerate(issues):
        (trivial_indices if _is_trivial(iss) else nontrivial_indices).append(i)

    nontrivial_issues = [issues[i] for i in nontrivial_indices]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Enriching {len(nontrivial_issues)} finding(s) with AI"
            f" (batch call)..." if nontrivial_issues else "Enriching findings...",
            total=len(nontrivial_issues) or 1,
        )

        if nontrivial_issues:
            # Attempt fast batch enrichment.
            batch_result = _enrich_batch(nontrivial_issues, llm)
            if batch_result is not None:
                enriched_nontrivial = batch_result
                progress.advance(task, len(nontrivial_issues))
            else:
                # Batch failed — fall back to per-issue mode with progress updates.
                console.print(
                    "[dim]Batch enrichment failed, falling back to per-issue mode...[/dim]"
                )
                enriched_nontrivial = _enrich_per_issue_fallback(
                    nontrivial_issues,
                    llm,
                    progress_callback=lambda: progress.advance(task),
                )
        else:
            enriched_nontrivial = []
            progress.advance(task)

    # Reassemble in original order.
    result: List[Issue] = list(issues)
    for i, iss in zip(trivial_indices, [_canned_enrichment(issues[i]) for i in trivial_indices]):
        result[i] = iss
    for i, iss in zip(nontrivial_indices, enriched_nontrivial):
        result[i] = iss

    return result
