"""Dashboard config schema for the Luminary Memory provider.

This module is a pure-data contract: it must not import any agent runtime code,
because the Hermes dashboard loads it by path (``plugins.memory.config_schema``
is the only import, and it is itself data-only).
"""

from plugins.memory.config_schema import (  # type: ignore[import-not-found]
    STORAGE_FLAT_JSON,
    ProviderConfigSchema,
)

CONFIG_SCHEMA = ProviderConfigSchema(
    name="luminary",
    label="Luminary Memory",
    storage=STORAGE_FLAT_JSON,
    fields=[
        {"key": "mode", "label": "Mode", "type": "select", "inline": True},
        {"key": "db_path", "label": "Database path", "type": "text", "inline": True},
        {"key": "backend", "label": "Backend", "type": "select", "inline": True},
        {"key": "recall_limit", "label": "Recall limit", "type": "number", "inline": True},
        {"key": "token_budget", "label": "Token budget", "type": "number", "inline": True},
        {"key": "auto_recall", "label": "Auto recall", "type": "boolean", "inline": True},
        {"key": "auto_retain", "label": "Auto retain", "type": "boolean", "inline": True},
        {"key": "recall_sync", "label": "Synchronous recall", "type": "boolean"},
        {"key": "retain_every_n_turns", "label": "Retain every N turns", "type": "number"},
        {"key": "retain_user_prefix", "label": "User prefix", "type": "text"},
        {"key": "retain_assistant_prefix", "label": "Assistant prefix", "type": "text"},
        {"key": "ingest_llm", "label": "LLM enrichment", "type": "boolean"},
        {"key": "llm_base_url", "label": "LLM base URL", "type": "text"},
        {"key": "llm_model", "label": "LLM model", "type": "text"},
        {"key": "llm_timeout", "label": "LLM timeout (s)", "type": "number"},
        {"key": "recall_indicator", "label": "Recall indicator", "type": "boolean"},
        {"key": "retain_indicator", "label": "Retain indicator", "type": "boolean"},
    ],
)
