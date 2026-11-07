export type ConsoleStatus = 'ok' | 'empty' | 'invalid_request' | 'denied' | 'conflict' | 'unavailable' | 'unsupported' | 'cancelled' | 'unknown_outcome';
export interface ConsoleRequest { operation: string; session_ref?: string; selection_handle?: string; arguments: Record<string, unknown>; request_id: string }
export interface ConsoleResult { status: ConsoleStatus; data: Record<string, unknown> | null; error: { code: string; message: string } | null; request_id: string; context_epoch: string; policy_revision: number; as_of: string }
export interface NativeInspectorContext { agent: 'pi' | 'omp' | 'opencode' | 'hermes'; workspace: string; session_id: string; host_id?: string; profile_id?: string }
export interface ConsoleTransport { request(request: ConsoleRequest, signal?: AbortSignal): Promise<ConsoleResult>; confirm?(preview_id: string, signal?: AbortSignal): Promise<ConsoleResult>; registerFile?(path: string, mode: 'read' | 'write', signal?: AbortSignal): Promise<string> }
export const TABS = [
  { id: 'memories', label: 'Memories', operation: 'browse' },
  { id: 'activity', label: 'Activity', operation: 'events' },
  { id: 'evidence', label: 'Evidence & History', operation: 'browse' },
  { id: 'relations', label: 'Relations', operation: 'graph' },
  { id: 'maintenance', label: 'Review & Maintenance', operation: 'browse' },
  { id: 'sharing', label: 'Sharing & Workspaces', operation: 'browse' },
  { id: 'settings', label: 'Settings & Diagnostics', operation: 'get_settings' },
  { id: 'transfer', label: 'Data Transfer', operation: 'browse' },
  { id: 'summary', label: 'Summary', operation: 'summary' },
] as const;
export type TabID = typeof TABS[number]['id'];
