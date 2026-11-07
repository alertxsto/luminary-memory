import { copyFile, mkdir, readdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
await build({
  entryPoints: [join(root, 'ui/browser/app.ts')],
  outfile: join(root, 'src/luminary_memory/inspector/assets/browser/app.js'),
  bundle: true, platform: 'browser', format: 'esm', target: 'es2023', legalComments: 'eof',
});
const hermes = join(root, 'plugins/hermes');
await mkdir(join(hermes, 'desktop'), { recursive: true });
await mkdir(join(hermes, 'dashboard/dist'), { recursive: true });
await build({
  entryPoints: [join(root, 'ui/hermes/desktop.mjs')],
  outfile: join(hermes, 'desktop/plugin.js'), bundle: true, format: 'esm', platform: 'browser',
  external: ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'], target: 'es2023', legalComments: 'eof',
});
await build({
  entryPoints: [join(root, 'ui/hermes/dashboard.mjs')],
  outfile: join(hermes, 'dashboard/dist/index.js'), bundle: true, format: 'iife', platform: 'browser',
  target: 'es2023', legalComments: 'eof',
});
// Wheels carry exactly the same unified plugin resources as the repository
// package; Python installation never needs this checkout or Node to run a UI.
async function stage(source, destination) {
  await mkdir(destination, { recursive: true });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    const from = join(source, entry.name), to = join(destination, entry.name);
    if (entry.isDirectory()) await stage(from, to);
    else await copyFile(from, to);
  }
}
await stage(hermes, join(root, 'src/luminary_memory/integrations/assets/compiled/hermes'));
console.error('Built optional browser, Hermes Desktop and native dashboard resources.');
