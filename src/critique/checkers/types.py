import subprocess
import re
from typing import List
from critique.checkers.base import BaseChecker, Issue, Severity

class MypyChecker(BaseChecker):
    name = "Mypy (Types)"
    description = "Static type checker."

    def run(self, files: List[str]) -> List[Issue]:
        if not files:
            return []
        
        issues = []
        try:
            cmd = ["mypy", "--show-column-numbers", "--no-error-summary"] + files
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Output format: file:line:col: error: message
            # e.g. main.py:10:5: error: Incompatible types...
            
            # Regex to parse
            pattern = re.compile(r"^(.*?):(\d+):(\d+):\s*error:\s*(.*)$")
            
            for line in result.stdout.splitlines():
                match = pattern.match(line)
                if match:
                    filename, line_num, col, msg = match.groups()
                    
                    issues.append(Issue(
                        file_path=filename,
                        line=int(line_num),
                        column=int(col),
                        message=msg.strip(),
                        code="TYPE",
                        severity=Severity.FATAL,
                        reasoning="Type mismatch found."
                    ))
                    
        except Exception:
            pass
            
        return issues
