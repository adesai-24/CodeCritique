import os
import stat
import subprocess
import sys
from pathlib import Path
from rich import print
from typing import List

def get_changed_files(target_branch: str = "origin/main") -> List[str]:
    try:
        cmd = ["git", "diff", "--name-only", "--diff-filter=ACM", f"{target_branch}...HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = result.stdout.strip().splitlines()
        abs_files = [os.path.abspath(f) for f in files if f.endswith(".py")]
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
    "{executable}" -m code_critique.cli check --incremental
    """

    with open(hook_path, "w") as f:
        f.write(script_content)

    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC)
    
    print(f"[bold green]Hook installed at {hook_path}![/bold green]")
