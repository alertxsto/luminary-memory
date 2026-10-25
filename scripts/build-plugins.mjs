import { access, copyFile, mkdir, readFile, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

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
    entryPoints: [source],
    outfile: join(destination, "index.js"),
    bundle: true,
    packages: "external",
    platform: "node",
    format: "esm",
    target: "node22",
    legalComments: "eof",
    // Avoid leaking a maintainer's absolute source path into published artifacts.
    minifyWhitespace: true,
  });
  await copyFile(join(root, "LICENSE"), join(directory, "LICENSE"));
  console.error(`Built luminary-memory-${agent}@${version}`);
}
