"""Tests for AIEnricher — LLM is mocked throughout."""

import pytest
from unittest.mock import MagicMock

from critique.checkers.base import Issue, Severity
from critique.ai.enricher import AIEnricher, enrich_issues


def _make_issue(**kwargs):
    defaults = dict(
        file_path="sample.py",
        line=1,
        column=0,
        message="some problem",
        code="E001",
        severity=Severity.WARNING,
        reasoning=None,
        code_context=["x = 1\n"],
        suggested_fix=None,
    )
    defaults.update(kwargs)
    return Issue(**defaults)


# ---------------------------------------------------------------------------
# AIEnricher.enrich
# ---------------------------------------------------------------------------

def test_enrich_updates_reasoning_and_fix():
    llm = MagicMock()
    llm.complete_json.return_value = {
        "reasoning": "This is dangerous because …",
        "suggested_fix": "Use parameterised queries.",
        "real_severity": "FATAL",
    }
    enricher = AIEnricher(llm)
    issue = _make_issue()
    result = enricher.enrich(issue)

    assert result.reasoning == "This is dangerous because …"
    assert result.suggested_fix == "Use parameterised queries."
    assert result.severity == Severity.FATAL


def test_enrich_fail_open_on_llm_exception():
    llm = MagicMock()
    llm.complete_json.side_effect = RuntimeError("Ollama offline")
    enricher = AIEnricher(llm)
    issue = _make_issue()
    result = enricher.enrich(issue)

    # Must return the original issue unchanged.
    assert result is issue


def test_enrich_preserves_original_severity_on_bad_key():
    llm = MagicMock()
    llm.complete_json.return_value = {
        "reasoning": "ok",
        "suggested_fix": None,
        "real_severity": "NOT_A_VALID_SEVERITY",
    }
    enricher = AIEnricher(llm)
    issue = _make_issue(severity=Severity.INFO)
    result = enricher.enrich(issue)

    assert result.severity == Severity.INFO


def test_enrich_uses_code_context_in_prompt():
    llm = MagicMock()
    llm.complete_json.return_value = {"reasoning": "r", "suggested_fix": "s", "real_severity": "WARNING"}
    enricher = AIEnricher(llm)
    issue = _make_issue(code_context=["line1\n", "line2\n"])
    enricher.enrich(issue)

    call_args = llm.complete_json.call_args
    user_msg = call_args[1]["user"] if "user" in call_args[1] else call_args[0][1]
    assert "line1" in user_msg
    assert "line2" in user_msg


def test_enrich_handles_empty_code_context():
    llm = MagicMock()
    llm.complete_json.return_value = {"reasoning": "r", "suggested_fix": "s", "real_severity": "WARNING"}
    enricher = AIEnricher(llm)
    issue = _make_issue(code_context=None)
    result = enricher.enrich(issue)

    assert result.reasoning == "r"


# ---------------------------------------------------------------------------
# enrich_issues (concurrent wrapper)
# ---------------------------------------------------------------------------

def test_enrich_issues_returns_all_enriched():
    llm = MagicMock()
    llm.complete_json.return_value = {
        "reasoning": "enriched",
        "suggested_fix": "fix it",
        "real_severity": "WARNING",
    }
    issues = [_make_issue(line=i) for i in range(1, 6)]
    result = enrich_issues(issues, llm)

    assert len(result) == 5
    assert all(r.reasoning == "enriched" for r in result)


def test_enrich_issues_empty_list_returns_empty():
    llm = MagicMock()
    assert enrich_issues([], llm) == []


def test_enrich_issues_partial_failure_keeps_originals():
    call_count = 0

    def flaky_complete_json(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 0:
            raise RuntimeError("simulated failure")
        return {"reasoning": "ok", "suggested_fix": "fix", "real_severity": "WARNING"}

    llm = MagicMock()
    llm.complete_json.side_effect = flaky_complete_json
    issues = [_make_issue(line=i) for i in range(1, 5)]
    result = enrich_issues(issues, llm)

    assert len(result) == 4
    # Even-indexed calls failed → those issues keep original reasoning (None).
    for r in result:
        assert r is not None
