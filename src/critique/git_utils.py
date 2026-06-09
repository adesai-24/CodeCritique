import os
import stat
import subprocess
import sys
from pathlib import Path
from rich import print
from typing import List

from critique.languages import is_supported_for_choice

def get_current_branch() -> str:
    """Return the current git branch name, or '' outside a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_changed_files(target_branch: str = "origin/main", language: str = "auto") -> List[str]:
    try:
        cmd = ["git", "diff", "--name-only", "--diff-filter=ACM", f"{target_branch}...HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = result.stdout.strip().splitlines()
        abs_files = [os.path.abspath(f) for f in files if is_supported_for_choice(f, language)]
        return [f for f in abs_files if os.path.exists(f)]
    except subprocess.CalledProcessError:
        return []

def install_pre_push_hook():
    """
    Creates the pre-push hook in .git/hooks/
    """
    hooks_dir = Path(".git/hooks")
    if not hooks_dir.exists():
        print("[red]Not a git repository (or no hooks dir). Run inside a git repo.[/red]")
        return

    hook_path = hooks_dir / "pre-push"
    executable = sys.executable
    
    script_content = f"""#!/bin/sh
    # CodeCritique Hook
    echo "Running CodeCritique..."
    # Run check. If it fails (exit 1), the push stops.
    "{executable}" -m critique.cli check --incremental
    """

    with open(hook_path, "w") as f:
        f.write(script_content)

    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC)
    
    print(f"[bold green]Hook installed at {hook_path}![/bold green]")
