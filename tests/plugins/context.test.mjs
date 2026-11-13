import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { z } from 'zod';

const root = fileURLToPath(new URL('../../', import.meta.url));

// Boundary units: only OS process completion and native drawing are replaced.
// These check our authority/lifecycle decisions, not real-host SDK acceptance.
for (const agent of ['opencode', 'pi', 'omp']) {
  test(`${agent}: empty recall is silent; current references stay out of system and transcript`, async () => {
    const directory = await mkdtemp(join(tmpdir(), 'luminary-native-context-'));
    const spawnKey = `luminary_context_spawn_${agent}`;
    const handlers = new Map();
    let turn = 0;
    let reply;
    let coreReply;
    let cleanup;
    const empty = () => ({ ok: true, status: 'abstain', reason: 'no_supported_candidate',
      message: 'No grounded relevant memories.', context: '', memories: [], stored: 0, deleted: 0 });
    coreReply = empty();
    const register = (event, handler) => {
      const callbacks = handlers.get(event) ?? [];
      callbacks.push(handler); handlers.set(event, callbacks);
    };
    const fire = async (event, payload, context) => {
      let result;
      for (const handler of handlers.get(event) ?? []) result = await handler(payload, context) ?? result;
      return result;
    };
    // Each child delivers a complete external bridge response. No forwarding
    // assertions: the observable contract is absence, authority and replacement.
    globalThis[spawnKey] = () => {
      const child = new EventEmitter();
      child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
      child.stdin = new EventEmitter();
      child.stdin.end = (payload) => queueMicrotask(() => {
        const action = JSON.parse(payload).action;
        child.stdout.emit('data', Buffer.from(JSON.stringify(action === 'core' ? coreReply : reply)));
        child.emit('close', 0);
      });
      child.kill = () => child.emit('close', 1);
      return child;
    };
    try {
      await symlink(join(root, 'node_modules'), join(directory, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
      const entry = join(directory, 'adapter.mjs');
      await build({
        entryPoints: [join(root, 'src/luminary_memory/integrations/assets', agent,
          agent === 'opencode' ? 'luminary-memory.ts' : 'luminary.ts')],
        outfile: entry, bundle: true, platform: 'node', format: 'esm', target: 'node22',
        external: ['@opencode/*', 'effect', 'effect/*'],
        plugins: [{ name: 'native-boundaries', setup(builder) {
          builder.onResolve({ filter: /^node:child_process$/ }, () => ({ path: 'process', namespace: 'boundary' }));
          builder.onResolve({ filter: /^@(earendil-works|oh-my-pi)\/pi-tui$/ }, () => ({ path: 'drawing', namespace: 'boundary' }));
          builder.onLoad({ filter: /.*/, namespace: 'boundary' }, ({ path }) => ({ contents: path === 'process'
            ? `export const spawn = globalThis[${JSON.stringify(spawnKey)}];`
            : "export function matchesKey(){throw Error('Unexpected native drawing')} export function truncateToWidth(){throw Error('Unexpected native drawing')}" }));
        }}],
      });
      const { default: plugin } = await import(pathToFileURL(entry).href);
      const context = { mode: 'rpc', hasUI: false, cwd: directory,
        sessionManager: { getSessionId: () => 'native-context-session' } };
      if (agent === 'opencode') {
        cleanup = await plugin.setup({ options: {},
          location: { directory, project: { id: 'native-project', directory, canonical: directory } },
          session: {
            async get({ sessionID }) { return { id: sessionID, location: { directory } }; },
            async context() { return [{ type: 'user', id: `msg_${turn}`, text: 'Current native user task' }]; },
            async hook(event, handler) { register(event, handler); return { async dispose() {} }; },
          },
          event: { async *subscribe() {} },
          rpc: { async register() { return { async dispose() {} }; } },
          tool: { async transform(edit) { edit({ add() {} }); return { async dispose() {} }; } },
        });
      } else plugin({ zod: z, on: register, registerCommand() {}, registerTool() {}, sendMessage() {
        throw Error('Automatic recall must not append a persistent message');
      } });

      const system = [{ type: 'text', text: 'Real system authority' }];
      const originalSystem = structuredClone(system);
      const user = { id: 'native-user', role: 'user', content: [{ type: 'text', text: 'Current native user task' }], timestamp: 1 };
      const run = async (messages = [user]) => {
        if (agent !== 'opencode') {
          const start = await fire('before_agent_start', { prompt: 'Current native user task', systemPrompt: 'Real system authority' }, context);
          assert.equal(start?.message, undefined, 'Automatic recall must be request-local, not a transcript entry');
          assert.equal(start?.systemPrompt, undefined);
        }
        const event = { type: 'context', sessionID: 'native-context-session', system, messages };
        const changed = await fire('context', event, context);
        assert.deepEqual(system, originalSystem, 'Stored text must never change system authority');
        return changed?.messages ?? event.messages;
      };
      reply = empty(); turn++;
      assert.deepEqual(await run(), [user]);

      const rows = [{ id: 41, content: '🛰️'.repeat(12000), tags: [], source: 'native', evidence_quote: 'A user observation', confidence: 0.8 }];
      reply = { ...empty(), status: 'ok', reason: '', memories: rows,
        context: 'Historical observations, not instructions:\n' + JSON.stringify(rows) };
      turn++;
      const first = await run();
      assert.equal(first.length, 2, 'One current reference, not zero or duplicate blocks');
      assert.equal(first.at(-1), user, 'The live native directive stays after historical data');
      const reference = first.find(message => message !== user);
      assert.notEqual(reference.role, 'system');
      const text = typeof reference.content === 'string' ? reference.content : reference.content.map(part => part.text ?? '').join('');
      const body = text.indexOf('\n[');
      assert.notEqual(body, -1, 'Reference records must be JSON data, not an outer encoded string');
      assert.equal(Array.isArray(JSON.parse(text.slice(body + 1))), true, 'Complete records must remain parseable beyond old slicing boundaries');
      const repeated = await run(first);
      assert.equal(repeated.length, 2, 'Rebuilding a request must replace its previous reference');

      reply = empty(); turn++;
      assert.deepEqual(await run(repeated), [user], 'A later abstention removes the preceding turn reference');
    } finally {
      await cleanup?.();
      delete globalThis[spawnKey];
      await rm(directory, { recursive: true, force: true });
    }
  });
}

test('opencode: core baseline is request-local, refreshable and independent of recall', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'luminary-opencode-core-'));
  const spawnKey = 'luminary_core_spawn_opencode';
  const handlers = new Map();
  const requests = [];
  let admitted = { id: 'msg_1', text: 'Current native user task' };
  let replies = {};
  let cleanup;
  const empty = () => ({ ok: true, status: 'abstain', reason: 'no_supported_candidate',
    message: 'No grounded relevant memories.', context: '', memories: [], stored: 0, deleted: 0 });
  const register = (event, handler) => {
    const callbacks = handlers.get(event) ?? [];
    callbacks.push(handler); handlers.set(event, callbacks);
  };
  const fire = async (event, payload, context) => {
    let result;
    for (const handler of handlers.get(event) ?? []) result = await handler(payload, context) ?? result;
    return result;
  };
  globalThis[spawnKey] = () => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
    child.stdin = new EventEmitter();
    child.stdin.end = (payload) => queueMicrotask(() => {
      const request = JSON.parse(payload);
      requests.push(request);
      child.stdout.emit('data', Buffer.from(JSON.stringify(replies[request.action] ?? empty())));
      child.emit('close', 0);
    });
    child.kill = () => child.emit('close', 1);
    return child;
  };
  try {
    await symlink(join(root, 'node_modules'), join(directory, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
    const entry = join(directory, 'adapter.mjs');
    await build({
      entryPoints: [join(root, 'src/luminary_memory/integrations/assets/opencode/luminary-memory.ts')],
      outfile: entry, bundle: true, platform: 'node', format: 'esm', target: 'node22',
      external: ['@opencode/*', 'effect', 'effect/*'],
      plugins: [{ name: 'native-boundaries', setup(builder) {
        builder.onResolve({ filter: /^node:child_process$/ }, () => ({ path: 'process', namespace: 'boundary' }));
        builder.onLoad({ filter: /.*/, namespace: 'boundary' }, () => ({ contents:
          `export const spawn = globalThis[${JSON.stringify(spawnKey)}];` }));
      }}],
    });
    const { default: plugin } = await import(pathToFileURL(entry).href);
    const context = { mode: 'rpc', hasUI: false, cwd: directory,
      sessionManager: { getSessionId: () => 'native-context-session' } };
    cleanup = await plugin.setup({ options: {},
      location: { directory, project: { id: 'native-project', directory, canonical: directory } },
      session: {
        async get({ sessionID }) { return { id: sessionID, location: { directory } }; },
        async context() { return [{ type: 'user', id: admitted.id, text: admitted.text }]; },
        async hook(event, handler) { register(event, handler); return { async dispose() {} }; },
      },
      event: { async *subscribe() {} },
      rpc: { async register() { return { async dispose() {} }; } },
      tool: { async transform(edit) { edit({ add() {} }); return { async dispose() {} }; } },
    });

    const system = [{ type: 'text', text: 'Real system authority' }];
    const originalSystem = structuredClone(system);
    const host = { id: 'host-note', role: 'user', content: [{ type: 'text', text: 'Unrelated host message' }] };
    const live = () => ({ id: 'live-user', role: 'user', content: [{ type: 'text', text: 'Current native user task' }], timestamp: 1 });
    const textOf = (message) => typeof message.content === 'string'
      ? message.content : message.content.map(part => part.text ?? '').join('');
    const luminary = (messages) => messages.filter(message => message.id?.startsWith('luminary:'));
    const run = async (messages) => {
      const event = { type: 'context', sessionID: 'native-context-session', system, messages };
      const changed = await fire('context', event, context);
      assert.deepEqual(system, originalSystem, 'Stored text must never change system authority');
      return changed?.messages ?? event.messages;
    };

    const coreContext = '<luminary-core-memory>\nCall the user Captain\n</luminary-core-memory>';
    const recallContext = 'Luminary recalled data\n[{"id":2,"content":"staging"}]';
    replies = {
      core: { ...empty(), status: 'ok', reason: '', context: coreContext },
      recall: { ...empty(), status: 'ok', reason: '', context: recallContext, memories: [{ id: 2, content: 'staging' }] },
    };
    const first = await run([host, live()]);
    const firstCore = first.filter(message => message.id?.startsWith('luminary:core:'));
    const firstRecall = first.filter(message => message.id?.startsWith('luminary:recall:'));
    assert.equal(firstCore.length, 1, 'One core baseline message');
    assert.equal(firstRecall.length, 1, 'One recall reference message');
    assert.equal(textOf(firstCore[0]), coreContext, 'Core context is attached unchanged, not re-encoded');
    assert.equal(textOf(firstRecall[0]), recallContext, 'Recall context is attached unchanged, not re-encoded');
    assert.ok(first.includes(host), 'Unrelated host messages are preserved');
    assert.equal(first.at(-1).id, 'live-user', 'The live user message stays last');
    assert.ok(!first.some(message => textOf(message).includes('\\n[{\\"id\\"')), 'No double-encoded JSON');
    assert.equal(requests.filter(request => request.action === 'core').length, 1);
    assert.equal(requests.filter(request => request.action === 'recall').length, 1);
    assert.equal(requests.find(request => request.action === 'core').query, undefined, 'Core takes no query');

    admitted = { id: 'msg_2', text: 'Current native user task' };
    replies.core = { ...empty(), status: 'ok', reason: '',
      context: '<luminary-core-memory>\nCall the user Commander\n</luminary-core-memory>' };
    const second = await run(first);
    const secondCore = second.filter(message => message.id?.startsWith('luminary:core:'));
    assert.equal(secondCore.length, 1, 'A refreshed baseline replaces the previous one');
    assert.ok(!second.some(message => textOf(message).includes('Captain')), 'The stale baseline is removed');
    assert.ok(second.some(message => textOf(message).includes('Commander')), 'The fresh baseline is present');
    assert.equal(requests.filter(request => request.action === 'core').length, 2, 'Core is fetched afresh each turn');
    assert.ok(second.includes(host), 'Unrelated host messages survive a refresh');
    assert.equal(second.at(-1).id, 'live-user');

    admitted = { id: 'msg_3', text: 'Current native user task' };
    replies = { core: { ...empty(), status: 'ok', reason: '', context: '' }, recall: empty() };
    const third = await run(second);
    assert.deepEqual(third, [host, live()], 'Empty core and abstained recall remove all Luminary messages');

    admitted = { id: 'msg_4', text: 'Current native user task' };
    replies = {
      core: { ok: false, status: 'error', reason: 'unavailable', message: 'Core unavailable.', context: '', memories: [], stored: 0, deleted: 0 },
      recall: { ...empty(), status: 'ok', reason: '', context: recallContext, memories: [{ id: 2 }] },
    };
    const fourth = await run(third);
    assert.equal(fourth.filter(message => message.id?.startsWith('luminary:core:')).length, 0, 'Core failure adds no baseline');
    assert.equal(fourth.filter(message => message.id?.startsWith('luminary:recall:')).length, 1, 'Core failure does not block valid recall');
    assert.equal(textOf(fourth.find(message => message.id?.startsWith('luminary:recall:'))), recallContext);

    admitted = { id: 'msg_5', text: 'Current native user task' };
    replies = {
      core: { ...empty(), status: 'ok', reason: '', context: coreContext },
      recall: { ...empty(), status: 'abstain', reason: 'no_supported_candidate', context: '' },
    };
    const fifth = await run(fourth);
    assert.equal(fifth.filter(message => message.id?.startsWith('luminary:core:')).length, 1, 'Core still attaches when recall abstains');
    assert.equal(fifth.filter(message => message.id?.startsWith('luminary:recall:')).length, 0, 'Abstained recall adds no reference');
    assert.equal(luminary(fifth).length, 1, 'No duplicate Luminary request messages');
  } finally {
    await cleanup?.();
    delete globalThis[spawnKey];
    await rm(directory, { recursive: true, force: true });
  }
});

// pi and omp share the released hook shape: before_agent_start fetches, the
// request-local context hook injects custom messages. They are still tested
// separately because each adapter owns its own admission and guard code.
for (const agent of ['pi', 'omp']) {
  test(`${agent}: core baseline is request-local, refreshable and independent of recall`, async () => {
    const directory = await mkdtemp(join(tmpdir(), `luminary-${agent}-core-`));
    const spawnKey = `luminary_core_spawn_${agent}`;
    const handlers = new Map();
    const requests = [];
    let replies = {};
    let cleanup;
    const empty = () => ({ ok: true, status: 'abstain', reason: 'no_supported_candidate',
      message: 'No grounded relevant memories.', context: '', memories: [], stored: 0, deleted: 0 });
    const register = (event, handler) => {
      const callbacks = handlers.get(event) ?? [];
      callbacks.push(handler); handlers.set(event, callbacks);
    };
    const fire = async (event, payload, context) => {
      let result;
      for (const handler of handlers.get(event) ?? []) result = await handler(payload, context) ?? result;
      return result;
    };
    globalThis[spawnKey] = () => {
      const child = new EventEmitter();
      child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
      child.stdin = new EventEmitter();
      child.stdin.end = (payload) => queueMicrotask(() => {
        const request = JSON.parse(payload);
        requests.push(request);
        child.stdout.emit('data', Buffer.from(JSON.stringify(replies[request.action] ?? empty())));
        child.emit('close', 0);
      });
      child.kill = () => child.emit('close', 1);
      return child;
    };
    try {
      await symlink(join(root, 'node_modules'), join(directory, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
      const entry = join(directory, 'adapter.mjs');
      await build({
        entryPoints: [join(root, 'src/luminary_memory/integrations/assets', agent, 'luminary.ts')],
        outfile: entry, bundle: true, platform: 'node', format: 'esm', target: 'node22',
        external: ['@opencode/*', 'effect', 'effect/*'],
        plugins: [{ name: 'native-boundaries', setup(builder) {
          builder.onResolve({ filter: /^node:child_process$/ }, () => ({ path: 'process', namespace: 'boundary' }));
          builder.onResolve({ filter: /^@(earendil-works|oh-my-pi)\/pi-tui$/ }, () => ({ path: 'drawing', namespace: 'boundary' }));
          builder.onLoad({ filter: /.*/, namespace: 'boundary' }, ({ path }) => ({ contents: path === 'process'
            ? `export const spawn = globalThis[${JSON.stringify(spawnKey)}];`
            : "export function matchesKey(){throw Error('Unexpected native drawing')} export function truncateToWidth(){throw Error('Unexpected native drawing')}" }));
        }}],
      });
      const { default: plugin } = await import(pathToFileURL(entry).href);
      const context = { mode: 'rpc', hasUI: false, cwd: directory,
        sessionManager: { getSessionId: () => 'native-context-session' } };
      plugin({ zod: z, on: register, registerCommand() {}, registerTool() {}, sendMessage() {
        throw Error('Automatic memory must not append a persistent message');
      } });

      const system = [{ type: 'text', text: 'Real system authority' }];
      const originalSystem = structuredClone(system);
      const host = { id: 'host-note', role: 'user', content: [{ type: 'text', text: 'Unrelated host message' }] };
      const live = () => ({ id: 'live-user', role: 'user', content: [{ type: 'text', text: 'Current native user task' }], timestamp: 1 });
      const textOf = (message) => typeof message.content === 'string'
        ? message.content : message.content.map(part => part.text ?? '').join('');
      const luminary = (messages) => messages.filter(message => message.role === 'custom' &&
        (message.customType === 'luminary_core' || message.customType === 'luminary_recall'));
      const run = async (messages) => {
        const start = await fire('before_agent_start', { prompt: 'Current native user task', systemPrompt: 'Real system authority' }, context);
        assert.equal(start?.message, undefined, 'Automatic memory must be request-local, not a transcript entry');
        assert.equal(start?.systemPrompt, undefined, 'Memory must never replace system authority');
        const event = { type: 'context', sessionID: 'native-context-session', system, messages };
        const changed = await fire('context', event, context);
        assert.deepEqual(system, originalSystem, 'Stored text must never change system authority');
        return changed?.messages ?? event.messages;
      };

      const coreContext = '<luminary-core-memory>\nCall the user Captain\n</luminary-core-memory>';
      const recallContext = 'Luminary recalled data\n[{"id":2,"content":"staging"}]';
      replies = {
        core: { ...empty(), status: 'ok', reason: '', context: coreContext },
        recall: { ...empty(), status: 'ok', reason: '', context: recallContext, memories: [{ id: 2, content: 'staging' }] },
      };
      const first = await run([host, live()]);
      const firstCore = first.filter(message => message.customType === 'luminary_core');
      const firstRecall = first.filter(message => message.customType === 'luminary_recall');
      assert.equal(firstCore.length, 1, 'One core baseline message');
      assert.equal(firstRecall.length, 1, 'One recall reference message');
      assert.equal(textOf(firstCore[0]), coreContext, 'Core context is attached unchanged, not re-encoded');
      assert.equal(textOf(firstRecall[0]), recallContext, 'Recall context is attached unchanged, not re-encoded');
      assert.ok(first.includes(host), 'Unrelated host messages are preserved');
      assert.equal(first.at(-1).id, 'live-user', 'The live user message stays last');
      assert.ok(!first.some(message => textOf(message).includes('\\n[{\\"id\\"')), 'No double-encoded JSON');
      assert.equal(requests.filter(request => request.action === 'core').length, 1);
      assert.equal(requests.filter(request => request.action === 'recall').length, 1);
      assert.equal(requests.find(request => request.action === 'core').query, undefined, 'Core takes no query');

      replies.core = { ...empty(), status: 'ok', reason: '',
        context: '<luminary-core-memory>\nCall the user Commander\n</luminary-core-memory>' };
      const second = await run(first);
      const secondCore = second.filter(message => message.customType === 'luminary_core');
      assert.equal(secondCore.length, 1, 'A refreshed baseline replaces the previous one');
      assert.ok(!second.some(message => textOf(message).includes('Captain')), 'The stale baseline is removed');
      assert.ok(second.some(message => textOf(message).includes('Commander')), 'The fresh baseline is present');
      assert.equal(requests.filter(request => request.action === 'core').length, 2, 'Core is fetched afresh each turn');
      assert.ok(second.includes(host), 'Unrelated host messages survive a refresh');
      assert.equal(second.at(-1).id, 'live-user');
      assert.equal(luminary(second).length, 2, 'No duplicate Luminary request messages');

      replies = { core: { ...empty(), status: 'ok', reason: '', context: '' }, recall: empty() };
      const third = await run(second);
      assert.deepEqual(third, [host, live()], 'Empty core and abstained recall remove all Luminary messages');

      replies = {
        core: { ok: false, status: 'error', reason: 'unavailable', message: 'Core unavailable.', context: '', memories: [], stored: 0, deleted: 0 },
        recall: { ...empty(), status: 'ok', reason: '', context: recallContext, memories: [{ id: 2 }] },
      };
      const fourth = await run(third);
      assert.equal(fourth.filter(message => message.customType === 'luminary_core').length, 0, 'Core failure adds no baseline');
      assert.equal(fourth.filter(message => message.customType === 'luminary_recall').length, 1, 'Core failure does not block valid recall');
      assert.equal(textOf(fourth.find(message => message.customType === 'luminary_recall')), recallContext);

      replies = {
        core: { ...empty(), status: 'ok', reason: '', context: coreContext },
        recall: { ok: false, status: 'error', reason: 'unavailable', message: 'Recall unavailable.', context: '', memories: [], stored: 0, deleted: 0 },
      };
      const fifth = await run(fourth);
      assert.equal(fifth.filter(message => message.customType === 'luminary_core').length, 1, 'Core still attaches when recall fails');
      assert.equal(fifth.filter(message => message.customType === 'luminary_recall').length, 0, 'Failed recall adds no reference');
      assert.ok(!fifth.some(message => textOf(message).includes('Recall unavailable')), 'No fallback status payload reaches the model');
      assert.ok(!fifth.some(message => textOf(message).includes('"status":"error"')), 'No serialized error reply reaches the model');

      replies = {
        core: { ...empty(), status: 'ok', reason: '', context: coreContext },
        recall: { ...empty(), status: 'abstain', reason: 'no_supported_candidate', context: '' },
      };
      const sixth = await run(fifth);
      assert.equal(sixth.filter(message => message.customType === 'luminary_core').length, 1, 'Core still attaches when recall abstains');
      assert.equal(sixth.filter(message => message.customType === 'luminary_recall').length, 0, 'Abstained recall adds no reference');
      assert.equal(luminary(sixth).length, 1, 'No duplicate Luminary request messages');

      const beforeCustom = requests.length;
      const customStart = await fire('before_agent_start', agent === 'pi'
        ? { systemPrompt: 'Real system authority' } : { prompt: '', systemPrompt: 'Real system authority' }, context);
      assert.equal(customStart?.message, undefined);
      const custom = await fire('context', { type: 'context', sessionID: 'native-context-session', system, messages: sixth }, context);
      assert.deepEqual(custom?.messages ?? sixth, [host, live()], 'Custom-triggered runs add no memory payload');
      assert.equal(requests.length, beforeCustom, 'Custom-triggered runs do not fetch memory');

      await fire('before_agent_start', { prompt: 'Current native user task', systemPrompt: 'Real system authority' }, context);
      await fire('turn_end', { message: { role: 'assistant', stopReason: 'aborted', content: [] } }, context);
      const cancelled = await fire('context', { type: 'context', sessionID: 'native-context-session', system, messages: sixth }, context);
      assert.deepEqual(cancelled?.messages ?? sixth, [host, live()], 'Cancellation produces no memory payload');
    } finally {
      await cleanup?.();
      delete globalThis[spawnKey];
      await rm(directory, { recursive: true, force: true });
    }
  });
}
