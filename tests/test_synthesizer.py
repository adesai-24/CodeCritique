"""Tests for AISynthesizer — LLM is mocked throughout."""

import pytest
from unittest.mock import MagicMock

from critique.checkers.base import Issue, Severity
from critique.ai.synthesizer import AISynthesizer, _CLEAN_RESULT, _REQUIRED_KEYS


def _make_issue(severity=Severity.WARNING, line=1):
    return Issue(
        file_path="f.py",
        line=line,
        column=0,
        message="msg",
        code="E1",
        severity=severity,
    )


def _valid_synth(overrides=None):
    base = {
        "summary": "One issue found.",
        "fix_first": 0,
        "critical": [0],
        "warnings": [],
        "suggestions": [],
        "whats_good": ["Good variable names."],
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

def test_synthesize_empty_issues_returns_clean_result():
    llm = MagicMock()
    synth = AISynthesizer(llm)
    result = synth.synthesize([])
    assert result == _CLEAN_RESULT
    llm.complete_json.assert_not_called()


# ---------------------------------------------------------------------------
# Normal LLM response
# ---------------------------------------------------------------------------

def test_synthesize_returns_llm_output_when_valid():
    llm = MagicMock()
    llm.complete_json.return_value = _valid_synth()
    synth = AISynthesizer(llm)
    result = synth.synthesize([_make_issue()])
    assert result["summary"] == "One issue found."
    assert result["critical"] == [0]


def test_synthesize_fills_missing_keys_from_defaults():
    # LLM returns a partial response missing some keys.
    partial = {"summary": "Partial", "fix_first": 0, "critical": []}
    llm = MagicMock()
    llm.complete_json.return_value = partial
    synth = AISynthesizer(llm)
    result = synth.synthesize([_make_issue()])
    for key in _REQUIRED_KEYS:
        assert key in result


# ---------------------------------------------------------------------------
# Fallback on LLM error
# ---------------------------------------------------------------------------

def test_synthesize_falls_back_on_llm_exception():
    llm = MagicMock()
    llm.complete_json.side_effect = RuntimeError("Offline")
    synth = AISynthesizer(llm)
    issues = [_make_issue(Severity.FATAL), _make_issue(Severity.WARNING)]
    result = synth.synthesize(issues)

    # Mechanical fallback still produces required keys.
    for key in _REQUIRED_KEYS:
        assert key in result
    # FATAL issue ends up in critical bucket.
    assert 0 in result["critical"]
    assert 1 in result["warnings"]


def test_synthesize_fallback_fix_first_points_to_fatal():
    llm = MagicMock()
    llm.complete_json.side_effect = Exception("boom")
    synth = AISynthesizer(llm)
    issues = [
        _make_issue(Severity.WARNING, line=1),
        _make_issue(Severity.FATAL, line=2),
    ]
    result = synth.synthesize(issues)
    assert result["fix_first"] == 1


# ---------------------------------------------------------------------------
# Prompt content
# ---------------------------------------------------------------------------

def test_synthesize_includes_all_issues_in_prompt():
    llm = MagicMock()
    llm.complete_json.return_value = _valid_synth({"critical": [], "fix_first": -1})
    synth = AISynthesizer(llm)
    issues = [_make_issue(line=i) for i in range(1, 4)]
    synth.synthesize(issues)

    call_args = llm.complete_json.call_args
    user_msg = call_args[1]["user"] if "user" in call_args[1] else call_args[0][1]
    assert "3 findings" in user_msg


def test_synthesize_includes_reasoning_when_present():
    llm = MagicMock()
    llm.complete_json.return_value = _valid_synth()
    synth = AISynthesizer(llm)
    issue = Issue(
        file_path="x.py", line=1, column=0, message="problem",
        code="E1", severity=Severity.WARNING, reasoning="custom reasoning here",
    )
    synth.synthesize([issue])

    user_msg = llm.complete_json.call_args[1].get("user") or llm.complete_json.call_args[0][1]
    assert "custom reasoning here" in user_msg
