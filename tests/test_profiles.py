"""Tests for review profiles / suggestion modes."""

from critique import profiles
from critique.config import CritiqueConfig
from critique.checkers.base import Issue, Severity
from critique.report import print_report


def _issue(sev: Severity, code="X") -> Issue:
    return Issue(
        file_path="x.py", line=1, column=0, message="m", code=code, severity=sev
    )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def test_default_mode_is_balanced():
    assert profiles.get_profile(None).name == "balanced"


def test_unknown_mode_falls_back_to_default():
    assert profiles.get_profile("nonsense").name == "balanced"


def test_all_builtins_have_valid_severities():
    valid = {"INFO", "WARNING", "FATAL", "NEVER"}
    for prof in profiles.list_profiles():
        assert prof.min_report_severity in valid
        assert prof.block_severity in valid


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

def test_severity_meets_ordering():
    assert profiles.severity_meets(Severity.FATAL, "WARNING") is True
    assert profiles.severity_meets(Severity.WARNING, "WARNING") is True
    assert profiles.severity_meets(Severity.INFO, "WARNING") is False
    assert profiles.severity_meets(Severity.FATAL, "NEVER") is False


def test_filter_by_min_severity():
    issues = [_issue(Severity.INFO), _issue(Severity.WARNING), _issue(Severity.FATAL)]
    lenient = profiles.get_profile("lenient")  # min WARNING
    kept = profiles.filter_by_min_severity(issues, lenient)
    assert {i.severity for i in kept} == {Severity.WARNING, Severity.FATAL}


def test_filter_balanced_keeps_everything():
    issues = [_issue(Severity.INFO), _issue(Severity.FATAL)]
    assert profiles.filter_by_min_severity(issues, profiles.get_profile("balanced")) == issues


def test_should_block_strict_blocks_warnings():
    strict = profiles.get_profile("strict")  # block WARNING
    assert profiles.should_block([_issue(Severity.WARNING)], strict) is True


def test_should_block_mentor_never_blocks():
    mentor = profiles.get_profile("mentor")  # block NEVER
    assert profiles.should_block([_issue(Severity.FATAL)], mentor) is False


# ---------------------------------------------------------------------------
# Prompt augmentation
# ---------------------------------------------------------------------------

def test_apply_profile_injects_instructions_and_context():
    prof = profiles.get_profile("security")
    out = profiles.apply_profile_to_system(
        "BASE PROMPT",
        prof,
        project_context="FastAPI service",
        custom_instructions="Prefer pydantic",
    )
    assert "BASE PROMPT" in out
    assert "security" in out
    assert "FastAPI service" in out
    assert "Prefer pydantic" in out


def test_apply_profile_changes_output_per_mode():
    a = profiles.apply_profile_to_system("B", profiles.get_profile("strict"))
    b = profiles.apply_profile_to_system("B", profiles.get_profile("lenient"))
    assert a != b  # different modes → different system prompt → different cache key


# ---------------------------------------------------------------------------
# Resolution from config
# ---------------------------------------------------------------------------

def test_resolve_active_profile_uses_config_field():
    cfg = CritiqueConfig(suggestion_mode="strict")
    assert profiles.resolve_active_profile(cfg).name == "strict"


def test_resolve_active_profile_block_severity_override():
    cfg = CritiqueConfig(suggestion_mode="balanced", extra={"block_severity": "warning"})
    prof = profiles.resolve_active_profile(cfg)
    assert prof.block_severity == "WARNING"


# ---------------------------------------------------------------------------
# Report gate integration
# ---------------------------------------------------------------------------

def test_print_report_blocks_on_warning_when_strict():
    issues = [_issue(Severity.WARNING)]
    assert print_report(issues, block_severity="WARNING") is False


def test_print_report_passes_warning_when_default():
    issues = [_issue(Severity.WARNING)]
    assert print_report(issues, block_severity="FATAL") is True


def test_print_report_never_blocks_for_mentor():
    issues = [_issue(Severity.FATAL)]
    assert print_report(issues, block_severity="NEVER") is True
