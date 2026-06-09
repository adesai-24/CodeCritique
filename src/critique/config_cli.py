"""
``codecritique config`` — manage providers, models, and API keys.

Examples
--------
    codecritique config show
    codecritique config providers
    codecritique config set provider gemini
    codecritique config language auto
    codecritique config set model gemini-2.0-flash
    codecritique config set-key gemini            # prompts, input hidden
    codecritique config set-key openai sk-...      # non-interactive
    codecritique config delete-key anthropic
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from critique import config as cfg_mod
from critique import secrets_store
from critique import profiles
from critique.config import SUPPORTED_PROVIDERS
from critique.languages import LANGUAGE_CHOICES

console = Console()
config_app = typer.Typer(help="View and edit CodeCritique configuration and API keys.")


def _short(text, width: int = 60) -> str:
    if not text:
        return "[dim](not set)[/dim]"
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


@config_app.command("show")
def show() -> None:
    """Print the active configuration and API-key status."""
    cfg = cfg_mod.load_config()

    table = Table(title="CodeCritique Configuration", show_header=True, header_style="bold cyan")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("provider", cfg.provider)
    table.add_row("model", cfg.resolved_model() + ("" if cfg.model else "  [dim](default)[/dim]"))
    table.add_row("base_url", str(cfg.base_url or "[dim](provider default)[/dim]"))
    table.add_row("temperature", str(cfg.temperature))
    table.add_row("timeout", str(cfg.timeout))
    table.add_row("language", cfg.language)
    table.add_row("suggestion_mode", cfg.suggestion_mode)
    table.add_row("project_context", _short(cfg.project_context))
    table.add_row("custom_instructions", _short(cfg.custom_instructions))
    for key, value in (cfg.extra or {}).items():
        table.add_row(f"extra.{key}", str(value))
    console.print(table)

    key_table = Table(title="API Keys", show_header=True, header_style="bold cyan")
    key_table.add_column("Provider")
    key_table.add_column("Key")
    key_table.add_column("Source")
    for provider in SUPPORTED_PROVIDERS:
        if provider == "ollama":
            continue
        key = secrets_store.get_api_key(provider)
        key_table.add_row(
            provider,
            secrets_store.mask_key(key),
            secrets_store.key_source(provider),
        )
    console.print(key_table)
    console.print(
        f"[dim]Config: {cfg_mod.CONFIG_PATH}\n"
        f"Secrets: {secrets_store.SECRETS_PATH} (permissions locked to 0600)[/dim]"
    )


@config_app.command("providers")
def providers() -> None:
    """List the supported AI providers and their default models."""
    table = Table(title="Supported Providers", header_style="bold cyan")
    table.add_column("Provider")
    table.add_column("Default model")
    table.add_column("Needs key?")
    needs_key = {"gemini", "openai", "anthropic"}
    for provider in SUPPORTED_PROVIDERS:
        table.add_row(
            provider,
            cfg_mod.DEFAULT_MODELS[provider],
            "yes" if provider in needs_key else "no / optional",
        )
    console.print(table)


@config_app.command("set")
def set_setting(
    key: str = typer.Argument(..., help="Setting name (provider, model, base_url, temperature, timeout, language)."),
    value: str = typer.Argument(..., help="New value. Use 'none' to clear an optional setting."),
) -> None:
    """Set a configuration value."""
    if key == "provider" and value.strip().lower() not in SUPPORTED_PROVIDERS:
        console.print(
            f"[red]Unknown provider '{value}'.[/red] "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
        raise typer.Exit(code=1)
    if key == "language" and value.strip().lower() not in LANGUAGE_CHOICES:
        console.print(
            f"[red]Unknown language '{value}'.[/red] "
            f"Supported: {', '.join(LANGUAGE_CHOICES)}"
        )
        raise typer.Exit(code=1)
    try:
        cfg = cfg_mod.set_value(key, value)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Set {key} = {getattr(cfg, key, cfg.extra.get(key))}[/green]")


@config_app.command("languages")
def languages() -> None:
    """List supported language choices for review file selection."""
    active = cfg_mod.load_config().language
    table = Table(title="Language Choices", header_style="bold cyan")
    table.add_column("Choice")
    table.add_column("Effect")
    rows = {
        "auto": "Review every supported Python and C/C++ file.",
        "python": "Review only Python files (.py, .pyi).",
        "cpp": "Review only C/C++ files (.c, .cc, .cpp, .h, .hpp, ...).",
    }
    for key, description in rows.items():
        marker = " [green]*[/green]" if key == active else ""
        table.add_row(key + marker, description)
    console.print(table)
    console.print("[dim]Set one with: codecritique config language <choice>[/dim]")


@config_app.command("language")
def language(
    choice: str = typer.Argument(..., help="Language choice: auto, python, or cpp."),
) -> None:
    """Set which language CodeCritique reviews by default."""
    choice = choice.strip().lower()
    if choice not in LANGUAGE_CHOICES:
        console.print(
            f"[red]Unknown language '{choice}'.[/red] "
            f"Supported: {', '.join(LANGUAGE_CHOICES)}"
        )
        raise typer.Exit(code=1)
    cfg_mod.set_value("language", choice)
    console.print(f"[green]Language choice set to '{choice}'.[/green]")


@config_app.command("set-key")
def set_key(
    provider: str = typer.Argument(..., help="Provider name, e.g. gemini, openai, anthropic."),
    key: Optional[str] = typer.Argument(None, help="API key. Omit to be prompted (input hidden)."),
) -> None:
    """Store an API key securely in the permission-locked secrets file."""
    provider = provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        console.print(
            f"[red]Unknown provider '{provider}'.[/red] "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
        raise typer.Exit(code=1)
    if not key:
        key = typer.prompt(f"Enter {provider} API key", hide_input=True)
    if not key or not key.strip():
        console.print("[red]No key provided.[/red]")
        raise typer.Exit(code=1)
    path = secrets_store.set_api_key(provider, key)
    console.print(
        f"[green]Saved {provider} key ({secrets_store.mask_key(key)}) to {path}[/green]"
    )
    console.print("[dim]Tip: keep this file private — it is git-ignored and chmod 0600.[/dim]")


@config_app.command("delete-key")
def delete_key(
    provider: str = typer.Argument(..., help="Provider whose stored key should be removed."),
) -> None:
    """Remove a stored API key."""
    if secrets_store.delete_api_key(provider.strip().lower()):
        console.print(f"[green]Removed stored {provider} key.[/green]")
    else:
        console.print(f"[yellow]No stored key found for {provider}.[/yellow]")


@config_app.command("modes")
def modes() -> None:
    """List the built-in review modes (suggestion profiles)."""
    active = cfg_mod.load_config().suggestion_mode
    table = Table(title="Review Modes", header_style="bold cyan")
    table.add_column("Mode")
    table.add_column("What it does")
    table.add_column("Reports ≥")
    table.add_column("Blocks push ≥")
    for prof in profiles.list_profiles():
        marker = " [green]●[/green]" if prof.name == active else ""
        table.add_row(
            prof.name + marker,
            prof.description,
            prof.min_report_severity,
            prof.block_severity,
        )
    console.print(table)
    console.print("[dim]Set one with: codecritique config mode <name>[/dim]")


@config_app.command("mode")
def mode(name: str = typer.Argument(..., help="Review mode, e.g. strict, lenient, mentor, security.")) -> None:
    """Set the active review mode (suggestion profile)."""
    if not profiles.is_valid_mode(name):
        valid = ", ".join(p.name for p in profiles.list_profiles())
        console.print(f"[red]Unknown mode '{name}'.[/red] Available: {valid}")
        raise typer.Exit(code=1)
    cfg_mod.set_value("suggestion_mode", name.strip().lower())
    prof = profiles.get_profile(name)
    console.print(f"[green]Review mode set to '{prof.name}'[/green] — {prof.description}")


@config_app.command("context")
def context(
    text: Optional[str] = typer.Argument(
        None, help="Project context for the AI reviewer. Omit with --clear to remove."
    ),
    clear: bool = typer.Option(False, "--clear", help="Clear the stored project context."),
) -> None:
    """Set the project context the AI reviewer should assume.

    Example:
        codecritique config context "Async FastAPI service; prefer pydantic models."
    """
    if clear:
        cfg_mod.set_value("project_context", "none")
        console.print("[green]Cleared project context.[/green]")
        return
    if not text:
        console.print("[yellow]Provide context text, or use --clear to remove it.[/yellow]")
        raise typer.Exit(code=2)
    cfg_mod.set_value("project_context", text)
    console.print("[green]Saved project context. The AI reviewer will use it on the next run.[/green]")


@config_app.command("wizard")
def wizard() -> None:
    """Interactive setup: pick a provider, key, and review mode."""
    console.print("[bold cyan]CodeCritique setup[/bold cyan]\n")

    provider = typer.prompt(
        f"Provider ({'/'.join(SUPPORTED_PROVIDERS)})",
        default=cfg_mod.load_config().provider,
    ).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        console.print(f"[red]Unknown provider '{provider}'.[/red]")
        raise typer.Exit(code=1)
    cfg_mod.set_value("provider", provider)

    needs_key = provider in {"gemini", "openai", "anthropic"}
    if needs_key and not secrets_store.get_api_key(provider):
        if typer.confirm(f"Add a {provider} API key now?", default=True):
            key = typer.prompt(f"{provider} API key", hide_input=True)
            if key.strip():
                secrets_store.set_api_key(provider, key)
                console.print(f"[green]Saved {provider} key ({secrets_store.mask_key(key)}).[/green]")

    mode_names = [p.name for p in profiles.list_profiles()]
    chosen = typer.prompt(
        f"Review mode ({'/'.join(mode_names)})",
        default=cfg_mod.load_config().suggestion_mode,
    ).strip().lower()
    if profiles.is_valid_mode(chosen):
        cfg_mod.set_value("suggestion_mode", chosen)

    if typer.confirm("Add project context for the AI reviewer?", default=False):
        ctx = typer.prompt("Project context")
        if ctx.strip():
            cfg_mod.set_value("project_context", ctx)

    console.print("\n[bold green]Setup complete.[/bold green] Run 'codecritique config show' to review.")


@config_app.command("path")
def path() -> None:
    """Show where config and secrets are stored."""
    console.print(f"Config:  {cfg_mod.CONFIG_PATH}")
    console.print(f"Secrets: {secrets_store.SECRETS_PATH}")
