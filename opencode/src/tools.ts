import { tool, type ToolContext } from "@opencode-ai/plugin";
import type { IngestResult, RecallResult, Scope } from "./protocol";

export type { ToolContext } from "@opencode-ai/plugin";
export interface MemoryClient {
  recall(query: string, options?: { limit?: number; tags?: string[]; strict?: boolean }): Promise<RecallResult>;
  ingest(content: string, options?: { tags?: string[] }): Promise<IngestResult>;
  dispose(): Promise<void>;
}

export type ToolDefinition = ReturnType<typeof tool>;

export interface ToolClientFactory {
  (scope: Scope, sessionID: string): MemoryClient;
}

export function createTools(factory: ToolClientFactory): Record<string, ToolDefinition> {
  return {
    luminary_recall: tool({
      description: "Search Luminary Memory for relevant durable reference material.",
      args: {
        query: tool.schema.string().describe("The durable-memory search query."),
        tags: tool.schema.array(tool.schema.string()).optional().describe("Optional memory tags."),
      },
      async execute(args: { query: string; tags?: string[] }, context) {
        if (!args.query.trim()) return toolResult({ status: "error", error: "query is required" }, "Luminary recall error");
        try {
          const client = factory(scopeFor(context), context.sessionID);
          return toolResult(await client.recall(args.query, { tags: cleanTags(args.tags) }), "Luminary recall");
        } catch (error) {
          return toolResult(toolError(error), "Luminary recall error");
        }
      },
    }),
    luminary_ingest: tool({
      description: "Explicitly store a concise durable fact in Luminary Memory.",
      args: {
        content: tool.schema.string().describe("The concise durable fact to store."),
        tags: tool.schema.array(tool.schema.string()).optional().describe("Optional memory tags."),
      },
      async execute(args: { content: string; tags?: string[] }, context) {
        if (!args.content.trim()) return toolResult({ status: "error", error: "content is required" }, "Luminary ingest error");
        try {
          const client = factory(scopeFor(context), context.sessionID);
          const result = await client.ingest(args.content, { tags: cleanTags(args.tags) });
          return toolResult({ status: "ok", ...result }, "Luminary ingest");
        } catch (error) {
          return toolResult(toolError(error), "Luminary ingest error");
        }
      },
    }),
  };
}

export function scopeFor(context: ToolContext, userID = localUserID()): Scope {
  return { user_id: userID, workspace_id: normalizeWorkspace(context.worktree || context.directory), agent_id: context.agent || "opencode", session_id: context.sessionID };
}

export function localUserID(): string {
  const processValue = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  const configured = processValue?.env?.LUMINARY_USER_ID?.trim()
    || processValue?.env?.USER?.trim()
    || processValue?.env?.USERNAME?.trim()
    || processValue?.env?.HOME?.trim();
  return `local:${configured || "unknown"}`;
}

function cleanTags(value: string[] | undefined): string[] | undefined {
  return value?.filter((tag) => tag.trim().length > 0).map((tag) => tag.trim());
}

function normalizeWorkspace(value: string): string {
  return value.replaceAll("\\", "/").replace(/\/+$/, "") || "/";
}

function toolError(error: unknown): { status: "error"; error: string } {
  return { status: "error", error: error instanceof Error ? error.message : String(error) };
}

function toolResult(value: unknown, title: string): { title: string; output: string; metadata: Record<string, unknown> } {
  const metadata = typeof value === "object" && value !== null ? value as Record<string, unknown> : { value };
  return { title, output: JSON.stringify(value), metadata };
}
