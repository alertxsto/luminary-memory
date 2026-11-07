import { createInspectorView } from './console.mjs';

// Dashboard SDK is deliberately independent from @hermes/plugin-sdk. The
// dashboard registry unmounts/forgets profile-owned bundles on profile switch;
// each mounted model disposes pending requests without publishing stale data.
const SDK = window.__HERMES_PLUGIN_SDK__;
const registry = window.__HERMES_PLUGINS__;
if (!SDK?.React || !SDK.fetchJSON || !registry) {
  throw new Error('Luminary Inspector requires the official Hermes dashboard plugin SDK');
}
const React = SDK.React;
const bundleContext = crypto.randomUUID();
function useNativeContext() {
  return { key: bundleContext, session: '' };
}
async function send(path, body, native, signal) {
  signal?.throwIfAborted();
  const url = `/api/plugins/luminary-inspector${path}`;
  if (path === '/upload') {
    if (!body.file || body.file.size > 4 * 1024 * 1024) throw new Error('Choose one file up to 4 MiB');
    const form = new FormData();
    form.append('file', body.file, body.file.name);
    const response = await SDK.authedFetch(`${url}?session_ref=${encodeURIComponent(body.session_ref)}`,
      { method: 'POST', body: form, signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return { status: 'ok', data: await response.json() };
  }
  if (path.startsWith('/download/')) {
    const response = await SDK.authedFetch(`${url}?session_ref=${encodeURIComponent(body.session_ref)}`, { signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    signal?.throwIfAborted();
    return { status: 'ok', data: { download_bytes: bytes, filename: 'luminary-export.json' } };
  }
  const result = await SDK.fetchJSON(url, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  } : { signal });
  return path === '/export-handle' ? { status: 'ok', data: result } : result;
}
const Inspector = createInspectorView(React, useNativeContext, send);
registry.register('luminary-inspector', () => React.createElement(Inspector));
registry.registerSlot('luminary-inspector', 'sidebar', () => React.createElement(Inspector, { compact: true }));
