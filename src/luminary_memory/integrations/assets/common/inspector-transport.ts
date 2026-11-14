import { spawn } from "node:child_process";
import { hostname } from "node:os";
import { resolve } from "node:path";
import { resolveBridgePython } from "./bridge-launch";
import type { ConsoleRequest, ConsoleResult, ConsoleTransport, NativeInspectorContext } from "./console-contract";

const MAX_REQUEST = 128 * 1024;
const MAX_RESPONSE = 192 * 1024;
const TIMEOUT = 60_000;
const MUTATIONS: Record<string, true> = {
  mutate: true, maintenance_commit: true, set_settings: true, transfer_commit: true, grant: true, revoke: true,
};

function failure(request: ConsoleRequest, status: ConsoleResult["status"], code: string): ConsoleResult {
  return {
    status, data: null, error: { code, message: status === "unknown_outcome"
      ? "The operation may have committed. Inspect activity before retrying."
      : "Inspector request did not complete; check the native runtime and configured backend." },
    request_id: request.request_id, context_epoch: "", policy_revision: 0, as_of: new Date().toISOString(),
  };
}

function launch(
  context: NativeInspectorContext, request: ConsoleRequest, signal?: AbortSignal,
  preview?: string, file?: { path: string; mode: "read" | "write" },
): Promise<ConsoleResult> {
  if (signal?.aborted) return Promise.resolve(failure(request, "cancelled", "cancelled"));
  const payload = JSON.stringify(request);
  if (Buffer.byteLength(payload) > MAX_REQUEST) return Promise.resolve(failure(request, "invalid_request", "request_budget_exceeded"));
  const native = {
    agent_id: context.agent, workspace: resolve(context.workspace), session_id: context.session_id,
    host_id: context.host_id || hostname(), profile_id: context.profile_id || "default",
  };
  // Native constructors/server handlers establish context. No request field can
  // override the environment's owner, backend, store or profile configuration.
  const environment: NodeJS.ProcessEnv = { ...process.env, LUMINARY_INSPECTOR_CONTEXT: JSON.stringify(native), LUMINARY_INSPECTOR_OPEN: "1" };
  delete environment.LUMINARY_INSPECTOR_CONFIRM;
  delete environment.LUMINARY_INSPECTOR_FILE;
  delete environment.LUMINARY_INSPECTOR_DOWNLOAD;
  if (preview) environment.LUMINARY_INSPECTOR_CONFIRM = preview;
  if (file) environment.LUMINARY_INSPECTOR_FILE = JSON.stringify(file);
  const executable = resolveBridgePython(context.agent, "__LUMINARY_PYTHON__");
  const { promise, resolve: done } = Promise.withResolvers<ConsoleResult>();
    const chunks: Buffer[] = [];
    let bytes = 0;
    let errorBytes = 0;
    let dispatched = false;
    let settled = false;
    const child = spawn(executable, ["-m", "luminary_memory.integrations", "inspector"], {
      cwd: native.workspace, env: environment, shell: false, windowsHide: true, stdio: ["pipe", "pipe", "pipe"],
    });
    const finish = (value: ConsoleResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
      done(value);
    };
    const stop = (code: string, cancelled = false) => {
      child.kill();
      finish(failure(request, dispatched && MUTATIONS[request.operation]
        ? "unknown_outcome" : cancelled ? "cancelled" : "unavailable", code));
    };
    const cancel = () => stop("cancelled", true);
    const timer = setTimeout(() => stop("timeout"), TIMEOUT);
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
    child.once("error", () => finish(failure(request, "unavailable", "runtime_unavailable")));
    child.stdin.on("error", () => stop("request_channel_failed"));
    child.stdout.on("data", (chunk: Buffer) => {
      bytes += chunk.length;
      if (bytes > MAX_RESPONSE) stop("response_budget_exceeded");
      else chunks.push(chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      errorBytes += chunk.length;
      if (errorBytes > MAX_RESPONSE) stop("diagnostic_budget_exceeded");
    });
    child.once("close", (code) => {
      if (settled) return;
      try {
        const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        const statuses = ["ok", "empty", "invalid_request", "denied", "conflict", "unavailable", "unsupported", "cancelled", "unknown_outcome"];
        if (code !== 0 || !value || typeof value !== "object" || !statuses.includes(value.status)
          || value.request_id !== request.request_id || typeof value.context_epoch !== "string"
          || !Number.isInteger(value.policy_revision) || typeof value.as_of !== "string"
          || !("data" in value) || !("error" in value)) throw new Error("invalid protocol");
        finish(value as ConsoleResult);
      } catch {
        finish(failure(request, dispatched && MUTATIONS[request.operation] ? "unknown_outcome" : "unavailable", "invalid_response"));
      }
    });
    if (!settled) {
      // Once handed to the pipe, cancellation cannot prove the child saw no write.
      dispatched = true;
      child.stdin.end(payload + "\n");
    }
  return promise;
}

/** Created only from a verified native session, never model-provided JSON. */
export function createInspectorTransport(context: NativeInspectorContext): ConsoleTransport {
  const identity = Object.freeze({ ...context });
  return {
    request: (request, signal) => launch(identity, request, signal),
    confirm: (preview_id, signal) => launch(identity, {
      operation: "preview_change", arguments: {}, request_id: crypto.randomUUID(),
    }, signal, preview_id),
    async registerFile(path, mode, signal) {
      const result = await launch(identity, {
        operation: "browse", arguments: {}, request_id: crypto.randomUUID(),
      }, signal, undefined, { path, mode });
      const handle = result.data?.file_handle;
      if (result.status !== "ok" || typeof handle !== "string") {
        throw new Error(result.error?.message || "Native file selection could not be registered.");
      }
      return handle;
    },
  };
}
