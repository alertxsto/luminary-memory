import { resolve } from 'node:path';
import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent';
import { matchesKey, truncateToWidth } from '@earendil-works/pi-tui';
import { TABS } from '../common/console-contract.js';
import { InspectorController } from '../common/console-controller.js';
import { createInspectorTransport } from '../common/inspector-transport.js';
import { inspectorActions, inspectorRows, runInspectorAction, type NativeDialogs } from '../common/console-actions.js';
import { TerminalInspectorView, type InspectorIntent } from '../common/terminal-view.js';

export function registerPiInspector(pi: ExtensionAPI) {
  let controller: InspectorController | undefined;
  let close: (() => void) | undefined;
  let session: string | undefined;
  let clearWidget: (() => void) | undefined;
  const dispose = () => { close?.(); close = undefined; clearWidget?.(); clearWidget = undefined; controller?.dispose(); controller = undefined; session = undefined; };
  pi.on('session_shutdown', dispose);
  pi.on('session_start', (_event, ctx) => { dispose(); if (ctx.mode === 'tui') ctx.ui.setWidget('luminary-inspector', undefined); });
  return async (ctx: ExtensionContext, presentation = 'full') => {
    if (presentation === 'close') { if (ctx.mode === 'tui') ctx.ui.setWidget('luminary-inspector', undefined); dispose(); return; }
    const id = `${ctx.sessionManager.getSessionId()}\0${resolve(ctx.cwd)}`;
    if (session !== id) { dispose(); session = id; controller = new InspectorController(createInspectorTransport({ agent: 'pi', session_id: ctx.sessionManager.getSessionId(), workspace: resolve(ctx.cwd) })); }
    const view = controller!; const live = () => controller === view && session === id;
    const dialogs: NativeDialogs = {
      input: (title, value) => value !== undefined && ctx.mode === 'tui' ? ctx.ui.editor(title, value) : ctx.ui.input(title, value),
      select: (title, choices) => ctx.ui.select(title, choices),
      confirm: (title, message) => ctx.ui.confirm(title, message),
      show: async (title, message) => { if (ctx.mode === 'tui') await ctx.ui.editor(`${title} · read-only preview; edits are discarded`, message); else await ctx.ui.select(`${title}\n${message}`, ['Back']); },
    };
    await view.load(); if (!live()) return;
    if (ctx.mode !== 'tui') {
      if (ctx.mode !== 'rpc') { pi.sendMessage({ customType: 'luminary_inspector', content: JSON.stringify(view.state), display: true, details: view.state }, { triggerTurn: false }); return; }
      while (live()) {
        const tab = await dialogs.select('Luminary inspector · select tab', [...TABS.map(t => t.label), 'Close']); if (!tab || tab === 'Close' || !live()) return;
        await view.selectTab(TABS.find(t => t.label === tab)!.id); if (!live()) return;
        await dialogs.show(tab, JSON.stringify(view.state.data, null, 2));
        const rows = inspectorRows(view); const rowLabel = rows.length ? await dialogs.select('Record', rows.map((r, i) => `${i + 1}. ${r.id ?? ''} ${r.content ?? r.kind ?? ''}`.replace(/[\u0000-\u001f\u007f-\u009f]/g, ' '))) : undefined;
        const row = rowLabel ? rows[Number(rowLabel.split('.')[0]) - 1] : undefined;
        const action = await dialogs.select('Actions', inspectorActions(view, row)); if (action && live()) await runInspectorAction(view, dialogs, action, row);
      }
      return;
    }
    const compact = async () => {
      await view.selectTab('activity'); if (!live()) return;
      clearWidget?.();
      let unsubscribe: (() => void) | undefined;
      ctx.ui.setWidget('luminary-inspector', (tui, theme) => {
        unsubscribe = view.subscribe(() => tui.requestRender());
        return {
          render: width => [`Luminary · Activity · ${view.state.status} · ${view.selectionHandle ? 'shared selection' : resolve(ctx.cwd)}`, `Session ${ctx.sessionManager.getSessionId()} · policy ${view.state.policy_revision ?? '—'} · rights rechecked on every operation`, view.state.error ?? view.state.as_of ?? '', ...inspectorRows(view).slice(0, 3).map(r => `${r.created_at ?? ''} ${r.kind ?? ''} ${r.source ?? r.memory_id ?? ''}`), '/luminary full: all tabs, per-record permissions and actions · /luminary close'].map(line => truncateToWidth(theme.fg('muted', line.replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')), width)),
          invalidate() {},
          dispose: () => unsubscribe?.(),
        };
      });
      clearWidget = () => { unsubscribe?.(); ctx.ui.setWidget('luminary-inspector', undefined); };
    };
    if (presentation === 'compact') { await compact(); return; }
    clearWidget?.(); clearWidget = undefined;
    ctx.ui.setWidget('luminary-inspector', undefined);
    while (live()) {
      const intent = await ctx.ui.custom<InspectorIntent>((tui, theme, _keys, done) => {
        close = () => done({ type: 'close' });
        const component = new TerminalInspectorView(view, matchesKey, truncateToWidth, (role, text) => theme.fg(role as 'accent' | 'muted' | 'warning', text), done, () => tui.requestRender(), () => tui.terminal.rows);
        const unsubscribe = view.subscribe(() => tui.requestRender());
        return { render: width => component.render(width), handleInput: data => component.handleInput(data), handleMouse: event => component.handleMouse(event), invalidate: () => component.invalidate(), dispose: unsubscribe };
      });
      close = undefined; if (!live() || intent.type === 'close') { if (live()) dispose(); return; }
      if (intent.type === 'compact') { await compact(); return; }
      if (intent.type === 'refresh') await view.load();
      else if (intent.type === 'search') await runInspectorAction(view, dialogs, 'Search / filters');
      else if (intent.type === 'tabs') { const tab = await dialogs.select('Inspector tabs', TABS.map(t => t.label)); if (tab && live()) await view.selectTab(TABS.find(t => t.label === tab)!.id); }
      else { const action = await dialogs.select('Luminary actions', inspectorActions(view, intent.row)); if (action && live()) await runInspectorAction(view, dialogs, action, intent.row); }
    }
  };
}
