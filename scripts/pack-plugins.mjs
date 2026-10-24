import { mkdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import "./build-plugins.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const destination = join(root, "artifacts", "plugins");
const npm = process.env.npm_execpath;
if (!npm) throw new Error("Run the pack command through npm run pack:plugins");
await mkdir(destination, { recursive: true });

for (const agent of ["pi", "opencode", "omp"]) {
  const manifest = JSON.parse(await readFile(join(root, "plugins", agent, "package.json"), "utf8"));
  // Spawn Node with npm's actual JS entrypoint, not a shell or Windows .cmd shim.
  const result = spawnSync(process.execPath, [
    npm, "pack", "--workspace", manifest.name, "--json", "--ignore-scripts",
    "--pack-destination", destination,
  ], { cwd: root, encoding: "utf8", maxBuffer: 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(result.stderr || `${manifest.name}: npm pack failed`);
  const [packed] = JSON.parse(result.stdout);
  const expected = `${manifest.name}-${manifest.version}.tgz`;
  if (packed?.filename !== expected) throw new Error(`${manifest.name}: unexpected pack artifact`);
  const files = new Set(packed.files.map((file) => file.path));
  for (const required of ["package.json", "dist/index.js", "README.md", "LICENSE"]) {
    if (!files.has(required)) throw new Error(`${manifest.name}: tarball is missing ${required}`);
  }
  if ([...files].some((path) => path.startsWith("node_modules/"))) {
    throw new Error(`${manifest.name}: tarball must not bundle a second copy of its host`);
  }
  console.log(join(destination, expected));
}
