import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { InspectorController } from '@luminary/installed-controller';
import { createInspectorTransport } from '@luminary/installed-transport';
import { resolveBridgePython } from '@luminary/installed-bridge-launch';
import { bridgeEnvironment } from '@luminary/installed-bridge-source';

const fixture = JSON.parse(process.argv[2]);
const transport = createInspectorTransport({
  agent: fixture.agent, workspace: fixture.workspace, session_id: 'installed-native-session',
  host_id: 'installed-test-host', profile_id: 'installed-test-profile',
});
assert.equal(Boolean(process.env.LUMINARY_PYTHON), Boolean(fixture.invalid_override));
const bridge = spawnSync(resolveBridgePython(fixture.agent, '__LUMINARY_PYTHON__'),
  ['-m', 'luminary_memory.integrations', 'bridge'], {
    input: JSON.stringify({ action: 'activity', agent: fixture.agent,
      workspace: fixture.workspace, session_id: 'installed-native-session' }) + '\n',
    cwd: fixture.workspace,
    env: bridgeEnvironment(fixture.agent, fixture.workspace, 'installed-native-session'),
    encoding: 'utf8', timeout: 30_000, maxBuffer: 256 * 1024,
  });
if (fixture.invalid_override) {
  assert.ok(bridge.error, 'Invalid explicit Python must fail rather than use the healthy record');
  assert.ok(!bridge.stdout, 'An invalid override must not return bridge data');
  const unavailable = await transport.request({ operation: 'browse', arguments: {}, request_id: 'invalid-installed-python' });
  assert.equal(unavailable.status, 'unavailable');
  assert.equal(unavailable.data, null);
  assert.ok(unavailable.error?.message);
  console.log(JSON.stringify({ agent: fixture.agent, explicit_override: 'unavailable', inspector_status: unavailable.status }));
} else {
assert.equal(bridge.status, 0, bridge.stderr || String(bridge.error));
const activity = JSON.parse(bridge.stdout);
assert.equal(activity.ok, true, JSON.stringify(activity));
assert.deepEqual(activity.memories.map((row: { id: number }) => row.id), [fixture.own_id]);
const current = new InspectorController(transport);
const stale = new InspectorController(transport);
try {
  await current.selectTab('memories');
  assert.equal(current.state.status, 'ok');
  const rows = current.state.data.items as Record<string, any>[];
  assert.deepEqual(rows.map(row => row.id), [fixture.own_id]);
  assert.equal(rows[0].content, 'Owned installed-wheel memory');
  assert.equal(rows[0].permissions.read, true);
  assert.equal(rows[0].permissions.edit, true);
  assert.equal(rows[0].permissions.retract, true);
  const epoch = current.state.context_epoch;
  const policy = current.state.policy_revision;
  assert.equal(typeof epoch, 'string');
  assert.ok(epoch);
  assert.ok(Number.isInteger(policy) && policy! > 0);
  assert.ok(Number.isFinite(Date.parse(current.state.as_of!)));
  const cancelled = new AbortController();
  cancelled.abort();
  const cancellation = await transport.request({ operation: 'browse', arguments: {}, request_id: 'installed-cancelled' }, cancelled.signal);
  assert.equal(cancellation.status, 'cancelled');
  assert.equal(cancellation.data, null);
  const fileHandle = await current.registerFile(fixture.export_path, 'write');
  assert.equal(typeof fileHandle, 'string');
  assert.ok(fileHandle);

  const detail = await current.detail(fixture.own_id);
  assert.equal(detail?.status, 'ok');
  const memory = detail!.data!.memory as Record<string, any>;
  assert.equal(memory.content, 'Owned installed-wheel memory');
  assert.equal(memory.permissions.edit, true);
  const change = { kind: 'tag', memory_id: fixture.own_id, expected_revision: memory.revision };
  await current.preview('preview_change', { ...change, tags: ['reviewed'] });
  await stale.preview('preview_change', { ...change, tags: ['stale-edit'] });
  const committed = await current.commit(async () => true);
  assert.equal(committed?.status, 'ok');
  assert.equal(committed?.data?.audit, 'committed');
  const rejected = await stale.commit(async () => true);
  assert.equal(rejected?.status, 'conflict');
  assert.equal(rejected?.error?.code, 'conflict');
  assert.equal(stale.state.status, 'conflict');
  assert.deepEqual(stale.state.data, {});

  const after = await current.detail(fixture.own_id);
  assert.deepEqual((after!.data!.memory as Record<string, any>).tags, ['reviewed']);
  assert.equal((after!.data!.memory as Record<string, any>).revision, memory.revision + 1);
  assert.equal(current.state.context_epoch, epoch);
  assert.equal(current.state.policy_revision, policy);
  assert.ok(Number.isFinite(Date.parse(current.state.as_of!)));
  const denied = await current.detail(fixture.foreign_id);
  assert.equal(denied?.status, 'denied');
  assert.equal(denied?.data, null);
  assert.equal(denied?.error?.code, 'denied');
  assert.equal(current.state.status, 'denied');
  assert.deepEqual(current.state.data, {});
  assert.equal(current.state.as_of, denied!.as_of);
  assert.equal(current.state.context_epoch, denied!.context_epoch);
  assert.equal(current.state.policy_revision, denied!.policy_revision);
  console.log(JSON.stringify({
    installed_package: fixture.package_root, agent: fixture.agent,
    bridge_ids: activity.memories.map((row: { id: number }) => row.id),
    browse_ids: rows.map(row => row.id),
    persisted_tags: (after!.data!.memory as Record<string, any>).tags,
    stale_status: rejected!.status, foreign_status: denied!.status,
    context_epoch: epoch, policy_revision: policy,
  }));
} finally {
  current.dispose();
  stale.dispose();
}
}
