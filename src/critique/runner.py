import glob
import os
import sys
from typing import List, Optional, Set

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from critique.git_utils import get_changed_files
from critique.checkers.base import Issue, Severity
from critique.checkers.lint import RuffChecker
from critique.checkers.security import BanditChecker
from critique.checkers.types import MypyChecker
from critique.checkers.coverage import CoverageChecker
from critique.report import print_report, print_ai_report
from critique.persistence import fallback_synthesis, save_report
from critique.config import load_config, Config

console = Console()

# Canonical lowercase names for each static checker.
_CHECKER_NAMES = {
    "ruff": RuffChecker,
    "bandit": BanditChecker,
    "mypy": MypyChecker,
    "coverage": CoverageChecker,
}


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


def _apply_severity_overrides(issues: List[Issue], overrides: dict) -> List[Issue]:
    """Apply severity_overrides from config to the issue list."""
    if not overrides:
        return issues
    result = []
    for issue in issues:
        override = overrides.get(issue.code)
        if override:
            try:
                new_sev = Severity[override.upper()]
                issue = issue._replace(severity=new_sev)
            except KeyError:
                pass  # ignore invalid severity strings
        result.append(issue)
    return result


def scan_files(
    files: List[str],
    use_ai: bool = True,
    skip_checkers: Optional[Set[str]] = None,
    ai_only: bool = False,
    config: Optional[Config] = None,
) -> List[Issue]:
    """
    Run all configured checkers on the provided file list.

    Parameters
    ----------
    files: list of absolute paths to check
    use_ai: enable AI Critic when a provider is available
    skip_checkers: lowercase checker names to omit (e.g. {"ruff", "coverage"})
    ai_only: run ONLY the AI Critic, skip all static checkers
    config: loaded Config object; loaded fresh when None
    """
    if not files:
        return []

    if config is None:
        config = load_config()

    skip = {s.lower() for s in (skip_checkers or set())} | {s.lower() for s in config.skip_checkers}

    checkers = []
    if not ai_only:
        for name, cls in _CHECKER_NAMES.items():
            if name not in skip:
                checkers.append(cls())

    if use_ai and "ai-critic" not in skip:
        try:
            from critique.ai.providers import get_llm_provider
            from critique.checkers.ai_critic import AICriticChecker
            provider = get_llm_provider(config)
            if provider.is_available():
                checkers.append(AICriticChecker(provider, max_file_chars=config.max_file_chars))
            else:
                console.print(
                    "[yellow]LLM provider not reachable — skipping AI Critic.[/yellow]"
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

    return _apply_severity_overrides(all_issues, config.severity_overrides)


def run_all_checks(
    incremental: bool = True,
    custom_files: Optional[List[str]] = None,
    use_ai: bool = True,
    skip_checkers: Optional[Set[str]] = None,
    ai_only: bool = False,
    config: Optional[Config] = None,
) -> bool:
    """
    Orchestrate the full check pipeline.

    Returns True if the push is allowed (no FATAL issues), False otherwise.
    """
    if config is None:
        config = load_config()

    files = get_target_files(incremental, custom_files)
    if not files and incremental and not custom_files:
        return True
    if not files and not incremental:
        console.print("[yellow]No python files found.[/yellow]")
        return True

    all_issues = scan_files(
        files,
        use_ai=use_ai,
        skip_checkers=skip_checkers,
        ai_only=ai_only,
        config=config,
    )

    if use_ai:
        try:
            from critique.ai.providers import get_llm_provider
            from critique.ai.enricher import enrich_issues
            from critique.ai.synthesizer import AISynthesizer
            provider = get_llm_provider(config)
            if provider.is_available():
                if all_issues:
                    all_issues = enrich_issues(all_issues, provider)
                synth = AISynthesizer(provider).synthesize(all_issues)
                saved = save_report(synth, all_issues)
                console.print(f"[dim]Saved review as {saved['id']}[/dim]")
                return print_ai_report(synth, all_issues)
            else:
                console.print("[yellow]LLM provider not reachable — falling back to basic report.[/yellow]")
        except Exception as exc:
            console.print(f"[yellow]AI report failed ({exc}) — falling back to basic report.[/yellow]")

    saved = save_report(fallback_synthesis(all_issues), all_issues)
    console.print(f"[dim]Saved review as {saved['id']}[/dim]")
    return print_report(all_issues)
