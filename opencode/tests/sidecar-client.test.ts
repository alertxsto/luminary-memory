import { describe, expect, test } from "bun:test";
import {
  SidecarClient,
  type HealthResult,
  type IngestResult,
  type ListResult,
  type RecallResult,
  type SidecarTransport,
} from "../src/sidecar-client";

const scope = {
  user_id: "user-1",
  workspace_id: "workspace-1",
  agent_id: "build",
  session_id: "session-1",
};

class FakeTransport implements SidecarTransport {
  readonly writes: string[] = [];
  writeError?: Error;
  private lineHandler?: (line: string) => void;
  private exitHandler?: (error: Error) => void;

  write(line: string): void {
    if (this.writeError) throw this.writeError;
    this.writes.push(line);
  }

  onLine(handler: (line: string) => void): void {
    this.lineHandler = handler;
  }

  onExit(handler: (error: Error) => void): void {
    this.exitHandler = handler;
  }

  respond(value: unknown): void {
    this.lineHandler?.(JSON.stringify(value));
  }

  emit(line: string): void {
    this.lineHandler?.(line);
  }

  exit(message = "sidecar exited"): void {
    this.exitHandler?.(new Error(message));
  }

  kill(): void {
    this.exit();
  }
}

function requestAt(transport: FakeTransport, index = 0): Record<string, unknown> {
  return JSON.parse(transport.writes[index]);
}

describe("SidecarClient", () => {
  test("correlates a typed response with its request id and keeps content as data", async () => {
    const transport = new FakeTransport();
    const client = new SidecarClient({ scope, transport });
    const resultPromise: Promise<RecallResult> = client.recall("deployment preference");
    const request = requestAt(transport);

    transport.respond({
      protocol_version: "1",
      request_id: request.request_id,
      status: "ok",
      result: { memories: [{ content: "Use SQLite" }], confidence: 0.9 },
    });

    await expect(resultPromise).resolves.toEqual({
      memories: [{ content: "Use SQLite" }],
      confidence: 0.9,
    });
  });

  test("exposes typed results for every operation", () => {
    const transport = new FakeTransport();
    const client = new SidecarClient({ scope, transport });
    const health: Promise<HealthResult> = client.health();
    const recall: Promise<RecallResult> = client.recall("query");
    const ingest: Promise<IngestResult> = client.ingest("content");
    const list: Promise<ListResult> = client.list();

    expect([health, recall, ingest, list]).toHaveLength(4);
  });

  test("serializes concurrent calls while assigning distinct request ids", async () => {
    const transport = new FakeTransport();
    const client = new SidecarClient({ scope, transport });
    const first = client.health();
    const second = client.list();

    expect(transport.writes).toHaveLength(1);
    const firstRequest = requestAt(transport, 0);
    transport.respond({ protocol_version: "1", request_id: firstRequest.request_id, status: "ok", result: 1 });
    await first;
    expect(transport.writes).toHaveLength(2);
    const secondRequest = requestAt(transport, 1);
    expect(secondRequest.request_id).not.toBe(firstRequest.request_id);
    transport.respond({ protocol_version: "1", request_id: secondRequest.request_id, status: "ok", result: { memories: [] } });
    await expect(second).resolves.toEqual({ memories: [] });
  });

  test("rejects structured sidecar errors and malformed responses", async () => {
    const transport = new FakeTransport();
    const client = new SidecarClient({ scope, transport });
    const failed = client.ingest("candidate");
    const request = requestAt(transport);
    transport.respond({
      protocol_version: "1",
      request_id: request.request_id,
      status: "error",
      error: { code: "invalid_request", message: "bad candidate" },
    });
    await expect(failed).rejects.toThrow("bad candidate");

    const malformed = client.health();
    transport.emit("not-json");
    await expect(malformed).rejects.toThrow("malformed sidecar response");
  });

  test("rejects pending calls on process exit and timeout", async () => {
    const transport = new FakeTransport();
    const client = new SidecarClient({ scope, transport, timeoutMs: 5 });
    const exited = client.health();
    transport.exit("python stopped");
    await expect(exited).rejects.toThrow("python stopped");

    const timedOutTransport = new FakeTransport();
    const timedOutClient = new SidecarClient({ scope, transport: timedOutTransport, timeoutMs: 5 });
    await expect(timedOutClient.health()).rejects.toThrow("timed out");
  });

  test("disposes the transport and rejects future calls", async () => {
    const transport = new FakeTransport();
    const client = new SidecarClient({ scope, transport });
    await client.dispose();
    await expect(client.health()).rejects.toThrow("disposed");
  });

  test("disposal rejects the active and queued calls", async () => {
    const transport = new FakeTransport();
    const client = new SidecarClient({ scope, transport });
    const active = client.health();
    const queued = client.list();

    await client.dispose();

    await expect(active).rejects.toThrow("disposed");
    await expect(queued).rejects.toThrow("disposed");
    expect(transport.writes).toHaveLength(1);
  });

  test("rejects immediately when the transport cannot write", async () => {
    const transport = new FakeTransport();
    transport.writeError = new Error("broken pipe");
    const client = new SidecarClient({ scope, transport, timeoutMs: 10_000 });
    const started = Date.now();

    await expect(client.health()).rejects.toThrow("broken pipe");
    expect(Date.now() - started).toBeLessThan(1000);
  });
});
