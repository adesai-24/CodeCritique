"""
Review profiles — a.k.a. "suggestion modes".

A profile tunes *how* CodeCritique reviews your code without touching the
checkers themselves.  It controls three things:

1. **Tone & focus** — extra instructions injected into every AI system prompt
   (e.g. "be a patient mentor" or "prioritise security").
2. **Reporting threshold** — the lowest severity worth surfacing
   (``min_report_severity``), so lenient modes hide nitpicks.
3. **Push gate** — which severity blocks a push (``block_severity``), so strict
   modes can fail on warnings while lenient modes only fail on real bugs.

Users pick a built-in mode (``codecritique config mode strict``) and can layer
their own project context on top
(``codecritique config set project_context "FastAPI service, async everywhere"``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from critique.checkers.base import Issue, Severity

# Severity ordering for threshold comparisons.
_SEV_ORDER: Dict[str, int] = {"INFO": 0, "WARNING": 1, "FATAL": 2}

DEFAULT_MODE = "balanced"


@dataclass(frozen=True)
class ReviewProfile:
    name: str
    description: str
    instructions: str
    min_report_severity: str = "INFO"   # drop anything below this from reports
    block_severity: str = "FATAL"       # this severity (and above) blocks a push
    verbosity: str = "normal"           # concise | normal | detailed
    temperature: Optional[float] = None  # optional sampling override


_VERBOSITY_HINT = {
    "concise": "Keep every explanation and fix to a single short sentence.",
    "normal": "",
    "detailed": "Explain the underlying cause and walk through the fix step by step.",
}


BUILTIN_PROFILES: Dict[str, ReviewProfile] = {
    "balanced": ReviewProfile(
        name="balanced",
        description="Sensible defaults: flag real problems, block only on fatal issues.",
        instructions=(
            "Review like a pragmatic senior engineer. Flag genuine correctness, "
            "security, and maintainability issues; don't nitpick style."
        ),
        min_report_severity="INFO",
        block_severity="FATAL",
        verbosity="normal",
    ),
    "strict": ReviewProfile(
        name="strict",
        description="Zero-tolerance: surface everything and block on warnings too.",
        instructions=(
            "Review like a meticulous staff engineer enforcing a high bar. Call out "
            "every correctness risk, missing edge case, unclear name, and weak test. "
            "Prefer caution: when unsure, raise it."
        ),
        min_report_severity="INFO",
        block_severity="WARNING",
        verbosity="normal",
    ),
    "lenient": ReviewProfile(
        name="lenient",
        description="Only real bugs. Hides nitpicks; blocks only on fatal issues.",
        instructions=(
            "Review like a senior engineer who respects the author's time. Report "
            "only issues that could cause incorrect behaviour, data loss, or security "
            "problems. Ignore style and minor suggestions entirely."
        ),
        min_report_severity="WARNING",
        block_severity="FATAL",
        verbosity="concise",
    ),
    "security": ReviewProfile(
        name="security",
        description="Security-first: emphasise vulnerabilities and unsafe patterns.",
        instructions=(
            "Review primarily through a security lens. Prioritise injection, unsafe "
            "deserialisation, secrets handling, auth/authz mistakes, path traversal, "
            "and unsafe subprocess/SQL usage. Treat exploitable issues as FATAL."
        ),
        min_report_severity="INFO",
        block_severity="FATAL",
        verbosity="detailed",
    ),
    "mentor": ReviewProfile(
        name="mentor",
        description="Teaching tone: detailed, friendly explanations. Never blocks.",
        instructions=(
            "Review like a supportive mentor teaching a junior developer. Explain the "
            "'why' behind each issue, suggest how to think about it next time, and keep "
            "an encouraging tone. Still be technically precise."
        ),
        min_report_severity="INFO",
        block_severity="NEVER",
        verbosity="detailed",
    ),
    "concise": ReviewProfile(
        name="concise",
        description="Terse output: one-line findings and fixes.",
        instructions=(
            "Review tersely. One short sentence per finding and per fix. No preamble."
        ),
        min_report_severity="INFO",
        block_severity="FATAL",
        verbosity="concise",
    ),
}


def list_profiles() -> List[ReviewProfile]:
    return list(BUILTIN_PROFILES.values())


def get_profile(name: Optional[str]) -> ReviewProfile:
    """Return a built-in profile by name, falling back to the default."""
    if not name:
        return BUILTIN_PROFILES[DEFAULT_MODE]
    return BUILTIN_PROFILES.get(name.strip().lower(), BUILTIN_PROFILES[DEFAULT_MODE])


def is_valid_mode(name: str) -> bool:
    return name.strip().lower() in BUILTIN_PROFILES


# ---------------------------------------------------------------------------
# Resolution from config
# ---------------------------------------------------------------------------

def resolve_active_profile(config) -> ReviewProfile:
    """Build the effective profile from the user's config.

    Starts from the named built-in mode, then applies any explicit overrides
    the user stored (e.g. a custom ``block_severity``).
    """
    mode = getattr(config, "suggestion_mode", None) or config.extra.get("suggestion_mode")
    profile = get_profile(mode)

    overrides = {}
    block = config.extra.get("block_severity")
    if block and block.upper() in {"INFO", "WARNING", "FATAL", "NEVER"}:
        overrides["block_severity"] = block.upper()
    if overrides:
        from dataclasses import replace
        profile = replace(profile, **overrides)
    return profile


# ---------------------------------------------------------------------------
# Prompt augmentation
# ---------------------------------------------------------------------------

def apply_profile_to_system(
    base_system: str,
    profile: ReviewProfile,
    project_context: Optional[str] = None,
    custom_instructions: Optional[str] = None,
) -> str:
    """Append profile + project context to a base system prompt.

    Because the augmented system prompt is part of the LLM cache key, switching
    modes or editing the project context naturally produces fresh AI output
    instead of serving a cached review from a different mode.
    """
    parts = [base_system, "", f"--- Reviewer mode: {profile.name} ---", profile.instructions]
    hint = _VERBOSITY_HINT.get(profile.verbosity, "")
    if hint:
        parts.append(hint)
    if project_context:
        parts.append("")
        parts.append("Project context provided by the author (treat as ground truth):")
        parts.append(project_context.strip())
    if custom_instructions:
        parts.append("")
        parts.append("Additional reviewer instructions from the author:")
        parts.append(custom_instructions.strip())
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

def severity_meets(severity: Severity, threshold: str) -> bool:
    """True if ``severity`` is at least as severe as ``threshold``."""
    threshold = (threshold or "INFO").upper()
    if threshold == "NEVER":
        return False
    return _SEV_ORDER.get(severity.value, 0) >= _SEV_ORDER.get(threshold, 0)


def filter_by_min_severity(issues: List[Issue], profile: ReviewProfile) -> List[Issue]:
    """Drop issues below the profile's reporting threshold."""
    if profile.min_report_severity == "INFO":
        return issues  # nothing to filter
    return [iss for iss in issues if severity_meets(iss.severity, profile.min_report_severity)]


def should_block(issues: List[Issue], profile: ReviewProfile) -> bool:
    """True if any issue meets the profile's blocking severity."""
    if profile.block_severity == "NEVER":
        return False
    return any(severity_meets(iss.severity, profile.block_severity) for iss in issues)
