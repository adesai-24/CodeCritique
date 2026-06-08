import difflib
import json
import typer
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

from critique.ai.client import LLMClient
from critique.runner import run_all_checks, get_target_files
from critique.git_utils import install_pre_push_hook
from critique.persistence import list_reports, load_report
from critique.config_cli import config_app
from critique.cache_cli import cache_app
from critique.style_cli import style_app

app = typer.Typer(help="CodeCritique: A pre-push quality gate for your code.")
app.add_typer(config_app, name="config")
app.add_typer(cache_app, name="cache")
app.add_typer(style_app, name="style")
console = Console()

@app.command()
def check(
    files: Optional[list[str]] = typer.Argument(None, help="Specific files to check."),
    incremental: bool = typer.Option(True, help="Only check changed files (git diff)."),
    ai: bool = typer.Option(True, help="Use AI Critic + enrichment + synthesis (requires Ollama)."),
    learn: Optional[bool] = typer.Option(
        None,
        "--learn/--no-learn",
        help="Adaptively update your style profile from the reviewed files "
        "(overrides the 'style auto' setting for this run).",
    ),
):
    """
    Run all configured checks (Lint, Types, Security, AI Review).

    Pass --no-ai to skip AI features and use fast static-only mode.
    Pass --learn to nudge your coding-style profile from the files reviewed
    this run (see also `codecritique style auto`). Ollama must be running for
    AI features: ollama serve
    """
    success = run_all_checks(
        incremental=incremental, custom_files=files, use_ai=ai, learn=learn
    )
    if not success:
        typer.echo("Checks failed. Fix the issues or use --no-verify to bypass (not recommended).")
        raise typer.Exit(code=1)
    typer.echo("All checks passed!")

def _print_diff(file_path: str, original: str, formatted: str) -> None:
    """Render a coloured unified diff of a formatting change."""
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        formatted.splitlines(keepends=True),
        fromfile=f"{file_path} (original)",
        tofile=f"{file_path} (formatted)",
    )
    for line in diff:
        text = line.rstrip("\n")
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"[green]{text}[/green]", markup=False, highlight=False)
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"[red]{text}[/red]", markup=False, highlight=False)
        elif line.startswith("@@"):
            console.print(f"[cyan]{text}[/cyan]", markup=False, highlight=False)
        else:
            console.print(text, markup=False, highlight=False)


@app.command("format")
def format_code(
    files: Optional[list[str]] = typer.Argument(None, help="Specific files to format."),
    incremental: bool = typer.Option(
        True, help="When no files are given, format only changed files (git diff)."
    ),
    in_place: bool = typer.Option(
        False, "--in-place", "-i", help="Write the reformatted code back to disk."
    ),
    backup: bool = typer.Option(
        True, help="With --in-place, save the original as <file>.bak first."
    ),
):
    """
    Reformat code into a clean, review-ready layout (spacing, aligned
    declarations, per-function comments) WITHOUT changing behaviour.

    By default this previews a diff. Pass --in-place to apply the changes.
    Requires an AI provider (same configuration as `check`).
    """
    targets = get_target_files(incremental=incremental, custom_files=files)
    if not targets:
        typer.echo("No supported files to format.")
        return

    llm = LLMClient()
    if not llm.is_available():
        console.print(f"[red]{llm.unavailable_message()}[/red]")
        raise typer.Exit(code=1)

    from critique.formatter import CodeFormatter
    formatter = CodeFormatter(llm)

    changed_count = 0
    with console.status("[bold blue]Formatting...[/bold blue]"):
        results = [formatter.format_file(path) for path in targets]

    for result in results:
        if not result.ok:
            console.print(f"[yellow]Skipped {result.file_path}: {result.error}[/yellow]")
            continue
        if not result.changed:
            console.print(f"[dim]{result.file_path}: already well-formatted.[/dim]")
            continue

        changed_count += 1
        if in_place:
            try:
                if backup:
                    with open(result.file_path + ".bak", "w", encoding="utf-8") as bak:
                        bak.write(result.original)
                with open(result.file_path, "w", encoding="utf-8") as f:
                    f.write(result.formatted)
            except Exception as exc:
                console.print(f"[red]Could not write {result.file_path}: {exc}[/red]")
                continue
            note = " (backup saved)" if backup else ""
            console.print(f"[green]Formatted {result.file_path}{note}.[/green]")
        else:
            console.print(f"\n[bold]{result.file_path}[/bold]")
            _print_diff(result.file_path, result.original, result.formatted)

    if changed_count == 0:
        console.print("[bold green]Nothing to reformat — all files look good.[/bold green]")
    elif not in_place:
        console.print(
            f"\n[bold]{changed_count} file(s) would change.[/bold] "
            "Re-run with [cyan]--in-place[/cyan] to apply."
        )


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
        console.print(f"[red]{llm.unavailable_message()}[/red]")
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
