import { InspectorController } from '../../src/luminary_memory/integrations/assets/common/console-controller.js';
import { TABS, type ConsoleResult, type ConsoleTransport } from '../../src/luminary_memory/integrations/assets/common/console-contract.js';
import { inspectorActions, inspectorRows, runInspectorAction, type NativeDialogs, type InspectorRow } from '../../src/luminary_memory/integrations/assets/common/console-actions.js';

const tabs = document.querySelector<HTMLElement>('#tabs')!;
const view = document.querySelector<HTMLElement>('#view')!;
const toolbar = document.querySelector<HTMLElement>('#toolbar')!;
const connection = document.querySelector<HTMLElement>('#connection')!;
const modal = document.querySelector<HTMLDialogElement>('#dialog')!;
let csrf = sessionStorage.getItem('luminary-inspector-csrf') || '';
let selected: InspectorRow | undefined;
let controller: InspectorController;

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(text: string, action: () => unknown, primary = false) {
  const node = element('button', text, primary ? 'primary' : '');
  node.type = 'button';
  node.addEventListener('click', () => { Promise.resolve(action()).catch(() => {
    connection.textContent = 'Operation unavailable. No successful change is claimed; inspect Activity before retrying.';
  }); });
  return node;
}
async function json(path: string, body: unknown): Promise<any> {
  const response = await fetch(path, { method: 'POST', headers: {
    'Content-Type': 'application/json', 'X-Luminary-CSRF': csrf,
  }, body: JSON.stringify(body), credentials: 'same-origin' });
  if (!response.ok) throw new Error('Authenticated inspector request failed');
  return response.json();
}
function dialog<T>(title: string, content: HTMLElement, choices: { label: string; value: T; primary?: boolean }[], cancelled: T): Promise<T> {
  const { promise, resolve } = Promise.withResolvers<T>();
  document.querySelector('#dialog-title')!.textContent = title;
  document.querySelector('#dialog-body')!.replaceChildren(content);
  const actions = document.querySelector('#dialog-actions')!;
  const cancel = (event: Event) => { event.preventDefault(); finish(cancelled); };
  const finish = (value: T) => { modal.removeEventListener('cancel', cancel); modal.close(); resolve(value); };
  actions.replaceChildren(...choices.map(choice => button(choice.label, () => finish(choice.value), choice.primary)));
  modal.addEventListener('cancel', cancel);
  modal.showModal();
  return promise;
}
const dialogs: NativeDialogs = {
  async input(title, value) {
    const input = element('textarea'); input.value = value || ''; input.setAttribute('aria-label', title);
    const answer = await dialog(title, input, [{ label: 'Cancel', value: false }, { label: 'Continue', value: true, primary: true }], false);
    return answer ? input.value : undefined;
  },
  async select(title, choices) {
    const select = element('select'); select.setAttribute('aria-label', title);
    for (const choice of choices) { const option = element('option', choice); option.value = choice; select.append(option); }
    const answer = await dialog(title, select, [{ label: 'Cancel', value: false }, { label: 'Select', value: true, primary: true }], false);
    return answer ? select.value : undefined;
  },
  confirm: (title, message) => dialog(title, element('pre', message), [{ label: 'Cancel', value: false }, { label: 'Confirm', value: true, primary: true }], false),
  async show(title, message) { await dialog(title, element('pre', message), [{ label: 'Close', value: true }], true); },
};

async function transfer(direction: 'import' | 'export') {
  let body: Blob | string = '';
  if (direction === 'import') {
    const input = element('input'); input.type = 'file'; input.accept = '.json,application/json';
    input.setAttribute('aria-label', 'Memory-record export file');
    if (!await dialog('Select a memory-record file', input, [{ label: 'Cancel', value: false }, { label: 'Preview import', value: true, primary: true }], false)) return;
    const file = input.files?.[0]; if (!file) return;
    if (file.size > 4 * 1024 * 1024) { await dialogs.show('File too large', 'Transfer accepts at most 4 MiB; no file was uploaded.'); return; }
    body = file;
  }
  const response = await fetch('/api/file?mode=' + (direction === 'import' ? 'read' : 'write'), {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/octet-stream', 'X-Luminary-CSRF': csrf }, body,
  });
  if (!response.ok) throw new Error('File selection failed');
  const registered = await response.json() as ConsoleResult;
  const handle = registered.data?.file_handle;
  if (registered.status !== 'ok' || typeof handle !== 'string') { await dialogs.show('File unavailable', registered.error?.message || registered.status); return; }
  await controller.preview('transfer_preview', { direction, file_handle: handle }, 'transfer_commit');
  const result = await controller.commit(preview => dialogs.confirm('Confirm data transfer', JSON.stringify(preview, null, 2)));
  if (direction === 'export' && result?.status === 'ok') {
    const downloaded = await fetch('/api/download/' + encodeURIComponent(handle), { headers: { 'X-Luminary-CSRF': csrf }, credentials: 'same-origin' });
    if (!downloaded.ok) throw new Error('Export was not downloadable');
    const url = URL.createObjectURL(await downloaded.blob());
    const anchor = element('a'); anchor.href = url; anchor.download = 'luminary-memories.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
async function action(name: string, row?: InspectorRow) {
  if (name === 'Import records' || name === 'Export records') await transfer(name === 'Import records' ? 'import' : 'export');
  else await runInspectorAction(controller, dialogs, name, row);
}
function fields(values: Record<string, unknown>) {
  const list = element('dl', undefined, 'fields');
  for (const [name, value] of Object.entries(values)) {
    list.append(element('dt', name.replaceAll('_', ' ')), element('dd', typeof value === 'string' ? value : JSON.stringify(value)));
  }
  return list;
}
function render() {
  const state = controller.state;
  connection.textContent = `${state.busy ? 'Loading' : state.status} · ${controller.selectionHandle ? 'Explicit shared project' : 'Own native project'} · policy ${state.policy_revision ?? '—'} · ${state.as_of || ''}${state.error ? ' · ' + state.error : ''}`;
  for (const node of tabs.querySelectorAll<HTMLButtonElement>('button')) {
    const active = node.dataset.tab === state.tab;
    node.setAttribute('aria-selected', String(active)); node.tabIndex = active ? 0 : -1;
  }
  toolbar.replaceChildren(...inspectorActions(controller, selected).filter(name => name !== 'View projection').map(name => button(name, () => action(name, selected))));
  view.replaceChildren();
  if (state.error) view.append(element('p', state.error, 'notice warning'));
  const data = state.data;
  if (data.gap === true) view.append(element('p', 'Activity history is incomplete. Refresh to load a new snapshot.', 'notice warning'));
  else if (data.replayed === true) view.append(element('p', `${Array.isArray(data.items) && data.items.length ? 'Showing new activity only.' : 'No new activity since the checkpoint.'} Refresh loads recent history.`, 'notice'));
  if (state.tab === 'summary' && data.totals && typeof data.totals === 'object') {
    const metrics = element('div', undefined, 'metrics');
    for (const [name, value] of Object.entries(data.totals)) { const card = element('div', undefined, 'metric'); card.append(element('strong', String(value)), element('span', name)); metrics.append(card); }
    view.append(metrics, element('p', String(data.count_basis || ''), 'muted'));
    if (data.time_range && typeof data.time_range === 'object') {
      const panel = element('section', undefined, 'record');
      panel.append(element('h2', 'Stored timestamp bounds (UTC)'), fields(data.time_range as Record<string, unknown>));
      view.append(panel);
    }
  }
  if (state.tab === 'settings') {
    for (const key of ['values', 'secret_presence', 'readiness']) if (data[key] && typeof data[key] === 'object') {
      const panel = element('section', undefined, 'record'); panel.append(element('h2', key.replaceAll('_', ' ')), fields(data[key] as Record<string, unknown>)); view.append(panel);
    }
  }
  if (state.tab === 'relations' && data.label) view.append(element('p', String(data.label), 'notice'));
  if (state.tab === 'sharing') view.append(element('p', 'Select a project explicitly. Read, contribute, edit and retract are separate rights; matching paths do not establish sharing.', 'notice'));
  if (state.tab === 'transfer') view.append(element('p', 'Memory-record transfer is not a full backup of evidence, episodes, audit, settings or grants. Every transfer shows a preview before confirmation.', 'notice'));
  const rows = inspectorRows(controller);
  for (const row of rows) {
    const card = element('article', undefined, 'record');
    card.append(element('h3', row.kind === 'native_recall' ? 'Recall activity' : row.kind === 'hermes_operation' ? 'Hermes activity' : row.id !== undefined ? `Memory #${row.id} · ${row.status ?? ''} · revision ${row.revision ?? '—'}` : String(row.kind ?? row.label ?? row.event_id ?? 'Record')));
    if (row.operation && typeof row.operation === 'object') {
      const operation = row.operation as Record<string, unknown>;
      card.append(element('p', String(operation.summary)),
        element('small', `Source ${row.source ?? 'unknown'} · session ${operation.session_id ?? 'unknown'} · operation ${operation.id} · ${row.created_at ?? ''}`));
    }
    if (row.content) card.append(element('p', String(row.content)));
    else if (row.source && row.target) card.append(element('p', `${row.source} → ${row.target} · ${row.kind || 'co-occurrence'}`));
    else if (!row.operation) card.append(fields(row));
    if (row.permissions) card.append(element('small', 'Allowed: ' + Object.keys(row.permissions).filter(key => row.permissions?.[key]).join(', ')));
    const actions = element('div', undefined, 'record-actions');
    actions.append(button('Actions', async () => {
      selected = row;
      const choice = await dialogs.select('Record actions', inspectorActions(controller, row));
      if (choice) await action(choice, row);
    }));
    if (row.id !== undefined) actions.append(button('Inspect', () => controller.detail(row.id!)));
    card.append(actions); view.append(card);
  }
  for (const key of ['evidence', 'claims', 'lineage', 'episodes', 'issues']) {
    const value = data[key];
    if (Array.isArray(value) && value.length) { const section = element('details', undefined, 'record'); section.append(element('summary', key), element('pre', JSON.stringify(value, null, 2))); view.append(section); }
  }
  if (data.audit === 'committed') {
    const receipt = element('article', undefined, 'record');
    receipt.setAttribute('aria-label', 'Operation receipt');
    receipt.append(element('h2', 'Confirmed operation committed'));
    if (typeof data.stored === 'number') receipt.append(element('p', `${data.stored} saved · ${data.duplicates ?? 0} duplicates skipped.`));
    if (typeof data.memory_id === 'number') receipt.append(element('p', `Memory #${data.memory_id} · revision ${data.revision ?? '—'}`), button('Inspect memory', () => controller.detail(data.memory_id as number)));
    if (data.coverage) receipt.append(element('p', String(data.coverage)));
    view.append(receipt);
  }
  if (typeof data.text === 'string') { const answer = element('article', undefined, 'record'); answer.append(element('h2', 'AI explanation · untrusted interpretation'), element('p', data.text), fields({ references: data.references, model: data.model, usage: data.usage, cost: data.cost })); view.append(answer); }
  if (!view.children.length) view.append(element('p', state.busy ? 'Loading authorized data…' : 'No records in this authorized view.', 'notice'));
}

async function start() {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get('token'); history.replaceState(null, '', location.pathname);
  if (token) { const response = await json('/api/bootstrap', { token }); csrf = response.csrf_token; sessionStorage.setItem('luminary-inspector-csrf', csrf); }
  if (!csrf) throw new Error('Launch the companion again for a one-use owner sign-in link.');
  const transport: ConsoleTransport = {
    async request(request, signal) {
      const response = await fetch('/api/request', { method: 'POST', credentials: 'same-origin', signal,
        headers: { 'Content-Type': 'application/json', 'X-Luminary-CSRF': csrf }, body: JSON.stringify(request) });
      if (!response.ok) throw new Error('Inspector session unavailable');
      return response.json();
    },
    confirm: preview_id => json('/api/confirm', { preview_id }),
  };
  controller = new InspectorController(transport);
  for (const tab of TABS) { const node = button(tab.label, async () => { selected = undefined; await controller.selectTab(tab.id); }); node.dataset.tab = tab.id; node.setAttribute('role', 'tab'); tabs.append(node); }
  tabs.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); const current = TABS.findIndex(tab => tab.id === controller.state.tab);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length;
    const tab = tabs.querySelector<HTMLButtonElement>(`[data-tab="${TABS[index].id}"]`)!; tab.click(); tab.focus();
  });
  controller.subscribe(render);
  document.querySelector('#compact')!.addEventListener('click', () => {
    const compact = document.body.classList.toggle('compact');
    document.querySelector('#compact')!.textContent = compact ? 'Full inspector' : 'Compact view';
    if (compact) void controller.selectTab('activity');
  });
  document.querySelector('#signout')!.addEventListener('click', async () => {
    await json('/api/sign-out', {}); sessionStorage.removeItem('luminary-inspector-csrf'); controller.dispose();
    view.replaceChildren(element('p', 'Signed out. Launch the companion again to inspect memory.', 'notice')); tabs.replaceChildren(); toolbar.replaceChildren();
  });
  window.addEventListener('pagehide', () => controller.dispose(), { once: true });
  await controller.load();
}
start().catch(error => { connection.textContent = error instanceof Error ? error.message : 'Inspector unavailable'; });
