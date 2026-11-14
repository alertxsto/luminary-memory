// Shared interpreter resolution for every native adapter.
//
// Order: explicit process environment, the setup record written by
// `luminary-memory setup` (or the pi package's postinstall), then the path
// embedded at install time.
import { spawn } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

const PROBE_TIMEOUT_MS = 15_000
const BOOTSTRAP_TIMEOUT_MS = 900_000

export function resolveBridgePython(agent: string, installed: string): string {
  const explicit = process.env.LUMINARY_PYTHON
  if (explicit) return explicit
  try {
    const raw = readFileSync(join(homedir(), ".luminary", "bridge.json"), "utf8").replace(/^\uFEFF/, "")
    const record = JSON.parse(raw)
    const entry = record?.agents?.[agent]
    if (entry && typeof entry.python === "string" && entry.python.trim()) return entry.python
  } catch {
    // A missing or malformed setup record falls back to the embedded path.
  }
  return installed.startsWith("__LUMINARY_") ? "python" : installed
}

/** Resolve true when the interpreter imports the engine; never throws. */
function probeAsync(python: string): Promise<boolean> {
  const { promise, resolve } = Promise.withResolvers<boolean>()
  const child = spawn(python, ["-I", "-c", "import luminary_memory"], {
    stdio: "ignore",
    windowsHide: true,
  })
  const done = (value: boolean) => {
    clearTimeout(timer)
    resolve(value)
  }
  const timer = setTimeout(() => {
    child.kill()
    done(false)
  }, PROBE_TIMEOUT_MS)
  timer.unref?.()
  child.once("error", () => done(false))
  child.once("close", (code) => done(code === 0))
  return promise
}

function runBootstrap(script: string, onProgress?: (message: string) => void): Promise<string> {
  const { promise, resolve } = Promise.withResolvers<string>()
  onProgress?.("Luminary: preparing the Python bridge")
  const child = spawn(process.execPath, [script], {
    stdio: ["ignore", "ignore", "pipe"],
    windowsHide: true,
  })
  let stderr = ""
  const timer = setTimeout(() => child.kill(), BOOTSTRAP_TIMEOUT_MS)
  timer.unref?.()
  child.stderr?.setEncoding("utf8")
  child.stderr?.on("data", (chunk: string) => {
    // Keep only the tail: provisioning logs are bounded but chatty.
    stderr = (stderr + chunk).slice(-4096)
  })
  const done = () => {
    clearTimeout(timer)
    resolve(stderr.trim().split(/\r?\n/).slice(-2).join(" "))
  }
  child.once("error", done)
  child.once("close", done)
  return promise
}

export type BridgeReady = { python: string; ready: boolean; detail?: string }

let pending: Promise<BridgeReady> | undefined

/**
 * Provision the managed Python bridge when the resolved interpreter cannot
 * import the engine.
 *
 * The pi package postinstall runs this same script, but installs that skip
 * lifecycle scripts (npm 12 blocks dependency install scripts), an interrupted
 * first install, or an offline machine would otherwise leave every memory call
 * broken. Provisioning stays asynchronous so a first-run install never blocks
 * the host's event loop.
 */
export function ensureBridgePython(
  agent: string,
  installed: string,
  onProgress?: (message: string) => void,
): Promise<BridgeReady> {
  pending ??= (async () => {
    const resolved = resolveBridgePython(agent, installed)
    if (await probeAsync(resolved)) return { python: resolved, ready: true }
    const fallback = `${resolved} cannot import luminary-memory; run \`luminary-memory setup --agents ${agent}\` or set LUMINARY_PYTHON`
    const script = fileURLToPath(new URL("bootstrap.js", import.meta.url))
    if (!existsSync(script)) return { python: resolved, ready: false, detail: fallback }
    const diagnostics = await runBootstrap(script, onProgress)
    const after = resolveBridgePython(agent, installed)
    if (await probeAsync(after)) return { python: after, ready: true }
    return { python: after, ready: false, detail: diagnostics || fallback }
  })()
  return pending
}
