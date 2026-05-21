import json
import typer
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

from critique.ai.client import LLMClient
from critique.runner import run_all_checks
from critique.git_utils import install_pre_push_hook
from critique.persistence import list_reports, load_report

app = typer.Typer(help="CodeCritique: A pre-push quality gate for your code.")
console = Console()

@app.command()
def check(
    files: Optional[list[str]] = typer.Argument(None, help="Specific files to check."),
    incremental: bool = typer.Option(True, help="Only check changed files (git diff)."),
    ai: bool = typer.Option(True, help="Use AI Critic + enrichment + synthesis (requires Ollama)."),
):
    """
    Run all configured checks (Lint, Types, Security, AI Review).

    Pass --no-ai to skip AI features and use fast static-only mode.
    Ollama must be running for AI features: ollama serve
    """
    success = run_all_checks(incremental=incremental, custom_files=files, use_ai=ai)
    if not success:
        typer.echo("Checks failed. Fix the issues or use --no-verify to bypass (not recommended).")
        raise typer.Exit(code=1)
    typer.echo("All checks passed!")

@app.command()
def install_hooks():
    """
    Install the pre-push hook into the .git directory.
    """
    install_pre_push_hook()


@app.command("list")
def list_saved_reports():
    """Show recently saved review reports."""
    reports = list_reports()
    if not reports:
        console.print("[yellow]No saved reports found.[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title="Recent CodeCritique Reports")
    table.add_column("ID", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Issues", justify="right")
    table.add_column("Summary")

    for report in reports:
        synth = report.get("synth_output", {})
        summary = str(synth.get("summary", "")).replace("\n", " ")
        if len(summary) > 72:
            summary = summary[:69] + "..."
        table.add_row(
            str(report.get("id", "")),
            str(report.get("timestamp", "")),
            str(len(report.get("issues", []))),
            summary,
        )

    console.print(table)


def _build_chat_context(report: Dict) -> str:
    compact = {
        "id": report.get("id"),
        "timestamp": report.get("timestamp"),
        "synth_output": report.get("synth_output", {}),
        "issues": report.get("issues", []),
    }
    return json.dumps(compact, indent=2)


@app.command()
def chat(
    report_id: Optional[str] = typer.Argument(
        None,
        help="Report ID to chat with, such as rev_abc123.",
    ),
    last: bool = typer.Option(False, "--last", help="Chat with the most recent report."),
):
    """Ask follow-up questions about a saved review report."""
    try:
        if last:
            report = load_report()
        elif report_id:
            report = load_report(report_id)
        else:
            console.print("[yellow]Pass a report id or use --last.[/yellow]")
            raise typer.Exit(code=2)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    llm = LLMClient()
    if not llm.is_available():
        console.print("[red]Ollama is not running. Start it with: ollama serve[/red]")
        raise typer.Exit(code=1)

    system = (
        "You just reviewed this code. Answer follow-up questions about the saved "
        "CodeCritique review. Reference actual findings, file paths, line numbers, "
        "reasoning, and suggested fixes when they are relevant. If the report does "
        "not contain enough evidence, say what is missing instead of inventing code."
    )
    context = _build_chat_context(report)
    history: List[Dict[str, str]] = []

    console.print(
        f"[bold cyan]Chatting with review {report.get('id')}[/bold cyan] "
        "[dim](type exit or quit to leave)[/dim]"
    )

    while True:
        try:
            question = input("critique> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break

        user_msg = (
            "Saved review context:\n"
            f"{context}\n\n"
            f"User follow-up: {question}"
        )

        chunks: List[str] = []
        try:
            for chunk in llm.complete_stream(system, user_msg, history[-20:]):
                chunks.append(chunk)
                console.print(chunk, end="", markup=False)
            console.print()
        except Exception as exc:
            console.print(f"[red]Chat failed: {exc}[/red]")
            continue

        answer = "".join(chunks)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        history = history[-20:]

if __name__ == "__main__":
    app()
