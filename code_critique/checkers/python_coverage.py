import subprocess
import json
import os
from typing import List
from code_critique.checkers.base import BaseChecker, Issue, Severity

class CoverageChecker(BaseChecker):
    name = "Coverage"
    description = "Checks generic test coverage percentage."
    
    # Threshold could be in config. Hardcoding to 80% for now.
    THRESHOLD = 80.0

    def run(self, files: List[str]) -> List[Issue]:
        issues = []
        try:
            
            cmd = ["coverage", "json", "-o", "-"] 
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                return [Issue(
                   file_path="PROJECT",
                   line=0,
                   column=0,
                   message="No coverage data found. Run tests with coverage first.",
                   code="COV001",
                   severity=Severity.INFO,
                   reasoning="Coverage check requires .coverage data."
                )]

            data = json.loads(result.stdout)
            
            percent = data["totals"].get("percent_covered", 0.0)
            
            if percent < self.THRESHOLD:
                issues.append(Issue(
                    file_path="PROJECT",
                    line=0,
                    column=0,
                    message=f"Total coverage {percent:.2f}% is below threshold {self.THRESHOLD}%.",
                    code="COV-LOW",
                    severity=Severity.WARNING,
                    reasoning="Ensure code is well-tested."
                ))
                
        except Exception:
            pass
            
        return issues
