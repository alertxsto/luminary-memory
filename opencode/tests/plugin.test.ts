import { expect, test } from "bun:test";
import { LuminaryMemoryPlugin } from "../src/plugin";
import type { Scope } from "../src/protocol";

function fakeClient() {
  return {
    recalls: [] as string[],
    recallOptions: [] as Array<{ limit?: number; tags?: string[]; strict?: boolean }>,
    ingests: [] as Array<{ content: string; tags?: string[] }>,
    disposed: false,
    async recall(query: string, options: { limit?: number; tags?: string[]; strict?: boolean } = {}) {
      this.recalls.push(query);
      this.recallOptions.push(options);
      return { status: "ok", reason: null, confidence: 0.91, memories: [{
        id: 1, content: "remembered", metadata: {}, source: "README.md", tags: [], importance: 0.5,
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", user_id: "local",
        session_id: null, workspace_id: "/repo", agent_id: "builder", observed_at: null, valid_from: null,
        valid_to: null, status: "active", confidence: 0.9, evidence_quote: null, source_id: "m1", claim_key: null,
      }], scores: [], strategies_hit: {}, provenance: [] };
    },
    async ingest(content: string, options: { tags?: string[] }) {
      this.ingests.push({ content, tags: options.tags });
      return { accepted: true, id: 4 };
    },
    async dispose() { this.disposed = true; },
  };
}

test("recalls only the active session query and injects bounded reference context", async () => {
  const clients: ReturnType<typeof fakeClient>[] = [];
  const hooks = await LuminaryMemoryPlugin(
    { directory: "/repo", worktree: "/repo" },
    { clientFactory: () => { const client = fakeClient(); clients.push(client); return client; } },
  );

  await hooks["chat.message"]?.({ sessionID: "s1", agent: "builder" }, { message: {}, parts: [{ type: "text", text: "active query" }] });
  const output = { system: ["Follow system rules"] };
  await hooks["experimental.chat.system.transform"]?.({ sessionID: "s1", model: {} }, output);

  expect(clients[0]?.recalls).toEqual(["active query"]);
  expect(clients[0]?.recallOptions).toEqual([{ limit: 5, strict: true }]);
  expect(output.system[0]).toBe("Follow system rules");
  expect(output.system[1]).toContain("Reference material from Luminary Memory");
});

test("registers explicit tools, scopes them from the tool session, and never ingests ordinary chat", async () => {
  const clients: ReturnType<typeof fakeClient>[] = [];
  const scopes: Scope[] = [];
  const hooks = await LuminaryMemoryPlugin(
    { directory: "/repo", worktree: "/repo" },
    { clientFactory: (scope) => { scopes.push(scope); const client = fakeClient(); clients.push(client); return client; } },
  );

  await hooks["chat.message"]?.({ sessionID: "s1", agent: "builder" }, { message: {}, parts: [{ type: "text", text: "hello" }] });
  expect(clients).toHaveLength(0);
  const recall = await hooks.tool.luminary_recall.execute({ query: "history", tags: ["work"] }, { sessionID: "s2", agent: "reviewer", directory: "/repo", worktree: "/repo" });
  const ingest = await hooks.tool.luminary_ingest.execute({ content: "durable fact", tags: ["fact"] }, { sessionID: "s2", agent: "reviewer", directory: "/repo", worktree: "/repo" });

  expect(JSON.parse((recall as { output: string }).output)).toMatchObject({ status: "ok", confidence: 0.91 });
  expect(JSON.parse((ingest as { output: string }).output)).toMatchObject({ status: "ok", accepted: true, id: 4 });
  expect(clients).toHaveLength(1);
  expect(clients[0]?.ingests).toEqual([{ content: "durable fact", tags: ["fact"] }]);
  expect(scopes[0]).toMatchObject({ workspace_id: "/repo", agent_id: "reviewer", session_id: "s2" });
  expect(scopes[0]?.user_id).not.toBe("local");
});

test("uses configured user identity without merging users into a shared local scope", async () => {
  const scopes: Scope[] = [];
  const hooks = await LuminaryMemoryPlugin(
    { directory: "/repo", worktree: "/repo" },
    {
      userID: "local:configured-user",
      clientFactory: (scope) => {
        scopes.push(scope);
        return fakeClient();
      },
    },
  );

  await hooks.tool.luminary_recall.execute({ query: "identity" }, { sessionID: "s1", agent: "builder", directory: "/repo", worktree: "/repo" });

  expect(scopes[0]?.user_id).toBe("local:configured-user");
});

test("deletes session state and disposes clients", async () => {
  const clients: ReturnType<typeof fakeClient>[] = [];
  const hooks = await LuminaryMemoryPlugin(
    { directory: "/repo", worktree: "/repo" },
    { clientFactory: () => { const client = fakeClient(); clients.push(client); return client; } },
  );
  await hooks["chat.message"]?.({ sessionID: "s1", agent: "builder" }, { message: {}, parts: [{ type: "text", text: "query" }] });
  await hooks["experimental.chat.system.transform"]?.({ sessionID: "s1", model: {} }, { system: [] });
  await hooks.event?.({ event: { type: "session.deleted", properties: { info: { id: "s1" } } } });

  expect(clients[0]?.disposed).toBe(true);
});

test("failed automatic recall and explicit tools degrade without throwing", async () => {
  const hooks = await LuminaryMemoryPlugin(
    { directory: "/repo", worktree: "/repo" },
    {
      clientFactory: () => ({
        recall: async () => { throw new Error("sidecar unavailable"); },
        ingest: async () => { throw new Error("sidecar unavailable"); },
        dispose: async () => undefined,
      }),
    },
  );
  await hooks["chat.message"]?.({ sessionID: "s1", agent: "builder" }, { message: {}, parts: [{ type: "text", text: "query" }] });
  const output = { system: ["rules"] };
  await expect(hooks["experimental.chat.system.transform"]?.({ sessionID: "s1", model: {} }, output)).resolves.toBeUndefined();
  await expect(hooks.tool.luminary_recall.execute({ query: "query" }, { sessionID: "s2", agent: "builder", directory: "/repo", worktree: "/repo" })).resolves.toMatchObject({ title: "Luminary recall error" });
  await expect(hooks.tool.luminary_ingest.execute({ content: "fact" }, { sessionID: "s2", agent: "builder", directory: "/repo", worktree: "/repo" })).resolves.toMatchObject({ title: "Luminary ingest error" });
  expect(output.system).toEqual(["rules"]);
});

test("recreates a session client when agent scope changes", async () => {
  const clients: ReturnType<typeof fakeClient>[] = [];
  const scopes: Scope[] = [];
  const hooks = await LuminaryMemoryPlugin(
    { directory: "/repo", worktree: "/repo" },
    { clientFactory: (scope) => { scopes.push(scope); const client = fakeClient(); clients.push(client); return client; } },
  );
  await hooks.tool.luminary_recall.execute({ query: "first" }, { sessionID: "s1", agent: "builder", directory: "/repo", worktree: "/repo" });
  await hooks.tool.luminary_recall.execute({ query: "second" }, { sessionID: "s1", agent: "reviewer", directory: "/repo", worktree: "/repo" });
  expect(clients).toHaveLength(2);
  expect(clients[0]?.disposed).toBe(true);
  expect(scopes.map((scope) => scope.agent_id)).toEqual(["builder", "reviewer"]);
});
