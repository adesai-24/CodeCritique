"""
AISynthesizer — turns a flat list of findings into a curated review.

Sends all enriched findings to the LLM in one call and receives a structured
summary with priority ordering, severity bucketing, and positive observations.
Falls back to a mechanical summary if the LLM call fails so the report always
renders.
"""

import os
from typing import Any, Dict, List, Optional

from critique.checkers.base import Issue, Severity
from critique.ai.client import LLMClient
from critique.ai.prompts import SYNTHESIZER_SYSTEM
from critique.ai.schemas import SYNTH_SCHEMA

_CLEAN_RESULT: Dict[str, Any] = {
    "summary": "No issues found. The code looks clean.",
    "fix_first": -1,
    "critical": [],
    "warnings": [],
    "suggestions": [],
    "whats_good": ["All automated checks passed — great work keeping things clean."],
}

_REQUIRED_KEYS = ("summary", "fix_first", "critical", "warnings", "suggestions", "whats_good")


class AISynthesizer:
    def __init__(self, llm: LLMClient, profile=None, project_context=None, custom_instructions=None):
        self.llm = llm
        if profile is not None:
            from critique.profiles import apply_profile_to_system
            self._system = apply_profile_to_system(
                SYNTHESIZER_SYSTEM, profile, project_context, custom_instructions
            )
        else:
            self._system = SYNTHESIZER_SYSTEM

    def synthesize(
        self,
        issues: List[Issue],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Return a synthesis dict. Never raises — falls back gracefully on error.

        `context` (project, branch, mode, file_count) lets the review speak to
        the specific situation instead of sounding generic.
        """
        if not issues:
            return _CLEAN_RESULT

        context_line = ""
        if context:
            parts = []
            if context.get("project"):
                parts.append(f"project '{context['project']}'")
            if context.get("branch"):
                parts.append(f"branch '{context['branch']}'")
            if context.get("file_count"):
                parts.append(f"{context['file_count']} file(s)")
            if context.get("mode"):
                parts.append(context["mode"])
            if parts:
                context_line = "Context: this is " + ", ".join(parts) + ".\n\n"

        lines = []
        for i, issue in enumerate(issues):
            try:
                rel = os.path.relpath(issue.file_path)
            except Exception:
                rel = issue.file_path
            entry = f"{i}. [{issue.severity.value}] {rel}:{issue.line} — {issue.message}"
            if issue.reasoning:
                entry += f"\n   Reasoning: {issue.reasoning}"
            if issue.suggested_fix:
                entry += f"\n   Fix: {issue.suggested_fix}"
            lines.append(entry)

        user_msg = (
            context_line
            + f"Here are {len(issues)} findings from automated code analysis:\n\n"
            + "\n\n".join(lines)
            + "\n\nProvide your synthesis."
        )

        try:
            result = self.llm.complete_json(
                system=self._system,
                user=user_msg,
                schema=SYNTH_SCHEMA,
            )
            for key in _REQUIRED_KEYS:
                if key not in result:
                    result[key] = _CLEAN_RESULT[key]
            return result
        except Exception:
            # Mechanical fallback: bucket by severity without LLM
            return {
                "summary": f"Found {len(issues)} issue(s). Review the list below.",
                "fix_first": next(
                    (i for i, iss in enumerate(issues) if iss.severity == Severity.FATAL), 0
                ),
                "critical": [i for i, iss in enumerate(issues) if iss.severity == Severity.FATAL],
                "warnings": [i for i, iss in enumerate(issues) if iss.severity == Severity.WARNING],
                "suggestions": [i for i, iss in enumerate(issues) if iss.severity == Severity.INFO],
                "whats_good": [],
            }
