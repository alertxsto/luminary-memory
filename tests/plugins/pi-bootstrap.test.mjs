import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, symlink } from "node:fs/promises";
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
