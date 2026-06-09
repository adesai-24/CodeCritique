"""
Language registry — the single source of truth for which file types
CodeCritique understands and how to talk about them.

Historically the tool was Python-only and the ``.py`` suffix was hard-coded in a
handful of places (git diff filtering, file globbing, the AI critic).  As soon
as a second language (C/C++) enters the picture, those scattered literals become
a liability.  This module centralises the mapping so every component agrees on:

* which extensions are reviewable (``SUPPORTED_EXTENSIONS``),
* the human-readable language name for reports and prompts, and
* the markdown fence label to wrap a snippet in when prompting the LLM.

Adding a new language is now a one-line change here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Language:
    """Static metadata about a programming language CodeCritique supports."""

    key: str                 # stable identifier, e.g. "python", "cpp"
    name: str                # human-readable, e.g. "Python", "C/C++"
    extensions: Tuple[str, ...]
    fence: str               # markdown code-fence label for LLM prompts


PYTHON = Language(
    key="python",
    name="Python",
    extensions=(".py", ".pyi"),
    fence="python",
)

# C and C++ share one logical "language" for review/format purposes: the same
# checker (cppcheck) and the same formatting conventions apply to both.
CPP = Language(
    key="cpp",
    name="C/C++",
    extensions=(
        ".c", ".h",
        ".cc", ".cpp", ".cxx", ".c++",
        ".hh", ".hpp", ".hxx", ".h++",
        ".ino",
    ),
    fence="cpp",
)

LANGUAGES: Tuple[Language, ...] = (PYTHON, CPP)
LANGUAGE_KEYS: Tuple[str, ...] = tuple(lang.key for lang in LANGUAGES)
LANGUAGE_CHOICES: Tuple[str, ...] = ("auto",) + LANGUAGE_KEYS

# extension (lower-case, with dot) -> Language
_EXT_MAP: Dict[str, Language] = {
    ext: lang for lang in LANGUAGES for ext in lang.extensions
}

# Every reviewable extension, handy for glob/diff filtering.
SUPPORTED_EXTENSIONS: Tuple[str, ...] = tuple(_EXT_MAP.keys())


def detect_language(path: str) -> Optional[Language]:
    """Return the :class:`Language` for a path, or ``None`` if unsupported."""
    return _EXT_MAP.get(Path(path).suffix.lower())


def is_supported(path: str) -> bool:
    """True if the path's extension is one CodeCritique knows how to review."""
    return Path(path).suffix.lower() in _EXT_MAP


def language_for_key(key: str) -> Optional[Language]:
    key = key.strip().lower()
    for lang in LANGUAGES:
        if lang.key == key:
            return lang
    return None


def extensions_for_choice(language: str = "auto") -> Tuple[str, ...]:
    """Return reviewable extensions for a configured language choice."""
    language = (language or "auto").strip().lower()
    if language == "auto":
        return SUPPORTED_EXTENSIONS
    lang = language_for_key(language)
    if lang is None:
        raise ValueError(
            f"Unknown language '{language}'. Supported: {', '.join(LANGUAGE_CHOICES)}"
        )
    return lang.extensions


def is_supported_for_choice(path: str, language: str = "auto") -> bool:
    return Path(path).suffix.lower() in extensions_for_choice(language)
