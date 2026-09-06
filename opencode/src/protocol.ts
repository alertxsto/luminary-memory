export const PROTOCOL_VERSION = "1" as const;

export type Operation = "health" | "recall" | "ingest" | "list";

export interface Scope {
  user_id: string;
  workspace_id: string;
  agent_id: string;
  session_id?: string;
}

export interface Request<TPayload = Record<string, unknown>> {
  protocol_version: typeof PROTOCOL_VERSION;
  request_id: string;
  operation: Operation;
  scope: Scope;
  payload: TPayload;
}

export interface ErrorValue {
  code: string;
  message: string;
}

export interface Response<TResult = unknown> {
  protocol_version: typeof PROTOCOL_VERSION;
  request_id: string;
  status: "ok" | "error";
  result?: TResult;
  error?: ErrorValue;
}

export type RecallPayload = { query: string; limit?: number; tags?: string[]; strict?: boolean };
export type IngestPayload = { content: string; tags?: string[] };
export type ListPayload = { limit?: number; cursor?: string };

export interface MemoryRecord {
  id: number | null;
  content: string;
  metadata: Record<string, unknown>;
  source: string | null;
  tags: string[];
  importance: number;
  created_at: string;
  updated_at: string;
  user_id: string | null;
  session_id: string | null;
  workspace_id: string | null;
  agent_id: string | null;
  observed_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  status: string;
  confidence: number;
  evidence_quote: string | null;
  source_id: string | null;
  claim_key: string | null;
}

export interface HealthResult {
  score: number;
  dimensions: Record<string, number>;
  recommendations: string[];
}

export interface RecallResult {
  status: string;
  reason: string | null;
  confidence: number;
  memories: MemoryRecord[];
  scores: number[];
  strategies_hit: Record<string, number>;
  provenance: Array<Record<string, unknown>>;
}

export interface IngestResult {
  accepted: boolean;
  id: number | null;
}

export interface ListResult {
  memories: MemoryRecord[];
  count: number;
  next_cursor: string | null;
}

export function encodeRequest<TPayload>(request: Request<TPayload>): string {
  return JSON.stringify(request);
}

export function decodeResponse(line: string): Response {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch (error) {
    throw new ProtocolError("malformed sidecar response", error);
  }
  if (!isRecord(value) || value.protocol_version !== PROTOCOL_VERSION || typeof value.request_id !== "string") {
    throw new ProtocolError("malformed sidecar response");
  }
  if (value.status !== "ok" && value.status !== "error") {
    throw new ProtocolError("malformed sidecar response");
  }
  if (value.status === "error") {
    if (!isRecord(value.error) || typeof value.error.code !== "string" || typeof value.error.message !== "string") {
      throw new ProtocolError("malformed sidecar response");
    }
  }
  return value as Response;
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export class ProtocolError extends Error {
  constructor(message: string, options?: unknown) {
    super(message, options ? { cause: options } : undefined);
    this.name = "ProtocolError";
  }
}
