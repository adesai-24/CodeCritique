"""Tests for the Phase 6 config system and provider abstraction."""

import os
import tempfile
from pathlib import Path
import pytest

from critique.config import load_config, write_starter_config, Config, OllamaConfig


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def test_load_config_returns_defaults_when_no_file(monkeypatch):
    """load_config() returns sensible defaults when config.toml is absent."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr("critique.config.CONFIG_PATH", Path(tmp) / "config.toml")
        cfg = load_config()
    assert cfg.provider == "ollama"
    assert cfg.model == "qwen2.5-coder:7b"
    assert cfg.max_file_chars == 30_000
    assert cfg.skip_checkers == []
    assert cfg.severity_overrides == {}


def test_load_config_reads_toml(monkeypatch):
    """load_config() parses a TOML file correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        config_file = Path(tmp) / "config.toml"
        config_file.write_text(
            'provider = "openai"\nmodel = "gpt-4o-mini"\nmax_file_chars = 10000\n'
            'skip_checkers = ["coverage"]\n[severity_overrides]\nE501 = "INFO"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("critique.config.CONFIG_PATH", config_file)
        cfg = load_config()

    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.max_file_chars == 10_000
    assert cfg.skip_checkers == ["coverage"]
    assert cfg.severity_overrides == {"E501": "INFO"}


def test_load_config_env_overrides_file(monkeypatch):
    """CRITIQUE_PROVIDER and CRITIQUE_MODEL env vars override the file."""
    with tempfile.TemporaryDirectory() as tmp:
        config_file = Path(tmp) / "config.toml"
        config_file.write_text('provider = "ollama"\nmodel = "qwen2.5-coder:7b"\n', encoding="utf-8")
        monkeypatch.setattr("critique.config.CONFIG_PATH", config_file)
        monkeypatch.setenv("CRITIQUE_PROVIDER", "anthropic")
        monkeypatch.setenv("CRITIQUE_MODEL", "claude-haiku-4-5-20251001")
        cfg = load_config()

    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-haiku-4-5-20251001"


def test_load_config_ollama_base_url(monkeypatch):
    """Custom Ollama base_url is respected."""
    with tempfile.TemporaryDirectory() as tmp:
        config_file = Path(tmp) / "config.toml"
        config_file.write_text(
            '[ollama]\nbase_url = "http://myserver:11434"\n', encoding="utf-8"
        )
        monkeypatch.setattr("critique.config.CONFIG_PATH", config_file)
        cfg = load_config()

    assert cfg.ollama.base_url == "http://myserver:11434"


def test_write_starter_config_creates_file(monkeypatch):
    """write_starter_config() creates a readable TOML file."""
    with tempfile.TemporaryDirectory() as tmp:
        config_file = Path(tmp) / "config.toml"
        monkeypatch.setattr("critique.config.CONFIG_PATH", config_file)
        monkeypatch.setattr("critique.config.CONFIG_DIR", Path(tmp))
        write_starter_config()
        assert config_file.exists()
        content = config_file.read_text(encoding="utf-8")

    assert "provider" in content
    assert "model" in content


# ---------------------------------------------------------------------------
# Severity overrides
# ---------------------------------------------------------------------------

def test_apply_severity_overrides_changes_severity():
    from critique.runner import _apply_severity_overrides
    from critique.checkers.base import Issue, Severity

    issues = [
        Issue("f.py", 1, 0, "msg", "E501", Severity.WARNING),
    ]
    result = _apply_severity_overrides(issues, {"E501": "INFO"})
    assert result[0].severity == Severity.INFO


def test_apply_severity_overrides_ignores_unknown_code():
    from critique.runner import _apply_severity_overrides
    from critique.checkers.base import Issue, Severity

    issues = [Issue("f.py", 1, 0, "msg", "RUFF99", Severity.WARNING)]
    result = _apply_severity_overrides(issues, {"E501": "FATAL"})
    assert result[0].severity == Severity.WARNING


def test_apply_severity_overrides_ignores_bad_severity_string():
    from critique.runner import _apply_severity_overrides
    from critique.checkers.base import Issue, Severity

    issues = [Issue("f.py", 1, 0, "msg", "E501", Severity.WARNING)]
    result = _apply_severity_overrides(issues, {"E501": "INVALID"})
    assert result[0].severity == Severity.WARNING


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def test_get_llm_provider_returns_ollama_by_default():
    """With provider='ollama', get_llm_provider returns an OllamaProvider."""
    from critique.ai.providers import get_llm_provider, OllamaProvider

    cfg = Config()  # defaults to ollama
    provider = get_llm_provider(cfg)
    assert isinstance(provider, OllamaProvider)


def test_get_llm_provider_anthropic_requires_key(monkeypatch):
    """Without ANTHROPIC_API_KEY, requesting anthropic raises RuntimeError."""
    from critique.ai.providers import get_llm_provider

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = Config(provider="anthropic", model="claude-haiku-4-5-20251001")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_llm_provider(cfg)


def test_get_llm_provider_openai_requires_key(monkeypatch):
    """Without OPENAI_API_KEY, requesting openai raises RuntimeError."""
    from critique.ai.providers import get_llm_provider

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = Config(provider="openai", model="gpt-4o-mini")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_llm_provider(cfg)


def test_get_llm_provider_anthropic_with_key(monkeypatch):
    """With ANTHROPIC_API_KEY set, get_llm_provider returns AnthropicProvider."""
    from critique.ai.providers import get_llm_provider, AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
    cfg = Config(provider="anthropic", model="claude-haiku-4-5-20251001")
    provider = get_llm_provider(cfg)
    assert isinstance(provider, AnthropicProvider)
    assert provider.is_available()


def test_get_llm_provider_openai_with_key(monkeypatch):
    """With OPENAI_API_KEY set, get_llm_provider returns OpenAIProvider."""
    from critique.ai.providers import get_llm_provider, OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")
    cfg = Config(provider="openai", model="gpt-4o-mini")
    provider = get_llm_provider(cfg)
    assert isinstance(provider, OpenAIProvider)
    assert provider.is_available()


# ---------------------------------------------------------------------------
# Cost guard
# ---------------------------------------------------------------------------

def test_anthropic_cost_guard_raises_when_over_limit():
    """AnthropicProvider._check_cost raises when estimated cost exceeds cap."""
    from critique.ai.providers import AnthropicProvider

    provider = AnthropicProvider(model="claude-sonnet-4-6", api_key="fake")
    provider._session_cost = 0.499
    # ~250k tokens × $0.000003 = $0.75 → over cap
    long_prompt = "x" * 1_000_000
    with pytest.raises(RuntimeError, match="cap"):
        provider._check_cost(long_prompt)


def test_openai_cost_guard_raises_when_over_limit():
    """OpenAIProvider._check_cost raises when estimated cost exceeds cap."""
    from critique.ai.providers import OpenAIProvider

    provider = OpenAIProvider(model="gpt-4o", api_key="fake")
    provider._session_cost = 0.499
    # ~250k tokens × $0.0000025 = $0.625 → over cap
    long_prompt = "x" * 1_000_000
    with pytest.raises(RuntimeError, match="cap"):
        provider._check_cost(long_prompt)


# ---------------------------------------------------------------------------
# Skip checkers
# ---------------------------------------------------------------------------

def test_scan_files_skips_checker_by_name(monkeypatch):
    """Passing skip_checkers={"ruff"} omits RuffChecker from the run."""
    from critique import runner
    from critique.checkers.base import Issue, Severity

    with tempfile.TemporaryDirectory() as tmp:
        file_path = Path(tmp) / "sample.py"
        file_path.write_text("x = 1\n", encoding="utf-8")

        called: dict = {}

        class TrackingRuff:
            name = "Ruff (Lint)"
            def run(self, files):
                called["ruff"] = True
                return []

        class NullChecker:
            name = "Null"
            def run(self, files):
                return []

        monkeypatch.setattr(runner, "RuffChecker", TrackingRuff)
        monkeypatch.setattr(runner, "BanditChecker", NullChecker)
        monkeypatch.setattr(runner, "MypyChecker", NullChecker)
        monkeypatch.setattr(runner, "CoverageChecker", NullChecker)

        runner.scan_files([str(file_path)], use_ai=False, skip_checkers={"ruff"})

    assert "ruff" not in called, "RuffChecker should have been skipped"


def test_scan_files_ai_only_skips_static_checkers(monkeypatch):
    """ai_only=True skips all static checkers regardless of skip_checkers."""
    from critique import runner

    with tempfile.TemporaryDirectory() as tmp:
        file_path = Path(tmp) / "sample.py"
        file_path.write_text("x = 1\n", encoding="utf-8")

        called: dict = {}

        class TrackingChecker:
            name = "Tracking"
            def run(self, files):
                called["static"] = True
                return []

        monkeypatch.setattr(runner, "RuffChecker", TrackingChecker)
        monkeypatch.setattr(runner, "BanditChecker", TrackingChecker)
        monkeypatch.setattr(runner, "MypyChecker", TrackingChecker)
        monkeypatch.setattr(runner, "CoverageChecker", TrackingChecker)

        runner.scan_files([str(file_path)], use_ai=False, ai_only=True)

    assert "static" not in called, "Static checkers should have been skipped in ai_only mode"
