"""Tests for adaptive 'learn as you review' style blending."""

from __future__ import annotations

from critique.style import (
    DEFAULT_LEARN_RATE,
    StyleProfile,
    learn_incrementally,
    load_profile,
    merge_profiles,
    save_profile,
)


def _profile(**kw) -> StyleProfile:
    base = dict(files_analyzed=1, functions=5)
    base.update(kw)
    return StyleProfile(**base)


def test_merge_blends_ratios_via_ema():
    existing = _profile(double_quote_ratio=1.0, type_hint_ratio=1.0)
    batch = _profile(double_quote_ratio=0.0, type_hint_ratio=0.0)

    merged = merge_profiles(existing, batch, alpha=0.15)

    # One batch only nudges: a single opposite-style batch cannot flip the ratio.
    assert merged.double_quote_ratio == 0.85
    assert merged.type_hint_ratio == 0.85


def test_merge_accumulates_counters():
    existing = _profile(files_analyzed=3, functions=10)
    batch = _profile(files_analyzed=2, functions=4)

    merged = merge_profiles(existing, batch)

    assert merged.files_analyzed == 5
    assert merged.functions == 14


def test_merge_ignores_empty_batch():
    existing = _profile(double_quote_ratio=1.0)
    empty = StyleProfile()  # functions == 0 → no signal

    assert merge_profiles(existing, empty) is existing


def test_no_overtraining_over_many_batches():
    """Repeated opposite-style batches converge but never fully flip in one step."""
    profile = _profile(double_quote_ratio=1.0)
    for _ in range(3):
        batch = _profile(double_quote_ratio=0.0)
        profile = merge_profiles(profile, batch, alpha=DEFAULT_LEARN_RATE)
        # Always strictly between the two extremes — gradual, not abrupt.
        assert 0.0 < profile.double_quote_ratio < 1.0


def test_learn_incrementally_seeds_then_blends(tmp_path, monkeypatch):
    sample = tmp_path / "mod.py"
    sample.write_text(
        'def greet(name: str) -> str:\n'
        '    """Say hi."""\n'
        '    return f"hi {name}"\n',
        encoding="utf-8",
    )
    store = tmp_path / "style_profile.json"

    # First call seeds the profile from scratch.
    first = learn_incrementally([str(sample)], path=store)
    assert first is not None and first.functions >= 1
    assert load_profile(store) is not None

    funcs_before = load_profile(store).functions
    # Second call accumulates rather than replacing.
    second = learn_incrementally([str(sample)], path=store)
    assert second.functions > funcs_before


def test_learn_incrementally_handles_no_python(tmp_path):
    (tmp_path / "notes.txt").write_text("not python", encoding="utf-8")
    assert learn_incrementally([str(tmp_path)], path=tmp_path / "p.json") is None
