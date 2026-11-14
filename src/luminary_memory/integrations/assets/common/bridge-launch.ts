// Shared interpreter resolution for every native adapter.
//
// Order: explicit process environment, the setup record written by
// `luminary-memory setup`, then the path embedded at install time. The setup
// record is what makes a one-command install work without asking the user to
// export LUMINARY_PYTHON before starting the host.
import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

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
