import tempfile
from pathlib import Path

from critique.checkers.base import Issue, Severity
from critique.runner import extract_code_context, get_target_files


def test_extract_code_context_missing_file_returns_empty():
    assert extract_code_context("does-not-exist.py", 1) == []


def test_extract_code_context_returns_expected_lines():
    with tempfile.TemporaryDirectory() as tmp:
        file_path = Path(tmp) / "sample.py"
        file_path.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
        result = extract_code_context(str(file_path), 3, context_lines=1)
    assert result == ["line2\n", "line3\n", "line4\n"]


def test_get_target_files_custom_files_returns_abs_paths():
    with tempfile.TemporaryDirectory() as tmp:
        file_one = Path(tmp) / "a.py"
        file_two = Path(tmp) / "b.py"
        file_one.write_text("x = 1\n", encoding="utf-8")
        file_two.write_text("y = 2\n", encoding="utf-8")
        result = get_target_files(custom_files=[str(file_one), str(file_two)])
        assert result == [str(file_one.resolve()), str(file_two.resolve())]


def test_get_target_files_incremental_no_changes(monkeypatch):
    from critique import runner

    monkeypatch.setattr(runner, "get_changed_files", lambda: [])

    assert runner.get_target_files(incremental=True, custom_files=None) == []


def test_scan_files_enriches_code_context(monkeypatch):
    from critique import runner

    with tempfile.TemporaryDirectory() as tmp:
        file_path = Path(tmp) / "sample.py"
        file_path.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")

        class FakeChecker:
            name = "Fake"
            description = "Fake"

            def run(self, files):
                return [
                    Issue(
                        file_path=str(file_path),
                        line=2,
                        column=0,
                        message="message",
                        code="TST",
                        severity=Severity.INFO,
                    )
                ]

        # scan_files uses _CHECKER_NAMES dict, so patch that
        monkeypatch.setattr(
            runner,
            "_CHECKER_NAMES",
            {"ruff": FakeChecker, "bandit": FakeChecker, "mypy": FakeChecker, "coverage": FakeChecker},
        )

        issues = runner.scan_files([str(file_path)], use_ai=False)

    assert len(issues) == 4
    assert all(issue.code_context for issue in issues)
    assert all("b = 2" in "".join(issue.code_context) for issue in issues)


def test_run_all_checks_incremental_no_files_returns_true(monkeypatch):
    from critique import runner

    monkeypatch.setattr(runner, "get_target_files", lambda incremental, custom_files: [])

    assert runner.run_all_checks(incremental=True, custom_files=None, use_ai=False) is True


def test_run_all_checks_uses_print_report(monkeypatch):
    from critique import runner

    fake_issue = Issue(
        file_path="x.py",
        line=1,
        column=0,
        message="message",
        code="CODE",
        severity=Severity.WARNING,
    )

    monkeypatch.setattr(runner, "get_target_files", lambda incremental, custom_files: ["x.py"])

    def fake_scan(files, use_ai=True, skip_checkers=None, ai_only=False, config=None):
        return [fake_issue]

    monkeypatch.setattr(runner, "scan_files", fake_scan)

    captured = {}

    def fake_print_report(issues):
        captured["issues"] = issues
        return False

    monkeypatch.setattr(runner, "print_report", fake_print_report)

    result = runner.run_all_checks(incremental=True, custom_files=None, use_ai=False)

    assert result is False
    assert captured["issues"] == [fake_issue]
