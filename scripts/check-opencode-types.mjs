import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const compiler = resolve(root, 'node_modules/typescript/bin/tsc');
const common = ['--noEmit', '--strict', '--skipLibCheck', '--target', 'esnext', '--module', 'esnext', '--moduleResolution', 'bundler', '--jsx', 'preserve', '--types', 'node'];
for (const [jsx, entries] of [
  ['solid-js', ['gui.tsx', 'luminary-memory.ts']],
  ['@opentui/solid', ['tui.tsx']],
]) {
  const result = spawnSync(process.execPath, [compiler, ...common, '--jsxImportSource', jsx, ...entries.map(entry => `src/luminary_memory/integrations/assets/opencode/${entry}`)], { cwd: root, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
