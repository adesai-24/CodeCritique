import os
from typing import Any, Dict, List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from critique.checkers.base import Issue, Severity
from critique.profiles import severity_meets

console = Console()

def print_report(issues: List[Issue], block_severity: str = "FATAL") -> bool:
    """
    Prints the issues to the console.

    Returns True if the push is allowed.  ``block_severity`` controls the gate:
    any issue at or above that severity blocks the push (e.g. strict mode passes
    ``"WARNING"``; mentor mode passes ``"NEVER"``).
    """
    if not issues:
        console.print(Panel("[bold green]All Clean! Code looks great.[/bold green]", title="Critique Result"))
        return True

    fatal_issues = [i for i in issues if i.severity == Severity.FATAL]
    warnings = [i for i in issues if i.severity == Severity.WARNING]
    infos = [i for i in issues if i.severity == Severity.INFO]

    table = Table(title="Code Critique Report", show_lines=True)
    table.add_column("Severity", style="bold")
    table.add_column("Location")
    table.add_column("Message")
    table.add_column("Reasoning", style="dim")

    for issue in fatal_issues + warnings + infos:
        sev_style = "red" if issue.severity == Severity.FATAL else "yellow" if issue.severity == Severity.WARNING else "blue"
        
        try:
            display_path = os.path.relpath(issue.file_path)
        except Exception:
            display_path = issue.file_path

        loc = f"{display_path}:{issue.line}"
        if issue.column:
            loc += f":{issue.column}"
            
        table.add_row(
            f"[{sev_style}]{issue.severity.value}[/{sev_style}]",
            loc,
            f"{issue.message} ({issue.code})",
            issue.reasoning or ""
        )

    console.print(table)

    blocking = [i for i in issues if severity_meets(i.severity, block_severity)]
    if blocking:
        console.print(
            f"\n[bold red]BLOCKED: Fix {len(blocking)} issue(s) at or above "
            f"{block_severity} severity to push.[/bold red]"
        )
        return False
    if warnings:
        console.print(f"\n[bold yellow]WARNINGS: Found {len(warnings)} warning(s).[/bold yellow]")
    return True

# ---------------------------------------------------------------------------
# Phase 4 — AI-powered report renderer
# ---------------------------------------------------------------------------

def print_ai_report(synth: Dict[str, Any], issues: List[Issue], block_severity: str = "FATAL") -> bool:
    """
    Render a curated, senior-engineer-style code review to the terminal.

    Layout:
      1. Summary panel          — overall assessment from the synthesizer
      2. Fix First callout      — the single highest-priority issue
      3. Critical section       — must-fix items with code context
      4. Warnings section       — should-fix items
      5. Suggestions section    — nice-to-have items
      6. What's Good panel      — positive observations (always present)

    Returns True if the push should be allowed (no FATAL issues), False otherwise.
    Uses only ASCII box-drawing characters for Windows cp1252 compatibility.
    """
    console.print()

    # 1. Summary
    summary = synth.get("summary", "Review complete.")
    console.print(Panel(
        f"[bold]{summary}[/bold]",
        title="[cyan]CodeCritique AI Review[/cyan]",
        border_style="cyan",
    ))
    console.print()

    # 2. Fix First
    fix_first_idx = synth.get("fix_first", -1)
    if isinstance(fix_first_idx, int) and 0 <= fix_first_idx < len(issues):
        ff = issues[fix_first_idx]
        try:
            ff_path = os.path.relpath(ff.file_path)
        except Exception:
            ff_path = ff.file_path
        fix_text = Text()
        fix_text.append("Fix First: ", style="bold yellow")
        fix_text.append(f"{ff_path}:{ff.line} - {ff.message}", style="white")
        if ff.suggested_fix:
            fix_text.append(f"\n  -> {ff.suggested_fix}", style="dim yellow")
        console.print(Panel(fix_text, title="[yellow]!! Priority[/yellow]", border_style="yellow"))
        console.print()

    # 3-5. Sectioned findings
    def _render_section(title: str, indices: List[int], color: str) -> None:
        if not indices:
            return
        console.print(f"[bold {color}]{'-' * 60}[/bold {color}]")
        console.print(f"[bold {color}]  {title}[/bold {color}]")
        console.print(f"[bold {color}]{'-' * 60}[/bold {color}]")
        for idx in indices:
            if idx >= len(issues):
                continue
            issue = issues[idx]
            try:
                rel_path = os.path.relpath(issue.file_path)
            except Exception:
                rel_path = issue.file_path
            console.print(f"\n  [{color}]{issue.message}[/{color}]  [dim]({issue.code})[/dim]")
            console.print(f"  [dim]{rel_path}:{issue.line}[/dim]")
            if issue.reasoning:
                console.print(f"  {issue.reasoning}")
            if issue.suggested_fix:
                console.print(f"  [dim]Fix:[/dim] [italic]{issue.suggested_fix}[/italic]")
            if issue.code_context:
                snippet = "".join(issue.code_context)
                console.print(Syntax(
                    snippet, "python",
                    line_numbers=True,
                    start_line=max(1, issue.line - 3),
                    theme="monokai",
                ))
        console.print()

    _render_section("CRITICAL - Must Fix", synth.get("critical", []), "red")
    _render_section("WARNINGS - Should Fix", synth.get("warnings", []), "yellow")
    _render_section("SUGGESTIONS - Nice to Have", synth.get("suggestions", []), "blue")

    # 6. What's Good
    whats_good = synth.get("whats_good", [])
    if whats_good:
        good_text = "\n".join(f"  + {item}" for item in whats_good)
        console.print(Panel(good_text, title="[green]What's Good[/green]", border_style="green"))
        console.print()

    # Exit logic — gate on the active profile's blocking severity across all
    # issues (not just the synthesizer's "critical" bucket).
    warning_ids = synth.get("warnings", [])
    blocking = [i for i in issues if severity_meets(i.severity, block_severity)]

    if blocking:
        console.print(
            f"[bold red]BLOCKED: Fix {len(blocking)} issue(s) at or above "
            f"{block_severity} severity before pushing.[/bold red]"
        )
        return False
    if warning_ids:
        console.print(f"[bold yellow]WARNING: Found {len(warning_ids)} warning(s).[/bold yellow]")
    return True
