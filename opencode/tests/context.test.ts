import { expect, test } from "bun:test";
import { SessionQueryCache, formatRecallContext } from "../src/context";
import type { MemoryRecord, RecallResult } from "../src/protocol";

const memory = (content: string, source_id: string | null = null): MemoryRecord => ({
  id: 1,
  content,
  metadata: {},
  source: source_id ? "README.md" : null,
  tags: [],
  importance: 0.5,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  user_id: "local",
  session_id: null,
  workspace_id: "/repo",
  agent_id: "builder",
  observed_at: null,
  valid_from: null,
  valid_to: null,
  status: "active",
  confidence: 0.88,
  evidence_quote: null,
  source_id,
  claim_key: null,
});

test("stores only bounded latest query per session and clears it", () => {
  const cache = new SessionQueryCache(5);
  cache.set("session-a", "abcdef", "agent-a");

  expect(cache.get("session-a")).toEqual({ query: "abcde", agent: "agent-a" });
  cache.delete("session-a");
  expect(cache.get("session-a")).toBeUndefined();
});

test("formats usable recall as bounded reference context with provenance", () => {
  const result: RecallResult = {
    status: "ok",
    reason: null,
    confidence: 0.93,
    memories: [memory("Use SQLite for local tests.", "doc-7"), memory("x".repeat(5000))],
    scores: [],
    strategies_hit: {},
    provenance: [],
  };
  const block = formatRecallContext(result);

  expect(block).toContain("Reference material from Luminary Memory");
  expect(block).toContain("confidence: 0.93");
  expect(block).toContain("doc-7");
  expect(block.length).toBeLessThanOrEqual(5000);
  expect(block).not.toContain("x".repeat(5000));
});

test("does not format abstained or empty recall", () => {
  const base: RecallResult = { status: "abstain", reason: "low confidence", confidence: 0.99, memories: [], scores: [], strategies_hit: {}, provenance: [] };
  expect(formatRecallContext(base)).toBeUndefined();
  expect(formatRecallContext({ ...base, status: "ok" })).toBeUndefined();
});

test("does not inject low-confidence results even when status is ok", () => {
  const result: RecallResult = {
    status: "ok",
    reason: null,
    confidence: 0.1,
    memories: [memory("Untrusted low-confidence fact.")],
    scores: [],
    strategies_hit: {},
    provenance: [],
  };

  expect(formatRecallContext(result)).toBeUndefined();
});
