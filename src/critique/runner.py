from typing import List
import os
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from critique.git_utils import get_changed_files
from critique.checkers.base import Issue
from critique.checkers.lint import RuffChecker
from critique.checkers.security import BanditChecker
from critique.checkers.types import MypyChecker
from critique.checkers.coverage import CoverageChecker
from critique.report import print_report

def extract_code_context(file_path: str, line: int, context_lines: int = 3) -> List[str]:
    """
    Extracts a few lines of code around the specified line number.
    """
    if not os.path.exists(file_path):
        return []
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        start = max(0, line - context_lines - 1)
        end = min(len(lines), line + context_lines)
        
        return lines[start:end]
    except Exception:
        return []

console = Console()

def run_all_checks(incremental: bool = True, custom_files: List[str] = None) -> bool:
    """
    Orchestrates the execution of all enabled checkers.
    Returns True if execution flows allow a push (Pass or Warnings only), False if Fatal.
    """
    import sys
    import os
    
    bin_dir = os.path.join(sys.prefix, 'Scripts' if os.name == 'nt' else 'bin')
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]

    if custom_files:
        files = [os.path.abspath(f) for f in custom_files]
        console.print(f"[bold blue]Checking {len(files)} target file(s)...[/bold blue]")
    elif incremental:
        files = get_changed_files()
        if not files:
            console.print("[bold green]No python files changed. Skipping checks.[/bold green]")
            return True
        console.print(f"[bold blue]Checking {len(files)} changed file(s)...[/bold blue]")
    else:
        import glob
        files = glob.glob("**/*.py", recursive=True)
        files = [f for f in files if "site-packages" not in f and "venv" not in f and ".venv" not in f]
        files = [os.path.abspath(f) for f in files]

        if not files:
             console.print("[yellow]No python files found.[/yellow]")
             return True
        console.print(f"[bold blue]Full scan: Checking {len(files)} file(s)...[/bold blue]")

    checkers = [
        RuffChecker(),
        BanditChecker(),
        MypyChecker(),
        CoverageChecker()
    ]

    all_issues: List[Issue] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        for checker in checkers:
            task = progress.add_task(description=f"Running {checker.name}...", total=None)
            
            new_issues = checker.run(files)
            
            enriched_issues = []
            for issue in new_issues:
                context = extract_code_context(issue.file_path, issue.line)
                enriched_issues.append(issue._replace(code_context=context))
            
            all_issues.extend(enriched_issues)
            
            progress.remove_task(task)

    return print_report(all_issues)
