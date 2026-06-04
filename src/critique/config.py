"""
CodeCritique user configuration.

Settings are stored as JSON in ``~/.codecritique/config.json`` and managed
through the ``codecritique config`` CLI commands.  We deliberately use JSON
(not TOML) for the machine-managed store because the standard library can both
read *and* write it without an extra dependency, which keeps the CLI's
``config set`` round-trip dependency-free on every supported Python version.

Resolution precedence (highest wins)
------------------------------------
1. Explicit keyword arguments passed in code (e.g. ``LLMClient(model=...)``).
2. Environment variables (``CODECRITIQUE_PROVIDER``, ``CODECRITIQUE_MODEL``,
   ``CODECRITIQUE_BASE_URL``, ``CODECRITIQUE_TEMPERATURE``).
3. The on-disk config file.
4. Built-in defaults (provider = ``gemini``, the free tier).

API keys are *never* stored here — they live in a separate, permission-locked
secrets file managed by :mod:`critique.secrets_store`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(os.environ.get("CODECRITIQUE_HOME", str(Path.home() / ".codecritique")))
CONFIG_PATH = CONFIG_DIR / "config.json"

# Default provider is Gemini because Google offers a generous free API tier.
DEFAULT_PROVIDER = "gemini"

# Per-provider default models.  ``None`` in the config means "use the provider
# default", so users only ever have to set a model if they want to override it.
DEFAULT_MODELS: Dict[str, str] = {
    "gemini": "gemini-2.0-flash",
    "ollama": "qwen2.5-coder:7b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "vllm": "Qwen/Qwen2.5-Coder-7B-Instruct",
}

# Providers we know how to build.  Kept here so the CLI can validate input and
# print a helpful list without importing every optional SDK.
SUPPORTED_PROVIDERS = tuple(DEFAULT_MODELS.keys())


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------

@dataclass
class CritiqueConfig:
    """User-facing configuration for the AI pipeline."""

    provider: str = DEFAULT_PROVIDER
    model: Optional[str] = None          # None → provider default
    base_url: Optional[str] = None       # for ollama / vllm / openai-compatible
    temperature: float = 0.2
    timeout: int = 300
    # Review customization (see critique.profiles).
    suggestion_mode: str = "balanced"    # built-in review profile
    project_context: Optional[str] = None    # author-provided context for the AI
    custom_instructions: Optional[str] = None  # extra reviewer instructions
    # Reserved for later features (style learning, etc.).
    # Stored verbatim so newer settings written by a newer CLI survive an older
    # one round-tripping the file.
    extra: Dict[str, Any] = field(default_factory=dict)

    def resolved_model(self) -> str:
        """Return the effective model name for the active provider."""
        if self.model:
            return self.model
        return DEFAULT_MODELS.get(self.provider, DEFAULT_MODELS[DEFAULT_PROVIDER])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_KNOWN_FIELDS = {f.name for f in fields(CritiqueConfig)}


def _coerce(raw: Dict[str, Any]) -> CritiqueConfig:
    """Build a CritiqueConfig from a raw dict, tolerating unknown keys."""
    known = {k: v for k, v in raw.items() if k in _KNOWN_FIELDS}
    extra = dict(raw.get("extra") or {})
    # Stash any unrecognised top-level keys in ``extra`` so we never lose data
    # written by a newer version of the tool.
    for k, v in raw.items():
        if k not in _KNOWN_FIELDS:
            extra[k] = v
    known["extra"] = extra
    cfg = CritiqueConfig(**known)
    return cfg


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def _apply_env_overrides(cfg: CritiqueConfig) -> CritiqueConfig:
    provider = os.environ.get("CODECRITIQUE_PROVIDER")
    if provider:
        cfg.provider = provider.strip().lower()
    model = os.environ.get("CODECRITIQUE_MODEL")
    if model:
        cfg.model = model
    base_url = os.environ.get("CODECRITIQUE_BASE_URL")
    if base_url:
        cfg.base_url = base_url
    temperature = os.environ.get("CODECRITIQUE_TEMPERATURE")
    if temperature:
        try:
            cfg.temperature = float(temperature)
        except ValueError:
            pass
    return cfg


def load_config(path: Optional[Path] = None) -> CritiqueConfig:
    """Load configuration from disk, applying environment overrides.

    Never raises: a missing or corrupt file falls back to defaults so the tool
    always runs.
    """
    path = path or CONFIG_PATH
    raw: Dict[str, Any] = {}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data
    except Exception:
        raw = {}
    cfg = _coerce(raw)
    return _apply_env_overrides(cfg)


def save_config(cfg: CritiqueConfig, path: Optional[Path] = None) -> Path:
    """Persist configuration to disk, creating the directory if needed."""
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def set_value(key: str, value: Any, path: Optional[Path] = None) -> CritiqueConfig:
    """Update a single config field and persist it.

    Unknown keys are stored under ``extra`` so forward-looking settings work
    before a field is formally added to the dataclass.
    """
    # Read the on-disk values *without* env overrides so we never bake a
    # transient environment value into the persisted file.
    on_disk = _coerce(_read_raw(path))

    if key in _KNOWN_FIELDS and key != "extra":
        setattr(on_disk, key, _convert_scalar(key, value))
    else:
        on_disk.extra[key] = value
    save_config(on_disk, path)
    # Return the fully-resolved (env-aware) view for display.
    return load_config(path)


def _read_raw(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or CONFIG_PATH
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _convert_scalar(key: str, value: Any) -> Any:
    """Coerce CLI string values into the right type for typed fields."""
    if key == "temperature":
        return float(value)
    if key == "timeout":
        return int(value)
    if key == "provider" and isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, str) and value.lower() in {"none", "null", ""}:
        return None
    return value
