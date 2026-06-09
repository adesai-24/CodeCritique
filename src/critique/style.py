"""
Style learning — personalise suggestions to *your* coding habits.

What it does (and doesn't)
--------------------------
This is **not** model fine-tuning. Instead, CodeCritique statically analyses the
code you've already written, extracts your measurable conventions (quote style,
type-hint usage, docstring habits, f-strings vs ``.format``, typical function
length, naming case, line width, …), and distils them into a short natural-
language **style profile**.

When the feature is toggled on, that profile is injected into the AI reviewer's
context (a form of in-context "training"), so its suggested fixes read like
something *you* would write rather than generic boilerplate.

The profile is deterministic, inspectable, and stored as plain JSON at
``~/.codecritique/style_profile.json`` — nothing leaves your machine.
"""

from __future__ import annotations

import ast
import io
import json
import os
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from critique.config import CONFIG_DIR

STYLE_PATH = CONFIG_DIR / "style_profile.json"

_SKIP_DIRS = {".venv", "venv", "env", "ENV", "site-packages", "__pycache__",
              ".git", "build", "dist", "node_modules", ".mypy_cache", ".ruff_cache"}


@dataclass
class StyleProfile:
    """Aggregated, human-readable summary of a codebase's conventions."""

    files_analyzed: int = 0
    functions: int = 0
    double_quote_ratio: float = 0.0       # double / (single + double) string literals
    type_hint_ratio: float = 0.0          # annotated params+returns / total
    docstring_ratio: float = 0.0          # defs with a docstring / total defs
    fstring_ratio: float = 0.0            # f-strings / (f-strings + %/.format)
    snake_case_ratio: float = 0.0         # snake_case function names / total
    avg_function_length: float = 0.0      # source lines per function
    typical_line_length: int = 0          # ~90th percentile line width
    comment_density: float = 0.0          # comment lines / non-blank lines
    samples: Dict[str, List[str]] = field(default_factory=dict)  # example names

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _iter_python_files(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            for sub in p.rglob("*.py"):
                if any(part in _SKIP_DIRS for part in sub.parts):
                    continue
                files.append(sub)
    return files


def _is_snake_case(name: str) -> bool:
    return name.islower() or ("_" in name and name.lower() == name)


class _Counters:
    def __init__(self) -> None:
        self.single = 0
        self.double = 0
        self.fstring = 0
        self.format_pct = 0
        self.annotated = 0
        self.annotatable = 0
        self.defs = 0
        self.defs_with_doc = 0
        self.func_names_snake = 0
        self.func_names_total = 0
        self.func_lengths: List[int] = []
        self.line_lengths: List[int] = []
        self.comment_lines = 0
        self.code_lines = 0
        self.snake_names: List[str] = []
        self.other_names: List[str] = []


def _analyze_tokens(source: str, c: _Counters) -> None:
    """Count quote style and comment density via the tokenizer."""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.STRING:
                # Inspect the prefix/quote of the literal.
                text = tok.string
                prefix = text[: len(text) - len(text.lstrip("rbuRBUfF"))].lower()
                quote_part = text[len(prefix):]
                if quote_part[:1] == '"':
                    c.double += 1
                elif quote_part[:1] == "'":
                    c.single += 1
            elif tok.type == tokenize.COMMENT:
                c.comment_lines += 1
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass


def _analyze_ast(source: str, c: _Counters) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            c.fstring += 1
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            # Heuristic: "..." % (...) string formatting.
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                c.format_pct += 1
        elif isinstance(node, ast.Attribute) and node.attr == "format":
            c.format_pct += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            c.defs += 1
            c.func_names_total += 1
            if _is_snake_case(node.name):
                c.func_names_snake += 1
                if len(c.snake_names) < 8:
                    c.snake_names.append(node.name)
            elif len(c.other_names) < 8:
                c.other_names.append(node.name)
            if ast.get_docstring(node):
                c.defs_with_doc += 1
            # Type-hint coverage on args + return.
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if arg.arg == "self" or arg.arg == "cls":
                    continue
                c.annotatable += 1
                if arg.annotation is not None:
                    c.annotated += 1
            c.annotatable += 1  # the return
            if node.returns is not None:
                c.annotated += 1
            end = getattr(node, "end_lineno", node.lineno)
            c.func_lengths.append(max(1, end - node.lineno + 1))
        elif isinstance(node, ast.ClassDef):
            c.defs += 1
            if ast.get_docstring(node):
                c.defs_with_doc += 1


def analyze_paths(paths: Optional[List[str]] = None) -> StyleProfile:
    """Build a StyleProfile from the Python files under ``paths``.

    Defaults to the current working directory.  Never raises on a bad file.
    """
    paths = paths or [os.getcwd()]
    files = _iter_python_files(paths)
    c = _Counters()
    analyzed = 0

    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except Exception:
            continue
        analyzed += 1
        for line in source.splitlines():
            if line.strip():
                c.code_lines += 1
                c.line_lengths.append(len(line))
        _analyze_tokens(source, c)
        _analyze_ast(source, c)

    return _aggregate(c, analyzed)


def _ratio(num: int, denom: int) -> float:
    return round(num / denom, 3) if denom else 0.0


def _percentile(values: List[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[idx]


def _aggregate(c: _Counters, analyzed: int) -> StyleProfile:
    avg_len = round(sum(c.func_lengths) / len(c.func_lengths), 1) if c.func_lengths else 0.0
    return StyleProfile(
        files_analyzed=analyzed,
        functions=len(c.func_lengths),
        double_quote_ratio=_ratio(c.double, c.single + c.double),
        type_hint_ratio=_ratio(c.annotated, c.annotatable),
        docstring_ratio=_ratio(c.defs_with_doc, c.defs),
        fstring_ratio=_ratio(c.fstring, c.fstring + c.format_pct),
        snake_case_ratio=_ratio(c.func_names_snake, c.func_names_total),
        avg_function_length=avg_len,
        typical_line_length=_percentile(c.line_lengths, 0.9),
        comment_density=_ratio(c.comment_lines, c.code_lines),
        samples={
            "snake_case_names": c.snake_names,
            "other_names": c.other_names,
        },
    )


# ---------------------------------------------------------------------------
# Summary for prompt injection
# ---------------------------------------------------------------------------

def summarize(profile: StyleProfile) -> str:
    """Render the profile as a concise instruction block for the AI reviewer."""
    if profile.files_analyzed == 0 or profile.functions == 0:
        return ""

    lines: List[str] = []

    if profile.double_quote_ratio >= 0.6:
        lines.append("- Prefer double quotes for strings.")
    elif profile.double_quote_ratio <= 0.4:
        lines.append("- Prefer single quotes for strings.")

    if profile.snake_case_ratio >= 0.8:
        lines.append("- Use snake_case for function and variable names.")

    if profile.type_hint_ratio >= 0.6:
        lines.append("- Include type hints on function parameters and return values.")
    elif profile.type_hint_ratio <= 0.2:
        lines.append("- This codebase rarely uses type hints; don't add them unless asked.")

    if profile.docstring_ratio >= 0.5:
        lines.append("- Write docstrings for functions and classes.")
    elif profile.docstring_ratio <= 0.15:
        lines.append("- Keep docstrings minimal; this codebase rarely uses them.")

    if profile.fstring_ratio >= 0.6:
        lines.append("- Use f-strings for string formatting.")

    if profile.avg_function_length:
        lines.append(
            f"- Keep functions around {int(round(profile.avg_function_length))} lines, "
            "matching the existing style."
        )
    if profile.typical_line_length:
        lines.append(f"- Aim for lines under ~{profile.typical_line_length} characters.")

    if not lines:
        return ""

    header = (
        "The author of this code has the following established style. Make your "
        "suggested fixes match these conventions so they feel native to the codebase:"
    )
    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_profile(profile: StyleProfile, path: Optional[Path] = None) -> Path:
    path = path or STYLE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_profile(path: Optional[Path] = None) -> Optional[StyleProfile]:
    path = path or STYLE_PATH
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        known = {k: v for k, v in data.items() if k in StyleProfile().to_dict()}
        return StyleProfile(**known)
    except Exception:
        return None


def clear_profile(path: Optional[Path] = None) -> bool:
    path = path or STYLE_PATH
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Adaptive (incremental) learning — "learn as you review"
# ---------------------------------------------------------------------------

# Exponential-moving-average weight for a single ``check`` batch. Deliberately
# small: each run only *nudges* the profile toward what it just saw, so a
# handful of changed files can never overwrite an established style. This is the
# core guard against overtraining on the latest diff.
DEFAULT_LEARN_RATE = 0.15


def _ema(old: float, new: float, alpha: float, ndigits: int = 3) -> float:
    return round((1.0 - alpha) * old + alpha * new, ndigits)


def merge_profiles(
    existing: StyleProfile,
    batch: StyleProfile,
    alpha: float = DEFAULT_LEARN_RATE,
) -> StyleProfile:
    """Nudge ``existing`` toward ``batch`` using an exponential moving average.

    Ratios are blended (so one batch can't dominate — anti-overtraining), while
    the ``files_analyzed`` / ``functions`` counters accumulate so the profile
    reflects everything observed over time. Sample names are refreshed from the
    most recent batch. Returns ``existing`` unchanged when the batch carries no
    usable signal.
    """
    if batch.functions == 0:
        return existing
    a = max(0.0, min(1.0, alpha))
    return StyleProfile(
        files_analyzed=existing.files_analyzed + batch.files_analyzed,
        functions=existing.functions + batch.functions,
        double_quote_ratio=_ema(existing.double_quote_ratio, batch.double_quote_ratio, a),
        type_hint_ratio=_ema(existing.type_hint_ratio, batch.type_hint_ratio, a),
        docstring_ratio=_ema(existing.docstring_ratio, batch.docstring_ratio, a),
        fstring_ratio=_ema(existing.fstring_ratio, batch.fstring_ratio, a),
        snake_case_ratio=_ema(existing.snake_case_ratio, batch.snake_case_ratio, a),
        avg_function_length=(
            _ema(existing.avg_function_length, batch.avg_function_length, a, 1)
            if existing.avg_function_length else batch.avg_function_length
        ),
        typical_line_length=(
            int(round(_ema(existing.typical_line_length, batch.typical_line_length, a, 1)))
            if existing.typical_line_length else batch.typical_line_length
        ),
        comment_density=_ema(existing.comment_density, batch.comment_density, a),
        samples=batch.samples or existing.samples,
    )


def learn_incrementally(
    paths: Optional[List[str]] = None,
    alpha: float = DEFAULT_LEARN_RATE,
    path: Optional[Path] = None,
) -> Optional[StyleProfile]:
    """Analyse ``paths`` and fold the result into the saved profile via EMA.

    This is the engine behind "learn as you review": call it after a ``check``
    run with the files that were just reviewed. The first ever call (no saved
    profile yet) simply seeds the profile from the batch. Returns the updated
    profile, or ``None`` when the batch had no Python functions to learn from.
    Never raises on a bad path.
    """
    batch = analyze_paths(paths)
    if batch.files_analyzed == 0 or batch.functions == 0:
        return None
    existing = load_profile(path)
    updated = merge_profiles(existing, batch, alpha) if existing is not None else batch
    save_profile(updated, path)
    return updated


# ---------------------------------------------------------------------------
# Integration helper
# ---------------------------------------------------------------------------

def style_context_for_prompts(config, path: Optional[Path] = None) -> Optional[str]:
    """Return the style instruction block if learning is enabled and a profile exists.

    Returns None when the feature is off or no profile has been built yet.
    """
    if not getattr(config, "style_learning", False):
        return None
    profile = load_profile(path)
    if profile is None:
        return None
    summary = summarize(profile)
    return summary or None
