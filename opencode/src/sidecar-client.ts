import {
  decodeResponse,
  encodeRequest,
  type HealthResult,
  type IngestResult,
  PROTOCOL_VERSION,
  type IngestPayload,
  type ListPayload,
  type ListResult,
  type RecallPayload,
  type RecallResult,
  type Request,
  type Response,
  type Scope,
} from "./protocol";

export type { HealthResult, IngestResult, ListResult, RecallResult } from "./protocol";

export interface SidecarTransport {
  write(line: string): void;
  onLine(handler: (line: string) => void): void;
  onExit(handler: (error: Error) => void): void;
  kill(): void;
}

export interface SidecarClientOptions {
  scope: Scope;
  pythonExecutable?: string;
  databasePath?: string;
  sidecarModule?: string;
  cwd?: string;
  timeoutMs?: number;
  transport?: SidecarTransport;
}

interface Pending {
  request: Request;
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class SidecarClient {
  private readonly scope: Scope;
  private readonly timeoutMs: number;
  private readonly transport: SidecarTransport;
  private readonly queue: Pending[] = [];
  private active?: Pending;
  private disposed = false;
  private processError?: Error;
  private readonly ignoredResponseIds = new Set<string>();
  private sequence = 0;

  constructor(options: SidecarClientOptions) {
    this.scope = options.scope;
    this.timeoutMs = Math.max(1, options.timeoutMs ?? 10_000);
    this.transport = options.transport ?? createProcessTransport(options);
    this.transport.onLine((line) => this.handleLine(line));
    this.transport.onExit((error) => this.handleExit(error));
  }

  health(): Promise<HealthResult> {
    return this.call<HealthResult>("health", {});
  }

  recall(query: string, options: { limit?: number; tags?: string[]; strict?: boolean } = {}): Promise<RecallResult> {
    return this.call<RecallResult>("recall", { query, ...options });
  }

  ingest(content: string, options: { tags?: string[] } = {}): Promise<IngestResult> {
    return this.call<IngestResult>("ingest", { content, ...options });
  }

  list(options: ListPayload = {}): Promise<ListResult> {
    return this.call<ListResult>("list", options);
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    const error = new Error("sidecar client disposed");
    this.rejectAll(error);
    this.transport.kill();
  }

  private call<TResult>(operation: Request["operation"], payload: RecallPayload | IngestPayload | ListPayload | Record<string, never>): Promise<TResult> {
    return new Promise<TResult>((resolve, reject) => {
      if (this.disposed) {
        reject(new Error("sidecar client disposed"));
        return;
      }
      if (this.processError) {
        reject(this.processError);
        return;
      }
      const request: Request = {
        protocol_version: PROTOCOL_VERSION,
        request_id: `opencode-${++this.sequence}`,
        operation,
        scope: this.scope,
        payload,
      };
      const pending = {
        request,
        resolve: (value: unknown) => resolve(value as TResult),
        reject,
        timer: setTimeout(() => undefined, 0),
      };
      clearTimeout(pending.timer);
      this.queue.push(pending);
      this.pump();
    });
  }

  private pump(): void {
    if (this.active || this.disposed || this.processError) return;
    const pending = this.queue.shift();
    if (!pending) return;
    this.active = pending;
    pending.timer = setTimeout(() => {
      if (this.active !== pending) return;
      this.active = undefined;
      this.ignoredResponseIds.add(pending.request.request_id);
      pending.reject(new Error(`sidecar request ${pending.request.request_id} timed out`));
      this.pump();
    }, this.timeoutMs);
    try {
      this.transport.write(`${encodeRequest(pending.request)}\n`);
    } catch (error) {
      const failure = error instanceof Error ? error : new Error(String(error));
      this.processError = failure;
      this.rejectAll(failure);
    }
  }

  private handleLine(line: string): void {
    const pending = this.active;
    if (!pending) return;
    let response: Response;
    try {
      response = decodeResponse(line);
    } catch (error) {
      this.finish(undefined, error instanceof Error ? error : new Error(String(error)));
      return;
    }
    if (response.request_id !== pending.request.request_id) {
      if (this.ignoredResponseIds.delete(response.request_id)) return;
      this.finish(undefined, new Error("sidecar response request id mismatch"));
      return;
    }
    if (response.status === "error") {
      this.finish(undefined, new Error(`${response.error?.code ?? "sidecar_error"}: ${response.error?.message ?? "unknown error"}`));
    } else {
      this.finish(response.result, undefined);
    }
  }

  private handleExit(error: Error): void {
    if (this.disposed) return;
    this.processError = error;
    this.rejectAll(error);
  }

  private finish(value: unknown, error?: Error): void {
    const pending = this.active;
    if (!pending) return;
    this.active = undefined;
    clearTimeout(pending.timer);
    if (error) pending.reject(error);
    else pending.resolve(value);
    this.pump();
  }

  private rejectAll(error: Error): void {
    if (this.active) {
      clearTimeout(this.active.timer);
      this.active.reject(error);
      this.active = undefined;
    }
    for (const pending of this.queue.splice(0)) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
  }
}

interface BunProcess {
  stdin: { write(data: string): void; end(): void };
  stdout: AsyncIterable<Uint8Array | string>;
  stderr: AsyncIterable<Uint8Array | string>;
  exited: Promise<number>;
  kill(): void;
}

declare const Bun: { spawn(command: string[], options: Record<string, unknown>): BunProcess };
declare const process: { env: Record<string, string | undefined> } | undefined;

function createProcessTransport(options: SidecarClientOptions): SidecarTransport {
  const process = Bun.spawn(
    [options.pythonExecutable ?? "python", "-m", options.sidecarModule ?? "luminary_memory.opencode.sidecar"],
    {
      cwd: options.cwd,
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
      env: options.databasePath ? { ...processEnv(), LUMINARY_DB_PATH: options.databasePath } : processEnv(),
    },
  );
  let lineHandler = (_line: string): void => undefined;
  let exitHandler = (_error: Error): void => undefined;
  void readLines(process.stdout, (line) => lineHandler(line));
  void readLines(process.stderr, () => undefined);
  void process.exited.then((code) => {
    exitHandler(new Error(code === 0 ? "sidecar exited" : `sidecar exited with code ${code}`));
  });
  return {
    write: (line) => process.stdin.write(line),
    onLine: (handler) => { lineHandler = handler; },
    onExit: (handler) => { exitHandler = handler; },
    kill: () => { process.stdin.end(); process.kill(); },
  };
}

function processEnv(): Record<string, string> {
  if (typeof process === "undefined") return {};
  return Object.fromEntries(Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined));
}

async function readLines(stream: AsyncIterable<Uint8Array | string>, onLine: (line: string) => void): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "";
  for await (const chunk of stream) {
    buffer += typeof chunk === "string" ? chunk : decoder.decode(chunk, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) if (line.trim()) onLine(line);
  }
  if (buffer.trim()) onLine(buffer);
}
