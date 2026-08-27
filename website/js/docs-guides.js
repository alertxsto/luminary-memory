(function () {
  "use strict";

  function parameter(name, type, defaultValue, description, input) {
    return {
      name: name,
      type: type,
      defaultValue: defaultValue,
      description: description,
      input: input || "—"
    };
  }

  function table(caption, columns, rows) {
    return { caption: caption, columns: columns, rows: rows };
  }

  var ingestParameters = [
    parameter("text", "str", "required", "The fact or evidence-backed claim to store."),
    parameter("tags", "list[str] | None", "None", "Labels used for inspection, filtering, and explicit core membership."),
    parameter("source", "str | None", "None", "Origin label preserved in the memory and activity output."),
    parameter("metadata", "dict | None", "None", "Additional structured metadata; validated claims are kept here too."),
    parameter("enrich", "bool", "True", "Run the configured enricher before writing; set false for an already-curated claim."),
    parameter("importance", "float | None", "None", "Caller or enricher importance hint; the lifecycle estimator may update it."),
    parameter("user_id / session_id", "str | None", "None", "Ownership scope. A bound client cannot be overridden by a per-call value."),
    parameter("workspace_id / agent_id", "str | None", "None", "Additional ownership dimensions used before deduplication and recall."),
    parameter("observed_at", "ISO datetime | None", "now", "When the source observation happened."),
    parameter("valid_from / valid_to", "ISO datetime | None", "None", "Validity window for temporal filtering."),
    parameter("status", "active | conflicted | superseded | expired | deleted", "active", "Claim lifecycle state."),
    parameter("confidence", "float | None", "None", "Evidence confidence carried into strict recall."),
    parameter("evidence_quote", "str | None", "content", "Quote that must be grounded in source_text or the stored content."),
    parameter("source_id", "str | None", "None", "Stable external provenance identifier."),
    parameter("claim_key", "str | None", "None", "Identity for an explicit claim version chain."),
    parameter("supersedes_id", "int | None", "None", "Existing memory id explicitly replaced by this claim."),
    parameter("source_text", "str | None", "content", "Original evidence context for a distilled memory; not searchable content.")
  ];

  var recallParameters = [
    parameter("query", "str", "required", "Natural-language query used by the four-strategy planner."),
    parameter("limit", "int", "10", "Maximum returned memories; zero means unlimited."),
    parameter("token_budget", "int | None", "Settings value", "Hard cap for serialized recall context."),
    parameter("tags", "list[str] | None", "None", "Restrict candidates to memories carrying tags."),
    parameter("tag_mode", "any | all | strict", "any", "Whether one, every, or strict tag matching must be applied."),
    parameter("scope", "dict | None", "client scope", "User, workspace, agent, and session ownership filter."),
    parameter("strict", "bool | None", "Settings value", "Allow an abstain result when support or margin is weak."),
    parameter("include_conflicted", "bool", "False", "Include conflicted rows for diagnostics; normal recall hides them.")
  ];

  var libraryStorage = [
    parameter("backend", "sqlite | pgvector", "sqlite", "Storage implementation.", "LUMINARY_BACKEND"),
    parameter("db_path", "path", "luminary_memory.db", "SQLite file path.", "LUMINARY_DB_PATH"),
    parameter("pg_dsn", "DSN", "postgresql://localhost/luminary_memory", "PostgreSQL connection string for pgvector.", "LUMINARY_PG_DSN"),
    parameter("pg_hnsw_index", "bool", "false", "Build an HNSW index for large pgvector stores.", "LUMINARY_PG_HNSW_INDEX"),
    parameter("pg_hnsw_m", "int", "16", "HNSW graph degree; higher improves search/build cost tradeoff.", "LUMINARY_PG_HNSW_M"),
    parameter("pg_hnsw_ef_construction", "int", "64", "HNSW build-time exploration factor.", "LUMINARY_PG_HNSW_EF_CONSTRUCTION")
  ];

  var libraryEmbeddings = [
    parameter("embedding_model", "str", "BAAI/bge-small-en-v1.5", "Sentence-transformer used for semantic similarity.", "LUMINARY_EMBEDDING_MODEL"),
    parameter("embedding_dim", "int", "384", "Must match the selected model and pgvector column.", "LUMINARY_EMBEDDING_DIM")
  ];

  var libraryRecall = [
    parameter("rrf_k", "int", "60", "Reciprocal Rank Fusion smoothing constant.", "LUMINARY_RRF_K"),
    parameter("weight semantic / keyword / graph / temporal", "float", "0.4 / 0.3 / 0.2 / 0.1", "Per-strategy fusion weights.", "LUMINARY_WEIGHT_*"),
    parameter("recall_cliff_threshold", "float", "0.45", "Trim results after a score drop larger than this fraction.", "LUMINARY_RECALL_CLIFF_THRESHOLD"),
    parameter("dedup_jaccard_threshold", "float", "0.85", "Token-overlap threshold for removing near duplicates.", "LUMINARY_DEDUP_JACCARD_THRESHOLD"),
    parameter("token_budget", "int", "4096", "Maximum tokens serialized into context.", "LUMINARY_TOKEN_BUDGET"),
    parameter("importance_recall_boost", "float", "1.0", "Multiplier for memories with importance at least 0.8.", "LUMINARY_IMPORTANCE_RECALL_BOOST"),
    parameter("recall_min_score", "float", "0.0", "Score floor; zero disables the floor.", "LUMINARY_RECALL_MIN_SCORE"),
    parameter("query_planner", "bool", "true", "Skip strategies without a useful signal.", "LUMINARY_QUERY_PLANNER"),
    parameter("query_planner_keyword_threshold", "float", "0.9", "Strong keyword score at which planner can skip other passes.", "LUMINARY_QUERY_PLANNER_KEYWORD_THRESHOLD")
  ];

  var safetyParameters = [
    parameter("strict_recall", "bool", "false for library; true in Hermes/CLI", "Permit abstention for weak or ambiguous support.", "LUMINARY_STRICT_RECALL"),
    parameter("scope_include_global", "bool", "true", "Keep intentionally global legacy rows visible to scoped reads.", "LUMINARY_SCOPE_INCLUDE_GLOBAL"),
    parameter("abstention_min_confidence", "float", "0.34", "Minimum confidence for strict recall.", "LUMINARY_ABSTENTION_MIN_CONFIDENCE"),
    parameter("abstention_min_margin", "float", "0.04", "Minimum top-vs-second score margin.", "LUMINARY_ABSTENTION_MIN_MARGIN"),
    parameter("evidence_required", "bool", "false for library; true in Hermes/CLI", "Require grounded provenance before returning or mutating claims.", "LUMINARY_EVIDENCE_REQUIRED")
  ];

  var coreParameters = [
    parameter("core_tag", "str", "core", "Tag that marks DB-backed core memories.", "LUMINARY_CORE_TAG"),
    parameter("core_top_n", "int", "12", "Maximum core rows loaded into the system prompt.", "LUMINARY_CORE_TOP_N"),
    parameter("core_budget", "int", "8000", "Maximum characters in the core block.", "LUMINARY_CORE_BUDGET")
  ];

  var lifecycleParameters = [
    parameter("max_memories", "int", "1000", "Hard store cap; pinned rows at importance at least 0.9 are exempt.", "LUMINARY_MAX_MEMORIES"),
    parameter("ttl_default_seconds", "int | None", "0 (none)", "Default expiry for memories without an explicit TTL.", "LUMINARY_TTL_DEFAULT_SECONDS"),
    parameter("prune_min_importance", "float", "0.2", "Rows below this importance are prune candidates.", "LUMINARY_PRUNE_MIN_IMPORTANCE"),
    parameter("consolidate_jaccard_threshold", "float", "0.9", "Token-overlap threshold for merging near duplicates.", "LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD"),
    parameter("consolidate_semantic", "bool", "true", "Use embedding cosine before Jaccard fallback.", "LUMINARY_CONSOLIDATE_SEMANTIC"),
    parameter("importance_auto", "bool", "true", "Estimate importance from access, recency, and graph centrality.", "LUMINARY_IMPORTANCE_AUTO")
  ];

  var llmParameters = [
    parameter("ingest_llm", "bool", "false", "Enable summary extraction and grounded incremental review.", "LUMINARY_INGEST_LLM"),
    parameter("ingest_whitelist", "comma-separated list", "[]", "Optional prefixes/tags accepted for ingest.", "LUMINARY_INGEST_WHITELIST"),
    parameter("llm_base_url", "URL | None", "None", "OpenAI-compatible enrichment endpoint.", "LUMINARY_LLM_BASE_URL"),
    parameter("llm_api_key", "secret", "None", "Credential for the enrichment endpoint.", "LUMINARY_LLM_API_KEY"),
    parameter("llm_model", "str", "gpt-4o-mini", "Enricher model id.", "LUMINARY_LLM_MODEL"),
    parameter("llm_timeout", "int seconds", "10", "Library request timeout.", "LUMINARY_LLM_TIMEOUT"),
    parameter("llm_max_tokens", "int", "512", "Maximum enrichment completion size.", "LUMINARY_LLM_MAX_TOKENS")
  ];

  var compatibilityParameters = [
    parameter("rule_keywords", "str", "empty", "Legacy phrase-matcher input; not used to classify durability.", "LUMINARY_RULE_KEYWORDS"),
    parameter("rule_importance", "float", "0.9", "Pin/protection threshold, not a language keyword score.", "LUMINARY_RULE_IMPORTANCE"),
    parameter("rule_auto_replace", "bool", "true library / false Hermes", "Legacy explicit replacement path; provider disables destructive replacement.", "LUMINARY_RULE_AUTO_REPLACE"),
    parameter("rule_auto_replace_threshold", "float", "0.85", "Similarity threshold only after caller authorizes replacement.", "LUMINARY_RULE_AUTO_REPLACE_THRESHOLD")
  ];

  var providerParameters = [
    parameter("mode", "context | tools | hybrid", "hybrid", "Automatic injection, explicit tools, or both.", "config.json / dashboard"),
    parameter("db_path", "path", "empty", "Empty resolves to $HERMES_HOME/luminary/memory.db.", "config.json / dashboard"),
    parameter("backend", "sqlite | pgvector", "sqlite", "Provider storage backend.", "config.json / dashboard"),
    parameter("recall_limit", "int", "10", "Top-N durable memories per recall.", "config.json / dashboard"),
    parameter("max_memories", "int", "1000", "Hard store cap.", "config.json / dashboard"),
    parameter("token_budget", "int", "2048", "Provider recall context budget.", "config.json / dashboard"),
    parameter("auto_recall", "bool", "true", "Run recall before each response.", "config.json / dashboard"),
    parameter("auto_retain", "bool", "true", "Record exact-session episodes and queue completed turn batches.", "config.json / dashboard"),
    parameter("recall_sync", "bool", "false", "Use live recall rather than warm prefetch.", "config.json / dashboard"),
    parameter("retain_every_n_turns", "int", "1", "Batch this many completed turns per retain task.", "config.json / dashboard"),
    parameter("retain_user_prefix", "str", "User", "Structural label sent to the optional curator.", "config.json / dashboard"),
    parameter("retain_assistant_prefix", "str", "Assistant", "Structural label sent to the optional curator.", "config.json / dashboard"),
    parameter("ingest_llm", "bool", "false", "Enable curation plus serialized post-turn reconciliation.", "config.json / dashboard"),
    parameter("auto_maintain", "bool", "false", "Run full LLM store review at session end; requires ingest_llm.", "config.json / dashboard"),
    parameter("consolidate_semantic", "bool", "true", "Use semantic consolidation in lifecycle.", "config.json / dashboard"),
    parameter("importance_auto", "bool", "true", "Estimate importance on ingest/lifecycle.", "config.json / dashboard"),
    parameter("llm_base_url / llm_model", "URL / str", "empty", "OpenAI-compatible curation endpoint and model.", "config.json / dashboard"),
    parameter("llm_timeout", "int seconds", "60", "Provider curation timeout.", "config.json / dashboard"),
    parameter("llm_api_key", "secret", "empty", "Dashboard secret, stored with restrictive permissions.", "config.json / dashboard"),
    parameter("recall_indicator / retain_indicator", "bool", "true / true", "Show deterministic status messages.", "config.json / dashboard"),
    parameter("core_tag", "str", "core", "Core-memory tag.", "config.json / dashboard"),
    parameter("core_top_n / core_budget", "int", "12 / 8000", "Core row and character limits.", "config.json / dashboard"),
    parameter("extract_on_session_end", "bool", "false", "Compatibility/dashboard flag; not a second extraction mode.", "config.json / dashboard"),
    parameter("importance_recall_boost", "float", "1.0", "Ranking multiplier at importance at least 0.8.", "config.json / dashboard"),
    parameter("recall_min_score", "float", "0.0", "Provider score floor; weak results may be empty.", "config.json / dashboard")
  ];

  var toolModes = table("Provider modes", ["Mode", "Auto recall", "Auto retain", "Tools"], [
    ["context", "yes", "yes", "none"],
    ["tools", "no", "yes", "all six explicit tools"],
    ["hybrid", "yes", "yes", "all six explicit tools"]
  ]);

  window.LUMINARY_GUIDES = {
    quickstart: {
      kicker: "Build / start here",
      lead: "Install Luminary locally, write a first fact, recall it, and keep the store inspectable.",
      sections: [
        {
          title: "Install",
          paragraphs: ["SQLite is the default backend. The core retrieval pipeline is local and does not require an LLM; optional LLM calls are limited to write-time curation and maintenance."],
          code: "python -m pip install luminary-memory\n# optional Hermes provider\npython -m pip install \"luminary-memory[hermes]\"",
          tips: ["Use Python 3.11+ for the supported development/runtime path.", "Keep the SQLite file under a backed-up application data directory, not inside a disposable working tree."],
          warnings: ["The embedding model may download on first semantic recall. Retrieval itself does not call a hosted memory vendor."]
        },
        {
          title: "First use: Python",
          paragraphs: ["Ingest accepts content plus evidence, ownership, validity, claim, and provenance fields. Recall is scoped and returns a stateful result instead of an opaque list."],
          code: "from luminary_memory import MemoryClient\n\nclient = MemoryClient(db_path=\"memory.db\", scope={\"user_id\": \"u1\"})\nmid = client.ingest(\n    \"The deploy target is the staging cluster\",\n    tags=[\"deploy\"],\n    source=\"quickstart\",\n    user_id=\"u1\",\n    claim_key=\"deploy.target\",\n    evidence_quote=\"The deploy target is the staging cluster\",\n)\nresult = client.recall(\"where do we deploy?\", limit=5)\nprint(mid, result.status, result.confidence, result.provenance)",
          returns: ["ingest() returns the canonical integer id, or None for empty/whitelist-rejected input.", "recall() returns RecallResult with memories, scores, strategies_hit, status, reason, confidence, and provenance."],
          tips: ["Pass a scope at client construction for a hard ownership boundary. A bound client cannot switch user, workspace, agent, or session in a later call.", "Use claim_key plus supersedes_id for a correction; a different same-key fact without explicit supersession remains a conflict."]
        },
        {
          title: "First use: CLI",
          paragraphs: ["The CLI enables strict abstention and evidence-aware output. Scope is read from LUMINARY_USER_ID, LUMINARY_WORKSPACE_ID, LUMINARY_AGENT_ID, and LUMINARY_SESSION_ID."],
          code: "export LUMINARY_USER_ID=u1\nluminary-memory add \"The deploy target is staging\" --tags deploy --source quickstart\nluminary-memory recall \"where do we deploy?\" --limit 5 --json\nluminary-memory activity --json",
          table: table("Common command options", ["Command", "Useful parameters", "Output"], [
            ["add", "text, --tags, --source, --db-path, --backend", "added id or rejection"],
            ["recall", "query, --limit, --json", "status, confidence, memories, provenance"],
            ["activity", "--limit, --json", "active durable rows only"],
            ["list", "--limit, --offset, --json", "recent rows, most recent first"]
          ]),
          tips: ["Use --json when another process or a hook consumes the result.", "activity is not a session transcript reader: it reports persisted active durable rows, not episode-ledger entries or skipped reviews."]
        },
        {
          title: "Backup, restore, and health",
          paragraphs: ["Export/import are versioned JSON operations. Health reports a 0–100 score with duplicate, staleness, importance, graph-density, and size dimensions."],
          code: "luminary-memory export --path backup.json --no-embeddings\nluminary-memory import --path backup.json\nluminary-memory health --json\nluminary-memory lifecycle",
          returns: ["Export returns a JSON summary and can omit embedding vectors. Import recomputes missing embeddings.", "Lifecycle returns pass counts; it does not read Hermes episode rows as semantic memories."],
          tips: ["Take an export before a manual lifecycle or authority repair pass.", "For a store created during mixed-authority operation, run repair in read-only mode before automatic writes."]
        },
        {
          title: "Hermes activation",
          paragraphs: ["The installer uses the public provider boundary, selects Luminary, and disables Hermes' two native persistent surfaces so there is one durable authority."],
          code: "HERMES_PYTHON=\"$HOME/.hermes/venv/bin/python\" bash hermes/install.sh\n\n# Hermes config.yaml\nmemory:\n  provider: luminary\n  memory_enabled: false\n  user_profile_enabled: false",
          warnings: ["No Hermes source file is patched and no Hermes version is pinned. If provider discovery fails, stop and fix capability compatibility instead of re-enabling a second memory authority."]
        },
        {
          title: "Three context surfaces",
          paragraphs: ["Core rows load every session, durable recall answers the current query, and an untrusted exact-session episode fallback preserves a short active follow-up only when durable recall has no usable block."],
          bullets: ["Core: DB-backed rows tagged core, bounded by core_top_n and core_budget.", "Durable recall: semantic, keyword, temporal, and graph candidates, scoped before fusion.", "Session continuity: up to four recent exact-session episodes under existing token/internal limits; never a semantic memory and never cross-session."]
        }
      ]
    },

    "docs-index": {
      kicker: "Map / reading order",
      lead: "A source map for choosing the right note before opening implementation details.",
      sections: [
        {
          title: "Build path",
          paragraphs: ["Start with the Quickstart, then use Architecture and Python API to understand the durable engine. Configuration and Agent tools define the integration inputs and exact schemas."],
          table: table("Build references", ["Note", "Tracked source", "Use it for"], [
            ["Quickstart", "docs/quickstart.md", "Install and first verified loop"],
            ["Architecture", "docs/architecture.md", "Pipeline and authority boundaries"],
            ["Python API", "docs/api.md", "Signatures, result types, mutation contracts"],
            ["Configuration", "docs/config-reference.md", "Every engine/provider setting"],
            ["Agent tools", "docs/agent-tools.md", "Exact tool schemas and mode behavior"]
          ])
        },
        {
          title: "Operate path",
          paragraphs: ["Use Recall to reason about ranking and abstention, Lifecycle to maintain an aging store, Backends to choose storage, and CLI/Debugging to inspect behavior."],
          table: table("Operator references", ["Note", "Tracked source", "Use it for"], [
            ["Recall", "docs/recall.md", "Strategies, thresholds, budgets, continuity"],
            ["Lifecycle", "docs/lifecycle.md", "Cleanup, consolidation, pruning, repair"],
            ["Backends", "docs/backends.md", "SQLite/pgvector guarantees and extension contract"],
            ["CLI", "docs/cli.md", "Commands, flags, JSON, exit codes"],
            ["Debugging", "docs/debugging-v0.2.17.md", "Context loss, hook, gateway, transparency checks"]
          ])
        },
        {
          title: "Integrate and contribute",
          paragraphs: ["Hermes Integration, the Native Memory Migration note, and the Hermes Install Kit document the capability boundary, authority handoff, hook, and upgrade path. Security, contribution, changelog, and benchmark notes remain linked as tracked references."],
          table: table("Integration references", ["Note", "Tracked source", "Use it for"], [
            ["Hermes integration", "docs/hermes-integration.md", "Provider runtime and three surfaces"],
            ["Native memory migration", "scripts/migrate_native_memory.py", "Lossless MEMORY.md/USER.md handoff"],
            ["Hermes install kit", "hermes/README.md", "Installer, hook, skill, repair"],
            ["Debugging scope", "docs/DEBUGGING-SCOPE-v0.2.17.md", "Historical investigation and shipped invariants"],
            ["Benchmarks", "benchmarks/README.md", "Matched measurement protocol"],
            ["Benchmark results", "benchmarks/RESULTS.md", "Historical numbers and controlled gold run"],
            ["Security", "SECURITY.md", "Data and disclosure boundaries"],
            ["Contribution", "CONTRIBUTING.md", "Tests, style, pull requests"]
          ]),
          tips: ["The website is a searchable reference layer: each note exposes its tracked source path, while related rows point to supplemental Markdown such as the skill, hook, and benchmark results.", "Local planning and audit notes under docs/ remain ignored by design; they are not the public contract."]
        }
      ]
    },

    architecture: {
      kicker: "System / architecture",
      lead: "Memory is a loop: recall before a response, ingest after a turn, and lifecycle maintenance in the background.",
      sections: [
        {
          title: "End-to-end stages",
          paragraphs: ["The system keeps ingestion, retrieval, context injection, and maintenance separate so an untrusted transcript cannot silently become durable truth."],
          table: table("Pipeline stages", ["Stage", "Inputs", "Guarantee"], [
            ["Ingest", "text, scope, evidence, claims", "Whitelist, hash, evidence validation, embed, index"],
            ["Recall", "query, scope, tags, budget", "Scope/status first, four candidates, fusion, abstention"],
            ["Injection", "core + recall + session", "Anti-duplicated, token-bounded context surfaces"],
            ["Lifecycle", "TTL, duplicate, importance", "Batched cleanup/consolidation/pruning"],
            ["Repair", "legacy provenance/scope", "Dry-run first; apply backs up and archives"]
          ])
        },
        {
          title: "Ingest and store",
          paragraphs: ["Facts enter with content, tags, source, ownership, validity, status, confidence, evidence, and claim lineage. SQLite stores the durable row, FTS5 index, embeddings, entities, provenance, claims, and an immutable exact-session source-episode ledger."],
          code: "ingest -> whitelist -> optional enrichment -> evidence/claims -> hash -> embed -> backend + indexes\nHermes completed turn -> exact-session episode ledger (continuity only)",
          tips: ["A raw automatic transcript is not promoted when curation is unavailable. Explicit ingest and core tools remain writable because their caller already supplied an intentional write."]
        },
        {
          title: "Recall and delivery",
          paragraphs: ["Semantic, keyword, temporal, and graph candidates are scoped before fusion. Weighted RRF, evidence gates, adaptive cutoff, deduplication, and token budgets shape the returned block."],
          code: "scope -> candidates -> RRF -> confidence/evidence -> cutoff -> dedup/budget -> context | abstain\nabstain/no usable block -> exact-session continuity fallback",
          warnings: ["Session episodes never participate in ranking, never widen user/workspace/agent/session scope, and never become durable merely because the agent quoted them."]
        },
        {
          title: "Hermes post-turn review",
          paragraphs: ["When ingest_llm is enabled, the serialized writer first handles the curated summary and then reviews the same turn against a bounded exact-scope candidate window. A mutation requires a candidate id and exact evidence quote from the current turn."],
          bullets: ["capture a new grounded claim", "supersede a known claim with explicit lineage", "retract a claim when the turn proves it invalid", "skip malformed/unsupported review without killing the writer"]
        },
        {
          title: "Authority and upgrades",
          paragraphs: ["Hermes selects Luminary through the public provider entry point. Existing memory.memory_enabled and memory.user_profile_enabled switches disable the two native persistent surfaces; Luminary does not import Hermes private modules, patch source, or branch on a version number."],
          code: "memory:\n  provider: luminary\n  memory_enabled: false\n  user_profile_enabled: false",
          tips: ["Capability compatibility is the contract. An unavailable provider lifecycle is a visible setup failure, not permission to run two memory authorities together."]
        },
        {
          title: "Backends and lifecycle",
          paragraphs: ["MemoryBackend defines CRUD, keyword/vector search, scoped recent reads, and optional event/evidence/claim/episode helpers. SQLite is the zero-configuration default; pgvector moves vector search to PostgreSQL. Lifecycle runs cleanup, consolidate, prune, and importance re-estimation; full LLM maintenance is separate."],
          returns: ["Backend implementations that omit episode helpers can still support basic library calls, but Hermes exact-session continuity and provenance must be reported as unavailable."]
        }
      ]
    },

    api: {
      kicker: "Library / Python API",
      lead: "MemoryClient exposes explicit operations for storing, recalling, maintaining, and inspecting memory.",
      sections: [
        {
          title: "Constructing a client",
          paragraphs: ["A client can use Settings, a database path, a custom backend/enricher/engine, and an optional bound ownership scope. Bound scope is a capability boundary for reads and mutations."],
          code: "MemoryClient(\n    settings=None, db_path=None, ingest_whitelist=None,\n    enricher=None, engine=None, backend=None, scope=None,\n    user_id=None, session_id=None, workspace_id=None, agent_id=None,\n)",
          tips: ["Bind scope at construction for agent/provider paths. Per-call scope can refine a bound identity but cannot switch it.", "Call close() when the client owns a backend connection, especially in CLI or short-lived scripts."]
        },
        {
          title: "Public data types and batch writes",
          paragraphs: ["Memory is the durable row; RecallResult is the retrieval envelope; Settings exposes engine configuration. Batch ingest applies the same evidence, scope, deduplication, and indexing rules as one-by-one writes."],
          table: table("Stable public types", ["Type", "Contains", "Use"], [
            ["Memory", "content, tags, scope, status, validity, confidence, evidence, claims", "Durable row and mutation input."],
            ["RecallResult", "memories, scores, strategies_hit, status, reason, confidence, provenance", "Safe retrieval result; handle abstain explicitly."],
            ["Settings", "backend, embeddings, recall, safety, core, lifecycle, LLM", "Engine defaults from LUMINARY_* environment variables."]
          ]),
          code: "client.ingest_batch(\n    texts,\n    tags=[...],\n    metadata=[...],\n)  # one id/None per input",
          returns: ["ingest_batch() returns one canonical id or None per input.", "Parallel tags and metadata lists must align with texts; each row still passes the normal scope and evidence rules."],
          tips: ["Use batch ingest for imports and lifecycle-adjacent writes. Use explicit single ingest when a claim needs a distinct evidence or supersession decision."]
        },
        {
          title: "ingest()",
          paragraphs: ["Writes a fact, validates its evidence, adds provenance and claim lineage, suppresses exact active duplicates within scope, and indexes the result."],
          parameters: ingestParameters,
          code: "client.ingest(text, tags=None, source=None, metadata=None, enrich=True,\n               importance=None, user_id=None, session_id=None,\n               workspace_id=None, agent_id=None, observed_at=None,\n               valid_from=None, valid_to=None, status=\"active\",\n               confidence=None, evidence_quote=None, source_id=None,\n               claim_key=None, supersedes_id=None, source_text=None)",
          returns: ["int: canonical id for an inserted or exact duplicate row.", "None: empty, whitelist-rejected, non-worth-saving, or otherwise empty enriched content."],
          warnings: ["source_text is evidence context for a distilled memory; it is not the memory's searchable content. An ungrounded evidence quote is replaced with grounded content rather than presented as provenance."]
        },
        {
          title: "recall()",
          paragraphs: ["Runs scoped semantic, keyword, temporal, and graph retrieval, fuses rankings, gates evidence, applies adaptive cutoff/deduplication, and serializes within a token budget."],
          parameters: recallParameters,
          code: "client.recall(query, limit=10, token_budget=None, tags=None,\n               tag_mode=\"any\", scope=None, strict=None,\n               include_conflicted=False)",
          returns: ["RecallResult.memories and parallel scores.", "strategies_hit, status (ok/fallback/abstain), reason, confidence, and provenance."],
          tips: ["Treat status=abstain as a correct no-answer outcome. Do not force the first candidate into a prompt.", "Normal recall hides conflicted, superseded, deleted, and expired rows; include_conflicted is for diagnostics."]
        },
        {
          title: "Mutation and inspection surface",
          table: table("Public methods", ["Method", "Parameters", "Contract"], [
            ["get", "id, scope=None", "Scope-visible row or None."],
            ["update", "Memory", "Updates row and derived indexes; bound client must own it."],
            ["delete", "id", "Hard delete after recording the pre-delete event; prefer retract for claims."],
            ["retract", "id, reason=None", "Soft-delete with audit history."],
            ["supersede", "id, content, evidence/source/claims...", "Creates a new version and preserves old lineage."],
            ["resolve_conflict", "id, status, evidence_quote, source_id", "Explicitly changes a conflict state."],
            ["list", "limit=100, offset=0, scope=None", "Recent rows; limit=0 means unlimited."],
            ["search", "query, limit=10, scope=None", "Keyword-only FTS search; not fused recall."],
            ["graph", "limit=20", "Entities and co-occurrence relations."],
            ["export/import", "path, include_embeddings", "Versioned backup/migration operations."]
          ])
        },
        {
          title: "Lifecycle, health, and consistency",
          code: "client.run_lifecycle(semantic=None)\nclient.run_maintenance(review_all=True)\nclient.health_score()\nclient.stats()\nclient.close()",
          returns: ["count() is the active, scope-visible public count and agrees with list(limit=0).", "Exact concurrent duplicates resolve to one canonical active row without duplicate episode/evidence/graph lineage."],
          tips: ["Regenerate the pdoc reference after public docstrings change; this website note documents the stable high-value contract, not every generated class member."]
        }
      ]
    },

    recall: {
      kicker: "Operate / retrieval",
      lead: "Recall is conservative by design: the most similar result is not automatically the right result.",
      sections: [
        {
          title: "Candidate strategies",
          paragraphs: ["Each strategy produces a scoped ranked list. The planner can skip a strategy when the query provides no useful signal; it does not use a language-specific alias table."],
          table: table("Four retrieval signals", ["Strategy", "Implementation", "Useful for"], [
            ["semantic", "Embedding cosine / vectorized matmul", "Paraphrase and conceptual matches"],
            ["keyword", "SQLite FTS5 BM25; pgvector ILIKE", "Exact terms, identifiers, names"],
            ["temporal", "Recency decay × access popularity", "Recently used/current facts"],
            ["graph", "Entity co-occurrence SQL aggregation", "Related people, projects, and entities"]
          ])
        },
        {
          title: "Fusion and query planning",
          paragraphs: ["Weighted reciprocal-rank fusion combines available lists using semantic 0.4, keyword 0.3, graph 0.2, and temporal 0.1 by default. Short queries may expand with co-occurring graph entities or tokens from a topically related important memory."],
          code: "score = Σ strategy_weight / (rrf_k + rank)\nsemantic=0.4  keyword=0.3  graph=0.2  temporal=0.1\nrrf_k=60",
          tips: ["Use keyword search for direct inspection and recall for evidence-aware context. They are intentionally different surfaces.", "If an unrelated query returns no memories, that is abstention doing its job, not a retrieval crash."]
        },
        {
          title: "Strict results, evidence, and conflicts",
          paragraphs: ["Scope, status, validity, tags, evidence grounding, conservative confidence, and top-vs-second margin are evaluated before output. A conflict remains visible until an explicit resolution or supersession."],
          output: "{\n  \"status\": \"abstain\",\n  \"reason\": \"no_supported_candidate\",\n  \"confidence\": 0.31,\n  \"memories\": [],\n  \"provenance\": []\n}",
          warnings: ["Importance is a ranking/pruning signal. It no longer creates an always-injected persistent-context tier; durable always-present rules belong in core memory."]
        },
        {
          title: "Cutoff, deduplication, and budget",
          paragraphs: ["Adaptive cliff detection trims a sparse result set after a steep score drop. Jaccard deduplication removes near-identical candidates, and token_budget bounds serialized context. Recalled rows receive batched access bookkeeping for the next importance estimate."],
          parameters: [
            parameter("recall_cliff_threshold", "float", "0.45", "Relative score drop that starts the cutoff."),
            parameter("dedup_jaccard_threshold", "float", "0.85", "Near-duplicate token-overlap threshold."),
            parameter("token_budget", "int", "4096 library / 2048 provider", "Hard serialization budget."),
            parameter("importance_recall_boost", "float", "1.0", "Multiplier for importance at least 0.8."),
            parameter("recall_min_score", "float", "0.0", "Minimum score accepted by provider/CLI recall.")
          ]
        },
        {
          title: "Core memory is separate",
          paragraphs: ["Core rows are tagged explicitly and loaded every Hermes session in stable id/insertion order within core_top_n/core_budget. Query recall omits a core match from its payload when the same content/id is already injected."],
          code: "core tag -> every-session prompt block\nquery -> ranked durable context\nexact-session episode -> fallback reference only",
          tips: ["Put stable identity/preferences/rules that must always be present in core. Put task-specific facts in ordinary durable recall with scope and evidence."]
        },
        {
          title: "Exact-session continuity fallback",
          paragraphs: ["If durable recall abstains or serializes no usable block, Hermes may read up to four recent immutable episodes from the exact current session under the existing token budget and an internal character ceiling. The current user request remains authoritative."],
          warnings: ["The fallback is not a new recall strategy, does not enter RRF, does not search the history of all sessions, and cannot turn a quoted transcript into a durable fact by itself."]
        }
      ]
    },

    lifecycle: {
      kicker: "Operate / maintenance",
      lead: "A memory store should get easier to trust as it gets older, not noisier.",
      sections: [
        {
          title: "run_lifecycle(): deterministic passes",
          paragraphs: ["The lifecycle runner executes cleanup, near-duplicate consolidation, importance estimation, and pruning in bounded backend operations."],
          table: table("Passes", ["Pass", "What it does", "Protection"], [
            ["cleanup", "Removes TTL-expired active rows", "Audit/history remains available through events"],
            ["consolidate", "Merges near duplicates by Jaccard or semantic cosine", "Pinned/core rows are protected"],
            ["importance", "Re-estimates importance from behavior", "Pinned rows never downgrade"],
            ["prune", "Drops low-value or least-recently-used rows", "Pinned rows and bounded caps are respected"]
          ]),
          code: "client.run_lifecycle()\nclient.run_lifecycle(semantic=False)  # Jaccard-only consolidation",
          tips: ["Use semantic=False when the embedding model is unavailable or you need a deterministic lexical-only maintenance pass."]
        },
        {
          title: "run_maintenance(): optional LLM review",
          paragraphs: ["Full maintenance reviews the store semantically and can keep, update, or delete stale, contradicted, and duplicate facts. It is complementary to Hermes incremental turn review: full maintenance is broad; incremental review is exact-turn and exact-scope."],
          code: "client.run_maintenance(review_all=True)",
          returns: ["A dictionary of reviewed/updated/deleted counts and status."],
          warnings: ["Provider maintenance is best-effort and fails closed on missing evidence. It requires ingest_llm and should not be confused with the non-durable episode ledger."]
        },
        {
          title: "health_score()",
          paragraphs: ["Health is an operator signal rather than a retrieval score. The report includes a 0–100 score, per-dimension health, and recommendations."],
          output: "{\n  \"score\": 87,\n  \"dimensions\": {\n    \"duplicates\": {\"health\": 92},\n    \"staleness\": {\"health\": 81},\n    \"importance\": {\"health\": 90},\n    \"graph_density\": {\"health\": 84},\n    \"size\": {\"health\": 88}\n  },\n  \"recommendations\": []\n}",
          tips: ["Run health after a migration or long-lived session period; use its recommendations to choose a targeted lifecycle pass."]
        },
        {
          title: "Authority repair",
          paragraphs: ["The SQLite repair utility identifies imported authority snapshots and structurally uncurated Hermes rows using provenance and scope metadata."],
          code: "# read-only inventory\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db\n\n# explicit migration: backup + archive + audit events\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db --apply",
          returns: ["Dry run prints a JSON plan and changes nothing.", "Apply creates a consistent SQLite backup, archives selected rows, and records audit events; it never hard-deletes those rows."],
          warnings: ["Review the dry-run rows and backup path before applying. Repair is a migration aid, not another runtime memory authority."]
        },
        {
          title: "Backup and scheduling",
          code: "luminary-memory export --path backup.json\nluminary-memory lifecycle\n# recovery\nluminary-memory import --path backup.json",
          tips: ["Schedule deterministic lifecycle separately from optional LLM maintenance so a curation outage cannot block cleanup.", "Back up before changing thresholds, switching backends, or applying authority repair."]
        }
      ]
    },

    config: {
      kicker: "Reference / configuration",
      lead: "Every engine and provider setting is listed with its source, default, and real runtime effect.",
      sections: [
        {
          title: "Library settings: storage",
          paragraphs: ["Settings are read once at startup from LUMINARY_* environment variables. They are engine-level values shared by direct Python clients and tools."],
          parameters: libraryStorage,
          tips: ["SQLite is the default and needs no server. pgvector is for managed PostgreSQL, larger stores, or concurrent access."]
        },
        {
          title: "Library settings: embeddings",
          parameters: libraryEmbeddings,
          warnings: ["embedding_dim must match model output and the database vector column. Model language coverage follows the selected model; the pipeline does not classify durability from vocabulary."]
        },
        {
          title: "Library settings: recall",
          paragraphs: ["These values tune candidate fusion, query planning, cutoff, deduplication, importance boost, and serialization."],
          parameters: libraryRecall,
          code: "LUMINARY_WEIGHT_SEMANTIC=0.4\nLUMINARY_WEIGHT_KEYWORD=0.3\nLUMINARY_WEIGHT_GRAPH=0.2\nLUMINARY_WEIGHT_TEMPORAL=0.1\nLUMINARY_TOKEN_BUDGET=4096"
        },
        {
          title: "Library settings: safety and scope",
          parameters: safetyParameters,
          table: table("Runtime scope environment", ["Variable", "Memory field", "Used before"], [
            ["LUMINARY_USER_ID", "user_id", "all candidate generation and mutations"],
            ["LUMINARY_WORKSPACE_ID", "workspace_id", "all candidate generation and mutations"],
            ["LUMINARY_AGENT_ID", "agent_id", "all candidate generation and mutations"],
            ["LUMINARY_SESSION_ID", "session_id", "exact session and claim ownership"]
          ]),
          tips: ["Set identity in the process environment instead of putting personal identifiers in shell history or query text.", "Set scope_include_global=false for strict tenant isolation when legacy NULL-owned rows should not be visible."]
        },
        {
          title: "Library settings: core and lifecycle",
          parameters: coreParameters.concat(lifecycleParameters),
          warnings: ["The removed persistent-context settings context_top_n, context_budget, and context_min_importance are not active configuration. Use explicit core memory for always-present rules."]
        },
        {
          title: "Library settings: ingest, LLM, compatibility",
          parameters: llmParameters.concat(compatibilityParameters),
          tips: ["ingest_llm is optional. Without it, direct explicit writes still work, while automatic Hermes transcript batches are not silently promoted as durable facts.", "Language-specific keyword lists are not part of the active memory classification logic."]
        },
        {
          title: "Hermes provider config.json",
          paragraphs: ["Provider settings live at $HERMES_HOME/luminary/config.json, are forward-compatible when keys are missing, and are surfaced by Hermes dashboard memory setup."],
          parameters: providerParameters,
          code: "{\n  \"mode\": \"hybrid\",\n  \"auto_recall\": true,\n  \"auto_retain\": true,\n  \"ingest_llm\": false,\n  \"core_tag\": \"core\",\n  \"core_top_n\": 12,\n  \"core_budget\": 8000\n}",
          tips: ["Provider config controls provider behavior; LUMINARY_* controls engine internals and direct tools. When tuning an overlapping value, set both layers deliberately or leave one at default."]
        },
        {
          title: "Activation boundary and continuity",
          code: "# Hermes $HERMES_HOME/config.yaml\nmemory:\n  provider: luminary\n  memory_enabled: false\n  user_profile_enabled: false",
          paragraphs: ["These three activation keys are owned by Hermes. The provider's own config.json is separate. auto_retain admits accepted turns to the exact-session episode ledger and queues curation; continuity intentionally has no extra toggle."],
          warnings: ["The installer edits the public config boundary only. It does not create profiles, patch Hermes source, import native files, or pin a Hermes version."]
        }
      ]
    },

    backends: {
      kicker: "Storage / backends",
      lead: "Start with a local SQLite file. Move to pgvector when the deployment needs PostgreSQL-backed vector search and concurrency.",
      sections: [
        {
          title: "SQLite default",
          paragraphs: ["SQLite uses stdlib sqlite3, FTS5 BM25 keyword search, in-process vectorized cosine, thread-local connections, WAL/busy timeout where supported, scoped indexes, and batched writes."],
          table: table("SQLite guarantees", ["Concern", "Behavior"], [
            ["Keyword search", "Sanitized FTS5 MATCH with quoted terms and OR semantics"],
            ["Vector search", "Linear scan with float32 matmul; no per-row Python cosine loop"],
            ["Concurrency", "Thread-local connections; background reader and writer do not share handles"],
            ["Deduplication", "Database unique invariant over ownership tuple + content_hash"],
            ["Provider continuity", "record_episode/recent_episodes exact-scope ledger, outside semantic recall"]
          ]),
          code: "client = MemoryClient(db_path=\"memory.db\")"
        },
        {
          title: "pgvector",
          paragraphs: ["pgvector requires PostgreSQL with the vector extension. It uses ILIKE keyword search and the <=> cosine-distance operator, with optional HNSW indexing for scale."],
          parameters: [
            parameter("LUMINARY_BACKEND", "env", "sqlite", "Set to pgvector to select the backend."),
            parameter("LUMINARY_PG_DSN", "DSN", "postgresql://localhost/luminary_memory", "Connection string."),
            parameter("LUMINARY_PG_HNSW_INDEX", "bool", "false", "Create HNSW index."),
            parameter("LUMINARY_PG_HNSW_M", "int", "16", "HNSW graph degree."),
            parameter("LUMINARY_PG_HNSW_EF_CONSTRUCTION", "int", "64", "HNSW build exploration factor.")
          ],
          warnings: ["The backend must provide the same scope, status, evidence, claim, supersession, episode, and provenance contract; changing backend must not change memory authority semantics."]
        },
        {
          title: "Choosing and migrating",
          table: table("Deployment fit", ["Need", "Choice"], [
            ["Zero setup, one agent, edge", "SQLite"],
            ["Large store or many concurrent queries", "pgvector"],
            ["Central managed database", "pgvector"],
            ["Portable local backup", "SQLite export/import"]
          ]),
          code: "export LUMINARY_BACKEND=pgvector\nexport LUMINARY_PG_DSN=postgresql://localhost/luminary_memory\n# then re-ingest/export-import according to the migration plan"
        },
        {
          title: "Adding a backend",
          paragraphs: ["Implement MemoryBackend CRUD, keyword/vector search, count, and the provider helpers when Hermes support is required."],
          table: table("Backend contract", ["Required", "Provider-capable optional helpers"], [
            ["add, get, update, delete, all, count", "record_event, add_evidence"],
            ["keyword_search, vector_search", "record_episode, recent_episodes"],
            ["bulk methods where lifecycle needs them", "add_claim, sync_claim_status"]
          ]),
          warnings: ["A lightweight custom backend can use compatibility defaults, but then Hermes session continuity and provenance are unavailable and must be reported rather than silently omitted."]
        }
      ]
    },

    cli: {
      kicker: "Operator / CLI",
      lead: "The CLI makes the store inspectable without requiring a separate dashboard.",
      sections: [
        {
          title: "Global options and scope",
          paragraphs: ["Every command accepts --db-path and --backend. The CLI client uses strict recall, evidence-required results, and non-destructive rule handling."],
          parameters: [
            parameter("--db-path PATH", "option", "unset", "Override SQLite path."),
            parameter("--backend sqlite|pgvector", "option", "sqlite", "Select storage backend."),
            parameter("LUMINARY_USER_ID etc.", "environment", "unset", "Set ownership scope without putting identity in query text or command arguments.")
          ],
          code: "export LUMINARY_USER_ID=u1\nexport LUMINARY_WORKSPACE_ID=luminary\nexport LUMINARY_AGENT_ID=coding-agent\nexport LUMINARY_SESSION_ID=session-42"
        },
        {
          title: "Store, recall, search, and list",
          table: table("Data commands", ["Command", "Parameters", "Output/behavior"], [
            ["add", "text; --tags; --source", "Stores one fact; prints added id or rejected by whitelist."],
            ["recall", "query; --limit; --json", "Full four-strategy recall; JSON includes status/reason/confidence/provenance."],
            ["search", "query; --limit; --json", "Keyword-only FTS/ILIKE search."],
            ["list", "--limit; --offset; --json", "Most recent rows; limit 0 is unlimited."],
            ["activity", "--limit; --json", "Active durable activity; not raw episodes or review decisions."]
          ]),
          code: "luminary-memory add \"The deploy target is staging\" --tags deploy --source cli\nluminary-memory recall \"where do we deploy?\" --limit 5 --json\nluminary-memory search postgresql --limit 10\nluminary-memory list --limit 50 --offset 0\nluminary-memory activity --limit 5 --json",
          tips: ["Use recall when you need evidence-aware fused context. Use search/list/activity when you need an operator view of stored rows."]
        },
        {
          title: "Maintain and back up",
          table: table("Maintenance commands", ["Command", "Parameters", "Output/behavior"], [
            ["lifecycle", "--semantic/--no-semantic", "Cleanup + consolidate + prune counts."],
            ["export", "--path; --include-embeddings/--no-embeddings", "Versioned JSON backup."],
            ["import", "--path", "Batch import; recomputes absent embeddings."],
            ["stats", "global options", "Store statistics as JSON."],
            ["health", "--json", "0–100 score, dimensions, recommendations."],
            ["graph", "--limit; --relations; --json", "Entities and optional co-occurrence edges."],
            ["version", "none", "Installed version and Python runtime."]
          ]),
          code: "luminary-memory lifecycle --no-semantic\nluminary-memory export --path backup.json --no-embeddings\nluminary-memory health --json\nluminary-memory graph --relations --limit 50"
        },
        {
          title: "Authority repair",
          paragraphs: ["Repair is intentionally a separate script so mutation requires an explicit database path and --apply."],
          code: "python scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db --apply",
          returns: ["Read-only mode prints a JSON plan. Apply creates a backup, archives selected imported/uncurated rows, and records audit events."],
          warnings: ["Apply never hard-deletes rows, but review the dry-run and backup before resuming automatic writes."]
        },
        {
          title: "Output and exit codes",
          output: "🌙 Luminary — no relevant memories found (no_supported_candidate)\n\n# success: 0\n# error or rejected ingest: 1",
          paragraphs: ["Human output stays compact; --json is the stable automation surface. Recall JSON contains status (ok, fallback, or abstain), reason, confidence, memories, scores, strategies_hit, and provenance."],
          tips: ["A zero-memory abstain is a valid success path for a query with no supported answer; distinguish it from process exit code 1, which indicates a command error or rejected ingest."]
        }
      ]
    },

    "agent-tools": {
      kicker: "Integration / agent surface",
      lead: "Explicit tools let an agent interact with memory without hiding which operation changed the store.",
      sections: [
        {
          title: "luminary_recall",
          paragraphs: ["Retrieves scoped context through the full four-strategy pipeline. Core matches already present in the system prompt are omitted from the tool payload and listed through deduplicated_core_ids."],
          parameters: [
            parameter("query", "string", "required", "Recall query."),
            parameter("limit", "integer", "provider recall_limit (10)", "Maximum results.")
          ],
          code: "{\n  \"name\": \"luminary_recall\",\n  \"parameters\": {\"query\": \"where do we deploy?\", \"limit\": 5}\n}",
          returns: ["status, reason, confidence, memories, scores, provenance, and deduplicated_core_ids.", "Weak or unsupported queries may return status=abstain with no memories."]
        },
        {
          title: "luminary_ingest and luminary_list",
          table: table("Tool parameters", ["Tool", "Parameters", "Behavior"], [
            ["luminary_ingest", "content: string required; tags: string[] optional", "Provider supplies source and ownership; exact active duplicates are suppressed."],
            ["luminary_list", "limit: integer optional, default 20", "Read-only recent inspection; returns id/content/tags only."]
          ]),
          tips: ["The ingest tool deliberately does not accept arbitrary source or importance. The provider owns provenance and scope so a model cannot forge authority metadata.", "luminary_list is not recall and does not read the episode ledger."]
        },
        {
          title: "Core tools",
          table: table("Core operations", ["Tool", "Parameters", "Effect"], [
            ["luminary_core_add", "content: string required", "Adds core tag and raises importance to the pin threshold (default 0.9)."],
            ["luminary_core_remove", "id: integer required", "Removes core tag; keeps the memory in the store."],
            ["luminary_core_list", "limit: integer optional, default 50", "Returns active core id/content/importance in stable id order."]
          ]),
          warnings: ["Prompt injection is independently bounded by core_top_n and core_budget. Similar contradictory rules remain auditable until explicit supersession."]
        },
        {
          title: "Mode availability and accuracy behavior",
          table: toolModes,
          paragraphs: ["Tools inherit the provider's exact scope and strict evidence policy. Automatic recall/retain and explicit tools are separate controls."],
          tips: ["Use context when the host should receive automatic memory only; use tools when the model must explicitly ask; use hybrid for both."]
        }
      ]
    },

    hermes: {
      kicker: "Integration / Hermes",
      lead: "Luminary plugs into Hermes through the public memory-provider boundary and keeps one persistent authority active.",
      sections: [
        {
          title: "Provider configuration",
          paragraphs: ["Set Luminary as provider and disable Hermes' two native persistent surfaces together. This is an activation boundary in Hermes config.yaml, not a Luminary config.json setting."],
          code: "memory:\n  provider: luminary\n  memory_enabled: false\n  user_profile_enabled: false",
          warnings: ["Native files may remain on disk for compatibility, but their normal prompt/tool surfaces are disabled. Luminary does not mirror or silently merge them."]
        },
        {
          title: "Capability-based setup and upgrades",
          paragraphs: ["Hermes discovers Luminary through its public provider entry point and lifecycle. The installer checks capabilities rather than comparing release numbers."],
          bullets: ["No Hermes source patch or private import", "No Hermes version pin", "Existing root/profile config boundaries are edited idempotently", "Missing provider capability is a visible setup failure"],
          tips: ["After a Hermes update, verify provider discovery and the three activation keys, then restart the gateway. No source merge is required."]
        },
        {
          title: "Three runtime context surfaces",
          table: table("Surface contract", ["Surface", "When used", "Durability"], [
            ["Core memory", "Every session", "Durable DB row; explicit core authority"],
            ["Durable query recall", "Current query has supported candidates", "Durable, scoped, evidence-aware"],
            ["Exact-session continuity", "Durable recall has no usable block", "Immutable episode reference; non-durable and exact-session only"]
          ]),
          paragraphs: ["Anti-duplication uses ids and content hashes. The current user request remains authoritative over all recalled/reference blocks."]
        },
        {
          title: "Auto recall, retain, and reconciliation",
          paragraphs: ["Auto-recall runs before the response. auto_retain records accepted completed turns in the episode ledger and queues batches. With ingest_llm enabled, the writer stores a factual summary and then runs a serialized exact-scope review for captures, supersessions, or retractions."],
          code: "auto_recall -> core + recall (or exact-session fallback)\nturn complete -> episode ledger -> retain queue\ningest_llm -> curated summary -> capture/supersede/retract review\nauto_maintain -> full store review at session end",
          returns: ["A failed curator/reviewer is skipped and cannot kill later retains or the agent response.", "An automatic raw transcript is not durable when curation is disabled, unavailable, trivial, or unsupported."]
        },
        {
          title: "Core memory and removed persistent context",
          paragraphs: ["Core is the DB-backed equivalent of MEMORY.md: explicit core-tagged rows load every session within core_top_n/core_budget. The old importance-based persistent-context tier was removed in v0.2.18; importance now affects recall ranking and pruning only."],
          tips: ["Use core for stable identity, preferences, or rules that must be present regardless of query. Use ordinary durable memory for task-specific facts."]
        },
        {
          title: "Scope, evidence, status, and logs",
          paragraphs: ["Provider paths enable strict recall, evidence-required results, and non-destructive rule replacement. Conflicting claims remain in the audit/version chain until explicitly superseded."],
          bullets: ["Every operation carries user/workspace/agent/session scope.", "Current-turn review requires candidate id plus exact evidence quote.", "Transparency JSONL keeps trace id, status/reason, counts, confidence, latency, and scope—not prompt or memory content.", "The activity hook mirrors active durable rows after committed writes; it is not the memory authority."]
        }
      ]
    },

    "native-migration": {
      kicker: "Authority / migration",
      lead: "Carry Hermes' native context into Luminary core without editing Hermes source or running two persistent authorities at once.",
      sections: [
        {
          title: "Why this utility exists",
          paragraphs: ["When Luminary becomes Hermes' provider, the native MEMORY.md and USER.md prompt surfaces are disabled. Those files can still contain workflow, identity, or skill-routing context that an older Luminary store does not have. This utility preserves that context as two lossless, DB-backed core snapshots instead of asking an LLM to summarize it."],
          bullets: ["Native files remain untouched.", "Snapshots use stable source ids for the MEMORY and USER targets.", "The resulting rows are explicit core memory, not a hidden native fallback."]
        },
        {
          title: "Read the plan before applying",
          paragraphs: ["The command is read-only by default. Review the JSON inventory, source paths, hashes, line counts, and section counts before opting into a database write."],
          code: "python scripts/migrate_native_memory.py --hermes-home ~/.hermes\n\n# after reviewing the plan\npython scripts/migrate_native_memory.py --hermes-home ~/.hermes --apply",
          returns: ["Existing snapshots with the same source id are reported as unchanged or updated.", "Missing or empty native files are skipped without inventing content."]
        },
        {
          title: "Backup and idempotence",
          paragraphs: ["Apply mode creates a consistent SQLite backup before inserting or updating snapshots. It never deletes a row and never rewrites the native source files. Re-running after a native file changes updates that target by its stable source id; re-running without changes is a no-op."],
          table: table("Safety contract", ["Operation", "Behavior"], [
            ["Read-only run", "Prints a redacted migration plan and changes nothing."],
            ["Apply", "Backs up the SQLite store, then inserts or updates snapshots."],
            ["Native files", "Read only; no edit, archive, or delete."],
            ["Existing row", "Promote an exact duplicate or update its snapshot metadata."],
            ["Core limits", "Native snapshots are included in full so the source is not silently truncated."]
          ]),
          warnings: ["Stop the gateway or other writers while applying the migration, then review the backup path and output before resuming automatic writes."]
        },
        {
          title: "Command arguments",
          parameters: [
            parameter("--hermes-home PATH", "path", "$HERMES_HOME or ~/.hermes", "Resolve native files, provider config, and the default Luminary store."),
            parameter("--native-dir PATH", "path", "<hermes-home>", "Read MEMORY.md and USER.md from an explicit directory."),
            parameter("--db-path PATH", "path", "<hermes-home>/luminary/memory.db", "Override the SQLite database target."),
            parameter("--core-tag TAG", "string", "provider config or core", "Tag inserted snapshots as DB-backed core memory."),
            parameter("--apply", "flag", "off", "Create a backup and apply the snapshot migration."),
            parameter("--backup-path PATH", "path", "timestamped .bak", "Choose the backup destination in apply mode.")
          ]
        },
        {
          title: "Verify the authority handoff",
          paragraphs: ["After apply, keep Hermes' native memory switches disabled, restart the gateway, and start a fresh session. Confirm the active provider database and inspect core rows through the normal operator surfaces."],
          code: "luminary-memory list --db-path ~/.hermes/luminary/memory.db --limit 20\nluminary-memory stats --db-path ~/.hermes/luminary/memory.db\n\n# Hermes config.yaml\nmemory:\n  provider: luminary\n  memory_enabled: false\n  user_profile_enabled: false",
          tips: ["A migration copies source context once. It does not create a live merge between Hermes files and Luminary.", "If the provider cannot be discovered after an upgrade, fix capability activation first instead of enabling the native surfaces as an implicit fallback."]
        }
      ]
    },

    debugging: {
      kicker: "Operate / troubleshooting",
      lead: "Trace a missing result from scope to candidate generation, evidence, provider startup, and delivery.",
      sections: [
        {
          title: "Current context flow",
          code: "provider.initialize(session_id, identity scope)\n  -> core block\n  -> durable recall (sync or prefetch)\n  -> exact-session episodes only when recall has no usable block\n  -> response\nturn end -> episode admission + retain/review queue",
          table: table("What to verify first", ["Question", "Evidence"], [
            ["Is this the same session?", "provider scope, session_id, session_episode events"],
            ["Did durable recall abstain?", "recall.completed status/reason/confidence"],
            ["Was continuity admitted?", "session_context event and exact scope"],
            ["Was a fact stored?", "retain.completed / memory.review.completed and activity/list"],
            ["Did the hook deliver it?", "hook cursor and Telegram ok=true response"]
          ])
        },
        {
          title: "Context-loss checklist",
          bullets: ["Confirm user_id, workspace_id, agent_id, and session_id at provider initialization.", "Check that prefetch cache belongs to the current session, query, generation, and scope signature.", "Check session_episode admission before changing ranking thresholds.", "Check whether durable recall was abstain, empty after evidence, or simply not returned because core already deduplicated it.", "Check active status, validity window, claim conflicts, and evidence grounding.", "Check the active database path; config.json relative paths resolve under HERMES_HOME/luminary."]
        },
        {
          title: "Gateway and Telegram hook",
          paragraphs: ["The activity hook is a delivery-safe agent:end mirror of persisted active rows. It resolves the provider database from HERMES_HOME, explicit LUMINARY_DB_PATH, or provider config; it keeps a cursor per HERMES_HOME and advances only after Telegram returns ok=true."],
          code: "luminary-memory activity --db-path ~/.hermes/luminary/memory.db --json\n# inspect hook/provider log without memory text\nrg 'memory_activity|retain.completed|session_context|session_episode' ~/.hermes/luminary",
          tips: ["If the hook is empty while activity has rows, debug hook path/cursor/Telegram delivery. If activity is empty, debug provider admission/curation/storage first."]
        },
        {
          title: "Transparency and concurrency",
          paragraphs: ["Trace events are redacted and correlated by trace_id. The provider serializes retain/review mutations, invalidates stale prefetch generations, and closes thread-local backend clients at shutdown."],
          table: table("Useful event families", ["Event", "Meaning"], [
            ["provider.initialize.*", "Provider startup and resolved lifecycle."],
            ["recall.started/completed/discarded", "Scope, status/reason, cache generation, latency."],
            ["session_episode / session_context", "Exact-session continuity admission and delivery."],
            ["retain.started/completed/skipped", "Curation, duplicate, whitelist, or writer result."],
            ["memory.review.*", "Incremental capture/supersede/retract decision."],
            ["maintenance.completed", "Full store review counts and latency."]
          ]),
          warnings: ["Logs intentionally omit prompts, memory content, secrets, Telegram tokens, and API keys. They explain the path without becoming a second memory store."]
        },
        {
          title: "Verification commands",
          code: "python -m pytest -o addopts='' -q\npython -m ruff check src tests hermes/hooks\npython -m compileall -q src hermes/hooks scripts\nluminary-memory health --json\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db",
          tips: ["Run repair read-only first. A healthy recall score cannot prove the provider is reading the intended session or database path; scope/path evidence must be checked separately."]
        }
      ]
    },

    benchmarks: {
      kicker: "Measurement / benchmark protocol",
      lead: "Measure latency and behavior under matched conditions without turning a controlled set into a universal superiority claim.",
      sections: [
        {
          title: "Two independent benchmark arms",
          table: table("Protocol arms", ["Arm", "Purpose", "Authority"], [
            ["Deterministic synthetic corpus", "Pipeline latency smoke test", "Fake embedding engine and fixed seed"],
            ["Independent gold set", "Recall, abstention, evidence, scope isolation", "Labels authored outside retriever"]
          ]),
          code: "python3 -m benchmarks.run_benchmarks --n 500 --report /tmp/bench.json",
          warnings: ["The controlled 12-case gold fixture is a regression signal, not proof of superiority over Mem0, Hindsight, or another provider."]
        },
        {
          title: "Measured fields and parameters",
          parameters: [
            parameter("--n", "int", "benchmark default", "Synthetic memory count."),
            parameter("--backend", "sqlite", "sqlite", "Current benchmark runner backend; pgvector is covered by integration tests."),
            parameter("--gold-set PATH", "path", "gold_micro.jsonl", "Versioned independent fixture."),
            parameter("--report PATH", "path", "none", "Complete JSON report output."),
            parameter("gold metrics", "metrics", "n/a", "recall@10, MRR, precision@10, abstention accuracy, unsupported answer rate, evidence support precision, cross-scope leakage.")
          ]
        },
        {
          title: "Provider resource comparison",
          paragraphs: ["The provider benchmark measures recall p50/p95, peak RSS, ingest duration, and lifecycle duration on the same synthetic store. Hindsight local_embedded is an optional manual reference arm because model downloads and a daemon are not CI-safe."],
          code: "python benchmarks/hermes_provider_bench.py --n 5000 --backend sqlite --report /tmp/lum_vs_hindsight.json",
          output: "{\n  \"n\": 5000,\n  \"backend\": \"sqlite\",\n  \"recall_latency_ms\": {\"p50\": ..., \"p95\": ..., \"mean\": ...},\n  \"lifecycle_ms\": ...,\n  \"peak_rss_mb\": ...\n}",
          tips: ["Keep corpus, model, extraction budget, answer model, and metrics identical before comparing providers."]
        },
        {
          title: "Interpretation boundary",
          paragraphs: ["Latency and cost smoke numbers are engineering signals. Third-party numbers made on different datasets, prompts, models, or extraction policies are not apples-to-apples. Accuracy claims require a matched independent gold set."],
          returns: ["Current controlled results belong to the exact fixture and revision that produced them; they should not be generalized to every language, workload, or competitor."]
        }
      ]
    },

    "hermes-kit": {
      kicker: "Integration / operator kit",
      lead: "A small install kit connects Hermes, optional activity reporting, and provider guidance without a source fork.",
      sections: [
        {
          title: "One-shot install",
          code: "git clone https://github.com/alertxsto/luminary-memory.git\ncd luminary-memory\nHERMES_PYTHON=\"$HOME/.hermes/venv/bin/python\" bash hermes/install.sh\nbash ~/.hermes/scripts/restart-bots.sh",
          table: table("Installer switches", ["Option", "Effect"], [
            ["--hook", "Install the optional activity hook only."],
            ["--skill", "Install the Hermes skill only."],
            ["--llm", "Enable the provider's LLM curation configuration path."],
            ["--no-hook --no-skill", "Provider-only install."]
          ]),
          tips: ["Set HERMES_PYTHON when Hermes uses a dedicated virtualenv so capability checks and installation use the same interpreter."]
        },
        {
          title: "What gets installed",
          table: table("Component boundary", ["Component", "Behavior"], [
            ["Provider", "Installs the package, selects Luminary, disables native persistent switches."],
            ["Hook", "Posts committed active durable rows after agent:end; separate from authority."],
            ["Skill", "Guides explicit recall/ingest/list/maintenance use by the agent."]
          ])
        },
        {
          title: "Optional LLM curation",
          paragraphs: ["Without curation, automatic transcript batches are not promoted into durable facts; explicit writes still work. With curation, chit-chat is dropped, factual summaries are stored, and serialized incremental review can capture/supersede/retract only with current-turn evidence."],
          code: "bash hermes/install.sh --llm\n# ~/.hermes/luminary/config.json\n{\n  \"ingest_llm\": true,\n  \"llm_base_url\": \"https://api.example/v1\",\n  \"llm_model\": \"your-model\",\n  \"llm_api_key\": \"<secret>\"\n}",
          warnings: ["If enrichment fails or produces no durable summary, the provider drops the automatic turn instead of saving a raw transcript as a false fact. The writer does not block the agent."]
        },
        {
          title: "Activity hook contract",
          paragraphs: ["The hook reads active durable rows from the resolved provider store, keeps a cursor per HERMES_HOME, and advances only after the Telegram endpoint returns ok=true. It does not read raw episodes or LLM decisions that produced no row."],
          parameters: [
            parameter("LUMINARY_HOOK_CHAT_ID", "string", "TELEGRAM_HOME_CHANNEL", "Telegram chat that receives the factual activity message."),
            parameter("LUMINARY_HOOK_THREAD_ID", "string | None", "TELEGRAM_HOME_CHANNEL_THREAD_ID", "Optional Forum Topic ID."),
            parameter("LUMINARY_DB_PATH", "path | None", "provider config/default", "Explicit store to watch; otherwise resolve from hook context, provider config, or $HERMES_HOME/luminary/memory.db.")
          ],
          code: "luminary-memory activity --db-path ~/.hermes/luminary/memory.db --json",
          output: "🌙 Luminary — 2 recent memories stored\n  📌 #12 ALWAYS verify tests before release\n    tags: core, rule · source: hermes\n  • #11 Deploy target is staging\n    tags: deploy · source: cli\n\n{\n  \"status\": \"active\",\n  \"event\": \"memory_activity\",\n  \"count\": 1,\n  \"memories\": [{\"id\": 11, \"content\": \"Deploy target is staging\", \"tags\": [\"deploy\"], \"source\": \"cli\"}]\n}",
          returns: ["Human: 🌙 Luminary — N recent memories stored.", "JSON: status, event=memory_activity, count, memories[]."],
          tips: ["If Telegram delivery fails, the cursor stays put so the next hook invocation can retry the same committed rows."]
        },
        {
          title: "Upgrade and repair",
          paragraphs: ["Hermes updates do not require a Luminary source merge. Keep the activation keys, restart the gateway, and use repair for old stores that contain imported snapshots or uncurated rows."],
          code: "python scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db --apply",
          warnings: ["Do not copy Luminary into the Hermes source tree or add a private import workaround. Provider capability discovery is the compatibility check."]
        }
      ]
    },

    project: {
      kicker: "Project / contribution",
      lead: "Contribute through small, inspectable changes with tests, documentation, and explicit safety boundaries.",
      sections: [
        {
          title: "Contribution path",
          bullets: ["Read the tracked project map and relevant source contract.", "Keep one focused change per branch/commit.", "Add or update behavior tests, including long-lived scope/concurrency cases.", "Update tracked Markdown and this website guide when public behavior changes.", "Run pytest, Ruff, compile checks, and website JS syntax checks."]
        },
        {
          title: "Documentation contract",
          table: table("When behavior changes", ["Change", "Update"], [
            ["Python public method/signature", "docs/api.md + website API guide + generated pdoc when applicable"],
            ["Setting/default/provider mode", "docs/config-reference.md + website Configuration/Hermes guides"],
            ["CLI flag/output", "docs/cli.md + website CLI guide"],
            ["Hermes/hook behavior", "docs/hermes-integration.md, hermes/README.md, hook README, website guides"],
            ["Tests/release behavior", "CHANGELOG.md and relevant benchmark/debugging notes"]
          ]),
          warnings: ["Planning/audit notes under docs/ are ignored by design. Do not treat them as the source-facing contract or stage them accidentally."]
        },
        {
          title: "Current release snapshot",
          paragraphs: ["The public package and website are aligned to v0.3.0. This release is the strict CLI/Hermes accuracy path: scope isolation, evidence/provenance, conflict history, abstention, scoped transparency events, and exact-session continuity fallback."],
          table: table("Release checks", ["Surface", "Current contract"], [
            ["Version", "0.3.0 / Python 3.11+"],
            ["Release baseline", "505 passed, 3 skipped; 83% full-source coverage"],
            ["Current workspace check", "534 passed, 3 skipped; 83% full-source coverage"],
            ["Accuracy boundary", "Controlled gold fixture is a regression signal, not a competitor ranking"],
            ["Native Hermes memory", "Disabled through documented config switches when Luminary is active"]
          ]),
          tips: ["Update CHANGELOG.md, the tracked Markdown guide, and the website guide together when a public contract changes."]
        },
        {
          title: "Recent release history",
          paragraphs: ["The release baseline comes from CHANGELOG.md. The current workspace check above includes the additional migration and regression coverage present in this working tree; it is not a new release claim."],
          table: table("Recent shipped changes", ["Release", "Date", "Scope"], [
            ["0.3.0", "2026-08-24", "Scoped, evidenced, auditable CLI/Hermes path with session continuity and post-turn reconciliation."],
            ["0.2.18", "2026-08-20", "Importance became retrieval-only; core memory replaced persistent-context injection; strict accuracy path shipped."],
            ["0.2.17", "2026-08-19", "Gateway envelope parsing, retry-safe curation, and Telegram activity hardening."],
            ["0.2.16", "2026-08-19", "Provider configuration coverage and importance recall tuning exposed in the dashboard."]
          ]),
          tips: ["Use CHANGELOG.md for the complete historical record and this reader for the current implementation map."]
        },
        {
          title: "Verification commands",
          code: "python -m pytest -o addopts='' -q\npython -m ruff check src tests hermes/hooks\npython -m compileall -q src hermes/hooks scripts\nnode --check website/js/docs-content.js\nnode --check website/js/docs-guides.js\nnode --check website/js/docs-page.js\ngit diff --check"
        }
      ]
    },

    security: {
      kicker: "Safety / boundaries",
      lead: "Luminary is local by design. Storage and retrieval stay on the machine or database you control.",
      sections: [
        {
          title: "Local authority",
          paragraphs: ["SQLite files and your own PostgreSQL instance hold the memory store. Ordinary ingest, recall, list, search, lifecycle, and core loading do not send memory data to a hosted memory vendor."],
          bullets: ["Local SQLite or operator-controlled PostgreSQL", "No hosted memory service required", "No network call for ordinary recall", "Optional LLM endpoints are explicit configuration"]
        },
        {
          title: "Optional network activity",
          paragraphs: ["LLM enrichment, incremental review, full maintenance, Hermes gateway traffic, and Telegram activity delivery are separate operational paths. Configure credentials and endpoint policies under the host agent's controls."],
          table: table("Path and data boundary", ["Path", "Can leave the local process?", "Control"], [
            ["Ordinary recall", "No", "Local embedding/index/backend"],
            ["LLM curation", "Yes, if enabled", "llm_base_url, api key, model, timeout"],
            ["Telegram hook", "Yes, if installed", "Telegram token/channel and delivery contract"],
            ["Transparency log", "No by itself", "Redacted local JSONL file"]
          ]),
          warnings: ["Do not place API keys, tokens, raw prompts, or private memory content in public issues, benchmark fixtures, or screenshots."]
        },
        {
          title: "Scope and mutation safety",
          paragraphs: ["Ownership scope is applied before candidates and mutations. Bound clients cannot rewrite another scope, global compatibility rows are read-visible only when configured, and claim replacement requires explicit lineage/evidence."],
          tips: ["Use user/workspace/agent/session identifiers consistently at provider initialization. A missing or changed session id can look like amnesia even when the database is healthy."]
        },
        {
          title: "Responsible reporting",
          paragraphs: ["Report vulnerabilities through the tracked security process. Include a minimal reproduction and sanitized environment details; never attach private memory databases or credentials."],
          returns: ["Security policy and supported-version expectations live in SECURITY.md, linked as the tracked source for this note."]
        }
      ]
    }
  };
}());
