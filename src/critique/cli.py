import typer
from typing import Optional
from critique.runner import run_all_checks
from critique.git_utils import install_pre_push_hook

app = typer.Typer(help="CodeCritique: A pre-push quality gate for your code.")

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

if __name__ == "__main__":
    app()
