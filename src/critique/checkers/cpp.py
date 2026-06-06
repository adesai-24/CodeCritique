"""
CppcheckChecker — static analysis for C/C++ via the ``cppcheck`` tool.

This is the C/C++ analogue of the Ruff/Bandit/Mypy checkers: it shells out to a
well-established external analyser, parses its machine-readable output, and maps
findings onto CodeCritique's :class:`Issue` model.

``cppcheck`` is an optional, language-specific dependency (it is not a Python
package, so it can't live in ``pyproject.toml``).  Following the same
fail-soft contract as the other checkers, this one degrades gracefully:

* no C/C++ files in the batch  -> returns ``[]`` without invoking anything,
* ``cppcheck`` not installed    -> returns ``[]`` (the AI critic still runs),
* any parsing/runtime error     -> returns ``[]`` rather than aborting the run.
"""

import subprocess
from typing import List

from critique.checkers.base import BaseChecker, Issue, Severity
from critique.languages import CPP

# A delimiter that won't appear in source paths or messages, so we can parse
# cppcheck's --template output unambiguously with a simple split.
_DELIM = "||CC||"

# cppcheck severity string -> CodeCritique severity.
_SEVERITY_MAP = {
    "error": Severity.FATAL,
    "warning": Severity.WARNING,
    "performance": Severity.WARNING,
    "portability": Severity.WARNING,
    "style": Severity.INFO,
    "information": Severity.INFO,
    "debug": Severity.INFO,
}


class CppcheckChecker(BaseChecker):
    name = "Cppcheck (C/C++)"
    description = "Static analysis for C/C++ source (requires the cppcheck tool)."

    def run(self, files: List[str]) -> List[Issue]:
        cpp_files = [f for f in files if f.lower().endswith(CPP.extensions)]
        if not cpp_files:
            return []

        template = _DELIM.join(
            ["{file}", "{line}", "{column}", "{severity}", "{id}", "{message}"]
        )
        cmd = [
            "cppcheck",
            "--enable=warning,style,performance,portability",
            "--inline-suppr",   # honour // cppcheck-suppress comments
            "--quiet",          # only report findings, not progress
            f"--template={template}",
        ] + cpp_files

        issues: List[Issue] = []
        try:
            # cppcheck writes findings to stderr; stdout stays empty.
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            # cppcheck isn't installed — stay silent, like the other checkers do
            # when their tool is missing, so the rest of the pipeline still runs.
            return []
        except Exception:
            return []

        for line in result.stderr.splitlines():
            parts = line.split(_DELIM)
            if len(parts) != 6:
                continue
            file_path, line_no, col_no, sev_str, code, message = parts
            severity = _SEVERITY_MAP.get(sev_str.strip().lower(), Severity.INFO)
            issues.append(
                Issue(
                    file_path=file_path,
                    line=_to_int(line_no),
                    column=_to_int(col_no),
                    message=message.strip(),
                    code=code.strip() or "cppcheck",
                    severity=severity,
                    reasoning=f"cppcheck flagged a {sev_str.strip().lower()} issue.",
                )
            )
        return issues


def _to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
