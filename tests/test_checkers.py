"""Unit tests for static analysis checkers — subprocess calls are mocked."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from critique.checkers.base import Severity
from critique.checkers.lint import RuffChecker
from critique.checkers.security import BanditChecker
from critique.checkers.types import MypyChecker
from critique.checkers.coverage import CoverageChecker
from critique.checkers.ai_critic import AICriticChecker


def _run_result(stdout="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = ""
    r.returncode = returncode
    return r


# ---------------------------------------------------------------------------
# RuffChecker
# ---------------------------------------------------------------------------

class TestRuffChecker:
    def test_empty_files_returns_no_issues(self):
        assert RuffChecker().run([]) == []

    def test_parses_warning_issue(self, tmp_path):
        ruff_output = json.dumps([
            {
                "filename": "sample.py",
                "location": {"row": 5, "column": 2},
                "message": "unused import",
                "code": "F401",
            }
        ])
        with patch("subprocess.run", return_value=_run_result(ruff_output)):
            issues = RuffChecker().run(["sample.py"])

        assert len(issues) == 1
        assert issues[0].line == 5
        assert issues[0].code == "F401"
        assert issues[0].severity == Severity.WARNING

    def test_syntax_error_is_fatal(self, tmp_path):
        ruff_output = json.dumps([
            {
                "filename": "broken.py",
                "location": {"row": 1, "column": 0},
                "message": "SyntaxError: invalid syntax",
                "code": "E902",
            }
        ])
        with patch("subprocess.run", return_value=_run_result(ruff_output)):
            issues = RuffChecker().run(["broken.py"])

        assert issues[0].severity == Severity.FATAL

    def test_empty_ruff_output_returns_no_issues(self):
        with patch("subprocess.run", return_value=_run_result("[]")):
            issues = RuffChecker().run(["clean.py"])
        assert issues == []

    def test_invalid_json_returns_no_issues(self):
        with patch("subprocess.run", return_value=_run_result("not json")):
            issues = RuffChecker().run(["f.py"])
        assert issues == []


# ---------------------------------------------------------------------------
# BanditChecker
# ---------------------------------------------------------------------------

class TestBanditChecker:
    def test_empty_files_returns_no_issues(self):
        assert BanditChecker().run([]) == []

    def test_high_severity_maps_to_fatal(self):
        bandit_output = json.dumps({
            "results": [
                {
                    "filename": "holes.py",
                    "line_number": 10,
                    "issue_text": "Use of exec detected.",
                    "test_id": "B102",
                    "issue_severity": "HIGH",
                }
            ]
        })
        with patch("subprocess.run", return_value=_run_result(bandit_output)):
            issues = BanditChecker().run(["holes.py"])

        assert issues[0].severity == Severity.FATAL

    def test_medium_severity_maps_to_warning(self):
        bandit_output = json.dumps({
            "results": [
                {
                    "filename": "holes.py",
                    "line_number": 5,
                    "issue_text": "Hardcoded password.",
                    "test_id": "B105",
                    "issue_severity": "MEDIUM",
                }
            ]
        })
        with patch("subprocess.run", return_value=_run_result(bandit_output)):
            issues = BanditChecker().run(["holes.py"])

        assert issues[0].severity == Severity.WARNING

    def test_empty_stdout_returns_no_issues(self):
        with patch("subprocess.run", return_value=_run_result("")):
            issues = BanditChecker().run(["f.py"])
        assert issues == []

    def test_no_results_key_returns_no_issues(self):
        with patch("subprocess.run", return_value=_run_result(json.dumps({}))):
            issues = BanditChecker().run(["f.py"])
        assert issues == []


# ---------------------------------------------------------------------------
# MypyChecker
# ---------------------------------------------------------------------------

class TestMypyChecker:
    def test_empty_files_returns_no_issues(self):
        assert MypyChecker().run([]) == []

    def test_parses_type_error_line(self):
        mypy_output = 'type_errors.py:10:5: error: Argument 1 to "double" has incompatible type\n'
        with patch("subprocess.run", return_value=_run_result(mypy_output)):
            issues = MypyChecker().run(["type_errors.py"])

        assert len(issues) == 1
        assert issues[0].line == 10
        assert issues[0].column == 5
        assert issues[0].severity == Severity.FATAL
        assert issues[0].code == "TYPE"

    def test_non_error_lines_are_ignored(self):
        mypy_output = "Found 1 error in 1 file (checked 1 source file)\n"
        with patch("subprocess.run", return_value=_run_result(mypy_output)):
            issues = MypyChecker().run(["f.py"])
        assert issues == []

    def test_multiple_errors_all_parsed(self):
        mypy_output = (
            "a.py:1:1: error: Msg one\n"
            "b.py:3:4: error: Msg two\n"
        )
        with patch("subprocess.run", return_value=_run_result(mypy_output)):
            issues = MypyChecker().run(["a.py", "b.py"])
        assert len(issues) == 2


# ---------------------------------------------------------------------------
# CoverageChecker
# ---------------------------------------------------------------------------

class TestCoverageChecker:
    def test_no_coverage_data_returns_info_issue(self):
        with patch("subprocess.run", return_value=_run_result("", returncode=1)):
            issues = CoverageChecker().run(["f.py"])

        assert len(issues) == 1
        assert issues[0].code == "COV001"
        assert issues[0].severity == Severity.INFO

    def test_low_coverage_returns_warning(self):
        cov_json = json.dumps({"totals": {"percent_covered": 55.0}})
        with patch("subprocess.run", return_value=_run_result(cov_json, returncode=0)):
            issues = CoverageChecker().run(["f.py"])

        assert len(issues) == 1
        assert issues[0].code == "COV-LOW"
        assert issues[0].severity == Severity.WARNING
        assert "55.00%" in issues[0].message

    def test_sufficient_coverage_returns_no_issues(self):
        cov_json = json.dumps({"totals": {"percent_covered": 90.0}})
        with patch("subprocess.run", return_value=_run_result(cov_json, returncode=0)):
            issues = CoverageChecker().run(["f.py"])
        assert issues == []

    def test_exception_returns_empty(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("coverage not found")):
            issues = CoverageChecker().run(["f.py"])
        assert issues == []


# ---------------------------------------------------------------------------
# AICriticChecker
# ---------------------------------------------------------------------------

class TestAICriticChecker:
    def test_non_python_files_are_skipped(self):
        llm = MagicMock()

        issues = AICriticChecker(llm).run(["README.md"])

        assert issues == []
        llm.complete_json.assert_not_called()

    def test_maps_llm_findings_to_issues(self, tmp_path):
        file_path = tmp_path / "buggy.py"
        file_path.write_text("def f():\n    return 1\n", encoding="utf-8")
        llm = MagicMock()
        llm.complete_json.return_value = {
            "findings": [
                {
                    "line": 2,
                    "title": "Suspicious return",
                    "severity": "WARNING",
                    "explanation": "This return looks incomplete.",
                }
            ]
        }

        issues = AICriticChecker(llm).run([str(file_path)])

        assert len(issues) == 1
        assert issues[0].file_path == str(file_path)
        assert issues[0].line == 2
        assert issues[0].code == "AI"
        assert issues[0].severity == Severity.WARNING

    def test_preserves_file_order_with_parallel_reviews(self, tmp_path, monkeypatch):
        first = tmp_path / "first.py"
        second = tmp_path / "second.py"
        first.write_text("a = 1\n", encoding="utf-8")
        second.write_text("b = 2\n", encoding="utf-8")
        monkeypatch.setenv("CODECRITIQUE_AI_CRITIC_WORKERS", "2")

        llm = MagicMock()

        def fake_complete_json(**kwargs):
            user = kwargs["user"]
            title = "first" if "a = 1" in user else "second"
            return {"findings": [{"line": 1, "title": title, "severity": "INFO"}]}

        llm.complete_json.side_effect = fake_complete_json

        issues = AICriticChecker(llm).run([str(first), str(second)])

        assert [issue.message for issue in issues] == ["first", "second"]
