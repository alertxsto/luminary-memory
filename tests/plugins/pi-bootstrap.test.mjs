import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { copyFile, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { build } from "esbuild";

const root = fileURLToPath(new URL("../../", import.meta.url));
const bootstrap = join(root, "plugins", "pi", "dist", "bootstrap.js");
const venvPython = join(root, ".venv", "bin", "python");

function run(home, env = {}) {
  return spawnSync(process.execPath, [bootstrap], {
    encoding: "utf8",
    timeout: 300_000,
    env: { ...process.env, HOME: home, USERPROFILE: home, ...env },
  });
}

async function bridgeRecord(home) {
  const path = join(home, ".luminary", "bridge.json");
  return existsSync(path) ? JSON.parse(await readFile(path, "utf8")) : null;
}

// These exercise the real provisioning script that `pi install` runs, with a
// throwaway HOME so no operator store or bridge record is touched.
test("records an explicit interpreter without installing anything", async () => {
  const home = await mkdtemp(join(tmpdir(), "luminary-bootstrap-"));
  try {
    const result = run(home, { LUMINARY_PYTHON: venvPython });
    assert.equal(result.status, 0, result.stderr);

    const record = await bridgeRecord(home);
    assert.equal(record.schema, 1);
    assert.equal(record.agents.pi.python, venvPython);
    assert.match(record.agents.pi.version, /^\d+\.\d+\.\d+$/);
    assert.equal(record.agents.pi.mode, "npm");
    assert.equal(existsSync(join(home, ".luminary", "venvs")), false);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("an invalid explicit interpreter is reported and never replaced", async () => {
  const home = await mkdtemp(join(tmpdir(), "luminary-bootstrap-"));
  try {
    const broken = join(home, "not-a-python");
    const result = run(home, { LUMINARY_PYTHON: broken });

    // A failed provision must not fail `pi install` and must not claim success.
    assert.equal(result.status, 0);
    assert.match(result.stderr, /does not provide luminary-memory/);
    assert.equal(await bridgeRecord(home), null);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("an existing managed record short-circuits without reinstalling", async () => {
  const home = await mkdtemp(join(tmpdir(), "luminary-bootstrap-"));
  try {
    const first = run(home, { LUMINARY_PYTHON: venvPython });
    assert.equal(first.status, 0, first.stderr);
    const seeded = await bridgeRecord(home);

    const second = run(home, {});
    assert.equal(second.status, 0, second.stderr);
    // The fast path stays silent and provisions nothing.
    assert.equal(second.stderr.trim(), "");
    assert.deepEqual(await bridgeRecord(home), seeded);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

// A host with only Node is the case that used to fail outright. The bootstrap
// must fetch its own uv there, and must say so plainly when that is forbidden.
test("a host without uv or Python reports the opt-out instead of failing silently", { skip: process.platform === "win32" }, async () => {
  const home = await mkdtemp(join(tmpdir(), "luminary-bootstrap-"));
  const bin = await mkdtemp(join(tmpdir(), "luminary-bin-"));
  try {
    await symlink(process.execPath, join(bin, "node"));
    const result = spawnSync(process.execPath, [bootstrap], {
      encoding: "utf8",
      timeout: 300_000,
      env: { HOME: home, USERPROFILE: home, PATH: bin, LUMINARY_NO_DOWNLOAD: "1" },
    });

    // The adapter stays installed; only the bridge is unavailable.
    assert.equal(result.status, 0);
    assert.match(result.stderr, /LUMINARY_NO_DOWNLOAD=1 forbids fetching one/);
    assert.equal(await bridgeRecord(home), null);
  } finally {
    await rm(home, { recursive: true, force: true });
    await rm(bin, { recursive: true, force: true });
  }
});

async function loadLauncher() {
  const directory = await mkdtemp(join(tmpdir(), "luminary-launch-"));
  const outfile = join(directory, "launch.mjs");
  await build({
    entryPoints: [join(root, "src/luminary_memory/integrations/assets/common/bridge-launch.ts")],
    outfile,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node22",
  });
  return { module: await import(pathToFileURL(outfile).href), cleanup: () => rm(directory, { recursive: true, force: true }) };
}

test("runtime provisioning reports an unusable interpreter instead of guessing", async () => {
  const { module, cleanup } = await loadLauncher();
  const home = await mkdtemp(join(tmpdir(), "luminary-launch-home-"));
  const previous = { home: process.env.HOME, explicit: process.env.LUMINARY_PYTHON };
  try {
    process.env.HOME = home;
    delete process.env.LUMINARY_PYTHON;
    const missing = await module.ensureBridgePython("pi", join(home, "no-python"));
    assert.equal(missing.ready, false);
    assert.match(missing.detail, /luminary-memory setup --agents pi|LUMINARY_PYTHON/);

    process.env.LUMINARY_PYTHON = venvPython;
    // A new module instance avoids the per-process provisioning cache.
    const fresh = await loadLauncher();
    try {
      const ok = await fresh.module.ensureBridgePython("pi", join(home, "no-python"));
      assert.equal(ok.ready, true);
      assert.equal(ok.python, venvPython);
    } finally {
      await fresh.cleanup();
    }
  } finally {
    if (previous.home === undefined) delete process.env.HOME;
    else process.env.HOME = previous.home;
    if (previous.explicit === undefined) delete process.env.LUMINARY_PYTHON;
    else process.env.LUMINARY_PYTHON = previous.explicit;
    await rm(home, { recursive: true, force: true });
    await cleanup();
  }
});

// A missing interpreter fails at spawn, not at close. The adapter must repair the
// bridge from that path too, or a plain `pi install` stays broken until restart.
test("a missing interpreter triggers provisioning instead of a dead adapter", async () => {
  const directory = await mkdtemp(join(tmpdir(), "luminary-adapter-"));
  const home = await mkdtemp(join(tmpdir(), "luminary-adapter-home-"));
  const previous = {
    home: process.env.HOME, path: process.env.PATH,
    explicit: process.env.LUMINARY_PYTHON, download: process.env.LUMINARY_NO_DOWNLOAD,
  };
  try {
    await symlink(join(root, "node_modules"), join(directory, "node_modules"), process.platform === "win32" ? "junction" : "dir");
    // Mirror the published layout: dist/index.js beside dist/bootstrap.js, with
    // the package manifest one level up, because the provisioner reads its version.
    const dist = join(directory, "dist");
    await mkdir(dist, { recursive: true });
    await writeFile(join(directory, "package.json"), JSON.stringify({ name: "luminary-memory-pi", version: "0.3.4" }));
    await copyFile(bootstrap, join(dist, "bootstrap.js"));
    const entry = join(dist, "adapter.mjs");
    await build({
      entryPoints: [join(root, "src/luminary_memory/integrations/assets/pi/luminary.ts")],
      outfile: entry, bundle: true, platform: "node", format: "esm", target: "node22",
      plugins: [{ name: "native-boundaries", setup(builder) {
        builder.onResolve({ filter: /^@(earendil-works|oh-my-pi)\/pi-tui$/ }, () => ({ path: "drawing", namespace: "boundary" }));
        builder.onLoad({ filter: /.*/, namespace: "boundary" }, () => ({ contents:
          "export function matchesKey(){return false} export function truncateToWidth(t,w){return String(t).slice(0,w)} export function visibleWidth(t){return String(t).length}" }));
      }}],
    });
    const { default: plugin } = await import(pathToFileURL(entry).href);
    let tool;
    plugin({ on() {}, registerCommand() {}, registerTool(definition) { tool = definition; }, sendMessage() {} });

    process.env.HOME = home;
    process.env.PATH = "";
    delete process.env.LUMINARY_PYTHON;
    process.env.LUMINARY_NO_DOWNLOAD = "1";
    const statuses = [];
    const ctx = {
      mode: "rpc", hasUI: true, cwd: directory,
      ui: { setStatus: (_key, value) => statuses.push(value), notify() {}, setWidget() {} },
      sessionManager: { getSessionId: () => "adapter-session" },
    };
    const result = await tool.execute("call", { action: "recall", query: "anything" }, undefined, undefined, ctx);

    assert.equal(result.isError, true);
    // Only the provisioning script emits this, so the spawn failure reached repair.
    assert.match(result.content[0].text, /LUMINARY_NO_DOWNLOAD=1 forbids fetching one/);
    assert.ok(statuses.some((value) => /preparing the Python bridge/.test(value)),
      "the operator must see that provisioning started");
  } finally {
    if (previous.home === undefined) delete process.env.HOME; else process.env.HOME = previous.home;
    if (previous.path === undefined) delete process.env.PATH; else process.env.PATH = previous.path;
    if (previous.explicit === undefined) delete process.env.LUMINARY_PYTHON; else process.env.LUMINARY_PYTHON = previous.explicit;
    if (previous.download === undefined) delete process.env.LUMINARY_NO_DOWNLOAD; else process.env.LUMINARY_NO_DOWNLOAD = previous.download;
    await rm(directory, { recursive: true, force: true });
    await rm(home, { recursive: true, force: true });
  }
});
