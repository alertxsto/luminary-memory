(function () {
  "use strict";

  var root = "docs.html?doc=";
  var docs = [
    {
      id: "quickstart",
      category: "build",
      label: "START HERE",
      title: "Quickstart",
      source: "docs/quickstart.md",
      blurb: "Install the library, write a first fact, recall it, run lifecycle maintenance, and wire Hermes without hiding the authority boundary or confusing continuity with durable memory.",
      facts: ["Python API + CLI", "SQLite default", "Scoped continuity"]
    },
    {
      id: "docs-index",
      category: "build",
      label: "MAP",
      title: "Documentation map",
      source: "docs/index.md",
      blurb: "The public reading order for the library, CLI, agent tools, lifecycle, backend, Hermes, repair utility, and benchmark notes.",
      facts: ["Public source map", "Reading order", "Source contracts"]
    },
    {
      id: "architecture",
      category: "build",
      label: "SYSTEM",
      title: "Architecture",
      source: "docs/architecture.md",
      blurb: "The complete loop from ingest and evidence to four-strategy recall, exact-session continuity, post-turn reconciliation, core injection, backends, and lifecycle passes.",
      facts: ["Three context surfaces", "Scope before candidates", "Evidence-backed review"]
    },
    {
      id: "api",
      category: "build",
      label: "LIBRARY",
      title: "Python API",
      source: "docs/api.md",
      blurb: "Client methods, ingest metadata, recall results, conflict handling, scope boundaries, core memory, lifecycle, health, and export interfaces.",
      facts: ["MemoryClient", "Evidence fields", "Health report"]
    },
    {
      id: "recall",
      category: "operate",
      label: "RETRIEVAL",
      title: "Recall",
      source: "docs/recall.md",
      blurb: "How semantic, keyword, temporal, graph, confidence, abstention, continuity fallback, deduplication, and token budgets shape a result.",
      facts: ["Strict recall", "Abstention", "Provenance"]
    },
    {
      id: "lifecycle",
      category: "operate",
      label: "MAINTENANCE",
      title: "Lifecycle",
      source: "docs/lifecycle.md",
      blurb: "TTL cleanup, near-duplicate consolidation, importance estimation, pruning, optional LLM maintenance, and authority repair.",
      facts: ["Cleanup", "Consolidate", "Repair before apply"]
    },
    {
      id: "config",
      category: "operate",
      label: "REFERENCE",
      title: "Configuration",
      source: "docs/config-reference.md",
      blurb: "The full Settings and provider configuration reference, including scope, core memory, secrets, incremental review, and Hermes activation keys.",
      facts: ["LUMINARY_*", "Provider config", "Review contract"]
    },
    {
      id: "backends",
      category: "operate",
      label: "STORAGE",
      title: "Backends",
      source: "docs/backends.md",
      blurb: "SQLite and pgvector behavior, exact deduplication, episode/provenance storage, schema expectations, indexing, and the backend contract.",
      facts: ["FTS5", "Cosine search", "pgvector option"]
    },
    {
      id: "cli",
      category: "operate",
      label: "OPERATOR",
      title: "CLI reference",
      source: "docs/cli.md",
      blurb: "Commands for add, recall, list, search, export, import, lifecycle, graph, health, stats, and diagnostics.",
      facts: ["JSON output", "Health checks", "Store inspection"]
    },
    {
      id: "agent-tools",
      category: "integrate",
      label: "AGENT SURFACE",
      title: "Agent tools",
      source: "docs/agent-tools.md",
      blurb: "Exact tool schemas and safety boundaries for recall, ingest, list, and the explicit core-memory operations.",
      facts: ["Exact schemas", "Scoped writes", "Core tools"]
    },
    {
      id: "hermes",
      category: "integrate",
      label: "ADAPTER",
      title: "Hermes integration",
      source: "docs/hermes-integration.md",
      blurb: "Public provider entry point, three context surfaces, scoped retain-and-review, the no-source-patch installer, and capability-based upgrades.",
      facts: ["CLI / gateway", "Session continuity", "No version pin"]
    },
    {
      id: "native-migration",
      category: "integrate",
      label: "AUTHORITY",
      title: "Native memory migration",
      source: "scripts/migrate_native_memory.py",
      related: ["docs/hermes-integration.md", "hermes/README.md"],
      blurb: "A read-only-first utility for carrying Hermes MEMORY.md and USER.md into lossless Luminary core snapshots without editing native files or creating a second runtime authority.",
      facts: ["Read-only by default", "SQLite backup", "Idempotent snapshots"]
    },
    {
      id: "debugging",
      category: "operate",
      label: "TROUBLESHOOTING",
      title: "Debugging guides",
      source: "docs/debugging-v0.2.17.md",
      related: ["docs/DEBUGGING-SCOPE-v0.2.17.md"],
      blurb: "A practical path for tracing missing recall, active-session loss, scope leakage, provider startup, logs, repair, and integration behavior.",
      facts: ["Continuity checks", "Transparency log", "Repair dry run"]
    },
    {
      id: "benchmarks",
      category: "operate",
      label: "MEASUREMENT",
      title: "Benchmark protocol",
      source: "benchmarks/README.md",
      related: ["benchmarks/RESULTS.md"],
      blurb: "Reproducible latency and gold-set evaluation with an explicit boundary: the controlled set is not a superiority claim over Mem0 or Hindsight.",
      facts: ["Gold set", "Abstention accuracy", "Matched conditions"]
    },
    {
      id: "hermes-kit",
      category: "integrate",
      label: "OPERATOR KIT",
      title: "Hermes install kit",
      source: "hermes/README.md",
      related: ["hermes/SKILL.md", "hermes/hooks/luminary-activity/README.md"],
      blurb: "One-shot provider install, optional activity hook, skill guidance, runtime selection, and the config contract that keeps one persistent authority.",
      facts: ["Install script", "Activity hook", "Upgrade-safe boundary"]
    },
    {
      id: "project",
      category: "integrate",
      label: "PROJECT",
      title: "Contribute safely",
      source: "CONTRIBUTING.md",
      related: ["README.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md"],
      blurb: "Contribution workflow, project overview, security boundaries, and release history for maintainers and operators.",
      facts: ["Contribution guide", "Security policy", "Changelog"]
    },
    {
      id: "security",
      category: "integrate",
      label: "SAFETY",
      title: "Security boundaries",
      source: "SECURITY.md",
      blurb: "Local storage, optional network activity, reporting expectations, and the boundaries that keep memory data on your infrastructure.",
      facts: ["Local by design", "Disclosure path", "No hosted store"]
    }
  ];

  window.LUMINARY_DOCS = docs.map(function (doc) {
    doc.href = root + encodeURIComponent(doc.id);
    return doc;
  });
}());
