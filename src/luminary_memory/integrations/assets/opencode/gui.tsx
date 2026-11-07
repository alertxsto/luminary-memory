import { Command, MenuItem, Panel, Plugin, SettingsPage, type Context, type DialogHandle, type MountedSession } from '@opencode/plugin/gui';
import { createEffect, createMemo, createSignal, For, onCleanup, Show, untrack } from 'solid-js';
import type { OpenCodeClient } from '@opencode/client/promise';
import { TABS, type ConsoleTransport } from '../common/console-contract.js';
import { InspectorController } from '../common/console-controller.js';
import { inspectorActions, inspectorRows, runInspectorAction, type InspectorRow, type NativeDialogs } from '../common/console-actions.js';
import { LuminaryConsole } from './rpc.js';

const flow = { display: 'flex', 'flex-wrap': 'wrap', gap: '8px', 'align-items': 'center' } as const;
const box = { border: '1px solid var(--border-base)', 'border-radius': '8px', padding: '12px', 'overflow-wrap': 'anywhere' } as const;
const kinds: Record<string, string> = { ingest: 'Memory saved', supersede: 'Memory corrected', retract: 'Memory retracted', inspector_import: 'Records imported', inspector_export: 'Records exported', native_recall: 'Recall activity', hermes_operation: 'Hermes activity' };

function Inspector(props: { ctx: Context; session: MountedSession; compact?: boolean; expand?: () => void }) {
  const ctx = props.ctx;
  const controller = new InspectorController({ request: async () => { throw new Error('Native session unavailable'); } });
  const [state, setState] = createSignal(controller.state);
  const [selected, setSelected] = createSignal<InspectorRow>();
  const [compact, setCompact] = createSignal(props.compact === true);
  const initialTab = props.compact ? 'activity' : 'memories';
  const pending = new Set<() => void>();
  const unsubscribe = controller.subscribe(value => setState(value));
  const closeDialogs = () => { for (const close of pending) close(); };

  function ask<T>(title: string, message: string | undefined, initial: string | undefined, choices: string[] | undefined, accepted: T, cancelled: T): Promise<T | string> {
    const { promise, resolve } = Promise.withResolvers<T | string>();
    let done = false;
    let handle: DialogHandle | undefined;
    const cancel = () => finish(cancelled);
    const finish = (value: T | string) => { if (done) return; done = true; pending.delete(cancel); handle?.close(); resolve(value); };
    pending.add(cancel);
    handle = ctx.dialogs.open(() => {
      const [value, setValue] = createSignal(initial ?? choices?.[0] ?? '');
      onCleanup(cancel);
      return <ctx.ui.Dialog title={title} size={initial !== undefined || message?.includes('\n') ? 'large' : 'fit'}
        footer={<><Show when={accepted !== cancelled}><ctx.ui.Button onClick={cancel}>Cancel</ctx.ui.Button></Show><ctx.ui.Button variant="contrast" onClick={() => finish(initial !== undefined || choices ? value() : accepted)}>{accepted === cancelled ? 'Close' : cancelled === false ? 'Confirm' : 'Continue'}</ctx.ui.Button></>}>
        <Show when={message}><pre style={{ 'white-space': 'pre-wrap', 'overflow-wrap': 'anywhere' }}>{message}</pre></Show>
        <Show when={initial !== undefined}><textarea aria-label={title} value={value()} onInput={event => setValue(event.currentTarget.value)} rows={6} autofocus style={{ width: '100%', ...box }} /></Show>
        <Show when={choices}><select aria-label={title} value={value()} onChange={event => setValue(event.currentTarget.value)} style={{ width: '100%', ...box }}><For each={choices}>{choice => <option value={choice}>{choice}</option>}</For></select></Show>
      </ctx.ui.Dialog>;
    });
    return promise;
  }
  const dialogs: NativeDialogs = {
    input: async (title, value) => { const result = await ask(title, undefined, value ?? '', undefined, true, undefined); return typeof result === 'string' ? result : undefined; },
    select: async (title, choices) => { const result = await ask(title, undefined, undefined, choices, true, undefined); return typeof result === 'string' ? result : undefined; },
    confirm: async (title, message) => await ask(title, message, undefined, undefined, true, false) === true,
    show: async (title, message) => { await ask(title, message, undefined, undefined, true, true); },
  };
  let bound: { key: string; client: OpenCodeClient; directory?: string; visit: object; connected: boolean } | undefined;
  let stopEvents: (() => void) | undefined;

  createEffect(() => {
    const session = props.session;
    const client = session.server.client;
    const directory = session.location?.directory;
    const sessionID = session.id;
    const visit = session.visit;
    const connected = session.server.connected;
    if (bound?.key === session.key && bound.client === client && bound.directory === directory &&
        bound.visit === visit && bound.connected === connected) return;
    stopEvents?.();
    bound = { key: session.key, client, directory, visit, connected };
    const location = directory ? { directory } : undefined;
    closeDialogs(); setSelected(undefined);
    const api = client.rpc(LuminaryConsole);
    const transport: ConsoleTransport = {
      request: (request, signal) => {
        if (!location || !connected) return Promise.reject(new Error('Native session location unavailable'));
        return api.inspect({ session_id: sessionID, request }, { location, signal });
      },
      confirm: (preview_id, signal) => {
        if (!location || !connected) return Promise.reject(new Error('Native session location unavailable'));
        return api.confirm({ session_id: sessionID, preview_id }, { location, signal });
      },
      registerFile: (path, mode, signal) => {
        if (!location || !connected) return Promise.reject(new Error('Native session location unavailable'));
        return api.registerFile({ session_id: sessionID, path, mode }, { location, signal });
      },
    };
    controller.switchContext(transport);
    stopEvents = api.events.on('invalidated', event => {
      if (event.data.session_id !== sessionID || !location || event.location.directory !== location.directory) return;
      closeDialogs(); setSelected(undefined); controller.switchContext(transport);
    });
    untrack(() => { void controller.selectTab(initialTab); });
  });
  onCleanup(() => { stopEvents?.(); closeDialogs(); unsubscribe(); controller.dispose(); });
  const rows = () => { state(); return inspectorRows(controller); };
  const actions = createMemo(() => { state(); return inspectorActions(controller, selected()).filter(name => name !== 'Refresh' && name !== 'View projection'); });
  let interacting = false;
  async function action(name: string, row?: InspectorRow) {
    if (interacting) return;
    interacting = true;
    const epoch = controller.contextVersion;
    try {
      let nativeDialogs = dialogs;
      if ((name === 'Import records' || name === 'Export records') && props.session.server.builtin && ctx.desktop) {
        const importing = name === 'Import records';
        const [path] = await ctx.desktop.pick({ title: importing ? 'Import memory records' : 'Choose folder for luminary-memories.json', directory: !importing, extensions: importing ? ['json'] : undefined });
        if (!path || !controller.activeContext || controller.contextVersion !== epoch) return;
        const separator = path.includes('\\') ? '\\' : '/';
        const selectedPath = importing ? path : path.replace(/[\\/]$/, '') + separator + 'luminary-memories.json';
        nativeDialogs = { ...dialogs, input: async () => selectedPath };
      } else if (name === 'Import records' || name === 'Export records') {
        nativeDialogs = { ...dialogs, input: title => dialogs.input(`${title} on server ${props.session.server.name}; no local file picker is used`) };
      }
      if (controller.activeContext && controller.contextVersion === epoch) await runInspectorAction(controller, nativeDialogs, name, row);
    } catch { if (controller.activeContext && controller.contextVersion === epoch) await dialogs.show('Inspector unavailable', 'No successful change is claimed. Refresh Activity before retrying a change.'); }
    finally { interacting = false; }
  }
  function tabKey(event: KeyboardEvent) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = TABS.findIndex(tab => tab.id === state().tab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length;
    setSelected(undefined); void controller.selectTab(TABS[next].id);
    (event.currentTarget as HTMLElement).querySelector<HTMLButtonElement>(`[data-tab="${TABS[next].id}"]`)?.focus();
  }
  return <section aria-label="Luminary memory inspector" style={{ display: 'flex', 'flex-direction': 'column', gap: '12px', padding: '12px', 'overflow-y': 'auto', 'min-width': '0', height: '100%', 'font-size': '14px', 'white-space': 'normal', 'overflow-wrap': 'anywhere' }}>
    <header style={flow}><strong>Luminary Memory</strong><span role="status">{state().busy ? 'Loading' : state().status}</span>
      <ctx.ui.Button size="small" onClick={() => { if (props.expand && compact()) props.expand(); else { setCompact(!compact()); void controller.selectTab(compact() ? 'activity' : 'memories'); } }}>{compact() ? 'Full inspector' : 'Compact Activity'}</ctx.ui.Button>
      <ctx.ui.Button size="small" onClick={() => void controller.load()} disabled={state().busy}>Refresh</ctx.ui.Button>
    </header>
    <small>{props.session.server.name} · {props.session.location?.directory ?? 'Location unavailable'} · {state() && controller.selectionHandle ? 'Explicit shared project' : 'Own native project'} · policy {state().policy_revision ?? '—'}</small>
    <Show when={state().error}><p role="alert">{state().error}</p></Show>
    <Show when={state().data.gap === true}><p role="alert">Activity history is incomplete. Refresh to load a new snapshot.</p></Show>
    <Show when={state().data.replayed === true && !state().data.gap}><p>{rows().length ? 'Showing new activity only.' : 'No new activity since the checkpoint.'} Refresh loads recent history.</p></Show>
    <Show when={!compact()}>
      <nav role="tablist" aria-label="Memory views" onKeyDown={tabKey} style={flow}><For each={TABS}>{tab => <button type="button" data-tab={tab.id} role="tab" aria-selected={state().tab === tab.id} tabIndex={state().tab === tab.id ? 0 : -1} style={{ ...box, padding: '6px 10px', 'font-weight': state().tab === tab.id ? '700' : '400' }} onClick={() => { setSelected(undefined); void controller.selectTab(tab.id); }}>{tab.label}</button>}</For></nav>
      <div aria-label="Inspector actions" style={flow}><For each={actions()}>{name => <ctx.ui.Button size="small" disabled={state().busy} onClick={() => void action(name, selected())}>{name}</ctx.ui.Button>}</For></div>
    </Show>
    <Show when={state().tab === 'summary' && state().data.totals}><div aria-label="Authorized lifecycle totals" style={flow}><For each={Object.entries(state().data.totals as Record<string, number> ?? {})}>{([label, count]) => <div style={box}><strong style={{ 'font-size': '24px', display: 'block' }}>{count}</strong>{label}</div>}</For></div><small>{String(state().data.count_basis ?? '')}</small></Show>
    <Show when={state().tab === 'summary' && state().data.time_range}><section style={box} aria-label="Stored timestamp bounds (UTC)"><h3>Stored timestamp bounds (UTC)</h3><dl><For each={Object.entries(state().data.time_range as Record<string, unknown> ?? {})}>{([name, value]) => <><dt>{name.replaceAll('_', ' ')}</dt><dd>{value === null ? 'Not available' : String(value)}</dd></>}</For></dl></section></Show>
    <Show when={state().tab === 'settings'}><For each={['values', 'secret_presence', 'readiness']}>{key => <Show when={state().data[key]}><details open={key === 'values'} style={box}><summary>{key.replaceAll('_', ' ')}</summary><dl><For each={Object.entries(state().data[key] as Record<string, unknown> ?? {})}>{([name, value]) => <><dt>{name.replaceAll('_', ' ')}</dt><dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd></>}</For></dl></details></Show>}</For></Show>
    <Show when={state().tab === 'sharing'}><p>Sharing is explicit. Read, contribute, edit and retract are independent rights. Matching paths grant nothing.</p></Show>
    <Show when={state().tab === 'relations'}><p>{String(state().data.label ?? 'Authorized co-occurrence adjacency, not proof of causation.')}</p></Show>
    <Show when={state().tab === 'transfer'}><p>Memory-record transfer is not a full backup. File content and overwrite effects require preview and owner confirmation.</p></Show>
    <Show when={state().data.audit === 'committed'}><article style={box} aria-label="Operation receipt">
      <h3>Confirmed operation committed</h3>
      <Show when={typeof state().data.stored === 'number'}><p>{String(state().data.stored)} saved · {String(state().data.duplicates ?? 0)} duplicates skipped.</p></Show>
      <Show when={typeof state().data.memory_id === 'number'}><p>Memory #{String(state().data.memory_id)} · revision {String(state().data.revision ?? '—')}</p><ctx.ui.Button size="small" onClick={() => void controller.detail(state().data.memory_id as number)}>Inspect memory</ctx.ui.Button></Show>
      <Show when={state().data.coverage}><p>{String(state().data.coverage)}</p></Show>
      <Show when={state().data.file_handle}><p>Export prepared for the confirmed native destination.</p></Show>
    </article></Show>
    <For each={compact() ? rows().slice(0, 3) : rows()}>{row => <article style={box}>
      <h3>{row.event_id !== undefined ? kinds[String(row.kind)] ?? String(row.kind) : row.id !== undefined ? `Memory #${row.id}` : String(row.label ?? row.kind ?? 'Record')}</h3>
      <Show when={row.content}><p style={{ 'white-space': 'pre-wrap' }}>{String(row.content)}</p></Show>
      <Show when={row.event_id !== undefined}><small>Event #{String(row.event_id)} · memory #{String(row.memory_id ?? '—')} · {String(row.created_at ?? '')}</small></Show>
      <Show when={row.operation as Record<string, unknown> | undefined}>{operation => <>
        <p>{String(operation().summary)}</p>
        <small>Source {String(row.source ?? 'unknown')} · session {String(operation().session_id ?? 'unknown')} · operation {String(operation().id)}</small>
      </>}</Show>
      <Show when={row.id !== undefined}><small>{String(row.status ?? '')} · revision {String(row.revision ?? '—')} · allowed: {Object.keys(row.permissions ?? {}).filter(key => row.permissions?.[key]).join(', ')}</small></Show>
      <Show when={row.source && row.target}><p>{String(row.source)} → {String(row.target)} · {String(row.kind ?? 'co-occurrence')}</p></Show>
      <div style={flow}><ctx.ui.Button size="small" onClick={async () => { setSelected(row); const epoch = controller.contextVersion; const selectedAction = await dialogs.select('Record actions', inspectorActions(controller, row)); if (selectedAction && controller.contextVersion === epoch) await action(selectedAction, row); }}>Actions</ctx.ui.Button>
      <Show when={row.id !== undefined}><ctx.ui.Button size="small" onClick={() => void controller.detail(row.id!)}>Inspect</ctx.ui.Button></Show></div>
    </article>}</For>
    <For each={['evidence', 'claims', 'lineage', 'episodes', 'issues']}>{key => <Show when={Array.isArray(state().data[key]) && (state().data[key] as unknown[]).length > 0}><details style={box}><summary>{key}</summary><pre style={{ 'white-space': 'pre-wrap', 'overflow-wrap': 'anywhere' }}>{JSON.stringify(state().data[key], null, 2)}</pre></details></Show>}</For>
    <Show when={typeof state().data.text === 'string'}><article style={box}><h3>AI explanation · untrusted interpretation</h3><p>{String(state().data.text)}</p><small>References: {JSON.stringify(state().data.references)} · {String(state().data.model)} · cost {state().data.cost === null ? 'unknown' : String(state().data.cost)}</small></article></Show>
    <Show when={!rows().length && !state().busy && !state().error && !state().data.audit && !state().data.gap && !state().data.replayed && !['summary', 'settings'].includes(state().tab)}><p>No records in this authorized view.</p></Show>
    <footer style={{ 'white-space': 'normal', 'overflow-wrap': 'anywhere' }}><small>As of {state().as_of ?? '—'}. Read-only inspection does not enable saving or call AI. Memory content is untrusted reference data.</small></footer>
  </section>;
}

export default Plugin.define({
  setup(ctx) {
    const tab = { id: 'memory', title: 'Luminary Memory', tabbable: true };
    const full = (session: MountedSession) => ctx.dialogs.open(dialog => {
      const visit = session.visit;
      createEffect(() => { if (ctx.sessions.current()?.visit !== visit) dialog.close(); });
      return <ctx.ui.Dialog title="Luminary Memory — full inspector" size="x-large"><Inspector ctx={ctx} session={session} /></ctx.ui.Dialog>;
    });
    const open = () => { const session = ctx.sessions.current(); if (session) ctx.layout.open(`${ctx.id}:memory`, session); else ctx.toast.show({ title: 'Open a native session before inspecting memory.' }); };
    ctx.add(Panel, { id: 'memory', region: 'side', wide: true, list: input => input.open.includes('memory') ? [tab] : [], render: props => <Inspector ctx={ctx} session={props.session} compact expand={() => full(props.session)} /> });
    ctx.add(Command, { id: 'inspect', title: 'Inspect Luminary memory', group: 'Luminary', bind: 'mod+alt+m', slash: { name: 'luminary' }, run: open });
    ctx.add(Command, { id: 'inspect-full', title: 'Luminary full memory inspector', group: 'Luminary', run: () => { const session = ctx.sessions.current(); if (session) full(session); } });
    ctx.add(MenuItem, { id: 'memory', menu: 'session.panel', title: 'Luminary Memory', run: open });
    ctx.add(SettingsPage, { id: 'memory', title: 'Luminary Memory', render: () => <section style={{ padding: '16px' }}><h2>Luminary Memory</h2><p>Use the session panel or command palette for authorized memory, sharing and settings. Installing or opening this UI does not enable retention. Backend settings are resolved on the session server, never from a different local database.</p><ctx.ui.Button onClick={open}>Open session inspector</ctx.ui.Button></section> });
  },
});
