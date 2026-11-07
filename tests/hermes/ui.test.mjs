import assert from 'node:assert/strict';
import test from 'node:test';

// These exercise the native view model used by both host renderers, not host doubles.
const load = () => import('../../ui/hermes/console.mjs');

test('a context switch clears data and rejects an old backend reply', async () => {
  const { createSession } = await load();
  let resolve;
  const session = createSession(() => new Promise(done => { resolve = done; }));
  session.setContext('profile-a:session-a');
  const pending = session.request('browse');
  session.setContext('profile-b:session-b');
  resolve({ status: 'ok', data: { items: [{ id: 1, content: 'private-a' }] }, context_epoch: 'old', policy_revision: 1 });
  await pending;
  assert.equal(session.state.result, null);
  assert.equal(session.state.preview, null);
});

test('commit needs explicit native confirmation and uses its separate endpoint', async () => {
  const { createSession } = await load();
  const calls = [];
  const session = createSession(async (path, body) => {
    calls.push({ path, body });
    return { status: 'ok', data: { preview_id: 'opaque-preview', before: 'before', after: 'after' }, context_epoch: 'a', policy_revision: 1 };
  });
  session.setContext('a');
  await session.request('preview_change', { kind: 'edit', memory_id: 1, content: 'after' });
  await session.confirm(false);
  assert.equal(calls.length, 1);
  await session.confirm(true);
  assert.equal(calls[1].path, '/confirm');
  assert.equal(calls[1].body.preview_id, 'opaque-preview');
  assert.equal(calls[1].body.session_ref, 'a');
  assert.equal(session.state.preview, null);
});

test('backend failure is unavailable and dispatched write failure is unknown', async () => {
  const { createSession } = await load();
  const session = createSession(async () => { throw new Error('HTTP 404'); });
  session.setContext('a');
  await session.request('browse');
  assert.equal(session.state.result.status, 'unavailable');
  await session.request('mutate', { receipt: 'one-use' });
  assert.equal(session.state.result.status, 'unknown_outcome');
});

test('revoked access drops retained items and outstanding preview', async () => {
  const { createSession } = await load();
  let allowed = true;
  const session = createSession(async () => allowed
    ? { status: 'ok', data: { preview_id: 'p', items: [{ content: 'private' }] }, context_epoch: 'a', policy_revision: 1 }
    : { status: 'denied', data: null, error: { code: 'revoked', message: 'Denied' }, context_epoch: 'a', policy_revision: 2 });
  session.setContext('a');
  await session.request('preview_change');
  allowed = false;
  await session.request('browse');
  assert.equal(session.state.preview, null);
  assert.equal(session.state.result.status, 'denied');
  assert.equal(session.state.result.data, null);
});

test('a context switch during open cannot reopen the previous session', async () => {
  const { createSession } = await load();
  let resolve;
  const session = createSession(() => new Promise(done => { resolve = done; }));
  session.setContext('a');
  const pending = session.open();
  session.setContext('b');
  resolve({ status: 'ok', data: { items: [{ content: 'old' }] } });
  await pending;
  assert.equal(session.state.opened, false);
  assert.equal(session.state.result, null);
});

test('changing resource selection discards pending and previous read state', async () => {
  const { createSession } = await load();
  let resolve;
  const session = createSession(() => new Promise(done => { resolve = done; }));
  session.setContext('a');
  const pending = session.request('browse');
  session.setSelection('shared-project');
  assert.equal(session.state.pending, false);
  resolve({ status: 'ok', data: { items: [{ content: 'old-own' }] } });
  await pending;
  assert.equal(session.state.result, null);
});


test('context switch aborts pending native upload before it can preview', async () => {
  const { createSession } = await load();
  let signal, finish;
  const session = createSession((path, body, active) => {
    signal = active;
    return new Promise(resolve => { finish = resolve; });
  });
  session.setContext('a');
  const pending = session.transfer('import', {});
  session.setContext('b');
  assert.equal(signal.aborted, true);
  finish({ status: 'ok', data: { file_handle: 'old' } });
  assert.equal(await pending, null);
  assert.equal(session.state.preview, null);
});

test('native effect cleanup and rebind restores a fresh model lifetime', async () => {
  const { createSession } = await load();
  const session = createSession(async () => ({ status: 'ok', data: { items: [] } }));
  session.setContext('s1');
  session.dispose();
  session.setContext('s1');
  const result = await session.open();
  assert.equal(result.status, 'ok');
  assert.equal(session.state.opened, true);
});
