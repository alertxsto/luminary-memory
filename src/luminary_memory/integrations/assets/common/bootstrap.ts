// Provision the Python bridge for a native adapter.
//
// The npm package is only the adapter; the engine is a Python package. npm 12
// blocks dependency install scripts by default and a package cannot approve
// itself, so the adapter runs this script on first use instead of relying on a
// postinstall hook. It creates the same managed venv that `luminary-memory
// setup` creates and records the interpreter in ~/.luminary/bridge.json, which
// resolveBridgePython() reads.
//
// Invoked as `node bootstrap.js <agent>`. It never exits non-zero: the caller
// reports the failure and keeps the adapter loaded.
import { spawn } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";

const SCHEMA = 1;
const MIN_PYTHON: readonly [number, number] = [3, 11];
const PROBE_TIMEOUT_MS = 60_000;
const INSTALL_TIMEOUT_MS = 900_000;
const LOCK_STALE_MS = 15 * 60_000;

type BridgeRecord = { schema: number; agents: Record<string, unknown> };
type RunResult = { code: number | null; stdout: string; stderr: string; error?: Error };

function note(message: string): void {
  process.stderr.write(`luminary-memory: ${message}\n`);
}

function pinnedVersion(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  const manifest = JSON.parse(readFileSync(join(here, "..", "package.json"), "utf8"));
  const version = manifest?.version;
  if (typeof version !== "string" || !/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error("package version is not a release version");
  }
  return version;
}

function bridgePath(): string {
  return join(homedir(), ".luminary", "bridge.json");
}

function readBridge(): BridgeRecord {
  try {
    const data = JSON.parse(readFileSync(bridgePath(), "utf8").replace(/^\uFEFF/, ""));
    if (data && typeof data === "object" && data.agents && typeof data.agents === "object") {
      return { schema: typeof data.schema === "number" ? data.schema : SCHEMA, agents: data.agents };
    }
  } catch {
    // Absent or malformed: start a fresh record rather than failing the caller.
  }
  return { schema: SCHEMA, agents: {} };
}

function writeBridge(record: BridgeRecord): void {
  const path = bridgePath();
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  renameSync(temporary, path);
}

function run(command: string, args: string[], timeout: number): Promise<RunResult> {
  return new Promise((settle) => {
    let stdout = "";
    let stderr = "";
    let done = false;
    const finish = (result: RunResult) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      settle(result);
    };
    const child = spawn(command, args, { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    const timer = setTimeout(() => child.kill(), timeout);
    child.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString("utf8"); });
    child.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString("utf8"); });
    child.on("error", (error) => finish({ code: null, stdout, stderr, error }));
    child.on("close", (code) => finish({ code, stdout, stderr }));
  });
}

/** Read the installed release without opening a store, workspace or session. */
async function probe(python: string): Promise<string | null> {
  const result = await run(python, ["-I", "-c", "import luminary_memory; print(luminary_memory.__version__)"], PROBE_TIMEOUT_MS);
  if (result.error || result.code !== 0) return null;
  const version = result.stdout.trim();
  return /^\d+\.\d+\.\d+$/.test(version) ? version : null;
}

function findUv(): string | null {
  const explicit = process.env.LUMINARY_UV;
  if (explicit && existsSync(explicit)) return explicit;
  const name = process.platform === "win32" ? "uv.exe" : "uv";
  for (const candidate of [
    join(homedir(), ".luminary", "bin", name),
    join(homedir(), ".local", "bin", name),
    join(homedir(), ".cargo", "bin", name),
  ]) {
    if (existsSync(candidate)) return candidate;
  }
  for (const directory of (process.env.PATH ?? "").split(process.platform === "win32" ? ";" : ":")) {
    if (!directory) continue;
    const candidate = join(directory, name);
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

async function findPython(): Promise<string | null> {
  for (const name of ["python3.13", "python3.12", "python3.11", "python3", "python"]) {
    const result = await run(name, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], 15_000);
    if (result.error || result.code !== 0) continue;
    const [major, minor] = result.stdout.trim().split(".").map(Number);
    if (major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])) return name;
  }
  return null;
}

/** uv release target for this host, or null when no build is published. */
function uvTarget(): string | null {
  const arch = process.arch === "arm64" ? "aarch64" : process.arch === "x64" ? "x86_64" : null;
  if (!arch) return null;
  if (process.platform === "linux") return `${arch}-unknown-linux-gnu`;
  if (process.platform === "darwin") return `${arch}-apple-darwin`;
  if (process.platform === "win32" && arch === "x86_64") return "x86_64-pc-windows-msvc";
  return null;
}

function findFile(root: string, name: string): string | null {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      const nested = findFile(path, name);
      if (nested) return nested;
    } else if (entry.name === name) {
      return path;
    }
  }
  return null;
}

/**
 * Extract a gzipped tar without external tools. A host that has only Node must
 * not depend on `tar` and `gzip` being on PATH, and Windows ships neither.
 */
function extractTarGz(archive: Buffer, destination: string): void {
  const data = gunzipSync(archive);
  const root = resolve(destination);
  let offset = 0;
  while (offset + 512 <= data.length) {
    const header = data.subarray(offset, offset + 512);
    if (header.every((byte) => byte === 0)) break;
    const name = header.subarray(0, 100).toString("utf8").replace(/\0.*$/s, "");
    const size = parseInt(header.subarray(124, 136).toString("utf8").replace(/\0.*$/s, "").trim(), 8) || 0;
    const type = String.fromCharCode(header[156] ?? 0);
    offset += 512;
    if (type === "0" || type === "\0" || type === "") {
      const target = resolve(root, name);
      // Refuse entries that would escape the staging directory.
      if (target === root || target.startsWith(root + sep)) {
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, data.subarray(offset, offset + size));
      }
    }
    offset += Math.ceil(size / 512) * 512;
  }
}

/**
 * Fetch a standalone uv so a host with only Node can still get an interpreter.
 * uv is a single static binary and can install its own CPython, which is what
 * makes this work on a machine that has neither Python nor uv.
 */
async function downloadUv(): Promise<string> {
  if (process.env.LUMINARY_NO_DOWNLOAD === "1") {
    throw new Error("no Python 3.11+ and no uv on PATH, and LUMINARY_NO_DOWNLOAD=1 forbids fetching one");
  }
  const target = uvTarget();
  if (!target) throw new Error(`no Python 3.11+ and no uv on PATH, and no uv build exists for ${process.platform}/${process.arch}`);
  const archive = process.platform === "win32" ? "zip" : "tar.gz";
  const url = `https://github.com/astral-sh/uv/releases/latest/download/uv-${target}.${archive}`;
  const directory = join(homedir(), ".luminary", "bin");
  const staging = join(directory, `.uv-${process.pid}`);
  mkdirSync(directory, { recursive: true });
  rmSync(staging, { recursive: true, force: true });
  mkdirSync(staging, { recursive: true });
  try {
    note(`downloading uv for ${target}`);
    const response = await fetch(url, { redirect: "follow" });
    if (!response.ok) throw new Error(`uv download failed: HTTP ${response.status}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (archive === "tar.gz") {
      extractTarGz(bytes, staging);
    } else {
      // Windows ships bsdtar, which reads zip; there is no built-in zip reader.
      const file = join(staging, "uv.zip");
      writeFileSync(file, bytes);
      const extracted = await run("tar", ["-xf", file, "-C", staging], 120_000);
      if (extracted.error || extracted.code !== 0) {
        throw new Error(`uv extraction failed: ${extracted.error?.message ?? extracted.stderr.trim()}`);
      }
    }
    const name = process.platform === "win32" ? "uv.exe" : "uv";
    const found = findFile(staging, name);
    if (!found) throw new Error("uv binary missing from the downloaded archive");
    const destination = join(directory, name);
    renameSync(found, destination);
    if (process.platform !== "win32") chmodSync(destination, 0o755);
    return destination;
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

function venvRoot(version: string): string {
  return join(homedir(), ".luminary", "venvs", version);
}

function venvPython(version: string): string {
  const root = venvRoot(version);
  return process.platform === "win32" ? join(root, "Scripts", "python.exe") : join(root, "bin", "python");
}

/** Serialise provisioning across concurrent host sessions. */
async function withLock<T>(version: string, work: () => Promise<T>): Promise<T> {
  const path = `${venvRoot(version)}.lock`;
  mkdirSync(dirname(path), { recursive: true });
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      mkdirSync(path);
      break;
    } catch {
      try {
        if (Date.now() - statSync(path).mtimeMs > LOCK_STALE_MS) {
          rmSync(path, { recursive: true, force: true });
          continue;
        }
      } catch {
        continue;
      }
      await new Promise((wait) => setTimeout(wait, 2_000));
    }
  }
  try {
    return await work();
  } finally {
    rmSync(path, { recursive: true, force: true });
  }
}

/** Reuse the managed layout so `luminary-memory setup` adopts this venv as-is. */
async function provision(version: string): Promise<string> {
  const target = venvPython(version);
  const root = venvRoot(version);
  // A managed venv that already answers for this release needs no network.
  if (existsSync(target) && (await probe(target)) === version) return target;
  return withLock(version, async () => {
    if (existsSync(target) && (await probe(target)) === version) return target;
    let uv = findUv();
    if (!uv) {
      const python = await findPython();
      if (python) {
        if (!existsSync(target)) {
          note("creating the bridge environment");
          const created = await run(python, ["-m", "venv", root], INSTALL_TIMEOUT_MS);
          if (created.error || created.code !== 0) throw new Error(`python -m venv failed: ${created.stderr.trim().split(/\r?\n/).slice(-2).join(" ")}`);
        }
        note("installing the bridge package");
        const installed = await run(target, ["-m", "pip", "install", "--upgrade", "--disable-pip-version-check", `luminary-memory==${version}`], INSTALL_TIMEOUT_MS);
        if (installed.error || installed.code !== 0) throw new Error(`pip install failed: ${installed.stderr.trim().split(/\r?\n/).slice(-2).join(" ")}`);
        return target;
      }
      uv = await downloadUv();
    }
    if (!existsSync(target)) {
      note("creating the bridge environment");
      const created = await run(uv, ["venv", root, "--python", "3.12"], INSTALL_TIMEOUT_MS);
      if (created.error || created.code !== 0) throw new Error(`uv venv failed: ${created.stderr.trim().split(/\r?\n/).slice(-2).join(" ")}`);
    }
    note("installing the bridge package");
    const installed = await run(uv, ["pip", "install", "--python", target, "--reinstall", `luminary-memory==${version}`], INSTALL_TIMEOUT_MS);
    if (installed.error || installed.code !== 0) throw new Error(`uv pip install failed: ${installed.stderr.trim().split(/\r?\n/).slice(-2).join(" ")}`);
    return target;
  });
}

async function main(): Promise<void> {
  const agent = process.argv[2] ?? "pi";
  if (process.env.LUMINARY_SKIP_BOOTSTRAP === "1") {
    note("LUMINARY_SKIP_BOOTSTRAP=1; the Python bridge was not provisioned.");
    return;
  }
  const version = pinnedVersion();
  const record = readBridge();
  const entry = record.agents[agent];
  const recorded = entry && typeof entry === "object" ? (entry as { python?: unknown }).python : undefined;

  // Fast path: this exact release is already recorded and still answers.
  if (typeof recorded === "string" && existsSync(recorded) && (await probe(recorded)) === version) return;

  const explicit = process.env.LUMINARY_PYTHON;
  if (explicit) {
    if ((await probe(explicit)) !== version) {
      note(`LUMINARY_PYTHON=${explicit} does not provide luminary-memory ${version}; left untouched.`);
      return;
    }
    record.agents[agent] = { python: explicit, version, mode: "npm" };
    writeBridge(record);
    note(`recorded LUMINARY_PYTHON for ${agent}.`);
    return;
  }

  const python = await provision(version);
  const actual = await probe(python);
  if (actual !== version) throw new Error(`provisioned bridge reports ${actual ?? "no version"}; expected ${version}`);
  record.agents[agent] = { python, version, mode: "npm" };
  writeBridge(record);
  note(`bridge ${version} ready at ${python}.`);
}

main().catch((error: unknown) => {
  note(`the Python bridge was not provisioned: ${error instanceof Error ? error.message : String(error)}`);
  note("Run `luminary-memory setup --agents pi` once, or set LUMINARY_PYTHON, then restart the host.");
});
