import { Console } from "node:console";
import { access, copyFile, mkdir, readFile, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { build as buildGui, createLogger } from "vite";
import { transformAsync } from "@babel/core";
import solid from "babel-preset-solid";
import typescript from "@babel/preset-typescript";

// Same universal Solid transform as OpenTUI's official Bun loader. React's
// default JSX transform cannot create native OpenTUI renderables.
const solidTransform = {
  name: "opentui-solid",
  setup(builder) {
    // OpenTUI 0.7's runtimeModuleIdForSpecifier ABI. The Node build cannot
    // import that Bun-only helper; these IDs bind to the host's renderer and
    // reactive owner instead of loading an independent Solid/SSR instance.
    const shared = new Set(["@opentui/core", "@opentui/solid", "solid-js", "solid-js/store"]);
    builder.onResolve({ filter: /^(@opentui\/(core|solid)|solid-js)(\/.*)?$/ }, ({ path }) => {
      if (shared.has(path)) return { path: `opentui:runtime-module:${encodeURIComponent(path)}`, external: true };
    });
    builder.onLoad({ filter: /\.tsx$/ }, async ({ path }) => ({
      contents: (await transformAsync(await readFile(path, "utf8"), {
        filename: path, configFile: false, babelrc: false,
        presets: [[solid, { moduleName: "@opentui/solid", generate: "universal" }], [typescript]],
      })).code,
      loader: "js",
    }));
  },
};

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const adapters = {
  pi: { source: "luminary.ts" },
  opencode: { source: "luminary-memory.ts" },
  omp: { source: "luminary.ts" },
};

const project = await readFile(join(root, "pyproject.toml"), "utf8");
const version = /^version = "([^"]+)"/m.exec(project)?.[1];
if (!version) throw new Error("Cannot read project version from pyproject.toml");
if (process.argv.length > 2) {
  if (process.argv.length !== 4 || process.argv[2] !== "--version") {
    throw new Error("Usage: build-plugins.mjs [--version X.Y.Z]");
  }
  if (process.argv[3] !== version) throw new Error("Release version does not match pyproject.toml");
}

// Validate every package before replacing any output, including hand-built packs.
const packages = [];
for (const [agent, adapter] of Object.entries(adapters)) {
  const directory = join(root, "plugins", agent);
  const manifest = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
  if (manifest.name !== `luminary-memory-${agent}` || manifest.version !== version) {
    throw new Error(`${agent}: package name/version must match luminary-memory-${agent}@${version}`);
  }
  if (agent === "pi" && !manifest.keywords?.includes("pi-package")) {
    throw new Error("pi: pi-package keyword is required for official catalog discovery");
  }
  const entry = "./dist/index.js";
  const exportedEntry = typeof manifest.exports === "string" ? manifest.exports : manifest.exports?.["."];
  if (manifest.main !== entry || exportedEntry !== entry || manifest.type !== "module") {
    throw new Error(`${agent}: package must expose the ESM dist/index.js entry`);
  }
  if (agent !== "opencode" && (
    manifest[agent]?.extensions?.length !== 1 || manifest[agent].extensions[0] !== entry
  )) {
    throw new Error(`${agent}: native manifest must discover ${entry}`);
  }
  const source = join(root, "src", "luminary_memory", "integrations", "assets", agent, adapter.source);
  await access(source);
  await access(join(directory, "README.md"));
  packages.push({ agent, directory, source });
}

for (const { agent, directory, source } of packages) {
  const destination = join(directory, "dist");
  await rm(destination, { recursive: true, force: true });
  await mkdir(destination, { recursive: true });
  await build({
    entryPoints: agent === "opencode" ? {
      index: source,
      rpc: join(dirname(source), "rpc.ts"),
      tui: join(dirname(source), "tui.tsx"),
    } : { index: source },
    outdir: destination,
    bundle: true,
    packages: "external",
    platform: "node",
    format: "esm",
    target: "node22",
    legalComments: "eof",
    // Avoid leaking a maintainer's absolute source path into published artifacts.
    minifyWhitespace: true,
    plugins: [solidTransform],
  });
  if (agent === "opencode") {
    // Preserve compiler diagnostics without corrupting `npm pack --json` stdout.
    await buildGui({
      configFile: join(root, "scripts/opencode-gui.vite.mjs"),
      customLogger: createLogger("info", {
        console: new Console({ stdout: process.stderr, stderr: process.stderr }),
        allowClearScreen: false,
      }),
    });
  }
  const resources = join(root, "src", "luminary_memory", "integrations", "assets", "compiled", agent);
  await mkdir(resources, { recursive: true });
  for (const name of agent === "opencode" ? ["index.js", "rpc.js", "tui.js", "gui-experimental.cjs"] : ["index.js"]) {
    await copyFile(join(destination, name), join(resources, name));
  }
  await copyFile(join(root, "LICENSE"), join(directory, "LICENSE"));
  console.error(`Built luminary-memory-${agent}@${version}`);
}
