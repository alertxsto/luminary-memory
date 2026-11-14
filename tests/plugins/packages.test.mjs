import assert from "node:assert/strict";
import { copyFile, cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { z } from "zod";
import { build } from "esbuild";

const packageRoot = process.env.LUMINARY_TEST_PLUGIN_ROOT ||
  fileURLToPath(new URL("../../plugins", import.meta.url));

// These are package consumer tests: a missing Python runtime must never turn
// an attempted remember into a claimed durable write or a thrown host error.
for (const agent of ["pi", "omp", "opencode"]) {
  test(`${agent} package reports unavailable bridge without claiming storage`, async () => {
    const directory = await mkdtemp(join(tmpdir(), "luminary-package-"));
    const previous = process.env.LUMINARY_PYTHON;
    process.env.LUMINARY_PYTHON = join(directory, "python-does-not-exist");
    let cleanup;
    try {
      let entry = join(packageRoot, agent, "dist", "index.js");
      if (agent !== "opencode") {
        // This unit exercises real OS bridge failure, not a native host. Drawing
        // is forbidden here; exact host/peer compatibility has separate acceptance.
        const guarded = join(directory, "headless-tool.mjs");
        await build({
          entryPoints: [entry], outfile: guarded, bundle: true, platform: "node", format: "esm",
          plugins: [{
            name: "forbid-native-drawing",
            setup(builder) {
              builder.onResolve({ filter: /^@(earendil-works|oh-my-pi)\/pi-tui$/ },
                () => ({ path: "native-drawing", namespace: "headless-guard" }));
              builder.onLoad({ filter: /.*/, namespace: "headless-guard" }, () => ({
                contents: "export function matchesKey(){throw Error('Unexpected native drawing')} export function truncateToWidth(){throw Error('Unexpected native drawing')}",
              }));
            },
          }],
        });
        entry = guarded;
      }
      const { default: plugin } = await import(pathToFileURL(entry).href);
      const abort = new AbortController();
      let result;
      if (agent === "opencode") {
        const tools = new Map();
        cleanup = await plugin.setup({
          options: {},
          location: { directory, project: { id: "package-project", directory, canonical: directory } },
          session: {
            async get({ sessionID }) { return { id: sessionID, location: { directory } }; },
            async context() { return [{ type: "user", id: "package-message", text: "Do not claim this was stored" }]; },
            async hook() { return { async dispose() {} }; },
          },
          event: { async *subscribe() {} },
          rpc: { async register() { return { async dispose() {} }; } },
          tool: {
            async transform(edit) {
              edit({ add(definition) { tools.set(definition.name, definition); } });
              return { async dispose() {} };
            },
          },
        });
        const output = await tools.get("luminary_remember").execute(
          { text: "Do not claim this was stored", evidence_quote: "Do not claim this was stored" },
          {
            sessionID: "package-consumer", agent: "build", messageID: "package-message", id: "package-call",
            signal: abort.signal, async progress() {},
          },
        );
        result = output.output;
        const visible = JSON.parse(output.content);
        assert.equal(visible.ok, false);
        assert.equal(visible.stored, 0);
        assert.deepEqual(visible.memories, []);
        assert.equal(result.reason, "unavailable");
      } else {
        const tools = new Map();
        plugin({
          zod: z,
          on() {}, registerCommand() {}, sendMessage() {},
          registerTool(definition) { tools.set(definition.name, definition); },
        });
        const output = await tools.get("luminary_memory").execute(
          "package-call", { action: "remember", text: "Do not claim this was stored" },
          abort.signal, undefined,
          { cwd: directory, hasUI: false, sessionManager: { getSessionId: () => "package-consumer" } },
        );
        result = output.details;
      }
      assert.equal(result.ok, false);
      assert.equal(result.status, "error");
      assert.equal(result.stored, 0);
      assert.deepEqual(result.memories, []);
    } finally {
      await cleanup?.();
      if (previous === undefined) delete process.env.LUMINARY_PYTHON;
      else process.env.LUMINARY_PYTHON = previous;
      await rm(directory, { recursive: true, force: true });
    }
  });
}

// Exercise the generated native packages with real bridge/inspector subprocesses.
// Only native drawing is guarded: these are loader consumers, not host-session
// acceptance, and neither Python protocol is replaced by a test double.
for (const agent of ["pi", "omp", "opencode"]) {
  test(`${agent} package discovers its managed bridge and inspector without Python on PATH`, async (t) => {
    const root = fileURLToPath(new URL("../../", import.meta.url));
    const directory = await mkdtemp(join(tmpdir(), "luminary managed package "));
    const workspace = join(directory, "workspace with spaces");
    const home = join(directory, "isolated home");
    const emptyPath = join(directory, "empty path");
    const python = process.env.LUMINARY_TEST_PYTHON ||
      join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
      !key.toUpperCase().startsWith("LUMINARY_") &&
      !["PYTHONPATH", "PYTHONHOME", "NODE_PATH", "PATH", "HOME", "USERPROFILE"].includes(key.toUpperCase())));
    Object.assign(environment, {
      HOME: home, USERPROFILE: home, PATH: emptyPath,
      LUMINARY_CONFIG_FILE: "none", LUMINARY_BACKEND: "sqlite",
      LUMINARY_USER_ID: "managed-package-owner", LUMINARY_DB_PATH: join(directory, "memory.db"),
      HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1",
    });
    try {
      await Promise.all([mkdir(workspace), mkdir(emptyPath), mkdir(join(home, ".luminary"), { recursive: true })]);
      const seeded = spawnSync(python, ["-c", `
import json, os, sys
from pathlib import Path
from luminary_memory import __version__
from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.types import Memory
workspace = os.path.normcase(str(Path(sys.argv[1]).resolve()))
agent = sys.argv[2]
backend = SQLiteBackend(os.environ['LUMINARY_DB_PATH'])
try:
    own = backend.add(Memory(content='Managed package scoped memory', user_id='managed-package-owner',
        workspace_id=workspace, agent_id=agent, session_id='seed-session'))
    backend.add(Memory(content='FOREIGN_WORKSPACE_SECRET', user_id='managed-package-owner',
        workspace_id=workspace + '-foreign', agent_id=agent))
    backend.add(Memory(content='FOREIGN_OWNER_SECRET', user_id='another-owner',
        workspace_id=workspace, agent_id=agent))
finally:
    backend.close()
print(json.dumps({'agent': agent, 'workspace': workspace, 'own_id': own, 'version': __version__,
    'prefix': sys.prefix, 'executable': os.path.relpath(sys.executable, sys.prefix)}))
`, workspace, agent], { cwd: workspace, env: environment, encoding: "utf8", timeout: 30_000 });
      assert.equal(seeded.status, 0, seeded.stderr || String(seeded.error));
      const fixture = JSON.parse(seeded.stdout);
      const managed = join(directory, "managed Python with spaces");
      await symlink(fixture.prefix, managed, process.platform === "win32" ? "junction" : "dir");
      const record = {
        schema: 1,
        agents: Object.fromEntries(["pi", "omp", "opencode"].map((name) => [name, {
          python: name === agent ? join(managed, fixture.executable) : join(directory, `wrong-${name}-python`),
          version: fixture.version, mode: "native",
        }])),
      };
      await writeFile(join(home, ".luminary", "bridge.json"), JSON.stringify(record));
      const consumer = join(directory, "consumer.mjs");
      await build({
        stdin: {
          resolveDir: root,
          contents: `
import assert from "node:assert/strict";
import { z } from "zod";
import plugin from ${JSON.stringify(join(packageRoot, agent, "dist", "index.js"))};
const fixture = JSON.parse(process.argv[2]);
const tools = new Map();
const commands = new Map();
const messages = [];
const signal = new AbortController().signal;
let cleanup;
let inspect;
let activity;
if (fixture.agent === "opencode") {
  let rpc;
  cleanup = await plugin.setup({
    options: {}, location: { directory: fixture.workspace, project: { id: "managed-project", directory: fixture.workspace, canonical: fixture.workspace } },
    session: {
      async get({ sessionID }) { return { id: sessionID, location: { directory: fixture.workspace } }; },
      async context() { return []; },
      async hook() { return { async dispose() {} }; },
    },
    event: { async *subscribe() {} },
    rpc: { async register(_contract, handlers) { rpc = handlers; return { async dispose() {} }; } },
    tool: { async transform(edit) { edit({ add(tool) { tools.set(tool.name, tool); } }); return { async dispose() {} }; } },
  });
  activity = async () => (await tools.get("luminary_activity").execute({}, {
    sessionID: "managed-native-session", signal, async progress() {},
  })).output;
  inspect = () => rpc.inspect({ session_id: "managed-native-session",
    request: { operation: "browse", arguments: {}, request_id: "managed-package-browse" } }, { signal });
} else {
  plugin({
    zod: z, on() {}, registerTool(tool) { tools.set(tool.name, tool); },
    registerCommand(name, command) { commands.set(name, command); }, sendMessage(message) { messages.push(message); },
  });
  const context = { cwd: fixture.workspace, hasUI: false, mode: "print",
    sessionManager: { getSessionId: () => "managed-native-session" } };
  activity = async () => (await tools.get("luminary_memory").execute("managed-call", { action: "activity" }, signal, undefined, context)).details;
  inspect = async () => {
    await commands.get("luminary").handler("full", context);
    return messages.findLast(message => message.customType === "luminary_inspector").details;
  };
}
try {
  const bridge = await activity();
  if (fixture.invalid_override) {
    assert.equal(bridge.ok, false);
    assert.equal(bridge.stored, 0);
    assert.deepEqual(bridge.memories, []);
    assert.ok(bridge.message);
    const inspector = await inspect();
    assert.equal(inspector.status, "unavailable");
    assert.ok(inspector.error);
    assert.deepEqual(inspector.data ?? {}, {});
  } else {
    assert.equal(bridge.ok, true, JSON.stringify(bridge));
    assert.equal(bridge.status, "ok");
    assert.deepEqual(bridge.memories.map(row => row.id), [fixture.own_id]);
    const inspector = await inspect();
    assert.equal(inspector.status, "ok", JSON.stringify(inspector));
    assert.deepEqual(inspector.data.items.map(row => row.id), [fixture.own_id]);
    assert.equal(inspector.data.items[0].content, "Managed package scoped memory");
    assert.equal(inspector.data.items[0].permissions.read, true);
  }
} finally { await cleanup?.(); }
`,
        },
        outfile: consumer, bundle: true, platform: "node", format: "esm", target: "node22",
        plugins: [{
          name: "forbid-native-drawing",
          setup(builder) {
            builder.onResolve({ filter: /^@(earendil-works|oh-my-pi)\/pi-tui$/ },
              () => ({ path: "native-drawing", namespace: "headless-guard" }));
            builder.onLoad({ filter: /.*/, namespace: "headless-guard" }, () => ({
              contents: "export function matchesKey(){throw Error('Unexpected native drawing')} export function truncateToWidth(){throw Error('Unexpected native drawing')}",
            }));
          },
        }],
      });
      for (const invalidOverride of [false, true]) {
        await t.test(invalidOverride ? "invalid explicit override fails visibly without fallback" : "managed per-agent record returns scoped bridge and inspector data", () => {
          const childEnvironment = { ...environment };
          if (invalidOverride) childEnvironment.LUMINARY_PYTHON = join(directory, "invalid explicit Python");
          const executed = spawnSync(process.execPath, [consumer, JSON.stringify({ ...fixture, invalid_override: invalidOverride })], {
            cwd: workspace, env: childEnvironment, encoding: "utf8", timeout: 120_000, maxBuffer: 1024 * 1024,
          });
          assert.equal(executed.status, 0, executed.stderr || String(executed.error));
        });
      }
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
}

async function packageFixture(run) {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const directory = await mkdtemp(join(tmpdir(), "luminary-release-"));
  try {
    await mkdir(join(directory, "scripts"), { recursive: true });
    for (const script of ["build-plugins.mjs", "opencode-gui.vite.mjs"]) {
      await copyFile(join(root, "scripts", script), join(directory, "scripts", script));
    }
    for (const file of ["package.json", "pyproject.toml", "LICENSE"]) {
      await copyFile(join(root, file), join(directory, file));
    }
    for (const agent of ["pi", "omp", "opencode"]) {
      const destination = join(directory, "plugins", agent);
      await mkdir(destination, { recursive: true });
      await copyFile(join(root, "plugins", agent, "package.json"), join(destination, "package.json"));
      await copyFile(join(root, "plugins", agent, "README.md"), join(destination, "README.md"));
    }
    await cp(join(root, "src", "luminary_memory", "integrations", "assets"),
      join(directory, "src", "luminary_memory", "integrations", "assets"), { recursive: true });
    await symlink(join(root, "node_modules"), join(directory, "node_modules"), process.platform === "win32" ? "junction" : "dir");
    await run(directory);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test("release build refuses pi metadata that would disappear from the official catalog", async () => {
  await packageFixture(async (directory) => {
    const run = () => spawnSync(process.execPath, [join(directory, "scripts", "build-plugins.mjs")], {
      cwd: directory, encoding: "utf8", maxBuffer: 1024 * 1024,
    });
    const valid = run();
    assert.equal(valid.status, 0, valid.stderr);
    const artifact = join(directory, "plugins", "pi", "dist", "index.js");
    const before = await readFile(artifact);
    const manifestPath = join(directory, "plugins", "pi", "package.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.keywords = manifest.keywords.filter((keyword) => keyword !== "pi-package");
    await writeFile(manifestPath, JSON.stringify(manifest));
    const invalid = run();
    assert.notEqual(invalid.status, 0, "A release must fail if pi can no longer discover its npm package");
    assert.deepEqual(await readFile(artifact), before, "Failed preflight must preserve the previous build");
  });
});

test("direct npm packing builds the native entry instead of publishing a broken clean checkout", async () => {
  await packageFixture(async (directory) => {
    for (const agent of ["pi", "omp", "opencode"]) {
      await rm(join(directory, "plugins", agent, "dist"), { recursive: true, force: true });
      const packed = spawnSync(process.execPath, [
        process.env.npm_execpath, "pack", "--workspace", `luminary-memory-${agent}`, "--json",
      ], { cwd: directory, encoding: "utf8", maxBuffer: 1024 * 1024 });
      assert.equal(packed.status, 0, packed.stderr);
      const [artifact] = JSON.parse(packed.stdout);
      assert.ok(artifact.files.some((file) => file.path === "dist/index.js"),
        `${agent}: direct pack must include its native entry from a clean checkout`);
    }
  });
});
