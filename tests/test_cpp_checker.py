"""Unit tests for the C/C++ static checker (cppcheck) — subprocess is mocked."""

import subprocess
from unittest.mock import MagicMock, patch

from critique.checkers.base import Severity
from critique.checkers.cpp import CppcheckChecker, _DELIM


def _cppcheck_result(stderr="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = ""
    r.stderr = stderr
    r.returncode = returncode
    return r


def _line(file, line, col, sev, code, msg):
    return _DELIM.join([file, str(line), str(col), sev, code, msg])


class TestCppcheckChecker:
    def test_no_cpp_files_returns_empty(self):
        # Python files must not trigger cppcheck at all.
        with patch("subprocess.run") as run:
            issues = CppcheckChecker().run(["main.py", "notes.txt"])
        assert issues == []
        run.assert_not_called()

    def test_error_maps_to_fatal(self):
        out = _line("a.c", 10, 3, "error", "nullPointer", "Null pointer dereference")
        with patch("subprocess.run", return_value=_cppcheck_result(out)):
            issues = CppcheckChecker().run(["a.c"])
        assert len(issues) == 1
        assert issues[0].severity == Severity.FATAL
        assert issues[0].line == 10
        assert issues[0].column == 3
        assert issues[0].code == "nullPointer"

    def test_style_maps_to_info_and_warning_maps_to_warning(self):
        out = "\n".join([
            _line("a.cpp", 1, 0, "style", "unusedVar", "Unused variable x"),
            _line("a.cpp", 2, 0, "warning", "uninitvar", "Uninitialized y"),
            _line("a.cpp", 3, 0, "performance", "passByValue", "Pass by reference"),
        ])
        with patch("subprocess.run", return_value=_cppcheck_result(out)):
            issues = CppcheckChecker().run(["a.cpp"])
        sev_by_code = {i.code: i.severity for i in issues}
        assert sev_by_code["unusedVar"] == Severity.INFO
        assert sev_by_code["uninitvar"] == Severity.WARNING
        assert sev_by_code["passByValue"] == Severity.WARNING

    def test_missing_cppcheck_degrades_gracefully(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("cppcheck")):
            issues = CppcheckChecker().run(["a.c"])
        assert issues == []

    def test_unparseable_lines_are_ignored(self):
        out = "Checking a.c ...\nsome noise without delimiters\n"
        with patch("subprocess.run", return_value=_cppcheck_result(out)):
            issues = CppcheckChecker().run(["a.c"])
        assert issues == []

    def test_only_cpp_files_passed_to_cppcheck(self):
        out = _line("a.c", 1, 0, "warning", "w", "msg")
        with patch("subprocess.run", return_value=_cppcheck_result(out)) as run:
            CppcheckChecker().run(["a.c", "b.py", "c.hpp"])
        cmd = run.call_args[0][0]
        assert "a.c" in cmd
        assert "c.hpp" in cmd
        assert "b.py" not in cmd
