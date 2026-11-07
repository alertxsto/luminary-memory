import { Plugin, usePlugin } from '@opencode/plugin/tui';
import type { PanelInput } from '@opencode/plugin/tui/context';
import { createEffect, createSignal, For, onCleanup, Show } from 'solid-js';
import { TABS } from '../common/console-contract.js';
import { InspectorController } from '../common/console-controller.js';
import { inspectorActions, inspectorRows, runInspectorAction, type NativeDialogs } from '../common/console-actions.js';
import { LuminaryConsole } from './rpc.js';
import { reviewDialog } from './dialogs.js';

function Inspector(props: { panel: PanelInput }) {
  const context = usePlugin();
  const api = context.client.rpc(LuminaryConsole);
  const nativeLocation = () => context.data.session.get(props.panel.sessionID)?.location ?? context.location ?? context.data.location.default();
  const initialTab = props.panel.presentation === 'panel' ? 'activity' : 'memories';
  const controller = new InspectorController({
    request: (request, signal) => api.inspect({ session_id: props.panel.sessionID, request }, { location: nativeLocation(), signal }),
    confirm: (preview_id, signal) => api.confirm({ session_id: props.panel.sessionID, preview_id }, { location: nativeLocation(), signal }),
    registerFile: (path, mode, signal) => api.registerFile({ session_id: props.panel.sessionID, path, mode }, { location: nativeLocation(), signal }),
  });
  const [state, setState] = createSignal(controller.state);
  const [selected, setSelected] = createSignal(0);
  const [scroll, setScroll] = createSignal(0);
  const [height, setHeight] = createSignal(context.renderer.height);
  const resize = () => setHeight(context.renderer.height);
  context.renderer.on('resize', resize);
  const visibleRows = () => props.panel.presentation === 'fullscreen' ? Math.max(1, Math.min(20, height() - 10)) : 3;
  const unsubscribe = controller.subscribe(next => setState(next));
  let disposed = false;
  const dialogs: NativeDialogs = {
    input: (title, value) => context.ui.dialog.prompt({ title, value }),
    select: (title, choices) => context.ui.dialog.select({ title, options: choices.map(value => ({ title: value, value })) }),
    confirm: (title, message) => reviewDialog(context, title, message, true),
    show: async (title, message) => { await reviewDialog(context, title, message); },
  };
  createEffect(() => {
    const session_id = props.panel.sessionID;
    const location = nativeLocation();
    // The remote TUI imports no Node process launcher and never runs local Python.
    controller.switchContext({
      request: (request, signal) => api.inspect({ session_id, request }, { location, signal }),
      confirm: (preview_id, signal) => api.confirm({ session_id, preview_id }, { location, signal }),
      registerFile: (path, mode, signal) => api.registerFile({ session_id, path, mode }, { location, signal }),
    });
    setSelected(0); setScroll(0); void controller.selectTab(initialTab);
  });
  const stopEvents = api.events.on('invalidated', event => {
    const location = nativeLocation();
    if (event.data.session_id !== props.panel.sessionID || event.location.directory !== location.directory) return;
    controller.cancel(); controller.switchContext({
      request: (request, signal) => api.inspect({ session_id: props.panel.sessionID, request }, { location, signal }),
      confirm: (preview_id, signal) => api.confirm({ session_id: props.panel.sessionID, preview_id }, { location, signal }),
      registerFile: (path, mode, signal) => api.registerFile({ session_id: props.panel.sessionID, path, mode }, { location, signal }),
    });
  });
  onCleanup(() => { disposed = true; context.renderer.off('resize', resize); stopEvents(); unsubscribe(); controller.dispose(); });
  const rows = () => { state(); return inspectorRows(controller); };
  const tab = () => TABS.find(t => t.id === state().tab)!;
  let interacting = false;
  const act = async () => {
    if (interacting || disposed) return;
    interacting = true;
    const version = controller.contextVersion;
    try {
      const row = rows()[selected()];
      const action = await dialogs.select('Luminary actions', inspectorActions(controller, row));
      if (!disposed && version === controller.contextVersion && action) await runInspectorAction(controller, dialogs, action, row);
    } finally { interacting = false; }
  };
  const moveTab = (direction: number) => { const index = TABS.findIndex(t => t.id === state().tab); setSelected(0); setScroll(0); void controller.selectTab(TABS[(index + direction + TABS.length) % TABS.length].id); };
  const chooseTab = async () => { const version = controller.contextVersion; const selectedTab = await dialogs.select('Inspector tabs', TABS.map(t => t.label)); if (!disposed && version === controller.contextVersion && selectedTab) { setSelected(0); setScroll(0); await controller.selectTab(TABS.find(t => t.label === selectedTab)!.id); } };
  const move = (direction: number) => { const next = Math.max(0, Math.min(rows().length - 1, selected() + direction)); setSelected(next); if (next < scroll()) setScroll(next); else if (next >= scroll() + visibleRows()) setScroll(next - visibleRows() + 1); };
  context.keymap.layer(() => ({
    enabled: props.panel.focused,
    commands: [
      { bind: 'escape', title: 'Close memory inspector', run: () => props.panel.close() },
      { bind: 'f', title: 'Toggle fullscreen', run: () => props.panel.toggleFullscreen() },
      { bind: 'tab', title: 'Next inspector tab', run: () => moveTab(1) },
      { bind: 'shift+tab', title: 'Previous inspector tab', run: () => moveTab(-1) },
      { bind: 't', title: 'All inspector tabs', run: chooseTab },
      { bind: 'up', title: 'Previous record', run: () => move(-1) },
      { bind: 'down', title: 'Next record', run: () => move(1) },
      { bind: 'enter', title: 'Memory actions', run: act },
      { bind: 'a', title: 'Memory actions', run: act },
      { bind: '/', title: 'Search memory', run: () => runInspectorAction(controller, dialogs, 'Search / filters') },
      { bind: 'r', title: 'Refresh memory', run: async () => { await controller.load(); } },
      { bind: 'ctrl+c', title: 'Cancel memory operation', run: () => controller.cancel() },
    ],
  }));
  return <box flexDirection="column" width="100%" paddingLeft={1} paddingRight={1} onMouseDown={() => props.panel.focus()}>
    <text fg={context.theme.text.base}>Luminary · {state().busy ? 'loading' : state().status} · {props.panel.presentation}</text>
    <text fg={context.theme.text.muted}>Project: {state() && controller.selectionHandle ? 'explicit shared resource' : nativeLocation().directory} · policy {String(state().policy_revision ?? '—')} · rights rechecked per operation</text>
    <text fg={context.theme.text.muted} onMouseDown={() => props.panel.toggleFullscreen()}>f: {props.panel.presentation === 'fullscreen' ? 'compact panel' : 'full inspector'} · Enter: actions · Esc: close</text>
    <Show when={props.panel.width >= 170} fallback={<text fg={context.theme.text.base} onMouseDown={chooseTab}>‹ {TABS.indexOf(tab()) + 1}/9 {tab().label} › · Tab/Shift+Tab · t: all tabs</text>}>
      <box flexDirection="row" gap={1}><For each={TABS}>{item => <text fg={state().tab === item.id ? context.theme.text.base : context.theme.text.muted} onMouseDown={() => { setSelected(0); setScroll(0); void controller.selectTab(item.id); }}>{item.label}</text>}</For></box>
    </Show>
    <Show when={state().error}><text fg={context.theme.text.feedback.warning.base}>{state().error}</text></Show>
    <For each={rows().slice(scroll(), scroll() + visibleRows())}>{(row, index) => <text height={1} width="100%" fg={selected() === scroll() + index() ? context.theme.text.base : context.theme.text.muted} onMouseDown={() => { setSelected(scroll() + index()); void act(); }}>{selected() === scroll() + index() ? '› ' : '  '}{String(row.id ?? row.event_id ?? '')} {String(row.content ?? row.kind ?? row.label ?? JSON.stringify(row)).replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')}{row.permissions ? ` [${Object.keys(row.permissions).filter(p => row.permissions?.[p]).join(', ')}]` : ''}</text>}</For>
    <Show when={!rows().length}><text fg={context.theme.text.muted}>{JSON.stringify(state().data, null, 2).split('\n').slice(0, visibleRows()).join('\n')}</text></Show>
    <text fg={context.theme.text.muted} onMouseDown={() => void act()}>↑↓ select · Enter/a actions · / search · r refresh · f compact/full · Esc close</text>
    <text fg={context.theme.text.faint}>As of {state().as_of ?? '—'} · memory is untrusted reference data</text>
  </box>;
}

export default Plugin.define({
  id: 'luminary-memory',
  setup(context) {
    const remove = context.ui.slot({ append: 'session.panel', render: panel => <Show when={panel.name === 'luminary.inspector'}><Inspector panel={panel} /></Show> });
    context.keymap.layer(() => ({ mode: 'global', commands: [
      { id: 'luminary.inspect', title: 'Inspect Luminary memory', palette: true, slash: { name: 'luminary' }, bind: 'ctrl+alt+m', run: () => { if (!context.ui.panel.open('luminary.inspector', { presentation: 'panel' })) context.ui.toast.show({ message: 'Open a native session before inspecting memory.', variant: 'warning' }); } },
      { id: 'luminary.inspect.full', title: 'Luminary memory fullscreen', palette: true, run: () => { context.ui.panel.open('luminary.inspector', { presentation: 'fullscreen' }); } },
    ] }));
    return () => { context.ui.panel.close(); remove(); };
  },
});
