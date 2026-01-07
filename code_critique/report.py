from typing import List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from code_critique.checkers.base import Issue, Severity

console = Console()

def print_report(issues: List[Issue]) -> bool:
    """
    Prints the issues to the console.
    Returns True if passed (no FATAL), False if failed.
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
        
        loc = f"{issue.file_path}:{issue.line}"
        if issue.column:
            loc += f":{issue.column}"
            
        table.add_row(
            f"[{sev_style}]{issue.severity.value}[/{sev_style}]",
            loc,
            f"{issue.message} ({issue.code})",
            issue.reasoning or ""
        )

    console.print(table)

    if fatal_issues:
        console.print(f"\n[bold red]\U0001F6AB Fix {len(fatal_issues)} FATAL issues to push.[/bold red]")
        return False
    elif warnings:
        console.print(f"\n[bold yellow]\U000026A0 Found {len(warnings)} WARNINGS.[/bold yellow]")
        return True
    
    return True
