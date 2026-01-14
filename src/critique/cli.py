import typer
from typing import Optional
from typing_extensions import Annotated
from critique.runner import run_all_checks
from critique.git_utils import install_pre_push_hook

app = typer.Typer(help="CodeCritique: A pre-push quality gate for your code.")

@app.command()
def check(
    files: Optional[list[str]] = typer.Argument(None, help="Specific files to check."),
    incremental: bool = typer.Option(True, help="Only check changed files (git diff)."),
    fix: bool = typer.Option(False, help="Attempt to auto-fix issues (where possible)."),
    ui: bool = typer.Option(False, help="Launch the GUI application."),
    dev: bool = typer.Option(False, help="Launch GUI in dev mode (localhost:5173).")
):
    """
    Run all configured checks (Lint, Types, Security, Tests).
    """
    if ui:
        from critique.app import start_app
        start_app(dev=dev)
        return

    success = run_all_checks(incremental=incremental, custom_files=files)
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
