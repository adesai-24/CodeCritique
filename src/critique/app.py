import webview
import sys
import os
import json
from typing import List
from critique.runner import get_target_files, scan_files
from critique.checkers.base import Issue

class Api:
    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def get_issues(self):
        """
        Called from React to get initial issues.
        """
        files = get_target_files(incremental=True)
        issues = scan_files(files)
        return [self._serialize_issue(i) for i in issues]

    def rescan(self):
        """
        Called from React when user clicks Rescan.
        """
        files = get_target_files(incremental=True) 
        issues = scan_files(files)
        return [self._serialize_issue(i) for i in issues]

    def open_file(self, file_path, line=1):
        """
        Opens the file in the default editor (VS Code preference).
        """
        try:
            import subprocess
            subprocess.Popen(["code", "--goto", f"{file_path}:{line}"], shell=True)
        except Exception as e:
            print(f"Failed to open editor: {e}")

    def _serialize_issue(self, issue: Issue):
        try:
            rel_file = os.path.relpath(issue.file_path)
        except Exception:
            rel_file = issue.file_path

        return {
            "severity": issue.severity.value,
            "file": rel_file,
            "line": issue.line,
            "column": issue.column,
            "message": issue.message,
            "code": issue.code,
            "reasoning": issue.reasoning,
            "code_context": issue.code_context,
            "context_start_line": max(1, issue.line - 3)
        }

def start_app(dev=False):
    api = Api()
    
    if dev:
        url = "http://localhost:5173"
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        dist_path = os.path.join(base_dir, "../web/dist/index.html")
        url = os.path.abspath(dist_path)
        
        if not os.path.exists(url):
             print(f"Error: Could not find build at {url}. Run 'npm run build' in src/web first.")
             sys.exit(1)

    window = webview.create_window('CodeCritique', url, js_api=api, width=1200, height=800)
    api.set_window(window)
    webview.start(debug=dev) 

if __name__ == '__main__':
    dev_mode = "--dev" in sys.argv
    start_app(dev=dev_mode)
