import { TABS } from './console-contract.js';
import { InspectorController } from './console-controller.js';
import { inspectorRows, inspectorRowContent, inspectorSummaryLines, inspectorContextLine, inspectorCanSearch, type InspectorRow } from './console-actions.js';
export type InspectorIntent = { type: 'close' | 'actions' | 'search' | 'refresh' | 'tabs' | 'compact'; row?: InspectorRow };
type InspectorKey = 'escape' | 'ctrl+c' | 'tab' | 'right' | 'shift+tab' | 'left' | 'up' | 'down' | 'pageUp' | 'pageDown' | 'enter';
/** Stateless host drawing helpers; native hosts retain input, themes, focus and sizing. */
export class TerminalInspectorView {
  selected = 0;
  offset = 0;
  private rowStart = 3;
  private rowCount = 0;
  private tabRanges: { start: number; end: number; index: number }[] = [];
  constructor(readonly controller: InspectorController, private key: (data: string, key: InspectorKey) => boolean, private truncate: (text: string, width: number) => string, private color: (role: string, text: string) => string, private finish: (intent: InspectorIntent) => void, private repaint: () => void, private height: () => number) {}
  handleInput(data: string) {
    const rows = inspectorRows(this.controller);
    if (this.key(data, 'escape') || this.key(data, 'ctrl+c')) this.finish({ type: 'close' });
    else if (this.key(data, 'tab') || this.key(data, 'right') || this.key(data, 'shift+tab') || this.key(data, 'left')) { const direction = this.key(data, 'shift+tab') || this.key(data, 'left') ? -1 : 1; const index = TABS.findIndex(t => t.id === this.controller.state.tab); this.selected = 0; this.offset = 0; void this.controller.selectTab(TABS[(index + direction + TABS.length) % TABS.length].id); }
    else if (this.key(data, 'up') || data === 'k') { if (rows.length) this.selected = Math.max(0, this.selected - 1); else this.offset = Math.max(0, this.offset - 1); }
    else if (this.key(data, 'down') || data === 'j') { if (rows.length) this.selected = Math.min(Math.max(0, rows.length - 1), this.selected + 1); else this.offset++; }
    else if (this.key(data, 'pageUp')) { if (rows.length) this.selected = Math.max(0, this.selected - 10); else this.offset = Math.max(0, this.offset - 10); }
    else if (this.key(data, 'pageDown')) { if (rows.length) this.selected = Math.min(Math.max(0, rows.length - 1), this.selected + 10); else this.offset += 10; }
    else if (this.key(data, 'enter') || data === 'a') this.finish({ type: 'actions', row: rows[this.selected] });
    else if (data === '/') this.finish({ type: 'search' });
    else if (data === 'r') this.finish({ type: 'refresh' });
    else if (data === 't') this.finish({ type: 'tabs' });
    else if (data === 'c') this.finish({ type: 'compact' });
    this.repaint();
  }
  /** pi forwards these normalized events only when its native fullscreen routes them. */
  handleMouse(event: { type: string; button: string; x: number; y: number; wheelDelta?: number; clickCount?: number }): { handled: boolean; focus?: boolean } | undefined {
    if (event.type === 'wheel') {
      const rows = inspectorRows(this.controller);
      const delta = event.wheelDelta ?? 0;
      if (rows.length) this.selected = Math.max(0, Math.min(rows.length - 1, this.selected + delta));
      else this.offset = Math.max(0, this.offset + delta);
      this.repaint(); return { handled: true };
    }
    if (event.type !== 'click' || event.button !== 'left') return;
    if (event.y === 1) {
      const tab = this.tabRanges.find(range => event.x >= range.start && event.x < range.end);
      if (tab) { this.selected = 0; this.offset = 0; void this.controller.selectTab(TABS[tab.index].id); }
      else this.finish({ type: 'tabs' });
      return { handled: true, focus: true };
    }
    const index = event.y - this.rowStart;
    if (index < 0 || index >= this.rowCount) return;
    this.selected = this.offset + index;
    if ((event.clickCount ?? 1) > 1) this.finish({ type: 'actions', row: inspectorRows(this.controller)[this.selected] });
    this.repaint(); return { handled: true, focus: true };
  }
  render(width: number): string[] {
    const state = this.controller.state; const tab = TABS.find(t => t.id === state.tab)!; const index = TABS.indexOf(tab);
    const tabs = TABS.map((t, i) => `${i + 1} ${t.label}`).join(' | ');
    this.tabRanges = [];
    if (tabs.length <= width) {
      let column = 0;
      for (const [index, tab] of TABS.entries()) {
        const length = `${index + 1} ${tab.label}`.length;
        this.tabRanges.push({ start: column, end: column + length, index });
        column += length + 3;
      }
    }
    const lines = [this.color('accent', `Luminary · ${tab.label} · ${state.busy ? 'loading' : state.status}`), tabs.length <= width ? tabs : `‹ ${index + 1}/${TABS.length} ${tab.label} ›  Tab/Shift+Tab · t: all tabs`, `Project: ${this.controller.selectionHandle ? 'explicit shared selection' : 'native session project'} · policy ${state.policy_revision ?? '—'} · ${state.as_of ?? ''}`];
    const nativeContext = inspectorContextLine(this.controller);
    if (nativeContext) lines.push(this.color('muted', nativeContext));
    if (state.error) lines.push(this.color('warning', state.error));
    if (state.data.gap === true) lines.push(this.color('warning', 'Activity history is incomplete. Press r to load a new snapshot.'));
    else if (state.data.replayed === true) lines.push(this.color('muted', `${Array.isArray(state.data.items) && state.data.items.length ? 'New activity only.' : 'No new activity.'} r: recent snapshot`));
    lines.push(...inspectorSummaryLines(this.controller));
    const rows = inspectorRows(this.controller); const available = Math.max(1, this.height() - lines.length - 4);
    this.rowStart = lines.length;
    this.rowCount = Math.min(rows.length, available);
    this.selected = Math.min(this.selected, Math.max(0, rows.length - 1));
    if (rows.length) {
      this.offset = Math.max(0, Math.min(this.offset, this.selected)); if (this.selected >= this.offset + available) this.offset = this.selected - available + 1;
      for (const [i, row] of rows.slice(this.offset, this.offset + available).entries()) {
        const text = `${this.offset + i === this.selected ? '›' : ' '} ${row.id ?? row.event_id ?? ''} ${inspectorRowContent(row)} ${row.permissions ? `[${Object.keys(row.permissions).filter(p => row.permissions?.[p]).join(',')}]` : ''}`;
        lines.push(this.offset + i === this.selected ? this.color('accent', text) : text);
      }
    } else if (state.status === 'empty' && state.tab !== 'activity') {
      lines.push('No records in this authorized view.');
    } else if (state.tab !== 'activity') {
      const projectionData = Object.fromEntries(Object.entries(state.data).filter(([key]) =>
        key !== 'native_context' && (state.tab !== 'summary' || !state.data.totals || key !== 'totals' && key !== 'time_range')));
      const projection = JSON.stringify(projectionData, null, 2).split('\n');
      this.offset = Math.min(this.offset, Math.max(0, projection.length - available));
      lines.push(...(Object.keys(projectionData).length ? projection.slice(this.offset, this.offset + available) : ['No records in this authorized view.']));
    }
    else if (!state.data.gap && !state.data.replayed) lines.push('No activity recorded in this authorized scope.');
    lines.push(this.color('muted', `↑↓/j k select · Enter/a actions${inspectorCanSearch(this.controller) ? ' · / search' : ''} · r refresh · c compact · Esc close`));
    return lines.map(line => this.truncate(line, Math.max(1, width)));
  }
  invalidate() { this.tabRanges = []; this.rowCount = 0; }
}
