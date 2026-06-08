"""
Agentic code formatter — reshapes source into a clean, review-ready layout.

This is the first half of CodeCritique's "reviewer assistant": before a human
reads a diff, the formatter rewrites the file so it is consistent and pleasant
to read — proper spacing, column-aligned declarations (the "straight-line"
look), and a documenting comment above every function.

Crucially it is **format-only**: it does not fix bugs, rename things, or change
behaviour. Auto-suggested fixes for technical errors are a deliberate later
step. The strong "behaviour-preserving" contract is what makes the output safe
to apply with a single flag.

It reuses the same provider-agnostic :class:`~critique.ai.client.LLMClient` and
response cache as the review pipeline, so re-formatting an unchanged file is
free after the first run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from critique.ai.client import LLMClient
from critique.ai.prompts import FORMATTER_SYSTEM
from critique.languages import Language, detect_language

# Whole files are sent in one request so the model can align across the file and
# keep the layout globally consistent. Skip anything larger to stay within the
# context budget (matches the AI critic's per-file cap).
MAX_FORMAT_CHARS = 30_000

_FENCE_RE = re.compile(r"^```[^\n]*\n(.*)\n```$", re.DOTALL)


@dataclass
class FormatResult:
    """Outcome of formatting a single file."""

    file_path: str
    language: Optional[str]            # Language.name, or None if unsupported
    original: str
    formatted: str
    changed: bool
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _strip_code_fences(text: str) -> str:
    """Remove a single wrapping markdown code fence if the model added one.

    The prompt asks for raw code, but small models sometimes wrap the answer in
    ```` ```cpp … ``` ````. We strip exactly one outer fence and leave any
    legitimately fenced content inside the file untouched.
    """
    stripped = text.strip("\n")
    match = _FENCE_RE.match(stripped.strip())
    if match:
        return match.group(1)
    return text


def _match_trailing_newline(original: str, formatted: str) -> str:
    """Make the formatted text agree with the original about a final newline."""
    if original.endswith("\n") and not formatted.endswith("\n"):
        return formatted + "\n"
    if not original.endswith("\n"):
        return formatted.rstrip("\n")
    return formatted


class CodeFormatter:
    """Reformats source files for review using the configured LLM."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self._system = FORMATTER_SYSTEM

    def format_source(self, source: str, language: Language) -> str:
        """Return the reformatted source for an in-memory snippet."""
        user = (
            f"Reformat this {language.name} file for code review. Apply spacing, "
            "column alignment, and per-function documentation comments, but do "
            "not change any behaviour.\n\n"
            f"```{language.fence}\n{source}\n```"
        )
        # Temperature 0 keeps formatting deterministic and cache-friendly.
        raw = self.llm.complete(self._system, user, temperature=0.0)
        formatted = _strip_code_fences(raw)
        return _match_trailing_newline(source, formatted)

    def format_file(self, file_path: str) -> FormatResult:
        """Read, reformat, and report on a single file (does not write to disk)."""
        language = detect_language(file_path)
        if language is None:
            return FormatResult(file_path, None, "", "", False, error="unsupported file type")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as exc:
            return FormatResult(file_path, None, "", "", False, error=f"could not read: {exc}")

        if len(source) > MAX_FORMAT_CHARS:
            return FormatResult(
                file_path, language.name, source, source, False,
                error=f"file too large to format (> {MAX_FORMAT_CHARS} chars)",
            )

        if not source.strip():
            return FormatResult(file_path, language.name, source, source, False)

        try:
            formatted = self.format_source(source, language)
        except Exception as exc:
            return FormatResult(
                file_path, language.name, source, source, False,
                error=f"formatting failed: {exc}",
            )

        return FormatResult(
            file_path=file_path,
            language=language.name,
            original=source,
            formatted=formatted,
            changed=formatted != source,
        )
