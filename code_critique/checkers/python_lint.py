import subprocess
import json
from typing import List
from code_critique.checkers.base import BaseChecker, Issue, Severity

class RuffChecker(BaseChecker):
    name = "Ruff (Lint)"
    description = "Fast Python linter."

    def run(self, files: List[str]) -> List[Issue]:
        if not files:
            return []
        
        issues = []
        try:
            cmd = ["ruff", "check", "--output-format=json"] + files
            result = subprocess.run(cmd, capture_output=True, text=True)            
            data = json.loads(result.stdout)
            
            for item in data:
                code = item.get("code", "UNKNOWN")
                severity = Severity.WARNING
                if code.startswith("E9") or "SyntaxError" in item.get("message", ""):
                    severity = Severity.FATAL
                
                issues.append(Issue(
                    file_path=item.get("filename"),
                    line=item["location"]["row"],
                    column=item["location"]["column"],
                    message=item["message"],
                    code=code,
                    severity=severity,
                    reasoning="Checking against coding standards."
                ))
                
        except json.JSONDecodeError:
            pass
        except Exception as e:
            pass
            
        return issues
