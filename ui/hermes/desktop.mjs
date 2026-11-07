import * as React from 'react';
import { host, useValue, gatewayActivationEpoch, ROUTES_AREA, SIDEBAR_NAV_AREA, PANES_AREA } from '@hermes/plugin-sdk';
import { createInspectorView } from './console.mjs';

export default {
  id: 'luminary-inspector',
  name: 'Luminary Inspector',
  defaultEnabled: false,
  register(ctx) {
    function useNativeContext() {
      const session = useValue(host.state.focusedStoredSessionId);
      const profile = useValue(host.state.focusedSessionProfile);
      const gateway = useValue(host.state.gateway);
      const [epoch, setEpoch] = React.useState(gatewayActivationEpoch());
      React.useEffect(() => {
        const stop = ctx.setInterval(() => setEpoch(gatewayActivationEpoch()), 200);
        return stop;
      }, []);
      return { session: session || '', epoch, key: `${epoch}:${profile}:${gateway}:${session || ''}` };
    }
    async function send(path, body, native, signal) {
      const epoch = gatewayActivationEpoch();
      const check = () => {
        if (signal?.aborted || !native || native.epoch !== epoch || gatewayActivationEpoch() !== epoch) {
          throw new Error('Native gateway changed; reopen the inspector');
        }
      };
      check();
      let result;
      if (path === '/upload') {
        const file = body.file;
        if (!file || file.size > 4 * 1024 * 1024) throw new Error('Choose one file up to 4 MiB');
        const bytes = new Uint8Array(await file.arrayBuffer());
        check();
        result = { status: 'ok', data: await ctx.rest(`/upload?session_ref=${encodeURIComponent(body.session_ref)}`,
          { method: 'POST', upload: { filename: file.name, contentType: file.type || 'application/octet-stream', bytes }, timeoutMs: 60000 }) };
      } else if (path === '/export-handle') {
        result = { status: 'ok', data: await ctx.rest(path, { method: 'POST', body }) };
      } else if (path.startsWith('/download/')) {
        const downloaded = await ctx.rest(`${path}?session_ref=${encodeURIComponent(body.session_ref)}&encoding=base64`);
        check();
        result = { status: 'ok', data: { filename: downloaded.filename,
          download_bytes: Uint8Array.from(atob(downloaded.bytes_base64), character => character.charCodeAt(0)) } };
      } else {
        result = await ctx.rest(path, body ? { method: 'POST', body, timeoutMs: 60000 } : {});
      }
      check();
      return result;
    }
    const Inspector = createInspectorView(React, useNativeContext, send, listener => {
      const stop = ctx.onEvent('plugin.luminary-inspector.access-revoked', listener);
      return stop;
    });
    ctx.registerMany([
      { id: 'pane', area: PANES_AREA, title: 'Luminary', data: { placement: 'right', width: '420px' },
        render: () => React.createElement(Inspector, { compact: true }) },
      { id: 'page', area: ROUTES_AREA, data: { path: '/luminary-inspector' },
        render: () => React.createElement(Inspector) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/luminary-inspector', label: 'Luminary Inspector', codicon: 'database' } },
    ]);
    ctx.registerSettingsPage({ id: 'settings', title: 'Luminary Inspector',
      render: () => React.createElement(Inspector, { initialTab: 'settings' }) });
  },
};
