"""Tests for the style-learning feature."""

import pytest

from critique import style
from critique.config import CritiqueConfig


# A small corpus with clear, consistent conventions:
# double quotes, type hints, docstrings, f-strings, snake_case.
_SAMPLE = '''\
"""Module docstring."""


def add_numbers(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def greet(name: str) -> str:
    """Build a greeting."""
    return f"Hello, {name}!"


class Calculator:
    """A small calculator."""

    def multiply(self, x: int, y: int) -> int:
        """Multiply two integers."""
        return x * y
'''


@pytest.fixture()
def sample_repo(tmp_path):
    (tmp_path / "mod.py").write_text(_SAMPLE, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def test_analyze_counts_files_and_functions(sample_repo):
    profile = style.analyze_paths([str(sample_repo)])
    assert profile.files_analyzed == 1
    assert profile.functions == 3  # add_numbers, greet, multiply


def test_analyze_detects_double_quotes(sample_repo):
    profile = style.analyze_paths([str(sample_repo)])
    assert profile.double_quote_ratio == 1.0


def test_analyze_detects_type_hints_and_docstrings(sample_repo):
    profile = style.analyze_paths([str(sample_repo)])
    assert profile.type_hint_ratio >= 0.9
    assert profile.docstring_ratio >= 0.9


def test_analyze_detects_fstrings_and_snake_case(sample_repo):
    profile = style.analyze_paths([str(sample_repo)])
    assert profile.fstring_ratio == 1.0
    assert profile.snake_case_ratio == 1.0


def test_analyze_skips_venv(tmp_path):
    (tmp_path / "real.py").write_text(_SAMPLE, encoding="utf-8")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "junk.py").write_text("x='1'\n", encoding="utf-8")
    profile = style.analyze_paths([str(tmp_path)])
    assert profile.files_analyzed == 1


def test_analyze_empty_dir(tmp_path):
    profile = style.analyze_paths([str(tmp_path)])
    assert profile.files_analyzed == 0
    assert profile.functions == 0


def test_analyze_tolerates_syntax_errors(tmp_path):
    (tmp_path / "bad.py").write_text("def (:\n", encoding="utf-8")
    # Should not raise; the bad file is counted but yields no functions.
    profile = style.analyze_paths([str(tmp_path)])
    assert profile.functions == 0


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_summarize_reflects_conventions(sample_repo):
    profile = style.analyze_paths([str(sample_repo)])
    summary = style.summarize(profile)
    assert "double quotes" in summary
    assert "snake_case" in summary
    assert "type hints" in summary
    assert "f-strings" in summary


def test_summarize_empty_profile_is_blank():
    assert style.summarize(style.StyleProfile()) == ""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip(sample_repo, tmp_path):
    profile = style.analyze_paths([str(sample_repo)])
    path = tmp_path / "style.json"
    style.save_profile(profile, path)
    loaded = style.load_profile(path)
    assert loaded is not None
    assert loaded.functions == profile.functions
    assert loaded.double_quote_ratio == profile.double_quote_ratio


def test_load_missing_returns_none(tmp_path):
    assert style.load_profile(tmp_path / "nope.json") is None


def test_clear_profile(sample_repo, tmp_path):
    path = tmp_path / "style.json"
    style.save_profile(style.analyze_paths([str(sample_repo)]), path)
    assert style.clear_profile(path) is True
    assert style.load_profile(path) is None


# ---------------------------------------------------------------------------
# Integration with config toggle
# ---------------------------------------------------------------------------

def test_style_context_off_returns_none(sample_repo, tmp_path):
    path = tmp_path / "style.json"
    style.save_profile(style.analyze_paths([str(sample_repo)]), path)
    cfg = CritiqueConfig(style_learning=False)
    assert style.style_context_for_prompts(cfg, path) is None


def test_style_context_on_returns_summary(sample_repo, tmp_path):
    path = tmp_path / "style.json"
    style.save_profile(style.analyze_paths([str(sample_repo)]), path)
    cfg = CritiqueConfig(style_learning=True)
    note = style.style_context_for_prompts(cfg, path)
    assert note is not None
    assert "conventions" in note


def test_style_context_on_but_no_profile_returns_none(tmp_path):
    cfg = CritiqueConfig(style_learning=True)
    assert style.style_context_for_prompts(cfg, tmp_path / "missing.json") is None
