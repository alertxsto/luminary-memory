import assert from "node:assert/strict";
import { copyFile, cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { z } from "zod";

// These are package consumer tests: a missing Python runtime must never turn
// an attempted remember into a claimed durable write or a thrown host error.
for (const agent of ["pi", "omp", "opencode"]) {
  test(`${agent} package reports unavailable bridge without claiming storage`, async () => {
    const directory = await mkdtemp(join(tmpdir(), "luminary-package-"));
    const previous = process.env.LUMINARY_PYTHON;
    process.env.LUMINARY_PYTHON = join(directory, "python-does-not-exist");
    let cleanup;
    try {
      const { default: plugin } = await import(
        new URL(`../../plugins/${agent}/dist/index.js`, import.meta.url)
      );
      const abort = new AbortController();
      let result;
      if (agent === "opencode") {
        const tools = new Map();
        cleanup = await plugin.setup({
          options: {},
          location: { directory, project: { id: "package-project", directory, canonical: directory } },
          session: {
            async get({ sessionID }) { return { id: sessionID, location: { directory } }; },
            async hook() { return { async dispose() {} }; },
          },
          event: { async *subscribe() {} },
          tool: {
            async transform(edit) {
              edit({ add(definition) { tools.set(definition.name, definition); } });
              return { async dispose() {} };
            },
          },
        });
        const output = await tools.get("luminary_remember").execute(
          { text: "Do not claim this was stored" },
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

async function packageFixture(run) {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const directory = await mkdtemp(join(tmpdir(), "luminary-release-"));
  try {
    await mkdir(join(directory, "scripts"), { recursive: true });
    await copyFile(join(root, "scripts", "build-plugins.mjs"), join(directory, "scripts", "build-plugins.mjs"));
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
