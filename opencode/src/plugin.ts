import { SessionQueryCache, extractText, formatRecallContext } from "./context";
import type { Hooks as OpenCodeHooks, Plugin, PluginInput as OpenCodePluginInput } from "@opencode-ai/plugin";
import { SidecarClient, type SidecarClientOptions } from "./sidecar-client";
import { createTools, localUserID, type MemoryClient } from "./tools";
import type { Scope } from "./protocol";

export type PluginInput = Pick<OpenCodePluginInput, "directory" | "worktree">;
export type Hooks = OpenCodeHooks;

export interface PluginOptions extends Record<string, unknown> {
  clientFactory?: (scope: Scope, sessionID: string) => MemoryClient;
  clientOptions?: Omit<SidecarClientOptions, "scope">;
  userID?: string;
}

export const LuminaryMemoryPlugin = async (input: PluginInput, rawOptions: Record<string, unknown> = {}): Promise<Hooks> => {
  const options = rawOptions as PluginOptions;
  const cache = new SessionQueryCache();
  const clients = new Map<string, { key: string; client: MemoryClient }>();
  const makeClient = options.clientFactory ?? ((scope: Scope) => new SidecarClient({ ...options.clientOptions, scope }));
  const baseScope = (sessionID: string, agent = "opencode"): Scope => ({
    user_id: options.userID || localUserID(),
    workspace_id: normalizeWorkspace(input.worktree || input.directory),
    agent_id: agent,
    session_id: sessionID,
  });
  const clientFor = (scope: Scope, sessionID: string): MemoryClient => {
    const key = scopeKey(scope);
    const existing = clients.get(sessionID);
    if (existing?.key === key) return existing.client;
    if (existing) void existing.client.dispose().catch(() => undefined);
    const client = makeClient(scope, sessionID);
    clients.set(sessionID, { key, client });
    return client;
  };
  const hooks: OpenCodeHooks = {
    tool: createTools((scope, sessionID) => clientFor({
      ...scope,
      user_id: options.userID || localUserID(),
      workspace_id: normalizeWorkspace(input.worktree || input.directory),
    }, sessionID)),
    "chat.message": async ({ sessionID, agent }, output) => {
      const query = extractText(output.parts);
      cache.set(sessionID, query, agent || "opencode");
    },
    "experimental.chat.system.transform": async ({ sessionID }, output) => {
      if (!sessionID) return;
      const entry = cache.get(sessionID);
      if (!entry) return;
      try {
        const result = await clientFor(baseScope(sessionID, entry.agent), sessionID).recall(entry.query, { limit: 5, strict: true });
        const block = formatRecallContext(result);
        if (block) output.system.push(block);
      } catch {
        // Memory is optional; preserve the user's OpenCode request on sidecar failure.
      }
    },
    event: async ({ event }) => {
      if (event.type !== "session.deleted") return;
      const properties = event.properties as Record<string, unknown> | undefined;
      const info = properties?.info;
      const sessionID = typeof info === "object" && info !== null && "id" in info && typeof info.id === "string"
        ? info.id
        : typeof properties?.sessionID === "string"
          ? properties.sessionID
          : undefined;
      if (!sessionID) return;
      cache.delete(sessionID);
      const entry = clients.get(sessionID);
      clients.delete(sessionID);
      try {
        await entry?.client.dispose();
      } catch {
        // Cleanup failures must not affect OpenCode event processing.
      }
    },
    dispose: async () => {
      cache.clear();
      const pending = [...clients.values()].map(({ client }) => client.dispose());
      clients.clear();
      await Promise.allSettled(pending);
    },
  };
  return hooks;
};

export const OpenCodePlugin: Plugin = LuminaryMemoryPlugin;

export default OpenCodePlugin;

function scopeKey(scope: Scope): string {
  return [scope.user_id, scope.workspace_id, scope.agent_id, scope.session_id || ""].join("\u0000");
}

function normalizeWorkspace(value: string): string {
  return value.replaceAll("\\", "/").replace(/\/+$/, "") || "/";
}
