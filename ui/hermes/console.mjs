export const TABS = [
  ['memories', 'Memories', 'browse'], ['activity', 'Activity', 'events'],
  ['evidence', 'Evidence & History', 'browse'], ['relations', 'Relations', 'graph'],
  ['maintenance', 'Review & Maintenance', 'browse'], ['sharing', 'Sharing & Workspaces', 'browse'],
  ['settings', 'Settings & Diagnostics', 'get_settings'], ['transfer', 'Data Transfer', 'browse'],
  ['summary', 'Summary', 'summary'],
];
const WRITES = new Set(['mutate', 'maintenance_commit', 'set_settings', 'transfer_commit', 'grant', 'revoke']);
const PAGINATED = new Set(['browse', 'history', 'events', 'graph']);
const commitFor = (operation, kind) => operation === 'maintenance_preview' ? 'maintenance_commit'
  : operation === 'transfer_preview' ? 'transfer_commit' : ['grant', 'revoke', 'set_settings', 'explain'].includes(kind) ? kind : 'mutate';

/** One bounded state per mounted native view. No sockets, AI or browser on enablement. */
export function createSession(send) {
  let version = 0, sequence = 0, context = '', selection, disposed = false;
  let activeController;
  let pagination;
  const listeners = new Set();
  const state = { result: null, preview: null, pending: false, opened: false };
  const publish = () => { for (const listener of listeners) listener({ ...state }); };
  const fresh = (epoch, seq) => !disposed && epoch === version && seq === sequence;
  async function run(path, body, writing = false) {
    const epoch = version, seq = ++sequence;
    activeController?.abort();
    activeController = new AbortController();
    const signal = activeController.signal;
    state.pending = true; state.preview = null; publish();
    pagination = undefined;
    let result;
    try {
      result = await send(path, { ...body, session_ref: context }, signal);
      if (!result || typeof result.status !== 'string') throw new Error('Invalid backend response');
    } catch (error) {
      const denied = error?.status === 403 || error?.statusCode === 403 || /\b403\b/.test(String(error?.message || ''));
      result = { status: denied ? 'denied' : writing ? 'unknown_outcome' : 'unavailable', data: null,
        error: { code: denied ? 'native_binding_required' : writing ? 'outcome_unknown' : 'backend_unavailable',
          message: denied ? 'Native scope denied. Run hermes luminary-inspector inspector-bind with the exact owned provider record scope; unowned legacy rows need an approved migration. For a new location of an existing project, open its already bound session and explicitly approve the location alias in Sharing & Workspaces.'
            : writing ? 'The operation may have committed. Refresh before deciding what to do; it was not replayed.'
            : 'Backend unavailable. Enable luminary-inspector for this profile, install the matching Python package and restart Hermes.' } };
    }
    if (!fresh(epoch, seq)) return null;
    if (['denied', 'unavailable', 'cancelled', 'unknown_outcome'].includes(result.status)) {
      state.preview = null;
      state.result = { ...result, data: null };
    } else state.result = result;
    state.pending = false;
    if (['ok', 'empty'].includes(result.status) && PAGINATED.has(body.operation)
        && typeof result.data?.next_cursor === 'string') {
      pagination = { operation: body.operation, arguments: structuredClone(body.arguments || {}),
        selection_handle: body.selection_handle, cursor: result.data.next_cursor };
    }
    publish();
    return result;
  }
  const api = {
    state,
    subscribe(listener) { listeners.add(listener); listener({ ...state }); return () => listeners.delete(listener); },
    setContext(next) {
      // A native React effect can mount → clean up → mount in StrictMode.
      // Rebinding starts a new lifetime, while versioning rejects its old work.
      disposed = false;
      version++; sequence++; context = next || ''; selection = undefined;
      pagination = undefined;
      activeController?.abort();
      Object.assign(state, { result: null, preview: null, pending: false, opened: false }); publish();
    },
    setSelection(handle) { activeController?.abort(); version++; sequence++; selection = handle; pagination = undefined; Object.assign(state, { result: null, preview: null, pending: false }); publish(); },
    async open() {
      if (!context) return null;
      const result = await run('/open', { operation: 'browse', arguments: {}, request_id: crypto.randomUUID() });
      if (!result) return null;
      state.opened = ['ok', 'empty'].includes(result.status); publish(); return result;
    },
    async request(operation, args = {}) {
      const result = await run('/console', { operation, arguments: args, selection_handle: selection, request_id: crypto.randomUUID() }, WRITES.has(operation));
      if (result && ['ok', 'empty'].includes(result.status) && result.data?.preview_id) {
        state.preview = { ...result.data, commit_operation: commitFor(operation, args.kind) }; publish();
      }
      return result;
    },
    nextPage() {
      if (!pagination || disposed || state.pending) return null;
      const page = pagination;
      return run('/console', { operation: page.operation, arguments: { ...page.arguments, cursor: page.cursor },
        selection_handle: page.selection_handle, request_id: crypto.randomUUID() });
    },
    async transfer(direction, file) {
      const registered = await run(direction === 'import' ? '/upload' : '/export-handle', file ? { file } : {});
      const handle = registered?.data?.file_handle;
      if (registered?.status !== 'ok' || typeof handle !== 'string') return null;
      const preview = await api.request('transfer_preview', { direction, file_handle: handle });
      return preview ? { handle, preview } : null;
    },
    download(handle) { return run(`/download/${encodeURIComponent(handle)}`, {}); },
    async confirm(approved) {
      if (!approved || !state.preview) return null;
      const preview = state.preview;
      state.preview = null;
      return run('/confirm', { preview_id: preview.preview_id, commit_operation: preview.commit_operation,
        request_id: crypto.randomUUID() }, true);
    },
    cancelPreview() { state.preview = null; publish(); },
    dispose() { activeController?.abort(); disposed = true; version++; listeners.clear(); },
  };
  return api;
}

/** Both SDK adapters supply their own host React singleton to this factory. */
export function createInspectorView(React, useNativeContext, send, subscribeInvalidation) {
  const h = React.createElement;
  const button = (label, onClick, disabled = false, extra = {}) => h('button', {
    type: 'button', onClick, disabled, style: { border: '1px solid var(--ui-border, var(--border))', borderRadius: 4, padding: '5px 9px', cursor: disabled ? 'default' : 'pointer' }, ...extra,
  }, label);
  const inputStyle = { border: '1px solid var(--ui-border, var(--border))', background: 'transparent', color: 'inherit', padding: 6, borderRadius: 4, minWidth: 0 };
  function Input({ label, value, onChange, type = 'text' }) {
    return h('label', { style: { display: 'grid', gap: 3 } }, label,
      h('input', { type, value, onChange: event => onChange(event.target.value), style: inputStyle }));
  }
  function Json({ value }) {
    return h('pre', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 12, maxHeight: 350, overflow: 'auto' } }, JSON.stringify(value, null, 2));
  }
  function Fields({ value }) {
    if (value === null || value === undefined) return h('span', null, 'Not available');
    if (typeof value !== 'object') return h('span', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }, String(value));
    if (Array.isArray(value)) return value.length ? h('ul', null, ...value.map((entry, index) =>
      h('li', { key: index }, h(Fields, { value: entry })))) : h('span', null, 'None');
    return h('dl', { style: { display: 'grid', gridTemplateColumns: 'minmax(90px, auto) 1fr', gap: '5px 12px', margin: 0 } },
      ...Object.entries(value).filter(([key]) => !['preview_id', 'selection_handle'].includes(key)).flatMap(([key, entry]) => [
        h('dt', { key: `${key}-label`, style: { fontWeight: 600 } }, key.replaceAll('_', ' ')),
        h('dd', { key, style: { margin: 0, minWidth: 0 } }, h(Fields, { value: entry })),
      ]));
  }
  function Projection({ tab, data, inspectMemory }) {
    if (tab === 'summary' && data.text) return h('article', { 'aria-label': 'Optional AI explanation' },
      h('h3', null, 'AI explanation — untrusted interpretation'),
      h('p', { style: { whiteSpace: 'pre-wrap' } }, data.text),
      h('h4', null, 'Authorized memory references'), h(Fields, { value: data.references || [] }),
      h('h4', null, 'Reported usage'), h(Fields, { value: data.usage || {} }),
      h('p', null, `Model: ${data.model || 'not reported'} · Cost: ${data.cost ?? 'unknown'} · Writes: ${data.writes ?? 0}`));
    if (tab === 'summary') return h('article', { 'aria-label': 'Authorized summary' },
      h('h3', null, 'Store summary'), h(Fields, { value: data.totals || data.counts || {} }),
      h('h4', null, 'Stored timestamp bounds (UTC)'), h(Fields, { value: data.time_range || {} }),
      h('h4', null, 'Changes'), h(Fields, { value: data.changes || [] }),
      h('h4', null, 'Issues'), h(Fields, { value: data.issues || [] }),
      data.ai && h('p', null, data.ai));
    if (tab === 'activity') return h('ol', { 'aria-label': 'Activity timeline' },
      data.gap === true && h('li', { role: 'status' }, 'Activity history is incomplete. Refresh to load a new snapshot.'),
      data.gap !== true && data.replayed === true && h('li', { role: 'status' }, `${data.items?.length ? 'Showing new activity only.' : 'No new activity since the checkpoint.'} Refresh loads recent history.`),
      ...(data.items || []).map((event, index) => h('li', { key: event.event_id ?? index, style: { marginBottom: 12 } },
        h('strong', null, event.kind === 'native_recall' ? 'Recall activity' : event.kind === 'hermes_operation' ? 'Hermes activity' : event.kind || 'Event'), ' ',
        h('time', null, event.created_at || ''),
        event.operation && h('p', null, event.operation.summary),
        event.operation && h('small', null, `Source ${event.source || 'unknown'} · session ${event.operation.session_id || 'unknown'} · operation ${event.operation.id}`),
        !event.operation && h(Fields, { value: event.payload || event }))));
    if (tab === 'relations' && data.memory) return h('article', { 'aria-label': 'Supporting memory' },
      h('h3', null, 'Supporting memory'), h(Fields, { value: data }));
    if (tab === 'relations') return h('article', null, h('h3', null, 'Accessible relations'),
      h('p', null, data.label || 'Authorized co-occurrence adjacency'),
      h('p', null, data.weight_basis || 'Recall ranking is not recorded for this graph.'),
      h('ul', null, ...(data.items || []).map((edge, index) => h('li', { key: index },
        `${edge.source} → ${edge.target} · ${edge.kind} `,
        button(`Inspect supporting memory #${edge.memory_id}`, () => inspectMemory(edge.memory_id))))));
    if (tab === 'settings') return h('article', null,
      h('h3', null, 'Effective profile settings'), h(Fields, { value: data.values || {} }),
      h('h4', null, 'Secret presence (never values)'), h(Fields, { value: data.secret_presence || {} }),
      h('h4', null, 'Readiness'), h(Fields, { value: data.readiness || {} }));
    if (tab === 'evidence' && data.memory) return h('article', null,
      h('h3', null, `Memory #${data.memory.id}`), h('p', { style: { whiteSpace: 'pre-wrap' } }, data.memory.content),
      ...['evidence', 'claims', 'episodes', 'lineage'].map(key => h('section', { key },
        h('h4', null, key), h(Fields, { value: data[key] || [] }))));
    return null;
  }
  function Inspector({ native, compact = false, initialTab = 'memories' }) {
    const liveNative = React.useRef(native.key);
    liveNative.current = native.key;
    const [model] = React.useState(() => createSession((path, body, signal) => send(path, body, native, signal)));
    const [state, setState] = React.useState({ ...model.state });
    const [tab, setTab] = React.useState(initialTab);
    const viewId = React.useId();
    const [session, setSession] = React.useState(native.session || '');
    const [sessions, setSessions] = React.useState([]);
    const [query, setQuery] = React.useState(''), [tags, setTags] = React.useState(''), [status, setStatus] = React.useState('active');
    const [content, setContent] = React.useState(''), [row, setRow] = React.useState(null);
    const [targetAgent, setTargetAgent] = React.useState(''), [rights, setRights] = React.useState({ read: false, contribute: false, edit: false, retract: false });
    const [setting, setSetting] = React.useState(''), [value, setValue] = React.useState('');
    const [maintenance, setMaintenance] = React.useState('prune');
    const [notice, setNotice] = React.useState('');
    const [conflictToken, setConflictToken] = React.useState('');
    const [hostId, setHostId] = React.useState(''), [location, setLocation] = React.useState('');
    const [targetProfile, setTargetProfile] = React.useState('');
    const [projectChoices, setProjectChoices] = React.useState([]);
    const [file, setFile] = React.useState(null), [exportHandle, setExportHandle] = React.useState('');
    const [download, setDownload] = React.useState(null);
    React.useEffect(() => model.subscribe(setState), [model]);
    React.useEffect(() => { setSession(native.session || ''); setSessions([]); setRow(null); setContent(''); setNotice(''); model.setContext(native.session || ''); }, [native.key, native.session]);
    React.useEffect(() => { model.setContext(session); setRow(null); setContent(''); setProjectChoices([]); setFile(null); setExportHandle(''); setDownload(null); }, [session]);
    React.useEffect(() => subscribeInvalidation?.(() => { model.setContext(session); setRow(null); setContent(''); setExportHandle(''); setDownload(null); }), [native.key, session]);
    React.useEffect(() => {
      if (['denied', 'unavailable', 'unknown_outcome', 'cancelled'].includes(state.result?.status)) {
        setRow(null); setContent(''); setProjectChoices([]); setConflictToken(''); setExportHandle(''); setDownload(null);
      }
    }, [state.result]);
    React.useEffect(() => {
      const bytes = state.result?.data?.download_bytes;
      if (!bytes) return;
      const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
      setDownload({ url, name: state.result.data.filename || 'luminary-export.json' });
      return () => { URL.revokeObjectURL(url); setDownload(null); };
    }, [state.result]);
    React.useEffect(() => () => model.dispose(), [model]);
    const operation = TABS.find(item => item[0] === tab)?.[2] || 'browse';
    const filters = () => ({ query, tags: tags.split(',').map(value => value.trim()).filter(Boolean),
      statuses: status === 'all' ? ['active', 'candidate', 'conflicted', 'superseded', 'expired', 'deleted'] : [status] });
    const load = () => model.request(operation, tab === 'relations' ? { entity_id: state.result?.data?.focus_entity_id ?? undefined, limit: 50 } : filters());
    const chooseTab = next => { setTab(next); setRow(null); setContent(''); model.cancelPreview(); if (model.state.opened) model.request(TABS.find(item => item[0] === next)[2]); };
    const tabKeyDown = (event, index) => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % TABS.length;
      else if (event.key === 'ArrowLeft') next = (index + TABS.length - 1) % TABS.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = TABS.length - 1;
      else return;
      event.preventDefault();
      event.currentTarget.parentElement.querySelectorAll('[role="tab"]')[next]?.focus();
      chooseTab(TABS[next][0]);
    };
    const data = state.result?.data || {};
    const rows = Array.isArray(data.items) ? data.items : Array.isArray(data.nodes) ? data.nodes : [];
    const change = (kind, args = {}, operation = 'preview_change') => model.request(operation, {
      kind, ...(row?.id !== undefined ? { memory_id: row.id, expected_revision: row.revision } : {}), ...args,
    });
    const detail = async item => {
      setRow(null); setContent('');
      const result = await model.request('detail', { memory_id: item.id });
      if (result?.data?.memory) {
        setRow(result.data.memory); setContent(result.data.memory.content || '');
        setConflictToken(result.data.conflict_set_token || '');
      }
    };
    const editable = Array.isArray(data.editable) ? data.editable : [];
    const canAct = state.opened && !state.pending;
    const controls = [];
    if (tab === 'memories') controls.push(
      h('label', { key: 'text' }, 'Memory content', h('textarea', { value: content, onChange: event => setContent(event.target.value), rows: compact ? 3 : 5, style: { ...inputStyle, width: '100%', boxSizing: 'border-box' } })),
      h('div', { key: 'actions', style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
        button('Preview new memory', () => change('create', { content }), !canAct || !content.trim()),
        button('Preview correction', () => change('correct', { content }), !canAct || !row?.permissions?.edit),
        button('Preview tags', () => change('tag', { tags: tags.split(',').map(value => value.trim()).filter(Boolean) }), !canAct || !row?.permissions?.edit),
        button('Mark core', () => change('core', { pinned: true }), !canAct || !row?.permissions?.edit),
        button('Remove core', () => change('core', { pinned: false }), !canAct || !row?.permissions?.edit),
        button('Preview retraction', () => change('retract'), !canAct || !row?.permissions?.retract)));
    if (tab === 'activity' && typeof data.replay_context === 'string') controls.push(
      button(data.has_more ? 'Next new activity' : 'Check new activity', () => model.request('events', {
        since_event_id: data.next_event_id ?? data.snapshot_boundary, replay_context: data.replay_context,
      }), !canAct));
    if (tab === 'evidence') controls.push(h('div', { key: 'evidence' },
      button('History', () => model.request('history', { memory_id: row.id, limit: 50 }), !canAct || !row),
      ...['evidence', 'claims', 'episodes', 'lineage'].map(expand =>
        button(`Expand ${expand}`, () => model.request('detail', { memory_id: row.id, expand, limit: 50 }), !canAct || !row, { key: expand }))));
    if (tab === 'relations') controls.push(
      h('label', { key: 'entity' }, 'Explore entity ', h('select', {
        value: data.focus_entity_id ?? '', disabled: !canAct, style: inputStyle,
        onChange: event => { if (event.target.value) model.request('graph', { entity_id: Number(event.target.value), limit: 50 }); },
      }, h('option', { value: '' }, 'Choose an authorized entity'),
      ...(data.nodes || []).map(node => h('option', { key: node.id, value: node.id }, node.label)))),
      button('All relations', () => model.request('graph', { limit: 50 }), !canAct));
    if (tab === 'maintenance') controls.push(h('div', { key: 'maintenance', style: { display: 'grid', gap: 8 } },
      h('label', null, 'Maintenance proposal ', h('select', { value: maintenance, onChange: event => setMaintenance(event.target.value), style: inputStyle }, ...['prune', 'cleanup_expired'].map(kind => h('option', { key: kind }, kind)))),
      button('Preview maintenance', () => change(maintenance, {}, 'maintenance_preview'), !canAct),
      h(Input, { label: 'Conflict-set token from claim details', value: conflictToken, onChange: setConflictToken }),
      button('Preview selected conflict winner', () => change('resolve_conflict', { expected_conflict_set_token: conflictToken }), !canAct || !row || !conflictToken)));
    if (tab === 'sharing') controls.push(h('div', { key: 'sharing', style: { display: 'grid', gap: 8 } },
      h('p', null, 'Rights are independent for this explicit project. Granting one never grants the others.'),
      h(Input, { label: 'Agent receiving project rights', value: targetAgent, onChange: setTargetAgent }),
      h('div', null, ...['read', 'contribute', 'edit', 'retract'].map(right => h('label', { key: right, style: { marginRight: 12 } }, h('input', { type: 'checkbox', checked: rights[right], onChange: event => setRights({ ...rights, [right]: event.target.checked }) }), right))),
      button('Preview grant', () => change('grant', { recipient_agent_id: targetAgent, capabilities: Object.keys(rights).filter(right => rights[right]) }), !canAct || !targetAgent),
      button('Preview revoke', () => change('revoke', { recipient_agent_id: targetAgent }), !canAct || !targetAgent),
      h(Input, { label: 'Explicit location host ID', value: hostId, onChange: setHostId }),
      h(Input, { label: 'Absolute location on that host', value: location, onChange: setLocation }),
      h(Input, { label: 'Explicit location profile ID', value: targetProfile, onChange: setTargetProfile }),
      button('Preview location binding', () => change('bind_location', { location: { workspace: location, host_id: hostId, profile_id: targetProfile } }), !canAct || !hostId || !location || !targetProfile)));
    if (tab === 'settings') controls.push(h('div', { key: 'settings', style: { display: 'grid', gap: 8 } },
      h('p', null, 'Profile-local effective settings. Opening this view never activates the provider or changes saving.'),
      h('label', null, 'Editable setting ', h('select', { value: setting, onChange: event => { setSetting(event.target.value); setValue(JSON.stringify(data.values?.[event.target.value])); }, style: inputStyle }, h('option', { value: '' }, 'Choose setting'), ...editable.map(key => h('option', { key, value: key }, key)))),
      h(Input, { label: 'New value (JSON string, boolean or number)', value, onChange: setValue }),
      button('Preview settings change', () => { try { change('set_settings', { changes: { [setting]: JSON.parse(value) }, expected_revision: data.revision }); } catch { setNotice('Enter a valid JSON setting value.'); } }, !canAct || !setting),
      button('Refresh readiness', () => model.request('get_settings', { diagnostics: true }), !canAct)));
    if (tab === 'transfer') controls.push(h('div', { key: 'transfer', style: { display: 'grid', gap: 8 } },
      h('p', null, 'Memory-record transfer is not a full backup of raw episodes, evidence, native sessions or configuration. Import accepts one file up to 4 MiB. No frontend filesystem path is authority.'),
      h('label', null, 'Choose memory records to import ', h('input', { type: 'file', accept: '.json,application/json',
        disabled: !canAct, onChange: event => { const selected = event.target.files?.[0]; setFile(selected || null); setNotice(selected?.size > 4 * 1024 * 1024 ? 'Choose a file no larger than 4 MiB.' : ''); } })),
      button('Upload and preview import', () => model.transfer('import', file), !canAct || !file || file.size > 4 * 1024 * 1024),
      button('Preview export', async () => { setExportHandle(''); const result = await model.transfer('export'); if (result?.preview.status === 'ok') setExportHandle(result.handle); }, !canAct),
      button('Prepare confirmed export download', () => model.download(exportHandle), !canAct || !exportHandle || !!state.preview),
      download && h('a', { href: download.url, download: download.name }, 'Save confirmed memory export')));
    if (tab === 'summary') controls.push(h('div', { key: 'summary' },
      h('p', null, 'Deterministic authorized Summary. AI is optional and never requested by navigation.'),
      button('Preview AI disclosure', () => model.request('explain', { phase: 'preview', kind: 'explain' }), !canAct)));
    return h('section', { 'aria-label': 'Luminary Inspector', style: { color: 'var(--ui-text, var(--foreground))', background: 'var(--ui-bg, var(--background))', padding: compact ? 10 : 20, display: 'grid', gap: 12, overflow: 'auto', height: '100%', boxSizing: 'border-box' } },
      h('header', null, h('h2', { style: { margin: 0 } }, 'Luminary Inspector'), h('small', null, compact ? 'Compact native pane' : 'Full native view')),
      h('p', { style: { margin: 0 } }, 'Bound to the authenticated Hermes profile and verified native session. Owner-level installed plugins are not sandboxed by memory grants.'),
      h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'end' } },
        native.session ? h('span', null, `Session: ${native.session}`) : h('label', null, 'Native session ', h('select', { value: session, onChange: event => setSession(event.target.value), style: inputStyle }, h('option', { value: '' }, 'Choose session'), ...sessions.map(item => h('option', { key: item.id, value: item.id }, item.title)))),
        !native.session && button('Load native sessions', async () => { const key = native.key; try { const result = await send('/sessions', undefined, native); if (key === liveNative.current) { setSessions(result.items || []); setNotice(''); } } catch { if (key === liveNative.current) setNotice('Native session list unavailable; enable the profile backend and restart Hermes.'); } }),
        button('Open / bind session', () => model.open(), !session || state.pending),
        button('Refresh', load, !canAct)),
      h('nav', { 'aria-label': 'Inspector tabs', role: 'tablist', style: { display: 'flex', flexWrap: 'wrap', gap: 5 } }, ...TABS.map(([id, label], index) => button(label, () => chooseTab(id), false, {
        key: id, id: `${viewId}-${id}`, role: 'tab', 'aria-selected': tab === id, 'aria-controls': `${viewId}-panel`,
        tabIndex: tab === id ? 0 : -1, onKeyDown: event => tabKeyDown(event, index),
      }))),
      tab !== 'relations' && h('form', { onSubmit: event => { event.preventDefault(); if (canAct) load(); }, style: { display: 'grid', gridTemplateColumns: compact ? '1fr' : '2fr 1fr 1fr', gap: 8 } },
        h(Input, { label: 'Search', value: query, onChange: setQuery }), h(Input, { label: 'Tags (comma separated)', value: tags, onChange: setTags }),
        h('label', null, 'Status ', h('select', { value: status, onChange: event => setStatus(event.target.value), style: inputStyle }, ...['active', 'candidate', 'conflicted', 'superseded', 'expired', 'deleted', 'all'].map(item => h('option', { key: item }, item))))),
      h('div', { role: 'status' }, state.pending ? 'Loading…' : state.result ? `${state.result.status}${state.result.error ? ': ' + state.result.error.message : ''}` : 'Open the native session to inspect its explicitly bound scope.'),
      notice && h('p', { role: 'alert' }, notice),
      h('div', { id: `${viewId}-panel`, role: 'tabpanel', 'aria-labelledby': `${viewId}-${tab}`, style: { display: 'grid', gap: 10 } },
        state.result?.status === 'ok' && Number.isInteger(data.stored) && Number.isInteger(data.duplicates) &&
          h('article', { 'aria-label': 'Memory operation receipt', role: 'status' },
            h('h3', null, 'Memory operation complete'),
            h('p', null, Number.isInteger(data.count) && data.audit === 'committed'
              ? `Processed ${data.count} memory records. Stored ${data.stored} new records; suppressed ${data.duplicates} duplicate records.`
              : `Stored ${data.stored} new memories; suppressed ${data.duplicates} duplicate memories.`),
            data.lineage_map && h('div', null, h('h4', null, 'Imported source → destination IDs'), h(Fields, { value: data.lineage_map }))),
        ...controls,
        rows.length > 0 && !['activity', 'relations'].includes(tab) && h('ul', { style: { margin: 0, paddingLeft: 20 } }, ...rows.map((item, index) => h('li', { key: item.id ?? item.event_id ?? index },
          item.id !== undefined && ['memories', 'evidence', 'maintenance'].includes(tab)
            ? h('div', null, button(`#${item.id} ${String(item.content || '').slice(0, 180)}`, () => detail(item), !canAct),
                h('small', null, ` ${item.status || ''} · revision ${item.revision ?? '—'} · ${(item.tags || []).join(', ')}`))
            : h(Fields, { value: item })))),
        h(Projection, { tab, data, inspectMemory: memory_id => model.request('detail', { memory_id }) }),
        data.next_cursor && button('Next page', () => model.nextPage(), !canAct),
        state.result?.as_of && h('small', null, `As of ${state.result.as_of}`),
        state.result?.data && !data.download_bytes && h('details', null, h('summary', null, 'Technical authorized response'), h(Json, { value: data })),
        button('Choose explicit project resource', async () => { const result = await model.request('browse'); if (result) setProjectChoices(result.data?.projects || []); }, !canAct),
        button('Return to native own scope', () => { model.setSelection(undefined); setRow(null); setContent(''); load(); }, !canAct),
        ...projectChoices.map(project => button(String(project.workspace_id || project.project_id), () => { model.setSelection(project.selection_handle); setRow(null); setContent(''); load(); }, !canAct, { key: project.project_id }))),
      state.preview && h('div', { role: 'dialog', 'aria-label': 'Confirm Luminary change', style: { border: '2px solid var(--ui-border, var(--border))', borderRadius: 6, padding: 12 } },
        h('h3', null, `Review ${state.preview.kind || 'operation'}`),
        h('h4', null, 'Before'), h(Fields, { value: state.preview.before }),
        h('h4', null, 'After'), h(Fields, { value: state.preview.after }),
        h('h4', null, 'Effects'), h(Fields, { value: state.preview.effects }),
        h('small', null, `Expires: ${state.preview.expires_at || 'server controlled'}`),
        h('p', null, 'Confirm only this preview. Revisions, owner scope and access are checked again before commit.'),
        button('Confirm this operation', () => model.confirm(true), state.pending), button('Cancel', () => model.cancelPreview(), state.pending)));
  }
  return function NativeInspector(props) {
    const native = useNativeContext();
    return h(Inspector, { ...props, native, key: native.key });
  };
}
