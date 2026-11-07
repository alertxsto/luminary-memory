import { TABS, type ConsoleResult, type ConsoleStatus, type ConsoleTransport, type TabID } from './console-contract.js';
export interface InspectorState { tab: TabID; status: ConsoleStatus; busy: boolean; data: Record<string, unknown>; preview?: Record<string, unknown>; error?: string; as_of?: string; policy_revision?: number; context_epoch?: string }
/** One active view per native session; no process, storage, browser or model side effects. */
export class InspectorController {
  state: InspectorState = { tab: 'memories', status: 'empty', busy: false, data: {} };
  private epoch = 0;
  private serial = 0;
  private active?: AbortController;
  private disposed = false;
  private listeners = new Set<(state: InspectorState) => void>();
  private query: Record<string, unknown> = {};
  selectionHandle?: string;
  private proposal?: { operation: string; epoch: number; preview: Record<string, unknown>; deciding: boolean };
  constructor(private transport: ConsoleTransport) {}
  get contextVersion() { return this.epoch; }
  get activeContext() { return !this.disposed; }
  async registerFile(path: string, mode: 'read' | 'write') {
    if (!this.transport.registerFile || this.disposed) throw new Error('Trusted native file registration unavailable');
    const epoch = this.epoch;
    const handle = await this.transport.registerFile(path, mode);
    if (epoch !== this.epoch || this.disposed) throw new Error('File selection belongs to an expired native context');
    return handle;
  }
  subscribe(listener: (state: InspectorState) => void): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  private publish(patch: Partial<InspectorState>) { if (this.disposed) return; this.state = { ...this.state, ...patch }; for (const listener of this.listeners) listener(this.state); }
  private invalidate() { this.epoch++; this.serial++; this.active?.abort(); this.active = undefined; this.proposal = undefined; }
  switchContext(transport: ConsoleTransport) { this.invalidate(); this.transport = transport; this.query = {}; this.selectionHandle = undefined; this.publish({ data: {}, preview: undefined, error: undefined, busy: false, status: 'empty', context_epoch: undefined, policy_revision: undefined, as_of: undefined }); }
  selectProject(selectionHandle: string | undefined) {
    this.invalidate(); this.selectionHandle = selectionHandle; this.query = {};
    this.publish({ data: {}, preview: undefined, error: undefined, busy: false, status: 'empty', context_epoch: undefined, policy_revision: undefined, as_of: undefined });
  }
  cancel() { const writing = this.state.busy && this.writing; this.invalidate(); this.publish({ busy: false, status: writing ? 'unknown_outcome' : 'cancelled', preview: undefined, error: writing ? 'Commit outcome unknown. Refresh Activity before attempting another change; this write was not replayed.' : undefined }); }
  dispose() { this.invalidate(); this.listeners.clear(); this.state = { tab: 'memories', data: {}, busy: false, status: 'cancelled' }; this.disposed = true; }
  private writing = false;
  async execute(operation: string, args: Record<string, unknown> = {}, writing = false): Promise<ConsoleResult | undefined> {
    if (this.disposed) return;
    this.proposal = undefined;
    this.active?.abort(); const active = new AbortController(); this.active = active;
    const epoch = this.epoch; const serial = ++this.serial; this.writing = writing;
    this.publish({ busy: true, preview: undefined, error: undefined });
    const request = { operation, arguments: args, selection_handle: this.selectionHandle, request_id: `inspector-${epoch}-${serial}` };
    try {
      const response = await this.transport.request(request, active.signal);
      if (this.disposed || epoch !== this.epoch || serial !== this.serial) return;
      if (response.request_id !== request.request_id) throw new Error('Mismatched inspector response');
      if (response.status === 'denied') { this.invalidate(); this.publish({ data: {}, preview: undefined, busy: false, status: 'denied', error: response.error?.message, as_of: response.as_of, context_epoch: response.context_epoch, policy_revision: response.policy_revision }); return response; }
      const changedPolicy = this.state.policy_revision !== undefined && response.policy_revision !== this.state.policy_revision;
      const changedContext = this.state.context_epoch !== undefined && response.context_epoch !== this.state.context_epoch;
      if (changedPolicy || changedContext) { this.invalidate(); this.publish({ data: {}, preview: undefined }); }
      this.publish({ busy: false, status: response.status, data: response.status === 'ok' || response.status === 'empty' ? response.data ?? {} : {}, error: response.error?.message, as_of: response.as_of, policy_revision: response.policy_revision, context_epoch: response.context_epoch });
      return response;
    } catch {
      if (this.disposed || epoch !== this.epoch || serial !== this.serial) return;
      this.publish({ busy: false, data: {}, status: writing ? 'unknown_outcome' : active.signal.aborted ? 'cancelled' : 'unavailable', error: writing ? 'Commit outcome unknown. Refresh activity before attempting another change; this write was not replayed.' : 'Inspector transport unavailable.' });
    } finally { if (this.active === active) this.active = undefined; }
  }
  async selectTab(tab: TabID) { this.proposal = undefined; this.query = {}; this.publish({ tab, data: {}, preview: undefined }); return this.load(); }
  load(args: Record<string, unknown> = {}) {
    this.query = { ...this.query, ...args };
    if (this.state.tab === 'activity' && (this.state.data.snapshot_required === true ||
        args.since_event_id === undefined && args.replay_context === undefined && args.cursor === undefined)) {
      delete this.query.since_event_id;
      delete this.query.replay_context;
      delete this.query.cursor;
    }
    const tab = TABS.find(t => t.id === this.state.tab)!;
    return this.execute(tab.operation, { view: tab.id, ...this.query });
  }
  detail(memory_id: number | string) { return this.execute('detail', { memory_id }); }
  async preview(operation: string, args: Record<string, unknown>, commitOperation?: string) {
    this.proposal = undefined; this.publish({ preview: undefined }); const epoch = this.epoch;
    const response = await this.execute(operation, args);
    if (epoch !== this.epoch || response?.status !== 'ok' || !response.data || typeof response.data.preview_id !== 'string') return;
    const commit = commitOperation ?? ({ maintenance_preview: 'maintenance_commit', transfer_preview: 'transfer_commit' }[operation] || 'mutate');
    this.proposal = { operation: commit, epoch, preview: response.data, deciding: false }; this.publish({ preview: response.data });
  }
  async commit(decide: (preview: Record<string, unknown>) => Promise<boolean>) {
    const proposal = this.proposal; if (!proposal || this.disposed || proposal.deciding) return;
    proposal.deciding = true;
    const valid = () => !this.disposed && this.proposal === proposal && this.epoch === proposal.epoch;
    let accepted: boolean;
    try { accepted = await decide(proposal.preview); }
    catch { if (valid()) { this.proposal = undefined; this.publish({ preview: undefined, status: 'cancelled' }); } return; }
    if (!valid()) return;
    if (!accepted) { this.proposal = undefined; this.publish({ preview: undefined, status: 'cancelled' }); return; }
    if (!this.transport.confirm) { this.proposal = undefined; this.publish({ preview: undefined, status: 'unsupported', error: 'Native owner confirmation is unavailable on this transport.' }); return; }
    const active = new AbortController(); this.active?.abort(); this.active = active;
    this.writing = false; this.publish({ busy: true });
    let confirmation: ConsoleResult;
    try { confirmation = await this.transport.confirm(String(proposal.preview.preview_id), active.signal); }
    catch { if (valid()) { this.proposal = undefined; this.publish({ busy: false, status: 'unavailable', error: 'Owner confirmation could not be delivered.', preview: undefined }); } return; }
    finally { if (this.active === active) this.active = undefined; }
    if (!valid()) return;
    const receipt = confirmation.data?.confirmation_receipt;
    this.proposal = undefined; this.publish({ preview: undefined, busy: false });
    if (confirmation.status !== 'ok' || typeof receipt !== 'string') { this.publish({ data: {}, status: confirmation.status === 'ok' ? 'unavailable' : confirmation.status, error: confirmation.error?.message || 'No owner confirmation receipt.' }); return; }
    return this.execute(proposal.operation, { ...(proposal.operation === 'explain' ? { phase: 'commit' } : {}), preview_id: proposal.preview.preview_id, confirmation_receipt: receipt }, true);
  }
}
