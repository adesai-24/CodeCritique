import subprocess
import json
from typing import List
from code_critique.checkers.base import BaseChecker, Issue, Severity

class BanditChecker(BaseChecker):
    name = "Bandit (Security)"
    description = "Common security issues finder."

    def run(self, files: List[str]) -> List[Issue]:
        if not files:
            return []
        
        issues = []
        try:
            cmd = ["bandit", "-f", "json", "-q"] + files
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            output = result.stdout
            if not output.strip():
                return []

            data = json.loads(output)
            results = data.get("results", [])
            
            for item in results:
                sev_str = item.get("issue_severity", "LOW").upper()

                severity = Severity.WARNING
                if sev_str == "HIGH":
                    severity = Severity.FATAL
                elif sev_str == "MEDIUM":
                    severity = Severity.WARNING
                
                issues.append(Issue(
                    file_path=item.get("filename"),
                    line=item.get("line_number", 0),
                    column=0,
                    message=item.get("issue_text"),
                    code=item.get("test_id"),
                    severity=severity,
                    reasoning=f"Security risk detected ({sev_str})."
                ))
                
        except Exception as e:
            console.print(f"[bold red]Error running Bandit: {str(e)}[/bold red]")
            pass
        return issues
