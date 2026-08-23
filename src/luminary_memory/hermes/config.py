"""Provider configuration: load/save $HERMES_HOME/luminary/config.json.

Config is a flat JSON file with ``0600`` permissions. Missing keys fall back to
defaults, so the file is optional and forward-compatible.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR = "luminary"
_CONFIG_FILE = "config.json"

_DEFAULTS: dict = {
    "mode": "hybrid",  # "context" | "tools" | "hybrid"
    "db_path": "",  # "" -> $HERMES_HOME/luminary/memory.db
    "backend": "sqlite",  # "sqlite" | "pgvector"
    "recall_limit": 10,
    "token_budget": 2048,
    "auto_recall": True,
    "recall_sync": False,
    "auto_retain": True,
    "retain_every_n_turns": 1,
    "retain_user_prefix": "User",
    "retain_assistant_prefix": "Assistant",
    "ingest_llm": False,
    "llm_base_url": "",
    "llm_model": "",
    "llm_timeout": 60,
    "llm_api_key": "",
    "recall_indicator": True,
    "retain_indicator": True,
    "extract_on_session_end": False,
    "auto_maintain": False,  # LLM store review on session end (needs ingest_llm)
    "consolidate_semantic": True,  # embedding-cosine consolidation in lifecycle
    "importance_auto": True,  # auto-estimate importance on ingest/lifecycle
    "max_memories": 1000,  # hard cap on store size; oldest/lowest-importance pruned when exceeded
    "core_tag": "core",  # tag marking DB-backed core memories (always loaded every session, like MEMORY.md)
    "core_top_n": 12,  # max core memories injected into the system prompt
    "core_budget": 8000,  # max chars of core memory injected into the system prompt
    "importance_recall_boost": 1.0,  # ranking bonus multiplier for memories at importance >= 0.8
    "recall_min_score": 0.0,  # score floor for recall results; weak results may be empty.
}


def _config_path(hermes_home: str) -> Path:
    return Path(hermes_home) / _CONFIG_DIR / _CONFIG_FILE


def _default_config() -> dict:
    return dict(_DEFAULTS)


def load_config(hermes_home: str) -> dict:
    """Load config from disk, filling defaults for missing keys."""
    cfg = _default_config()
    path = _config_path(hermes_home)
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                cfg.update({k: v for k, v in stored.items() if k in _DEFAULTS})
            else:
                logger.warning(
                    "load_config: ignoring non-object config at %s; using defaults",
                    path,
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # Keep startup resilient, but make a mode/DB fallback visible in
            # the provider log instead of letting it masquerade as amnesia.
            logger.warning(
                "load_config: ignoring unreadable config at %s (%s); using defaults",
                path,
                type(exc).__name__,
            )
    return cfg


def save_config(values: dict, hermes_home: str) -> None:
    """Persist config values to disk with 0600 permissions.

    Unspecified keys are preserved from the current on-disk state; defaults are
    used when nothing has been persisted yet.
    """
    current = load_config(hermes_home)
    known = {k: v for k, v in values.items() if k in _DEFAULTS}
    unknown = {k for k in values if k not in _DEFAULTS}
    if unknown:
        logger.warning(
            "save_config: dropping unknown keys (not in _DEFAULTS): %s",
            sorted(unknown),
        )
    current.update(known)

    cfg_dir = Path(hermes_home) / _CONFIG_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / _CONFIG_FILE
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
