"""
``codecritique cache`` — inspect and manage the AI response cache.

The cache is what makes repeated reviews of unchanged code fast: identical (and
near-identical) prompts reuse a stored model response instead of paying for a
fresh, slow inference call.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from critique.ai import client as llm_client

console = Console()
cache_app = typer.Typer(help="Inspect and manage the AI response cache.")


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


@cache_app.command("stats")
def stats() -> None:
    """Show cache size, entry counts, and this session's hit/miss ratio."""
    info = llm_client.cache_info()
    table = Table(title="AI Response Cache", header_style="bold cyan")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Location", info["cache_dir"])
    table.add_row("Cached responses", str(info["entries"]))
    table.add_row("On-disk size", _human_bytes(info["bytes"]))
    table.add_row("Semantic buckets", str(info["semantic_buckets"]))
    console.print(table)
    console.print(
        "[dim]Per-session counters reset each run; persistent reuse comes from "
        "the on-disk cache above.[/dim]"
    )


@cache_app.command("clear")
def clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Delete all cached AI responses (forces fresh inference next run)."""
    if not yes and not typer.confirm("Clear the entire AI response cache?", default=False):
        raise typer.Exit(code=0)
    removed = llm_client.clear_cache()
    console.print(f"[green]Cleared cache ({removed} file(s) removed).[/green]")


@cache_app.command("path")
def path() -> None:
    """Print the cache directory."""
    console.print(str(llm_client.DEFAULT_CACHE_DIR))
