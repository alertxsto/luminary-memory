import assert from 'node:assert/strict';
import { InspectorController } from '@luminary/installed-controller';
import { createInspectorTransport } from '@luminary/installed-transport';

const fixture = JSON.parse(process.argv[2]);
const transport = createInspectorTransport({
  agent: 'pi', workspace: fixture.workspace, session_id: 'installed-native-session',
  host_id: 'installed-test-host', profile_id: 'installed-test-profile',
});
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
    installed_package: fixture.package_root, browse_ids: rows.map(row => row.id),
    persisted_tags: (after!.data!.memory as Record<string, any>).tags,
    stale_status: rejected!.status, foreign_status: denied!.status,
    context_epoch: epoch, policy_revision: policy,
  }));
} finally {
  current.dispose();
  stale.dispose();
}
