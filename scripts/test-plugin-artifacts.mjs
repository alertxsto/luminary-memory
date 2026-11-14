import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const project = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const directory = await mkdtemp(join(tmpdir(), 'luminary packed consumers '));
try {
  for (const agent of ['pi', 'omp', 'opencode']) {
    const manifest = JSON.parse(await readFile(join(project, 'plugins', agent, 'package.json'), 'utf8'));
    const target = join(directory, agent);
    await mkdir(target);
    const archive = join(project, 'artifacts', 'plugins', `${manifest.name}-${manifest.version}.tgz`);
    const extracted = spawnSync('tar', ['-xzf', archive, '-C', target, '--strip-components=1'], { encoding: 'utf8' });
    assert.equal(extracted.status, 0, extracted.stderr || String(extracted.error));
    const packed = JSON.parse(await readFile(join(target, 'package.json'), 'utf8'));
    assert.equal(packed.name, manifest.name);
    assert.equal(packed.version, manifest.version);
  }
  // Expose the host/test toolchain's peer modules, not another plugin source.
  await symlink(join(project, 'node_modules'), join(directory, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
  const result = spawnSync(process.execPath, [
    '--test', '--test-name-pattern=package (reports|discovers)', 'tests/plugins/packages.test.mjs',
  ], {
    cwd: project, env: { ...process.env, LUMINARY_TEST_PLUGIN_ROOT: directory },
    encoding: 'utf8', timeout: 180_000, maxBuffer: 4 * 1024 * 1024,
  });
  process.stdout.write(result.stdout || '');
  process.stderr.write(result.stderr || '');
  assert.equal(result.status, 0, String(result.error || 'Packed consumers failed'));
} finally {
  await rm(directory, { recursive: true, force: true });
}
