import subprocess
import sys
from typing import List
from critique.checkers.base import BaseChecker, Issue, Severity


class FormatChecker(BaseChecker):
    """Flags files that `ruff format` would rewrite.

    Formatting never blocks a push; each finding is INFO with a one-command
    fix so the report stays actionable.
    """

    name = "Format"
    description = "Checks code formatting via ruff format."

    def run(self, files: List[str]) -> List[Issue]:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return []

        issues = []
        try:
            cmd = [sys.executable, "-m", "ruff", "format", "--check"] + py_files
            result = subprocess.run(cmd, capture_output=True, text=True)
            prefix = "Would reformat:"
            for line in result.stdout.splitlines():
                # Output: "Would reformat: path/to/file.py"
                # Slice past the prefix (not split on ":") so Windows drive
                # letters like C:\ survive intact.
                if line.startswith(prefix):
                    path = line[len(prefix):].strip()
                    issues.append(Issue(
                        file_path=path,
                        line=1,
                        column=0,
                        message="File is not formatted consistently.",
                        code="FMT001",
                        severity=Severity.INFO,
                        reasoning="Consistent formatting keeps diffs small and code easy to read.",
                        suggested_fix="Run `codecritique fix` to reformat automatically.",
                    ))
        except Exception:
            pass

        return issues
