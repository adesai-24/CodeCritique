import glob
import os
import sys
from typing import List, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from critique.git_utils import get_changed_files
from critique.checkers.base import Issue
from critique.checkers.lint import RuffChecker
from critique.checkers.security import BanditChecker
from critique.checkers.types import MypyChecker
from critique.checkers.coverage import CoverageChecker
from critique.report import print_report, print_ai_report
from critique.persistence import fallback_synthesis, save_report

console = Console()


def save_report_notice(synth: dict, issues: List[Issue]) -> None:
    """Persist a review report without letting storage errors fail a check run."""
    try:
        saved = save_report(synth, issues)
    except Exception as exc:
        console.print(f"[yellow]Could not save review report: {exc}[/yellow]")
        return
    console.print(f"[dim]Saved review as {saved['id']}[/dim]")


def extract_code_context(file_path: str, line: int, context_lines: int = 3) -> List[str]:
    """Return a few lines of source around `line` for display in reports."""
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


def get_target_files(
    incremental: bool = True,
    custom_files: Optional[List[str]] = None,
) -> List[str]:
    """Resolve which files to check based on the active mode."""
    bin_dir = os.path.join(sys.prefix, "Scripts" if os.name == "nt" else "bin")
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]

    if custom_files:
        files = [os.path.abspath(f) for f in custom_files]
        console.print(f"[bold blue]Checking {len(files)} target file(s)...[/bold blue]")
        return files

    if incremental:
        files = get_changed_files()
        if not files:
            console.print("[bold green]No python files changed. Skipping checks.[/bold green]")
            return []
        console.print(f"[bold blue]Checking {len(files)} changed file(s)...[/bold blue]")
        return files

    files = glob.glob("**/*.py", recursive=True)
    files = [f for f in files if "site-packages" not in f and "venv" not in f and ".venv" not in f]
    return [os.path.abspath(f) for f in files]


def scan_files(files: List[str], use_ai: bool = True) -> List[Issue]:
    """
    Run all configured checkers on the provided file list.

    When use_ai=True, appends AICriticChecker if Ollama is reachable.
    Degrades gracefully to static-only mode if Ollama is offline.
    """
    if not files:
        return []

    checkers = [
        RuffChecker(),
        BanditChecker(),
        MypyChecker(),
        CoverageChecker(),
    ]

    if use_ai:
        try:
            from critique.ai.client import LLMClient
            from critique.checkers.ai_critic import AICriticChecker
            llm = LLMClient()
            if llm.is_available():
                checkers.append(AICriticChecker(llm))
            else:
                console.print(
                    "[yellow]Ollama not reachable — skipping AI Critic. "
                    "Start it with: ollama serve[/yellow]"
                )
        except Exception as exc:
            console.print(f"[yellow]AI Critic unavailable: {exc}[/yellow]")

    all_issues: List[Issue] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        for checker in checkers:
            task = progress.add_task(
                description=f"Running {checker.name}...", total=None
            )
            new_issues = checker.run(files)
            enriched = [
                issue._replace(code_context=extract_code_context(issue.file_path, issue.line))
                for issue in new_issues
            ]
            all_issues.extend(enriched)
            progress.remove_task(task)

    return all_issues


def run_all_checks(
    incremental: bool = True,
    custom_files: Optional[List[str]] = None,
    use_ai: bool = True,
) -> bool:
    """
    Orchestrate the full check pipeline.

    Returns True if the push is allowed (no FATAL issues), False otherwise.
    """
    files = get_target_files(incremental, custom_files)
    if not files and incremental and not custom_files:
        return True
    if not files and not incremental:
        console.print("[yellow]No python files found.[/yellow]")
        return True

    all_issues = scan_files(files, use_ai=use_ai)

    if use_ai:
        try:
            from critique.ai.client import LLMClient
            from critique.ai.enricher import enrich_issues
            from critique.ai.synthesizer import AISynthesizer
            llm = LLMClient()
            if llm.is_available():
                if all_issues:
                    all_issues = enrich_issues(all_issues, llm)
                synth = AISynthesizer(llm).synthesize(all_issues)
                save_report_notice(synth, all_issues)
                return print_ai_report(synth, all_issues)
            else:
                console.print("[yellow]Ollama not reachable — falling back to basic report.[/yellow]")
        except Exception as exc:
            console.print(f"[yellow]AI report failed ({exc}) — falling back to basic report.[/yellow]")

    save_report_notice(fallback_synthesis(all_issues), all_issues)
    return print_report(all_issues)
