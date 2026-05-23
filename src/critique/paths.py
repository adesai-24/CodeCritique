"""
Single source of truth for every path CodeCritique writes to disk.

All data lives under ~/.codecritique/:

  ~/.codecritique/
    cache/
      inference.json      — LLM response cache (exact + semantic hits)
      semantic.json       — per-system-prompt fingerprint index
    reports/
      <timestamp>_<id>.json
"""

from pathlib import Path

BASE_DIR: Path = Path.home() / ".codecritique"
CACHE_DIR: Path = BASE_DIR / "cache"
REPORTS_DIR: Path = BASE_DIR / "reports"

# Individual cache files (used by LLMClient)
INFERENCE_CACHE: Path = CACHE_DIR / "inference.json"
SEMANTIC_INDEX: Path = CACHE_DIR / "semantic.json"
