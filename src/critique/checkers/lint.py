import os
import subprocess
import json
import sys
from typing import List
from critique.checkers.base import BaseChecker, Issue, Severity

# Curated rule set used when the target project has no ruff config of its own.
# Goes well beyond ruff's defaults (E4/E7/E9/F):
#   E/W  pycodestyle errors + warnings        F    pyflakes
#   B    bugbear (likely bugs)                C4   comprehension rewrites
#   SIM  simplifiable code                    UP   modern Python idioms (pyupgrade)
#   C90  mccabe complexity                    RUF  ruff-native checks
CURATED_RULES = "E,W,F,B,C4,SIM,UP,C90,RUF"

# Rule prefixes that indicate likely runtime bugs, not just style.
_BUG_PREFIXES = ("B", "F8")


def project_has_ruff_config(cwd: str = ".") -> bool:
    """True if the project being checked carries its own ruff configuration.

    When it does, we respect it instead of imposing the curated rule set.
    """
    for name in ("ruff.toml", ".ruff.toml"):
        if os.path.exists(os.path.join(cwd, name)):
            return True
    try:
        with open(os.path.join(cwd, "pyproject.toml"), encoding="utf-8") as f:
            return "[tool.ruff" in f.read()
    except OSError:
        return False


class RuffChecker(BaseChecker):
    name = "Ruff (Lint)"
    description = "Fast Python linter."

    def run(self, files: List[str]) -> List[Issue]:
        files = [f for f in files if f.endswith((".py", ".pyi"))]
        if not files:
            return []

        issues = []
        try:
            # `python -m ruff` so the tool is found even when the venv's
            # console-script launchers are broken (e.g. after a venv move).
            cmd = [sys.executable, "-m", "ruff", "check", "--output-format=json"]
            if not project_has_ruff_config():
                cmd.append(f"--select={CURATED_RULES}")
            cmd += files
            result = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(result.stdout)

            for item in data:
                code = item.get("code") or "UNKNOWN"
                message = item.get("message", "")
                if code.startswith("E9") or "SyntaxError" in message:
                    severity = Severity.FATAL
                elif code.startswith(_BUG_PREFIXES):
                    severity = Severity.WARNING
                elif code.startswith(("SIM", "UP", "C4", "RUF", "W")):
                    # Readability / modernization hints: never block, just inform.
                    severity = Severity.INFO
                else:
                    severity = Severity.WARNING

                issues.append(Issue(
                    file_path=item.get("filename"),
                    line=item["location"]["row"],
                    column=item["location"]["column"],
                    message=message,
                    code=code,
                    severity=severity,
                    reasoning="Checking against coding standards."
                ))

        except json.JSONDecodeError:
            pass
        except Exception:
            pass

        return issues
