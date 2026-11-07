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
    // Each child delivers a complete external bridge response. No forwarding
    // assertions: the observable contract is absence, authority and replacement.
    globalThis[spawnKey] = () => {
      const child = new EventEmitter();
      child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
      child.stdin = new EventEmitter();
      child.stdin.end = () => queueMicrotask(() => {
        child.stdout.emit('data', Buffer.from(JSON.stringify(reply)));
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
