"""Tests for secure API-key storage (critique.secrets_store)."""

import os
import stat

import pytest

from critique import secrets_store


@pytest.fixture()
def secrets_path(tmp_path):
    return tmp_path / "secrets.env"


def test_mask_key_hides_middle():
    assert secrets_store.mask_key("AIzaSyABCDEFGHq7Yk") == "AIza…q7Yk"


def test_mask_key_handles_none_and_short():
    assert secrets_store.mask_key(None) == "(not set)"
    # Keys of 8 chars or fewer are fully masked (never reveal head+tail).
    assert secrets_store.mask_key("short") == "…" * 4


def test_set_and_get_key(secrets_path):
    secrets_store.set_api_key("gemini", "my-secret-key", secrets_path)
    assert secrets_store.get_api_key("gemini", secrets_path) == "my-secret-key"


def test_secrets_file_permissions_locked(secrets_path):
    secrets_store.set_api_key("gemini", "k", secrets_path)
    mode = stat.S_IMODE(os.stat(secrets_path).st_mode)
    # Owner-only read/write (group/other have no access).
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def test_env_var_takes_precedence(secrets_path, monkeypatch):
    secrets_store.set_api_key("gemini", "file-key", secrets_path)
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    assert secrets_store.get_api_key("gemini", secrets_path) == "env-key"


def test_alias_env_var_resolves(monkeypatch, secrets_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-aliased")
    assert secrets_store.get_api_key("gemini", secrets_path) == "google-aliased"


def test_delete_key(secrets_path):
    secrets_store.set_api_key("openai", "sk-test", secrets_path)
    assert secrets_store.delete_api_key("openai", secrets_path) is True
    assert secrets_store.get_api_key("openai", secrets_path) is None
    assert secrets_store.delete_api_key("openai", secrets_path) is False


def test_key_source_reports_origin(secrets_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert secrets_store.key_source("openai", secrets_path) == "unset"
    secrets_store.set_api_key("openai", "sk", secrets_path)
    assert secrets_store.key_source("openai", secrets_path) == "secrets file"
    monkeypatch.setenv("OPENAI_API_KEY", "env")
    assert "environment" in secrets_store.key_source("openai", secrets_path)


def test_unknown_provider_set_raises(secrets_path):
    with pytest.raises(ValueError):
        secrets_store.set_api_key("not-a-provider", "k", secrets_path)


def test_keys_survive_multiple_writes(secrets_path):
    secrets_store.set_api_key("gemini", "g", secrets_path)
    secrets_store.set_api_key("openai", "o", secrets_path)
    assert secrets_store.get_api_key("gemini", secrets_path) == "g"
    assert secrets_store.get_api_key("openai", secrets_path) == "o"
