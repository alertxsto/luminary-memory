import type { ScrollBoxRenderable } from '@opentui/core';
import type { Context } from '@opencode/plugin/tui/context';
import { createSignal, onCleanup, Show } from 'solid-js';

/** Keep the decision visible while the complete untrusted proposal scrolls. */
export function reviewDialog(context: Context, title: string, message: string, confirmation = false): Promise<boolean> {
  const { promise, resolve } = Promise.withResolvers<boolean>();
  let settled = false;
  const finish = (accepted: boolean) => {
    if (settled) return;
    settled = true;
    resolve(accepted);
    context.ui.dialog.clear();
  };
  context.ui.dialog.show(() => <Review context={context} title={title} message={message} confirmation={confirmation} finish={finish} />,
    () => { if (!settled) { settled = true; resolve(false); } });
  return promise;
}

function Review(props: { context: Context; title: string; message: string; confirmation: boolean; finish(accepted: boolean): void }) {
  const context = props.context;
  context.ui.dialog.set({ size: 'large', centered: true });
  let body: ScrollBoxRenderable | undefined;
  const [accepted, setAccepted] = createSignal(false);
  const [height, setHeight] = createSignal(context.renderer.height);
  const resize = () => setHeight(context.renderer.height);
  context.renderer.on('resize', resize);
  onCleanup(() => context.renderer.off('resize', resize));
  context.keymap.layer(() => ({ mode: 'global', priority: 10, commands: [
    { bind: 'escape', title: 'Cancel review', run: () => props.finish(false) },
    { bind: 'ctrl+c', title: 'Cancel review', run: () => props.finish(false) },
    { bind: 'up', title: 'Scroll review up', run: () => body?.scrollBy(-1) },
    { bind: 'down', title: 'Scroll review down', run: () => body?.scrollBy(1) },
    { bind: 'pageup', title: 'Previous review page', run: () => body?.scrollBy(-Math.max(1, height() - 14)) },
    { bind: 'pagedown', title: 'Next review page', run: () => body?.scrollBy(Math.max(1, height() - 14)) },
    { bind: 'home', title: 'Review beginning', run: () => body?.scrollTo(0) },
    { bind: 'end', title: 'Review ending', run: () => body?.scrollTo(body.scrollHeight) },
    { bind: 'left', title: 'Select cancel', run: () => setAccepted(false) },
    { bind: 'right', title: 'Select confirm', run: () => setAccepted(true) },
    { bind: 'tab', title: 'Toggle review decision', run: () => setAccepted(value => !value) },
    { bind: 'enter', title: 'Apply review decision', run: () => props.finish(props.confirmation && accepted()) },
  ] }));
  // Preserve every printable character and line; stored terminal controls are data.
  const message = props.message.replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g, ' ');
  return <box flexDirection="column" width="100%" paddingLeft={2} paddingRight={2} paddingTop={1} paddingBottom={1}>
    <text fg={context.theme.text.base}>{props.title}</text>
    <scrollbox ref={body} height={Math.max(3, height() - 14)} width="100%" scrollX={false}>
      <text fg={context.theme.text.base}>{message}</text>
    </scrollbox>
    <text fg={context.theme.text.muted}>↑↓ scroll · PgUp/PgDn · Home/End</text>
    <Show when={props.confirmation} fallback={<text fg={context.theme.text.base} onMouseDown={() => props.finish(false)}>Enter / Esc: Back</text>}>
      <box flexDirection="row" gap={2}>
        <text fg={context.theme.text.base} onMouseDown={() => props.finish(false)}>{accepted() ? 'Cancel' : '› Cancel'}</text>
        <text fg={context.theme.text.base} onMouseDown={() => props.finish(true)}>{accepted() ? '› Confirm' : 'Confirm'}</text>
      </box>
      <text fg={context.theme.text.muted}>←/→ choose · Enter apply · Esc cancel</text>
    </Show>
  </box>;
}
