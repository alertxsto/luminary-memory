"""Secret-free, profile-local settings persistence for the shared inspector."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from luminary_memory.hermes.config import _DEFAULTS, load_config, save_config

# Store/identity/credentials are deliberately not user-editable through a view.
_EDITABLE = frozenset({
    "mode", "recall_limit", "token_budget", "auto_recall", "recall_sync", "auto_retain",
    "retain_every_n_turns", "retain_user_prefix", "retain_assistant_prefix", "ingest_llm",
    "recall_indicator", "retain_indicator", "extract_on_session_end", "auto_maintain",
    "consolidate_semantic", "importance_auto", "max_memories", "core_tag", "core_top_n",
    "core_budget", "importance_recall_boost", "recall_min_score", "llm_timeout", "llm_model",
})
_LOCK = threading.RLock()


class HermesSettingsAdapter:
    """One native adapter instance is bound to one authenticated profile home."""

    def __init__(self, home: str):
        self.home = str(Path(home).resolve())

    def read(self, context) -> dict:
        if str(Path(context.profile_id).resolve()) != self.home:
            raise PermissionError("Settings profile changed")
        from agent.secret_scope import get_secret
        config = load_config(self.home)
        values = {key: config[key] for key in sorted(_EDITABLE)}
        revision = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        return {"values": values, "revision": revision, "editable": sorted(_EDITABLE),
                "secret_presence": {"llm_api_key": bool(get_secret("LUMINARY_LLM_API_KEY")),
                                    "pg_dsn": bool(get_secret("LUMINARY_PG_DSN"))},
                "readiness": {"settings_profile": "bound", "provider_restart_required": True,
                              "note": "Saving settings does not activate the provider. Restart existing provider sessions to apply changes."}}

    def apply(self, context, changes: dict, expected_revision, *, on_external_effect) -> dict:
        from luminary_memory.inspector.mutations import Conflict
        if not isinstance(changes, dict) or not changes or set(changes) - _EDITABLE:
            raise PermissionError("Unsupported Hermes setting")
        for key, value in changes.items():
            default = _DEFAULTS[key]
            if isinstance(default, bool):
                valid = type(value) is bool
            elif isinstance(default, int):
                valid = type(value) is int and value >= 0
            elif isinstance(default, float):
                valid = type(value) in (int, float) and 0 <= value <= 1000
            else:
                valid = isinstance(value, str) and len(value) <= 4096
            if not valid or (key == "mode" and value not in {"context", "tools", "hybrid"}):
                raise ValueError("Invalid Hermes setting value")
        # Serialize same-process writers; save_config atomically replaces the
        # native flat-json file. Revision is checked again inside that lock.
        with _LOCK:
            if self.read(context)["revision"] != expected_revision:
                raise Conflict("Hermes settings changed; refresh before saving")
            on_external_effect()
            save_config(changes, self.home)
            return self.read(context)
