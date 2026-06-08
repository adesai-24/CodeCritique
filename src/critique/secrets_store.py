"""
Secure API-key storage for CodeCritique.

Why a separate module from :mod:`critique.config`?
--------------------------------------------------
API keys are secrets and must be handled differently from ordinary settings:

* They are stored in ``~/.codecritique/secrets.env`` with ``0600`` permissions
  (owner read/write only) so other users on a shared machine can't read them.
* That directory is git-ignored, and the file uses a ``.env`` format that
  common secret-scanners recognise — it is never committed.
* Keys are masked (``AIza…q7Yk``) whenever they are printed.

Resolution precedence for a provider's key (highest wins)
---------------------------------------------------------
1. A provider-specific environment variable (e.g. ``GEMINI_API_KEY``).
2. A recognised alias env var (e.g. ``GOOGLE_API_KEY`` for Gemini).
3. The on-disk secrets file.

This means CI systems and one-off shells can export a key without ever writing
it to disk, while interactive users can persist a key once with
``codecritique config set-key``.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Dict, List, Optional

from critique.config import CONFIG_DIR

SECRETS_PATH = CONFIG_DIR / "secrets.env"

# Canonical env var per provider, plus any well-known aliases people already
# have set in their shell.  The first name is the canonical one we write.
PROVIDER_ENV_VARS: Dict[str, List[str]] = {
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    # Local servers usually need no key; an optional one is supported for
    # authenticated vLLM / OpenAI-compatible gateways.
    "vllm": ["VLLM_API_KEY", "OPENAI_API_KEY"],
    "ollama": ["OLLAMA_API_KEY"],
}


def canonical_env_var(provider: str) -> Optional[str]:
    names = PROVIDER_ENV_VARS.get(provider.lower())
    return names[0] if names else None


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

def mask_key(key: Optional[str]) -> str:
    """Return a safe-to-display version of a key, e.g. ``AIza…q7Yk``."""
    if not key:
        return "(not set)"
    key = key.strip()
    if len(key) <= 8:
        return "…" * 4
    return f"{key[:4]}…{key[-4:]}"


# ---------------------------------------------------------------------------
# Secrets file I/O (.env-style)
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def _read_secrets_file(path: Optional[Path] = None) -> Dict[str, str]:
    path = path or SECRETS_PATH
    out: Dict[str, str] = {}
    try:
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = _LINE_RE.match(line)
            if not match:
                continue
            name, value = match.group(1), match.group(2)
            # Strip optional surrounding quotes.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            out[name] = value
    except Exception:
        return {}
    return out


def _write_secrets_file(values: Dict[str, str], path: Optional[Path] = None) -> Path:
    path = path or SECRETS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CodeCritique API keys — DO NOT COMMIT.",
        "# Managed by `codecritique config set-key`. Permissions are locked to 0600.",
    ]
    for name in sorted(values):
        lines.append(f'{name}="{values[name]}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _lock_permissions(path)
    return path


def _lock_permissions(path: Path) -> None:
    """Restrict the secrets file to owner read/write (best effort)."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except Exception:
        # Filesystems without POSIX perms (e.g. some Windows setups) just skip.
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_api_key(provider: str, path: Optional[Path] = None) -> Optional[str]:
    """Resolve the API key for a provider via env vars then the secrets file."""
    names = PROVIDER_ENV_VARS.get(provider.lower(), [])
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    stored = _read_secrets_file(path)
    for name in names:
        if stored.get(name):
            return stored[name].strip()
    return None


def set_api_key(provider: str, key: str, path: Optional[Path] = None) -> Path:
    """Persist a provider's key to the permission-locked secrets file."""
    name = canonical_env_var(provider)
    if not name:
        raise ValueError(f"Unknown provider: {provider!r}")
    values = _read_secrets_file(path)
    values[name] = key.strip()
    return _write_secrets_file(values, path)


def delete_api_key(provider: str, path: Optional[Path] = None) -> bool:
    """Remove a provider's stored key. Returns True if a key was removed."""
    name = canonical_env_var(provider)
    if not name:
        return False
    values = _read_secrets_file(path)
    if name in values:
        del values[name]
        _write_secrets_file(values, path)
        return True
    return False


def key_source(provider: str, path: Optional[Path] = None) -> str:
    """Describe where a provider's key is coming from, for diagnostics."""
    names = PROVIDER_ENV_VARS.get(provider.lower(), [])
    for name in names:
        if os.environ.get(name):
            return f"environment ({name})"
    stored = _read_secrets_file(path)
    for name in names:
        if stored.get(name):
            return "secrets file"
    return "unset"
