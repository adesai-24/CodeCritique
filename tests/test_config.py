"""Tests for the configuration system (critique.config)."""

import json

import pytest

from critique import config as cfg_mod
from critique.config import CritiqueConfig, DEFAULT_PROVIDER, DEFAULT_MODELS


@pytest.fixture()
def cfg_path(tmp_path):
    return tmp_path / "config.json"


def test_default_provider_is_gemini():
    cfg = CritiqueConfig()
    assert cfg.provider == DEFAULT_PROVIDER == "gemini"


def test_resolved_model_uses_provider_default():
    assert CritiqueConfig(provider="ollama").resolved_model() == DEFAULT_MODELS["ollama"]
    assert CritiqueConfig(provider="gemini").resolved_model() == DEFAULT_MODELS["gemini"]


def test_resolved_model_prefers_explicit_model():
    assert CritiqueConfig(provider="gemini", model="custom").resolved_model() == "custom"


def test_load_missing_file_returns_defaults(cfg_path):
    cfg = cfg_mod.load_config(cfg_path)
    assert cfg.provider == "gemini"


def test_save_and_load_roundtrip(cfg_path):
    cfg = CritiqueConfig(provider="openai", model="gpt-4o-mini", temperature=0.5)
    cfg_mod.save_config(cfg, cfg_path)
    loaded = cfg_mod.load_config(cfg_path)
    assert loaded.provider == "openai"
    assert loaded.model == "gpt-4o-mini"
    assert loaded.temperature == 0.5


def test_set_value_updates_typed_field(cfg_path):
    cfg_mod.set_value("provider", "anthropic", cfg_path)
    cfg_mod.set_value("temperature", "0.7", cfg_path)
    loaded = cfg_mod.load_config(cfg_path)
    assert loaded.provider == "anthropic"
    assert loaded.temperature == 0.7


def test_set_value_unknown_key_goes_to_extra(cfg_path):
    cfg_mod.set_value("suggestion_mode", "strict", cfg_path)
    loaded = cfg_mod.load_config(cfg_path)
    assert loaded.extra["suggestion_mode"] == "strict"


def test_set_value_none_clears_optional(cfg_path):
    cfg_mod.set_value("model", "gpt-4o-mini", cfg_path)
    cfg_mod.set_value("model", "none", cfg_path)
    loaded = cfg_mod.load_config(cfg_path)
    assert loaded.model is None


def test_corrupt_file_falls_back_to_defaults(cfg_path):
    cfg_path.write_text("{ not json", encoding="utf-8")
    cfg = cfg_mod.load_config(cfg_path)
    assert cfg.provider == "gemini"


def test_env_override_provider(cfg_path, monkeypatch):
    cfg_mod.save_config(CritiqueConfig(provider="openai"), cfg_path)
    monkeypatch.setenv("CODECRITIQUE_PROVIDER", "anthropic")
    cfg = cfg_mod.load_config(cfg_path)
    assert cfg.provider == "anthropic"


def test_unknown_top_level_key_preserved(cfg_path):
    cfg_path.write_text(json.dumps({"provider": "gemini", "future_flag": 1}), encoding="utf-8")
    cfg = cfg_mod.load_config(cfg_path)
    assert cfg.extra["future_flag"] == 1
