import glob
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from critique.git_utils import get_changed_files, get_current_branch
from critique.checkers.base import Issue, Severity
from critique.checkers.lint import CURATED_RULES, RuffChecker, project_has_ruff_config
from critique.checkers.security import BanditChecker
from critique.checkers.types import MypyChecker
from critique.checkers.coverage import CoverageChecker
from critique.checkers.format import FormatChecker
from critique.report import print_report, print_ai_report
from critique.persistence import fallback_synthesis, issue_to_dict, save_report

# Status/progress messages go to stderr so stdout stays clean for reports
# and machine-readable JSON output.
console = Console(stderr=True)
_DEFAULT_CHECKER_WORKERS = 4


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def save_report_notice(synth: dict, issues: List[Issue]) -> Optional[Dict[str, Any]]:
    """Persist a review report without letting storage errors fail a check run."""
    try:
        saved = save_report(synth, issues)
    except Exception as exc:
        console.print(f"[yellow]Could not save review report: {exc}[/yellow]")
        return None
    console.print(f"[dim]Saved review as {saved['id']}[/dim]")
    return saved


def emit_json_report(
    files: List[str],
    issues: List[Issue],
    synth: Dict[str, Any],
    report_id: Optional[str] = None,
) -> bool:
    """Print a machine-readable result to stdout. Returns True if no FATAL issues."""
    passed = not any(issue.severity == Severity.FATAL for issue in issues)
    payload = {
        "passed": passed,
        "files_checked": files,
        "issue_count": len(issues),
        "issues": [issue_to_dict(issue) for issue in issues],
        "synthesis": synth,
        "report_id": report_id,
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return passed


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
        FormatChecker(),
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
        console=console,
    ) as progress:
        max_workers = max(
            1,
            min(
                len(checkers),
                _env_int("CODECRITIQUE_CHECKER_WORKERS", _DEFAULT_CHECKER_WORKERS),
            ),
        )
        tasks = {
            i: progress.add_task(description=f"Running {checker.name}...", total=None)
            for i, checker in enumerate(checkers)
        }
        results: List[List[Issue]] = [[] for _ in checkers]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(checker.run, files): i
                for i, checker in enumerate(checkers)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    console.print(
                        f"[yellow]{checkers[idx].name} failed: {exc}[/yellow]"
                    )
                finally:
                    progress.remove_task(tasks[idx])

        for checker_issues in results:
            all_issues.extend(
                issue._replace(code_context=extract_code_context(issue.file_path, issue.line))
                for issue in checker_issues
            )

    return all_issues


def build_review_context(
    files: List[str],
    incremental: bool,
    custom_files: Optional[List[str]],
) -> Dict[str, Any]:
    """Describe the current run so the AI review can speak to the situation."""
    if custom_files:
        mode = "a targeted review of specific files"
    elif incremental:
        mode = "a pre-push review of files changed on this branch"
    else:
        mode = "a full scan of the whole project"
    return {
        "project": os.path.basename(os.path.abspath(os.getcwd())),
        "branch": get_current_branch(),
        "mode": mode,
        "file_count": len(files),
    }


def fix_files(
    incremental: bool = True,
    custom_files: Optional[List[str]] = None,
    unsafe: bool = False,
) -> bool:
    """Auto-fix lint issues and reformat the target files in place.

    Runs `ruff check --fix` (safe fixes only unless unsafe=True) followed by
    `ruff format`. Returns False only if ruff itself could not be run.
    """
    import subprocess

    files = get_target_files(incremental, custom_files)
    if not files:
        return True

    try:
        fix_cmd = ["ruff", "check", "--fix", "--exit-zero"]
        if not project_has_ruff_config():
            fix_cmd.append(f"--select={CURATED_RULES}")
        if unsafe:
            fix_cmd.append("--unsafe-fixes")
        fix_result = subprocess.run(fix_cmd + files, capture_output=True, text=True)

        fmt_result = subprocess.run(
            ["ruff", "format"] + files, capture_output=True, text=True
        )
    except FileNotFoundError:
        console.print("[red]ruff is not installed or not on PATH.[/red]")
        return False

    summary = fix_result.stdout.strip().splitlines()
    if summary:
        console.print(f"[green]{summary[-1]}[/green]")
    fmt_summary = (fmt_result.stdout.strip() or fmt_result.stderr.strip()).splitlines()
    if fmt_summary:
        console.print(f"[green]{fmt_summary[-1]}[/green]")
    return True


def run_all_checks(
    incremental: bool = True,
    custom_files: Optional[List[str]] = None,
    use_ai: bool = True,
    emit_json: bool = False,
) -> bool:
    """
    Orchestrate the full check pipeline.

    Returns True if the push is allowed (no FATAL issues), False otherwise.
    With emit_json=True, prints a machine-readable JSON result to stdout
    instead of the rich terminal report.
    """
    files = get_target_files(incremental, custom_files)
    if not files:
        if not incremental:
            console.print("[yellow]No python files found.[/yellow]")
        if emit_json:
            return emit_json_report([], [], fallback_synthesis([]))
        return True

    all_issues = scan_files(files, use_ai=use_ai)

    synth: Optional[Dict[str, Any]] = None
    if use_ai:
        try:
            from critique.ai.client import LLMClient
            from critique.ai.enricher import enrich_issues
            from critique.ai.synthesizer import AISynthesizer
            llm = LLMClient()
            if llm.is_available():
                if all_issues:
                    all_issues = enrich_issues(all_issues, llm)
                context = build_review_context(files, incremental, custom_files)
                synth = AISynthesizer(llm).synthesize(all_issues, context=context)
            else:
                console.print("[yellow]Ollama not reachable — falling back to basic report.[/yellow]")
        except Exception as exc:
            console.print(f"[yellow]AI report failed ({exc}) — falling back to basic report.[/yellow]")

    ai_synthesis = synth is not None
    if synth is None:
        synth = fallback_synthesis(all_issues)

    saved = save_report_notice(synth, all_issues)

    if emit_json:
        return emit_json_report(
            files, all_issues, synth,
            report_id=saved.get("id") if saved else None,
        )
    if ai_synthesis:
        return print_ai_report(synth, all_issues)
    return print_report(all_issues)
