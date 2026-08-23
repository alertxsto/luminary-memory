(function () {
  "use strict";

  window.LUMINARY_GUIDES = {
    quickstart: {
      kicker: "Build / start here",
      lead: "Install Luminary locally, write a first fact, recall it, and keep the store inspectable.",
      sections: [
        { title: "Install", paragraphs: ["SQLite is the default backend and retrieval does not require an LLM."], code: "pip install luminary-memory" },
        { title: "First useful loop", paragraphs: ["Ingest a factual observation with scope and optional evidence. Recall returns a status, confidence, memories, and provenance rather than an opaque list."], code: "from luminary_memory import MemoryClient\n\nclient = MemoryClient(db_path=\"memory.db\")\nclient.ingest(\n    \"The deploy target is the staging cluster\",\n    tags=[\"deploy\"],\n    source=\"quickstart\",\n    evidence_quote=\"The deploy target is the staging cluster\",\n)\nresult = client.recall(\"where do we deploy?\")\nprint(result.status, result.confidence)" },
        { title: "Hermes continuity", paragraphs: ["Hermes separates core memory, durable query recall, and a bounded untrusted fallback from exact current-session episodes. The fallback keeps a short follow-up on its active task; it is not durable semantic memory."], code: "HERMES_PYTHON=\"$HOME/.hermes/venv/bin/python\" bash hermes/install.sh" },
        { title: "Keep it healthy", paragraphs: ["Lifecycle maintenance removes expired entries, consolidates near duplicates, and reports store health. For an older mixed-authority store, inspect the repair plan before applying it."], code: "luminary-memory lifecycle\nluminary-memory health\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db" }
      ]
    },
    "docs-index": {
      kicker: "Map / reading order",
      lead: "A focused map for choosing the right note before opening implementation details.",
      sections: [
        { title: "Build first", paragraphs: ["Start with Quickstart, then read Architecture and the Python API. Agent tools and Configuration describe the integration surfaces, including the exact provider boundary."], bullets: ["Quickstart", "Architecture", "Python API", "Agent tools", "Configuration"] },
        { title: "Operate next", paragraphs: ["Recall, Lifecycle, Backends, and the CLI reference explain how to run and maintain a store over time."], bullets: ["Recall", "Lifecycle", "Backends", "CLI reference", "Debugging guides"] },
        { title: "Integrate last", paragraphs: ["Hermes notes describe the provider boundary, installer, activity hook, repair utility, and the single-authority configuration. Planning notes are local and ignored; tracked guides are the public contract."], bullets: ["Hermes integration", "Hermes install kit", "Security boundaries", "Contribute safely"] }
      ]
    },
    architecture: {
      kicker: "System / architecture",
      lead: "Memory is a loop: recall before a response, ingest after a turn, and lifecycle maintenance in the background.",
      sections: [
        { title: "Ingest and store", paragraphs: ["Facts enter with content, tags, scope, source, validity, and optional evidence. SQLite stores the durable record, FTS5 index, embeddings, entity relations, provenance, and an immutable source-episode ledger."], code: "ingest -> whitelist -> evidence -> embed -> durable store\nHermes turn -> exact-session episode ledger" },
        { title: "Recall and delivery", paragraphs: ["Semantic, keyword, temporal, and graph candidates are scoped before fusion. Weighted RRF ranks the candidates, evidence gates the result, and token limits bound delivery. Hermes may use recent exact-session episodes only when durable recall has no usable block."], code: "scope -> candidates -> RRF -> evidence -> context | abstain\nabstain -> exact-session continuity fallback" },
        { title: "Maintenance and authority", paragraphs: ["A provider-owned post-turn review catches evidence-backed corrections before the session boundary; TTL cleanup, consolidation, importance estimation, pruning, and optional full LLM maintenance keep stale or duplicate memory from accumulating. The authority-repair script is dry-run first and archives rather than deletes."] }
      ]
    },
    api: {
      kicker: "Library / Python API",
      lead: "The MemoryClient exposes explicit operations for storing, recalling, maintaining, and inspecting memory.",
      sections: [
        { title: "Client surface", paragraphs: ["Use ingest and ingest_batch for writes, recall for scoped retrieval, and list or search for direct inspection. Explicit claim versioning uses supersede rather than similarity-only replacement."], code: "client.ingest(content, tags=[...], source=..., evidence_quote=...)\nclient.recall(query, limit=5, scope={...})\nclient.supersede(memory_id, replacement, source_text=...)" },
        { title: "Results carry state", paragraphs: ["RecallResult includes status, reason, confidence, memories, scores, and provenance. Strict paths can return abstain when no supported candidate survives the gate. Bound clients cannot mutate another scope."] },
        { title: "Durable core", paragraphs: ["Core-tagged records are loaded every session in stable insertion/id order within core_top_n and core_budget. They are kept separate from ordinary query recall. Explicit core add, remove, and list operations keep that surface visible."] }
      ]
    },
    recall: {
      kicker: "Operate / retrieval",
      lead: "Recall is conservative by design: the most similar result is not automatically the right result.",
      sections: [
        { title: "Four candidate signals", paragraphs: ["Semantic embeddings, SQLite FTS5 keyword search, temporal access patterns, and entity co-occurrence each produce candidates before fusion."], bullets: ["Semantic similarity", "Keyword relevance", "Temporal decay and access", "Entity graph relations"] },
        { title: "Evidence and abstention", paragraphs: ["Scope and status filters run first. Evidence grounding, conservative confidence, cliff cutoff, deduplication, and token budget run before serialization. If support is weak, the result is explicitly empty."], code: "{\n  \"status\": \"abstain\",\n  \"reason\": \"no_supported_candidate\"\n}" },
        { title: "Continuity is separate", paragraphs: ["When durable recall has no usable block, Hermes may read a bounded window of recent immutable episodes from the exact current session. It is untrusted reference context, does not participate in ranking, and never broadens scope or becomes a durable fact by being quoted."] }
      ]
    },
    lifecycle: {
      kicker: "Operate / maintenance",
      lead: "A memory store should get easier to trust as it gets older, not noisier.",
      sections: [
        { title: "Scheduled passes", paragraphs: ["Lifecycle can remove expired records, consolidate near duplicates, recompute importance, and prune low-value entries in bounded passes."], bullets: ["TTL cleanup", "Near-duplicate consolidation", "Importance estimation", "Pruning"] },
        { title: "Pinned and core records", paragraphs: ["Durable rules and pinned records are exempt from destructive maintenance unless an explicit operation changes them. Every pass leaves an inspectable result. Hermes episode continuity is outside these semantic passes." ] },
        { title: "Authority repair", paragraphs: ["For stores created during a mixed-authority period, run the SQLite repair utility read-only first. Applying it creates a consistent backup, archives structurally identified imported/uncurated rows, and records audit events."], code: "python scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db --apply" }
      ]
    },
    config: {
      kicker: "Reference / configuration",
      lead: "Library and provider settings stay explicit, scoped, and available through environment variables or configuration objects.",
      sections: [
        { title: "Local library settings", paragraphs: ["SQLite, database path, embedding model, token budget, strategy weights, scope identifiers, lifecycle thresholds, and core limits use the LUMINARY_* namespace."], code: "LUMINARY_BACKEND=sqlite\nLUMINARY_DB_PATH=memory.db\nLUMINARY_TOKEN_BUDGET=4096" },
        { title: "Provider settings", paragraphs: ["Hermes-specific options control auto-recall, auto-retain, incremental curation/reconciliation, full maintenance, indicators, core bounds, and recall limits. The exact-session continuity fallback intentionally reuses the existing session and token boundaries rather than adding another config surface."] },
        { title: "Authority boundary", paragraphs: ["The installer changes only provider selection plus Hermes' two native memory switches. `HERMES_PYTHON` selects the runtime used for installation and capability checks; no Hermes version is pinned and no source file is patched."] }
      ]
    },
    backends: {
      kicker: "Storage / backends",
      lead: "Start with a local SQLite file. Move to pgvector when the deployment needs a PostgreSQL-backed store.",
      sections: [
        { title: "SQLite default", paragraphs: ["SQLite provides zero-config persistence, FTS5 keyword search, local embeddings, schema migrations, exact scoped deduplication, provenance, and an inspectable file-backed authority. The provider also uses its episode ledger for exact-session continuity."], code: "client = MemoryClient(db_path=\"memory.db\")" },
        { title: "pgvector option", paragraphs: ["The pgvector backend follows the same client and ownership contract while moving vector storage and similarity search into PostgreSQL. Episode/provenance helpers must be available for the full Hermes contract."], code: "LUMINARY_BACKEND=pgvector\nLUMINARY_PG_DSN=postgresql://localhost/luminary_memory" },
        { title: "Choosing", paragraphs: ["Use SQLite for a local agent, a single operator, or a small deployment. Choose pgvector when the database is already managed centrally and concurrent scale matters."] }
      ]
    },
    cli: {
      kicker: "Operator / CLI",
      lead: "The CLI makes the store inspectable without requiring a separate dashboard.",
      sections: [
        { title: "Store and recall", paragraphs: ["Add facts, recall scoped context, list records, and search by content or metadata. JSON output is available for automation. `activity` reports active durable writes only, not raw session episodes."], code: "luminary-memory add \"deploy target is staging\" --tags deploy\nluminary-memory recall \"where do we deploy?\" --json\nluminary-memory list\nluminary-memory activity --json" },
        { title: "Maintain and diagnose", paragraphs: ["Run lifecycle, inspect graph and stats, export or import a backup, and check health when a result needs investigation. The authority repair script is separate and explicit."], code: "luminary-memory lifecycle\nluminary-memory health\nluminary-memory stats\nluminary-memory export --path backup.json\npython scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db" }
      ]
    },
    "agent-tools": {
      kicker: "Integration / agent surface",
      lead: "Explicit tools let an agent interact with memory without hiding which operation changed the store.",
      sections: [
        { title: "Query and write", paragraphs: ["luminary_recall retrieves scoped context with status, confidence, and provenance. luminary_ingest accepts only content plus an optional string-array of tags; source and importance are provider-controlled, not tool arguments. luminary_list is a recent inspection view."], bullets: ["luminary_recall", "luminary_ingest", "luminary_list"] },
        { title: "Core operations", paragraphs: ["Core add, remove, and list are separate from ordinary recall so durable prompt memory remains an explicit authority. Core list is stable by store id and bounded by its limit; prompt injection is additionally bounded by core_top_n/core_budget."], bullets: ["luminary_core_add", "luminary_core_remove", "luminary_core_list"] }
      ]
    },
    hermes: {
      kicker: "Integration / Hermes",
      lead: "Luminary plugs into Hermes through the public memory-provider boundary and keeps one persistent authority active.",
      sections: [
        { title: "Provider configuration", paragraphs: ["Set Luminary as the provider and disable Hermes' two native persistent surfaces together. The installer edits existing configuration keys and does not patch the Hermes source tree."], code: "memory:\n  provider: luminary\n  memory_enabled: false\n  user_profile_enabled: false" },
        { title: "Capability-based setup", paragraphs: ["The integration checks for the public provider contract. If the host cannot expose it, setup stops visibly instead of starting two competing memory systems."] },
        { title: "Runtime behavior", paragraphs: ["Auto-recall runs before the agent answers. With ingest_llm enabled, the serialized provider queue retains a curated summary and then reviews the same turn against exact-scope candidates for grounded captures, supersessions, or retractions. Every accepted turn also enters a non-durable exact-session episode ledger; when durable recall has no usable block, recent turns can preserve the active task without widening scope or promoting raw conversation into semantic memory. Full maintenance remains a session-boundary sweep."] },
        { title: "Visible output", paragraphs: ["CLI-capable Hermes status can report only committed changes, for example: saved 1, updated 1, retracted 1. The Telegram activity hook remains a separate delivery-safe agent:end mirror of persisted active rows. If an old store mixes authorities, the repair helper is dry-run first and backup-before-apply."] }
      ]
    },
    debugging: {
      kicker: "Operate / troubleshooting",
      lead: "Trace a missing result from scope to candidate generation, evidence, provider startup, and delivery.",
      sections: [
        { title: "A reliable investigation", paragraphs: ["Start with the active scope, then inspect health and counts, compare list and recall visibility, and check the redacted transparency event for status, reason, and latency. For context loss, verify session_episode and session_context events before changing ranking."], bullets: ["Confirm user, workspace, agent, and session scope", "Check session episode admission", "Check active status and validity", "Inspect evidence grounding", "Read the redacted trace event"] },
        { title: "What logs omit", paragraphs: ["Transparency events deliberately exclude prompt text, memory content, secrets, Telegram tokens, and API keys. They explain the path without becoming a second memory store. A repair dry run is the safe way to inspect mixed-authority rows."] }
      ]
    },
    benchmarks: {
      kicker: "Measurement / benchmark protocol",
      lead: "Measure latency and behavior under matched conditions without turning a controlled set into a universal superiority claim.",
      sections: [
        { title: "What is measured", paragraphs: ["The protocol covers latency, retrieval behavior, abstention accuracy, and a reproducible gold set with known scope and expected outcomes."], bullets: ["Matched local conditions", "Gold-set recall", "Abstention behavior", "Latency distribution"] },
        { title: "What is not claimed", paragraphs: ["Results do not establish universal superiority over Mem0, Hindsight, or another memory system. Comparisons remain bounded by the exact environment and set described in the protocol."] }
      ]
    },
    "hermes-kit": {
      kicker: "Integration / operator kit",
      lead: "A small install kit connects Hermes, optional activity reporting, and provider guidance without a source fork.",
      sections: [
        { title: "Install path", paragraphs: ["The installer checks the host capability, writes the provider configuration, and keeps native persistent surfaces disabled while Luminary is selected. Set HERMES_PYTHON when Hermes uses a dedicated virtualenv."], code: "HERMES_PYTHON=\"$HOME/.hermes/venv/bin/python\" bash hermes/install.sh" },
        { title: "Optional activity hook", paragraphs: ["The activity hook is separate from the memory authority. It reads active durable rows from the provider's resolved store, keeps a per-HERMES_HOME cursor, and advances it only after Telegram returns ok=true." ] },
        { title: "Upgrade and repair", paragraphs: ["Hermes upgrades require no source merge. Keep the three public memory keys, restart, and use the repair utility for stores created during a mixed-authority period."], code: "python scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db" }
      ]
    },
    project: {
      kicker: "Project / contribution",
      lead: "Contribute through small, inspectable changes with tests, documentation, and explicit safety boundaries.",
      sections: [
        { title: "Contribution path", paragraphs: ["Read the project map, run the test suite, keep changes scoped, and update tracked documentation when behavior changes."], bullets: ["Create a focused change", "Add or update tests", "Run lint and verification", "Describe the authority boundary"] },
        { title: "Project notes", paragraphs: ["The repository includes release history, contribution guidance, a code of conduct, and security expectations for maintainers and operators."] }
      ]
    },
    security: {
      kicker: "Safety / boundaries",
      lead: "Luminary is local by design. Storage and retrieval stay on the machine or database you control.",
      sections: [
        { title: "Local authority", paragraphs: ["SQLite files and your own PostgreSQL instance hold the memory store. Storage and retrieval do not send data to a hosted memory vendor."], bullets: ["Local SQLite or your PostgreSQL", "No hosted memory service", "No network call for ordinary recall"] },
        { title: "Optional network activity", paragraphs: ["LLM curation and maintenance are optional features that you configure explicitly. Keep credentials, prompts, and provider boundaries under the same operational controls as the host agent."] },
        { title: "Responsible reporting", paragraphs: ["Report security issues through the project security process and avoid publishing private memory data, credentials, or reproducible exploit details in public issues."] }
      ]
    }
  };
}());
