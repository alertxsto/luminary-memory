import { InspectorController } from './console-controller.js';
export interface NativeDialogs {
  input(title: string, value?: string): Promise<string | undefined>;
  select(title: string, choices: string[]): Promise<string | undefined>;
  confirm(title: string, message: string): Promise<boolean>;
  show(title: string, message: string): Promise<void>;
}

/** Native confirm lists do not scroll; long reviews need the host's editor first. */
export async function confirmTerminalText(
  ui: { editor(title: string, value: string): Promise<string | undefined>; select(title: string, choices: string[]): Promise<string | undefined>; confirm(title: string, message: string): Promise<boolean> },
  title: string, message: string, active: () => boolean,
): Promise<boolean> {
  if (message.length <= 400 && message.split('\n').length <= 6) return ui.confirm(title, message);
  const reviewed = await ui.editor(`${title} · read-only review; edits are discarded`, message);
  if (reviewed === undefined || !active()) return false;
  return await ui.select(`${title} · apply the exact reviewed proposal?`, ['Cancel', 'Confirm reviewed change']) === 'Confirm reviewed change';
}
export interface InspectorRow { id?: number | string; content?: string; revision?: number; permissions?: Record<string, boolean>; [key: string]: unknown }
const base = ['Refresh', 'View projection', 'Search / filters', 'Next page', 'Select project'];
const resourceBase = ['Refresh', 'View projection', 'Next page', 'Select project'];
export function inspectorCanSearch(controller: InspectorController): boolean {
  return controller.state.tab === 'memories' || controller.state.tab === 'evidence' || controller.state.tab === 'maintenance';
}
export function inspectorRows(controller: InspectorController): InspectorRow[] {
  const data = controller.state.data;
  if (data.memory && typeof data.memory === 'object') return [data.memory as InspectorRow];
  const rows = data.items ?? data.nodes ?? data.changes ?? data.projects ?? data.grants;
  return Array.isArray(rows) ? rows.filter((r): r is InspectorRow => !!r && typeof r === 'object') : [];
}

export function inspectorRowContent(row: InspectorRow): string {
  const operation = row.operation as Record<string, unknown> | undefined;
  const activity = operation ? `${operation.summary} · ${row.source ?? 'unknown'} / ${operation.session_id ?? 'unknown'}` : undefined;
  const memory = typeof row.content === 'string' && typeof row.status === 'string'
    ? `[${row.status} · r${row.revision ?? '—'}] ${row.content}` : row.content;
  const adjacency = row.source && row.target ? `${row.source} → ${row.target} · ${row.kind ?? 'co-occurrence'} · memory #${row.memory_id}` : undefined;
  const grant = typeof row.grantor_agent_id === 'string' && typeof row.recipient_agent_id === 'string'
    ? `${row.grantor_agent_id} → ${row.recipient_agent_id} · ${Array.isArray(row.capabilities) ? row.capabilities.join(', ') : 'no rights'}` : undefined;
  return String(activity ?? memory ?? adjacency ?? grant ?? row.kind ?? row.label ?? JSON.stringify(row)).replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ');
}

/** Display-only native identity from the verified server, never request authority. */
export function inspectorContextLine(controller: InspectorController): string {
  const native = controller.state.data.native_context as Record<string, unknown> | undefined;
  if (!native || typeof native !== 'object') return '';
  return `Agent ${native.agent_id} · profile ${native.profile_id} · store ${String(native.store_id).slice(0, 12)} · host ${native.host_id}`.replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ');
}

export function inspectorSummaryLines(controller: InspectorController): string[] {
  const { tab, data } = controller.state;
  if (tab !== 'summary' || !data.totals) return [];
  const totals = data.totals as Record<string, unknown>;
  const lines = [Object.entries(totals).map(([name, value]) => `${name}: ${value}`).join(' · ')];
  const range = data.time_range as Record<string, unknown> | undefined;
  if (range) lines.push(`Stored timestamp bounds (UTC) · ${range.status}`,
    `Created: ${range.created_from ?? 'not available'} → ${range.created_to ?? 'not available'}`,
    `Updated: ${range.updated_from ?? 'not available'} → ${range.updated_to ?? 'not available'}`);
  return lines;
}
export function inspectorActions(controller: InspectorController, row?: InspectorRow): string[] {
  switch (controller.state.tab) {
    case 'memories': return [...base, 'Create memory', ...(row?.id !== undefined ? ['Inspect', 'History', 'Expand evidence', 'Expand source episodes', 'Claims / conflicts', 'Lineage', ...(row.permissions?.edit ? ['Correct', 'Tags', 'Core designation', ...(row.claim_key ? ['Resolve conflict'] : [])] : []), ...(row.permissions?.retract ? ['Retract'] : [])] : [])];
    case 'activity': return [...resourceBase, ...(typeof controller.state.data.replay_context === 'string' ? ['Check new activity'] : []), 'Event details'];
    case 'evidence': return [...base, ...(row?.id !== undefined ? ['Inspect', 'History', 'Expand evidence', 'Expand source episodes', 'Claims / conflicts', 'Lineage'] : [])];
    case 'relations': return [...resourceBase, 'Explore entity', 'All relations', 'Adjacency details', ...(typeof row?.memory_id === 'number' ? ['Inspect supporting memory'] : [])];
    case 'maintenance': return [...base, 'Preview maintenance', ...(row?.id !== undefined ? ['Inspect', ...(row.permissions?.edit && row.claim_key ? ['Resolve conflict'] : [])] : [])];
    case 'sharing': return [...resourceBase, 'Project information', ...(!controller.selectionHandle ? ['Grant rights', 'Revoke rights', 'Bind location'] : [])];
    case 'settings': return ['Refresh', 'View projection', 'Change setting', 'Readiness / diagnostics'];
    case 'transfer': return ['Refresh', 'View projection', 'Export records', 'Import records', 'Backup limitations'];
    case 'summary': return ['Refresh', 'View projection', 'Explain with AI'];
  }
}
async function replayActivity(controller: InspectorController, dialogs: NativeDialogs) {
  const data = controller.state.data;
  const boundary = data.next_event_id ?? data.snapshot_boundary;
  if (typeof boundary !== 'number' || typeof data.replay_context !== 'string') {
    await dialogs.show('Activity', 'Refresh to load a current activity snapshot first.');
    return;
  }
  await controller.load({ since_event_id: boundary, replay_context: data.replay_context, cursor: undefined });
}

/** Native-only caller supplies dialogs. No model-callable handler can grant owner confirmation. */
export async function runInspectorAction(controller: InspectorController, nativeDialogs: NativeDialogs, action: string, row?: InspectorRow, registerFile?: (path: string, mode: 'read' | 'write') => Promise<string>) {
  registerFile ??= (path, mode) => controller.registerFile(path, mode);
  const epoch = controller.contextVersion;
  const live = () => controller.activeContext && controller.contextVersion === epoch;
  const dialogs: NativeDialogs = {
    input: async (title, value) => { const answer = await nativeDialogs.input(title, value); return live() ? answer : undefined; },
    select: async (title, choices) => { const answer = await nativeDialogs.select(title, choices); return live() ? answer : undefined; },
    confirm: async (title, message) => { const answer = await nativeDialogs.confirm(title, message); return live() && answer; },
    show: async (title, message) => { if (live()) await nativeDialogs.show(title, message); },
  };
  const input = (title: string, value?: string) => dialogs.input(title, value);
  const candidate = row?.id ?? row?.memory_id;
  const memory = typeof candidate === 'number' || typeof candidate === 'string' ? candidate : undefined;
  const revision = row?.revision;
  const change = async (kind: string, fields: Record<string, unknown>, operation = 'preview_change', commit?: string) => {
    if (!live()) return;
    await controller.preview(operation, { kind, ...(memory !== undefined ? { memory_id: memory, expected_revision: revision } : {}), ...fields }, commit);
    if (!live()) return;
    if (!controller.state.preview) return;
    const result = await controller.commit(preview => dialogs.confirm('Confirm Luminary change', JSON.stringify(preview, null, 2)));
    if (result?.status === 'ok' && kind === 'correct' && typeof result.data?.memory_id === 'number' && live()) await controller.detail(result.data.memory_id);
  };
  switch (action) {
    case 'Refresh': await controller.load(); break;
    case 'Check new activity': await replayActivity(controller, dialogs); break;
    case 'Search / filters': {
      if (!inspectorCanSearch(controller)) { await dialogs.show('Memory search', 'Search is available in Memories, Evidence & History, and Review & Maintenance. No filter was applied to this view.'); return; }
      const query = await input('Search memory (empty clears)'); if (query === undefined) return;
      const tags = await input('Filter tags (comma separated; empty clears)'); if (tags === undefined) return;
      const status = await dialogs.select('Status', ['active', 'candidate', 'conflicted', 'superseded', 'expired', 'deleted', 'all']); if (!status) return;
      const statuses = status === 'all' ? ['active', 'candidate', 'conflicted', 'superseded', 'expired', 'deleted'] : [status];
      await controller.load({ query, tags: tags.split(',').map(t => t.trim()).filter(Boolean), statuses, cursor: undefined }); break;
    }
    case 'Next page': if (controller.state.tab === 'activity' && controller.state.data.replayed && controller.state.data.has_more) await replayActivity(controller, dialogs); else if (controller.state.data.next_cursor) await controller.load({ cursor: controller.state.data.next_cursor }); else await dialogs.show('Pagination', 'No further page.'); break;
    case 'Select project': {
      // Selection is always reachable from a shared view, including after grants change.
      controller.selectProject(undefined);
      const version = controller.contextVersion;
      const result = await controller.execute('browse', { view: 'projects' });
      const projects = Array.isArray(result?.data?.projects) ? result.data.projects as Record<string, unknown>[] : [];
      if (!controller.activeContext || controller.contextVersion !== version) return;
      const labels = projects.map((p, index) => `${index + 1}. ${p.workspace_id ?? p.project_id}`);
      const selected = await nativeDialogs.select('Explicit project resource', ['Own native project', ...labels]);
      if (!selected || !controller.activeContext || controller.contextVersion !== version) return;
      if (selected !== 'Own native project') {
        const project = projects[labels.indexOf(selected)];
        if (typeof project?.selection_handle !== 'string') return;
        controller.selectProject(project.selection_handle);
      }
      await controller.load(); break;
    }
    case 'Create memory': { const content = await input('New durable memory'); if (content?.trim()) await change('create', { content }); break; }
    case 'Inspect': if (memory !== undefined) { await controller.detail(memory); await dialogs.show('Memory ownership, permissions and detail', JSON.stringify(controller.state.data, null, 2)); } break;
    case 'Correct': { if (memory === undefined) return; const detail = await controller.detail(memory); const current = detail?.data?.memory as InspectorRow | undefined; if (!live() || detail?.status !== 'ok' || !current) return; const content = await input('Versioned correction', String(current.content ?? '')); if (content?.trim()) await change('correct', { content, expected_revision: current.revision }); break; }
    case 'Tags': { const value = await input('Tags (comma separated)', Array.isArray(row?.tags) ? row.tags.join(', ') : ''); if (value !== undefined) await change('tag', { tags: value.split(',').map(t => t.trim()).filter(Boolean) }); break; }
    case 'Core designation': { const value = await dialogs.select('Core memory', ['Core', 'Ordinary']); if (value) await change('core', { pinned: value === 'Core' }); break; }
    case 'Retract': await change('retract', {}); break;
    case 'History': {
      if (memory === undefined) return;
      let cursor: unknown;
      while (live()) {
        const page = await controller.execute('history', { memory_id: memory, limit: 50, ...(cursor ? { cursor } : {}) });
        if (!live() || !page) return;
        await dialogs.show('Durable memory history', JSON.stringify({ status: page.status, ...page.data, error: page.error }, null, 2));
        cursor = page.data?.next_cursor;
        if (!cursor || await dialogs.select('History pages', ['Next page', 'Back']) !== 'Next page') break;
      }
      if (live()) await controller.load();
      break;
    }
    case 'Expand evidence': if (memory !== undefined) { await controller.execute('detail', { memory_id: memory, expand: 'evidence', limit: 50 }); await dialogs.show('Evidence expansion', JSON.stringify(controller.state.data, null, 2)); } break;
    case 'Expand source episodes': if (memory !== undefined) { await controller.execute('detail', { memory_id: memory, expand: 'episodes', limit: 50 }); await dialogs.show('Explicit source episode expansion', JSON.stringify(controller.state.data, null, 2)); } break;
    case 'Claims / conflicts': if (memory !== undefined) { await controller.execute('detail', { memory_id: memory, expand: 'claims', limit: 50 }); await dialogs.show('Claims and conflicts', JSON.stringify(controller.state.data, null, 2)); } break;
    case 'Lineage': if (memory !== undefined) { await controller.execute('detail', { memory_id: memory, expand: 'lineage', limit: 50 }); await dialogs.show('Correction lineage', JSON.stringify(controller.state.data, null, 2)); } break;
    case 'Explore entity': {
      const nodes = Array.isArray(controller.state.data.nodes) ? controller.state.data.nodes as InspectorRow[] : [];
      const choices = nodes.map((node, index) => `${index + 1}. ${node.label ?? node.id}`.replace(/[\u0000-\u001f\u007f-\u009f]/g, ' '));
      if (!choices.length) { await dialogs.show('Relations', 'This authorized page has no entities.'); break; }
      const selected = await dialogs.select('Explore authorized entity', choices);
      const node = selected ? nodes[choices.indexOf(selected)] : undefined;
      if (node && typeof node.id === 'number' && live()) await controller.load({ entity_id: node.id, cursor: undefined });
      break;
    }
    case 'All relations': await controller.load({ entity_id: undefined, cursor: undefined }); break;
    case 'Inspect supporting memory':
      if (typeof row?.memory_id === 'number') {
        await controller.detail(row.memory_id);
        await dialogs.show('Supporting memory and recorded evidence', JSON.stringify(controller.state.data, null, 2));
        if (live()) await controller.load();
      }
      break;
    case 'View projection': case 'Event details': case 'Adjacency details': await dialogs.show(action, JSON.stringify(action === 'View projection' ? controller.state.data : row ?? controller.state.data, null, 2)); break;
    case 'Preview maintenance': { const kind = await dialogs.select('Manual maintenance proposal', ['prune', 'cleanup_expired']); if (kind) await change(kind, {}, 'maintenance_preview'); break; }
    case 'Resolve conflict': { if (memory === undefined) return; const detail = await controller.detail(memory); const current = detail?.data?.memory as InspectorRow | undefined; const token = detail?.data?.conflict_set_token; if (!live() || detail?.status !== 'ok' || typeof token !== 'string' || !current) return; await change('resolve_conflict', { memory_id: memory, expected_revision: current.revision, expected_conflict_set_token: token }); break; }
    case 'Project information': { const result = await controller.execute('browse', { view: 'sharing' }); if (live() && result?.status === 'ok') await dialogs.show('Project information and explicit rights', JSON.stringify(result.data, null, 2)); break; }
    case 'Grant rights': { const recipient_agent_id = await input('Agent receiving explicit project rights'); if (!recipient_agent_id) return; const capabilities: string[] = []; for (const right of ['read', 'contribute', 'edit', 'retract']) { if (await dialogs.confirm(`Grant ${right}?`, `Independently grant ${right} to ${recipient_agent_id} in this project?`)) capabilities.push(right); if (!live()) return; } if (!capabilities.length) { await dialogs.show('No rights selected', 'No grant was proposed. Existing rights are unchanged.'); return; } await change('grant', { recipient_agent_id, capabilities }, 'preview_change', 'grant'); break; }
    case 'Revoke rights': { const recipient_agent_id = await input('Agent to revoke'); if (recipient_agent_id) await change('revoke', { recipient_agent_id }, 'preview_change', 'revoke'); break; }
    case 'Bind location': { const host_id = await input('Explicit host ID'); if (!host_id) return; const profile_id = await input('Explicit profile ID'); if (!profile_id) return; const workspace = await input('Absolute project location on that host'); if (workspace) await change('bind_location', { location: { host_id, profile_id, workspace } }); break; }
    case 'Change setting': {
      const settings = controller.state.data;
      const keys = Array.isArray(settings.editable) ? settings.editable.filter((key): key is string => typeof key === 'string') : [];
      if (!keys.length) { await dialogs.show('Settings', 'This host exposes no editable settings. Saving configuration is unchanged.'); return; }
      const key = await dialogs.select('Editable setting', keys); if (!key) return;
      const values = settings.values as Record<string, unknown> | undefined;
      const value = await input(`New ${key} value (JSON)`, values?.[key] === undefined ? undefined : JSON.stringify(values[key]));
      if (value === undefined) return;
      let parsed: unknown;
      try { parsed = JSON.parse(value); }
      catch { await dialogs.show('Invalid setting', 'Enter a JSON string, number, boolean, array or object.'); return; }
      await change('set_settings', { changes: { [key]: parsed }, expected_revision: settings.revision }, 'preview_change', 'set_settings');
      break;
    }
    case 'Readiness / diagnostics': await controller.execute('get_settings', { diagnostics: true }); break;
    case 'Export records': case 'Import records': { if (!registerFile) { await dialogs.show('Data transfer unavailable', 'This host has no trusted file-selection transport. No file was read or written.'); return; } const direction = action === 'Import records' ? 'import' : 'export'; const path = await input(direction === 'import' ? 'Select existing memory-record file (absolute path)' : 'Select output memory-record file (absolute path)'); if (!path) return; try { const file_handle = await registerFile(path, direction === 'import' ? 'read' : 'write'); await change('transfer', { direction, file_handle }, 'transfer_preview'); } catch { await dialogs.show('File selection failed', 'The native server could not register this file. No transfer was committed.'); } break; }
    case 'Backup limitations': await dialogs.show('Data transfer', 'Memory-record export is not a full store backup. It does not back up backend configuration, secrets, raw source episodes or native host state. The preview reports exact authorized coverage.'); break;
    case 'Explain with AI': if (await dialogs.confirm('Optional AI explanation', 'Request a disclosure preview for this authorized Summary? No model call runs until you confirm that disclosure.')) await change('explain', { phase: 'preview' }, 'explain', 'explain'); break;
  }
}
