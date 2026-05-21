import json
import typer
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

from critique.config import load_config, write_starter_config, CONFIG_PATH
from critique.runner import run_all_checks
from critique.git_utils import install_pre_push_hook
from critique.persistence import list_reports, load_report

app = typer.Typer(help="CodeCritique: A pre-push quality gate for your code.")
console = Console()

@app.command()
def check(
    files: Optional[list[str]] = typer.Argument(None, help="Specific files to check."),
    incremental: bool = typer.Option(True, help="Only check changed files (git diff)."),
    ai: bool = typer.Option(True, help="Use AI Critic + enrichment + synthesis."),
    skip: Optional[List[str]] = typer.Option(
        None,
        "--skip",
        help="Skip a checker by name. Repeatable: --skip ruff --skip coverage. "
             "Valid names: ruff, bandit, mypy, coverage, ai-critic",
    ),
    ai_only: bool = typer.Option(
        False,
        "--ai-only",
        help="Run only the AI Critic; skip all static checkers.",
    ),
):
    """
    Run all configured checks (Lint, Types, Security, AI Review).

    Examples:
      critique check                          # full run
      critique check --no-ai                  # static only
      critique check --skip ruff --skip mypy  # skip specific checkers
      critique check --ai-only                # AI Critic only
    """
    cfg = load_config()
    skip_set = set(skip) if skip else set()

    success = run_all_checks(
        incremental=incremental,
        custom_files=files,
        use_ai=ai,
        skip_checkers=skip_set,
        ai_only=ai_only,
        config=cfg,
    )
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


@app.command("init-config")
def init_config():
    """
    Write a starter config.toml to ~/.codecritique/config.toml.

    Safe to run on an existing config — will not overwrite unless you confirm.
    """
    if CONFIG_PATH.exists():
        overwrite = typer.confirm(
            f"Config already exists at {CONFIG_PATH}. Overwrite?", default=False
        )
        if not overwrite:
            console.print("[yellow]Aborted — existing config kept.[/yellow]")
            raise typer.Exit(code=0)

    write_starter_config()
    console.print(f"[green]Config written to {CONFIG_PATH}[/green]")
    console.print(
        "Edit it to set your provider (ollama / anthropic / openai) and model."
    )


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

    cfg = load_config()
    try:
        from critique.ai.providers import get_llm_provider
        llm = get_llm_provider(cfg)
    except Exception as exc:
        console.print(f"[red]Could not initialise LLM provider: {exc}[/red]")
        raise typer.Exit(code=1)

    if not llm.is_available():
        console.print(
            "[red]LLM provider is not available. "
            "For Ollama: run 'ollama serve'. "
            "For cloud providers: check your API key.[/red]"
        )
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
