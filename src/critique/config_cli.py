"""
``codecritique config`` — manage providers, models, and API keys.

Examples
--------
    codecritique config show
    codecritique config providers
    codecritique config set provider gemini
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
from critique.config import SUPPORTED_PROVIDERS

console = Console()
config_app = typer.Typer(help="View and edit CodeCritique configuration and API keys.")


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
    key: str = typer.Argument(..., help="Setting name (provider, model, base_url, temperature, timeout)."),
    value: str = typer.Argument(..., help="New value. Use 'none' to clear an optional setting."),
) -> None:
    """Set a configuration value."""
    if key == "provider" and value.strip().lower() not in SUPPORTED_PROVIDERS:
        console.print(
            f"[red]Unknown provider '{value}'.[/red] "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
        raise typer.Exit(code=1)
    try:
        cfg = cfg_mod.set_value(key, value)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Set {key} = {getattr(cfg, key, cfg.extra.get(key))}[/green]")


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


@config_app.command("path")
def path() -> None:
    """Show where config and secrets are stored."""
    console.print(f"Config:  {cfg_mod.CONFIG_PATH}")
    console.print(f"Secrets: {secrets_store.SECRETS_PATH}")
