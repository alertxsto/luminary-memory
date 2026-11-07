"""Hermes's data-only typed provider contract, loaded by path by its dashboard.

This module deliberately requires the real Hermes schema module. It must never
import the provider/agent or replace a missing SDK with a permissive fake schema.
"""
from plugins.memory.config_schema import (
    STORAGE_FLAT_JSON,
    ProviderConfigSchema,
    ProviderField,
    ProviderFieldOption,
)

CONFIG_SCHEMA = ProviderConfigSchema(
    name="luminary",
    label="Luminary Memory",
    storage=STORAGE_FLAT_JSON,
    fields=(
        ProviderField("mode", "Mode", kind="select", default="hybrid", inline=True,
                      options=tuple(ProviderFieldOption(value, value.title()) for value in ("context", "tools", "hybrid"))),
        ProviderField("db_path", "Database path", inline=True),
        ProviderField("backend", "Backend", kind="select", default="sqlite", inline=True,
                      options=(ProviderFieldOption("sqlite", "SQLite"), ProviderFieldOption("pgvector", "PostgreSQL / pgvector"))),
        ProviderField("recall_limit", "Recall limit", kind="number", default="10", inline=True),
        ProviderField("max_memories", "Max memories (store cap)", kind="number", default="1000", inline=True),
        ProviderField("token_budget", "Token budget", kind="number", default="2048", inline=True),
        ProviderField("auto_recall", "Auto recall", kind="bool", default="true", inline=True),
        ProviderField("auto_retain", "Auto retain", kind="bool", default="true", inline=True),
        ProviderField("recall_sync", "Synchronous recall", kind="bool", default="false"),
        ProviderField("retain_every_n_turns", "Retain every N turns", kind="number", default="1"),
        ProviderField("retain_user_prefix", "User prefix", default="User"),
        ProviderField("retain_assistant_prefix", "Assistant prefix", default="Assistant"),
        ProviderField("ingest_llm", "LLM memory curation", kind="bool", default="false"),
        ProviderField("auto_maintain", "Auto-maintain store (LLM)", kind="bool", default="false"),
        ProviderField("consolidate_semantic", "Semantic consolidation", kind="bool", default="true"),
        ProviderField("importance_auto", "Auto importance estimation", kind="bool", default="true"),
        ProviderField("llm_base_url", "LLM base URL"),
        ProviderField("llm_model", "LLM model"),
        ProviderField("llm_timeout", "LLM timeout (s)", kind="number", default="60"),
        ProviderField("llm_api_key", "LLM API key", kind="secret", env_key="LUMINARY_LLM_API_KEY"),
        ProviderField("pg_dsn", "PostgreSQL DSN", kind="secret", env_key="LUMINARY_PG_DSN"),
        ProviderField("recall_indicator", "Recall indicator", kind="bool", default="true"),
        ProviderField("retain_indicator", "Retain indicator", kind="bool", default="true"),
        ProviderField("core_tag", "Core memory tag", default="core"),
        ProviderField("core_top_n", "Core memory: max top N", kind="number", default="12"),
        ProviderField("core_budget", "Core memory: max chars", kind="number", default="8000"),
        ProviderField("extract_on_session_end", "Extract memories on session end", kind="bool", default="false"),
        ProviderField("importance_recall_boost", "Recall boost for important memories", kind="number", default="1.0"),
        ProviderField("recall_min_score", "Recall min score (floor)", kind="number", default="0.0"),
    ),
)
