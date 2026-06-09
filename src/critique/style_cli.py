"""
``codecritique style`` — learn and manage your personal coding-style profile.

Workflow
--------
    codecritique style enable            # turn the feature on
    codecritique style learn             # analyse your code, build the profile
    codecritique style auto on           # learn a little from every `check` run
    codecritique style show              # inspect what was learned
    codecritique style disable           # turn it off (profile is kept)
    codecritique style clear             # delete the learned profile
"""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from critique import config as cfg_mod
from critique import style as style_mod

console = Console()
style_app = typer.Typer(help="Learn your coding style and tailor AI suggestions to it.")


@style_app.command("enable")
def enable() -> None:
    """Turn on style-aware suggestions."""
    cfg_mod.set_value("style_learning", "on")
    console.print("[green]Style learning enabled.[/green]")
    if style_mod.load_profile() is None:
        console.print("[dim]No profile yet — run 'codecritique style learn' to build one.[/dim]")


@style_app.command("disable")
def disable() -> None:
    """Turn off style-aware suggestions (keeps the learned profile)."""
    cfg_mod.set_value("style_learning", "off")
    console.print("[yellow]Style learning disabled.[/yellow]")


@style_app.command("auto")
def auto(
    state: Optional[str] = typer.Argument(
        None, help="on | off | status (default: status)."
    ),
) -> None:
    """Adaptive 'learn as you review' mode.

    When on, every 'codecritique check' nudges your style profile toward the
    files it just reviewed (EMA-blended, so it can't overtrain on one diff).
    """
    if state is None or state.strip().lower() == "status":
        on = cfg_mod.load_config().adaptive_style
        label = "[green]on[/green]" if on else "[yellow]off[/yellow]"
        console.print(f"Adaptive style learning is {label}.")
        return

    val = state.strip().lower()
    if val in cfg_mod._TRUE_WORDS:
        cfg_mod.set_value("adaptive_style", "on")
        console.print(
            "[green]Adaptive style learning enabled[/green] — every "
            "'codecritique check' now nudges your profile."
        )
        if not cfg_mod.load_config().style_learning:
            console.print(
                "[dim]Tip: run 'codecritique style enable' so the learned "
                "profile is actually applied to reviews.[/dim]"
            )
    elif val in cfg_mod._FALSE_WORDS:
        cfg_mod.set_value("adaptive_style", "off")
        console.print("[yellow]Adaptive style learning disabled.[/yellow]")
    else:
        console.print("[red]Usage: codecritique style auto [on|off|status][/red]")
        raise typer.Exit(code=2)


@style_app.command("learn")
def learn(
    paths: Optional[List[str]] = typer.Argument(
        None, help="Files or directories to learn from. Defaults to the current directory."
    ),
) -> None:
    """Analyse your existing code and build/update your style profile."""
    target = paths or ["."]
    console.print(f"[cyan]Analysing your code in: {', '.join(target)}[/cyan]")
    profile = style_mod.analyze_paths(target)
    if profile.files_analyzed == 0:
        console.print("[red]No Python files found to learn from.[/red]")
        raise typer.Exit(code=1)
    path = style_mod.save_profile(profile)
    console.print(
        f"[green]Learned your style from {profile.files_analyzed} file(s) / "
        f"{profile.functions} function(s).[/green] Saved to {path}"
    )
    if not cfg_mod.load_config().style_learning:
        console.print(
            "[dim]Tip: run 'codecritique style enable' to apply it to reviews.[/dim]"
        )
    _print_summary(profile)


@style_app.command("show")
def show() -> None:
    """Display the learned style profile and how it's applied."""
    profile = style_mod.load_profile()
    if profile is None:
        console.print("[yellow]No style profile yet. Run 'codecritique style learn'.[/yellow]")
        raise typer.Exit(code=0)
    cfg = cfg_mod.load_config()
    state = "[green]enabled[/green]" if cfg.style_learning else "[yellow]disabled[/yellow]"
    auto = "[green]on[/green]" if cfg.adaptive_style else "[yellow]off[/yellow]"
    console.print(f"Style learning is {state}.  Adaptive (learn-as-you-review) is {auto}.\n")
    _print_summary(profile)


@style_app.command("clear")
def clear() -> None:
    """Delete the learned style profile."""
    if style_mod.clear_profile():
        console.print("[green]Cleared style profile.[/green]")
    else:
        console.print("[yellow]No style profile to clear.[/yellow]")


def _print_summary(profile: style_mod.StyleProfile) -> None:
    table = Table(title="Your Coding Style", header_style="bold cyan")
    table.add_column("Habit")
    table.add_column("Value", justify="right")
    table.add_row("Files analyzed", str(profile.files_analyzed))
    table.add_row("Functions", str(profile.functions))
    table.add_row("Double-quote preference", f"{profile.double_quote_ratio:.0%}")
    table.add_row("Type-hint coverage", f"{profile.type_hint_ratio:.0%}")
    table.add_row("Docstring coverage", f"{profile.docstring_ratio:.0%}")
    table.add_row("f-string usage", f"{profile.fstring_ratio:.0%}")
    table.add_row("snake_case functions", f"{profile.snake_case_ratio:.0%}")
    table.add_row("Avg function length", f"{profile.avg_function_length:.0f} lines")
    table.add_row("Typical line length", f"{profile.typical_line_length} chars")
    console.print(table)

    summary = style_mod.summarize(profile)
    if summary:
        console.print("\n[bold]Injected into the AI reviewer when enabled:[/bold]")
        console.print(f"[dim]{summary}[/dim]")
