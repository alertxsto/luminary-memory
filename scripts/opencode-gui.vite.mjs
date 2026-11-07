import { defineConfig } from 'vite';
import { gui } from '@opencode/plugin/gui/vite';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export default defineConfig({
  root,
  plugins: [gui({
    entry: resolve(root, 'src/luminary_memory/integrations/assets/opencode/gui.tsx'),
    outFile: resolve(root, 'plugins/opencode/dist/gui-experimental.cjs'),
  })],
});
