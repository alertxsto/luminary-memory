import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const interpreter = process.argv[2];
if (!interpreter) throw new Error('Pass the Python interpreter of a separately installed wheel');
const project = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = await mkdtemp(join(tmpdir(), 'luminary-installed-consumer-'));
const workspace = join(root, 'workspace');
const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  !key.toUpperCase().startsWith('LUMINARY_') && !['PYTHONPATH', 'PYTHONHOME', 'NODE_PATH'].includes(key.toUpperCase())));
Object.assign(environment, {
  LUMINARY_CONFIG_FILE: 'none', LUMINARY_BACKEND: 'sqlite', LUMINARY_USER_ID: 'installed-native-owner',
  LUMINARY_DB_PATH: join(root, 'memory.db'), LUMINARY_PYTHON: interpreter,
  HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1',
});
try {
  await mkdir(workspace);
  const seeded = spawnSync(interpreter, ['-c', `
import json, os, sys
from pathlib import Path
import luminary_memory
from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.types import Memory
package = Path(luminary_memory.__file__).resolve().parent
assert package.is_relative_to(Path(sys.prefix).resolve()), 'consumer imported repository/system package instead of its installed wheel'
workspace = os.path.normcase(str(Path(sys.argv[1]).resolve()))
backend = SQLiteBackend(os.environ['LUMINARY_DB_PATH'])
try:
    own = backend.add(Memory(content='Owned installed-wheel memory', tags=['unreviewed'],
        user_id='installed-native-owner', workspace_id=workspace, agent_id='pi', session_id='original-session'))
    foreign = backend.add(Memory(content='FOREIGN_PROJECT_SECRET', user_id='installed-native-owner',
        workspace_id=workspace + '-foreign', agent_id='pi'))
finally:
    backend.close()
print(json.dumps({'package_root': str(package), 'workspace': workspace, 'own_id': own, 'foreign_id': foreign}))
`, workspace], { cwd: workspace, env: environment, encoding: 'utf8', timeout: 30_000 });
  assert.equal(seeded.status, 0, seeded.stderr || String(seeded.error));
  const fixture = JSON.parse(seeded.stdout);
  const common = join(fixture.package_root, 'integrations', 'assets', 'common');
  const consumer = join(root, 'consumer.mjs');
  // Build only the sources actually present in the installed wheel. The child
  // runs the resulting standalone bundle outside the checkout/node_modules.
  await build({
    entryPoints: [join(project, 'tests/ui/installed-consumer.ts')], outfile: consumer,
    bundle: true, platform: 'node', format: 'esm', target: 'node22',
    alias: {
      '@luminary/installed-controller': join(common, 'console-controller.ts'),
      '@luminary/installed-transport': join(common, 'inspector-transport.ts'),
    },
  });
  const executed = spawnSync(process.execPath, [consumer, JSON.stringify(fixture)], {
    cwd: workspace, env: environment, encoding: 'utf8', timeout: 120_000,
  });
  assert.equal(executed.status, 0, executed.stderr || String(executed.error));
  console.log(executed.stdout.trim());
} finally {
  await rm(root, { recursive: true, force: true });
}
