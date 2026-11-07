import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { pathToFileURL } from 'node:url';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = await mkdtemp(join(tmpdir(), 'luminary-controller-'));
await build({ entryPoints: ['src/luminary_memory/integrations/assets/common/console-controller.ts'], outfile: join(dir, 'controller.mjs'), bundle: true, platform: 'neutral', format: 'esm' });
const { InspectorController } = await import(pathToFileURL(join(dir, 'controller.mjs')).href);
await build({ entryPoints: ['src/luminary_memory/integrations/assets/common/console-actions.ts'], outfile: join(dir, 'actions.mjs'), bundle: true, platform: 'neutral', format: 'esm' });
const { runInspectorAction, inspectorActions } = await import(pathToFileURL(join(dir, 'actions.mjs')).href);
await build({ entryPoints: ['src/luminary_memory/integrations/assets/common/terminal-view.ts'], outfile: join(dir, 'view.mjs'), bundle: true, platform: 'neutral', format: 'esm' });
const { TerminalInspectorView } = await import(pathToFileURL(join(dir, 'view.mjs')).href);
process.on('exit', () => { void rm(dir, { recursive: true, force: true }); });
const result = (request, data = {}, status = 'ok', policy = 1) => ({ status, data, error: status === 'ok' ? null : { code: status, message: status }, request_id: request.request_id, context_epoch: 'owner-project', policy_revision: policy, as_of: '2026-10-26T00:00:00Z' });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('switching native context rejects late content and aborts old reads', async () => {
  const pending = deferred(); let signal; let oldRequest;
  const controller = new InspectorController({ request(request, s) { oldRequest = request; signal = s; return pending.promise; } });
  const load = controller.load();
  controller.switchContext({ request: async request => result(request, { items: [{ id: 2, content: 'new project' }] }) });
  await controller.load();
  pending.resolve(result(oldRequest, { items: [{ id: 1, content: 'private old project' }] }));
  await load;
  assert.equal(signal.aborted, true);
  assert.deepEqual(controller.state.data.items, [{ id: 2, content: 'new project' }]);
});

test('newer selection wins over an out-of-order detail response', async () => {
  const first = deferred(); let firstRequest;
  const controller = new InspectorController({ request: request => { if (request.arguments.memory_id === 1) { firstRequest = request; return first.promise; } return Promise.resolve(result(request, { memory: { id: 2, content: 'second' } })); } });
  const old = controller.detail(1);
  await controller.detail(2);
  first.resolve(result(firstRequest, { memory: { id: 1, content: 'first' } })); await old;
  assert.equal(controller.state.data.memory.id, 2);
});

test('denial clears cached records and outstanding owner previews', async () => {
  let denied = false;
  const controller = new InspectorController({ request: async request => result(request, request.operation === 'preview_change' ? { preview_id: 'p', before: 'old', after: 'new' } : { items: [{ content: 'secret' }] }, denied ? 'denied' : 'ok') });
  await controller.load(); await controller.preview('preview_change', { kind: 'correct', memory_id: 1 });
  denied = true; await controller.load();
  assert.equal(controller.state.status, 'denied'); assert.deepEqual(controller.state.data, {}); assert.equal(controller.state.preview, undefined);
});

test('mutation requires native decision and transport receipt before commit', async () => {
  const order = [];
  const controller = new InspectorController({
    request: async request => { order.push(request.operation); if (request.operation === 'preview_change') return result(request, { preview_id: 'opaque-p', before: 'old', after: 'new' }); assert.equal(request.arguments.confirmation_receipt, 'receipt'); return result(request, { committed: true }); },
    confirm: async id => { assert.equal(id, 'opaque-p'); order.push('receipt'); return result({ request_id: 'confirm' }, { confirmation_receipt: 'receipt' }); },
  });
  await controller.preview('preview_change', { kind: 'correct', memory_id: 1, expected_revision: 2 });
  await controller.commit(async preview => { assert.equal(preview.after, 'new'); order.push('native'); return false; });
  assert.deepEqual(order, ['preview_change', 'native']);
  await controller.preview('preview_change', { kind: 'correct', memory_id: 1, expected_revision: 2 });
  await controller.commit(async () => { order.push('native'); return true; });
  assert.deepEqual(order, ['preview_change', 'native', 'preview_change', 'native', 'receipt', 'mutate']);
  assert.equal(controller.state.data.committed, true);
});

test('context switch during native confirmation cannot commit old preview', async () => {
  const choice = deferred(); let writes = 0;
  const controller = new InspectorController({ request: async request => result(request, { preview_id: 'old' }), confirm: async () => { writes++; throw new Error('must not confirm'); } });
  await controller.preview('preview_change', { kind: 'retract', memory_id: 1 });
  const commit = controller.commit(() => choice.promise);
  controller.switchContext({ request: async request => result(request) }); choice.resolve(true); await commit;
  assert.equal(writes, 0); assert.equal(controller.state.preview, undefined);
});

test('lost dispatched mutation has unknown outcome without automatic replay', async () => {
  let mutations = 0;
  const controller = new InspectorController({ request: async request => { if (request.operation === 'mutate') { mutations++; throw new Error('connection lost'); } return result(request, { preview_id: 'p' }); }, confirm: async () => result({ request_id: 'c' }, { confirmation_receipt: 'r' }) });
  await controller.preview('preview_change', { kind: 'retract', memory_id: 1 }); await controller.commit(async () => true);
  assert.equal(controller.state.status, 'unknown_outcome'); assert.equal(mutations, 1); assert.equal(controller.state.preview, undefined);
});

test('cancel and dispose release pending work without stale rendering', async () => {
  const pending = deferred(); let request; let signal;
  const controller = new InspectorController({ request: (r, s) => { request = r; signal = s; return pending.promise; } });
  let renders = 0; controller.subscribe(() => renders++); const load = controller.load(); controller.cancel();
  assert.equal(signal.aborted, true); assert.equal(controller.state.status, 'cancelled');
  controller.dispose(); const before = renders; pending.resolve(result(request, { items: [{ content: 'late' }] })); await load;
  assert.equal(renders, before); assert.deepEqual(controller.state.data, {});
});


test('refresh while an owner dialog is open invalidates that exact proposal', async () => {
  const decision = deferred(); let confirmations = 0;
  const controller = new InspectorController({
    request: async request => result(request, request.operation === 'preview_change' ? { preview_id: 'old' } : { items: [] }),
    confirm: async () => { confirmations++; return result({ request_id: 'confirm' }, { confirmation_receipt: 'r' }); },
  });
  await controller.preview('preview_change', { kind: 'retract', memory_id: 1 });
  const commit = controller.commit(() => decision.promise);
  await controller.load(); decision.resolve(true); await commit;
  assert.equal(confirmations, 0); assert.equal(controller.state.preview, undefined);
});

test('a late failed confirmation cannot clear a newer proposal', async () => {
  const pending = deferred(); let count = 0;
  const controller = new InspectorController({
    request: async request => result(request, { preview_id: `p${++count}` }),
    confirm: () => pending.promise,
  });
  await controller.preview('preview_change', { kind: 'retract', memory_id: 1 });
  const commit = controller.commit(async () => true);
  await Promise.resolve();
  await controller.preview('preview_change', { kind: 'retract', memory_id: 2 });
  pending.reject(new Error('transport disappeared'));
  await commit;
  assert.equal(controller.state.preview.preview_id, 'p2');
});

const dialogs = (answers = {}) => ({
  input: async title => answers[title],
  select: async title => answers[title],
  confirm: async () => true,
  show: async () => {},
});


test('native fullscreen mouse selects rows and opens keyboard-equivalent actions', async () => {
  const controller = new InspectorController({ request: async request => result(request, { items: [{ id: 1 }, { id: 2 }] }) });
  await controller.load(); const intents = [];
  const view = new TerminalInspectorView(controller, (data, key) => data === key, text => text, (_role, text) => text, intent => intents.push(intent), () => {}, () => 24);
  view.render(80);
  assert.equal(view.handleMouse({ type: 'click', button: 'left', x: 2, y: 4 }).handled, true);
  assert.equal(view.selected, 1);
  view.handleMouse({ type: 'click', button: 'left', x: 2, y: 4, clickCount: 2 });
  assert.equal(intents.at(-1).row.id, 2);
  assert.equal(intents.at(-1).type, 'actions');
});

test('conflict resolution forwards the observed conflict-set token', async () => {
  const requests = [];
  const controller = new InspectorController({
    request: async request => { requests.push(request); return result(request, request.operation === 'detail' ? { memory: { id: 4, revision: 8 }, conflict_set_token: 'observed-set' } : request.operation === 'preview_change' ? { preview_id: 'p' } : {}); },
    confirm: async () => result({ request_id: 'c' }, { confirmation_receipt: 'receipt' }),
  });
  await runInspectorAction(controller, dialogs(), 'Resolve conflict', { id: 4, revision: 7 });
  const preview = requests.find(r => r.operation === 'preview_change');
  assert.equal(preview.arguments.expected_revision, 8);
  assert.equal(preview.arguments.expected_conflict_set_token, 'observed-set');
});

test('read-only records offer grounding but never correction or retraction', () => {
  const controller = new InspectorController({ request: async request => result(request) });
  const actions = inspectorActions(controller, { id: 1, permissions: { read: true, edit: false, retract: false } });
  assert.ok(actions.includes('History')); assert.ok(actions.includes('Expand evidence'));
  assert.equal(actions.includes('Correct'), false); assert.equal(actions.includes('Retract'), false);
});

test('project grant capabilities are selected independently', async () => {
  const requests = [];
  const controller = new InspectorController({
    request: async request => { requests.push(request); return result(request, request.operation === 'preview_change' ? { preview_id: 'p' } : {}); },
    confirm: async () => result({ request_id: 'c' }, { confirmation_receipt: 'receipt' }),
  });
  await runInspectorAction(controller, {
    ...dialogs({ 'Agent receiving explicit project rights': 'omp' }),
    confirm: async title => title === 'Grant contribute?' || title === 'Confirm Luminary change',
  }, 'Grant rights');
  const preview = requests.find(r => r.operation === 'preview_change');
  assert.equal(preview.arguments.recipient_agent_id, 'omp');
  assert.deepEqual(preview.arguments.capabilities, ['contribute']);
  assert.equal(requests.at(-1).operation, 'grant');
});

test('refresh after an activity gap loads a snapshot instead of replaying the lost boundary', async () => {
  const controller = new InspectorController({
    request: async request => {
      const args = request.arguments;
      if (args.since_event_id !== undefined || args.replay_context !== undefined || args.cursor !== undefined) {
        return result(request, { items: [], gap: true, snapshot_required: true, replay_context: null }, 'empty');
      }
      return result(request, { items: [{ event_id: 99, kind: 'ingest', memory_id: 7 }], snapshot_boundary: 99 });
    },
  });
  await controller.selectTab('activity');
  await controller.load({ since_event_id: 10, replay_context: 'previous-boundary', cursor: 'old-history-page' });
  assert.equal(controller.state.data.gap, true);
  await controller.load();
  assert.deepEqual(controller.state.data.items.map(row => row.event_id), [99]);
  assert.equal(controller.state.data.snapshot_required, undefined);
});

test('new activity excludes witnessed events and Refresh returns the full recent snapshot', async () => {
  const events = [{ event_id: 6, kind: 'ingest' }, { event_id: 7, kind: 'native_recall' }];
  const controller = new InspectorController({
    request: async request => {
      const since = request.arguments.since_event_id;
      const rows = since === undefined ? [...events].reverse() : events.filter(row => row.event_id > since);
      const boundary = rows.length ? Math.max(...rows.map(row => row.event_id)) : since;
      return result(request, {
        items: rows, replayed: since !== undefined, has_more: false,
        snapshot_boundary: since === undefined ? boundary : undefined,
        next_event_id: since === undefined ? undefined : boundary,
        replay_context: `bound-${boundary}`,
      });
    },
  });
  await controller.selectTab('activity');
  events.push({ event_id: 9, kind: 'ingest' });
  await runInspectorAction(controller, {}, 'Check new activity');
  assert.deepEqual(controller.state.data.items.map(row => row.event_id), [9]);
  await runInspectorAction(controller, {}, 'Refresh');
  assert.deepEqual(controller.state.data.items.map(row => row.event_id), [9, 7, 6]);
});
