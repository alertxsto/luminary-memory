// Pi inspector surface styled after Zentui (github.com/lmilojevicc/pi-zentui, MIT):
// one quiet ledger — a single accent rail on the selected row, a numbered section
// strip, hairline dividers and a compact key line. Zentui owns Pi's editor,
// transcript and footer; this view renders only Luminary's overlay and never
// takes those host surfaces over.
import { visibleWidth } from "@earendil-works/pi-tui";
import { TABS } from "../common/console-contract.js";
import type { InspectorController } from "../common/console-controller.js";
import {
  inspectorCanSearch,
  inspectorContextLine,
  inspectorRowContent,
  inspectorRows,
  inspectorSummaryLines,
  type InspectorRow,
} from "../common/console-actions.js";
import type { InspectorIntent } from "../common/terminal-view.js";

type InspectorKey =
  | "escape"
  | "ctrl+c"
  | "tab"
  | "right"
  | "shift+tab"
  | "left"
  | "up"
  | "down"
  | "pageUp"
  | "pageDown"
  | "enter";

type ColorRole = "accent" | "muted" | "warning";

/** Luminary's inspector, drawn as a compact ledger. */
export class ZentuiInspectorView {
  selected = 0;
  offset = 0;
  private rowStart = 0;
  private rowCount = 0;
  private tabRanges: { start: number; end: number; index: number }[] = [];

  constructor(
    readonly controller: InspectorController,
    private key: (data: string, key: InspectorKey) => boolean,
    private truncate: (text: string, width: number) => string,
    private color: (role: ColorRole, text: string) => string,
    private finish: (intent: InspectorIntent) => void,
    private repaint: () => void,
    private height: () => number,
  ) {}

  /**
   * Decode raw terminal input first, then fall back to the host matcher.
   *
   * The host's key names differ between Pi releases and a custom overlay does
   * not always receive them, so the sequences a terminal actually sends decide
   * navigation. Returning true tells the host the key was consumed.
   */
  handleInput(data: string): boolean {
    const rows = inspectorRows(this.controller);
    const is = (key: InspectorKey, ...sequences: string[]) =>
      sequences.includes(data) || this.key(data, key);
    const close = is("escape", "\u001b", "q") || is("ctrl+c", "\u0003");
    const nextSection = is("tab", "\t", "\u001b[C") || is("right");
    const previousSection = is("shift+tab", "\u001b[Z") || is("left", "\u001b[D");
    const up = is("up", "\u001b[A") || data === "k";
    const down = is("down", "\u001b[B") || data === "j";
    const pageUp = is("pageUp", "\u001b[5~") || data === "\u001b[1;5A";
    const pageDown = is("pageDown", "\u001b[6~") || data === "\u001b[1;5B";
    const confirm = is("enter", "\r", "\n") || data === "a";

    if (close) this.finish({ type: "close" });
    else if (nextSection || previousSection) {
      const index = TABS.findIndex((tab) => tab.id === this.controller.state.tab);
      const step = previousSection ? -1 : 1;
      this.selected = 0;
      this.offset = 0;
      void this.controller.selectTab(TABS[(index + step + TABS.length) % TABS.length].id);
    } else if (/^[1-9]$/.test(data) && Number(data) <= TABS.length) {
      this.selected = 0;
      this.offset = 0;
      void this.controller.selectTab(TABS[Number(data) - 1].id);
    } else if (up) {
      if (rows.length) this.selected = Math.max(0, this.selected - 1);
      else this.offset = Math.max(0, this.offset - 1);
    } else if (down) {
      if (rows.length) this.selected = Math.min(Math.max(0, rows.length - 1), this.selected + 1);
      else this.offset++;
    } else if (pageUp) {
      this.selected = Math.max(0, this.selected - 10);
    } else if (pageDown) {
      this.selected = rows.length ? Math.min(rows.length - 1, this.selected + 10) : this.offset + 10;
    } else if (confirm) this.finish({ type: "actions", row: rows[this.selected] });
    else if (data === "/") this.finish({ type: "search" });
    else if (data === "r") this.finish({ type: "refresh" });
    else if (data === "t") this.finish({ type: "tabs" });
    else if (data === "c") this.finish({ type: "compact" });
    this.repaint();
    return true;
  }

  /** Pi forwards these normalized events only when its native fullscreen routes them. */
  handleMouse(event: { type: string; button: string; x: number; y: number; wheelDelta?: number; clickCount?: number }) {
    if (event.type === "wheel") {
      const rows = inspectorRows(this.controller);
      const delta = event.wheelDelta ?? 0;
      if (rows.length) this.selected = Math.max(0, Math.min(rows.length - 1, this.selected + delta));
      else this.offset = Math.max(0, this.offset + delta);
      this.repaint();
      return { handled: true };
    }
    if (event.type !== "click" || event.button !== "left") return;
    if (event.y === 2) {
      const tab = this.tabRanges.find((range) => event.x >= range.start && event.x < range.end);
      if (tab) {
        this.selected = 0;
        this.offset = 0;
        void this.controller.selectTab(TABS[tab.index].id);
      } else this.finish({ type: "tabs" });
      return { handled: true, focus: true };
    }
    const index = event.y - this.rowStart;
    if (index < 0 || index >= this.rowCount) return;
    this.selected = this.offset + index;
    if ((event.clickCount ?? 1) > 1) this.finish({ type: "actions", row: inspectorRows(this.controller)[this.selected] });
    this.repaint();
    return { handled: true, focus: true };
  }

  private line(text: string, width: number, role?: ColorRole): string {
    const body = this.truncate(text, Math.max(1, width));
    const padding = " ".repeat(Math.max(0, width - visibleWidth(body)));
    return (role ? this.color(role, body) : body) + padding;
  }

  private divider(width: number): string {
    return this.color("muted", "─".repeat(Math.max(1, width)));
  }

  private tabStrip(width: number): string {
    const lines: string[] = [];
    this.tabRanges = [];
    let column = 1;
    let line = "";
    let clipped = false;
    for (const [index, tab] of TABS.entries()) {
      const label = `${index + 1} ${tab.label}`;
      const active = tab.id === this.controller.state.tab;
      const rendered = active ? this.color("accent", `▎${label}`) : `  ${label}`;
      const size = visibleWidth(rendered);
      if (column + size > width) {
        clipped = true;
        break;
      }
      this.tabRanges.push({ start: column, end: column + size, index });
      line += `${rendered}  `;
      column += size + 2;
    }
    // The rest stay reachable with Tab; say so rather than hiding them silently.
    if (clipped && column + 1 <= width) line += this.color("muted", "…");
    lines.push(` ${line.trimEnd()}`);
    return lines[0];
  }

  private fitRow(row: InspectorRow, width: number): string {
    const permissions = row.permissions
      ? Object.keys(row.permissions).filter((name) => row.permissions?.[name]).join(" ")
      : "";
    const id = String(row.id ?? row.event_id ?? "");
    const left = `${id.padStart(3)}  ${inspectorRowContent(row)}`;
    if (!permissions) return left;
    const mark = `  ${permissions}`;
    const room = width - visibleWidth(left) - visibleWidth(mark);
    // Drop the trailing badge first: the record itself is what the user acts on.
    return room > 0 ? `${left}${" ".repeat(room)}${this.color("muted", mark)}` : left;
  }

  render(width: number): string[] {
    const state = this.controller.state;
    const tab = TABS.find((item) => item.id === state.tab)!;
    const status = state.busy ? "loading" : state.status;
    const project = this.controller.selectionHandle ? "shared" : "native";
    const right = `policy ${state.policy_revision ?? "—"} · ${project}`;
    const title = ` 🌙 Luminary · ${tab.label} · ${status}`;
    const gap = Math.max(1, width - visibleWidth(title) - visibleWidth(right));
    const lines: string[] = [title + " ".repeat(gap) + this.color("muted", right), this.divider(width)];
    lines.push(this.line(this.tabStrip(width), width));
    lines.push(this.divider(width));

    const context = inspectorContextLine(this.controller);
    if (context) lines.push(this.line(` ${this.color("muted", context)}`, width));

    const rows = inspectorRows(this.controller);
    const footer = 2 + (state.error ? 1 : 0) + inspectorSummaryLines(this.controller).length;
    const available = Math.max(1, this.height() - lines.length - footer - 1);
    this.rowStart = lines.length + 1;
    this.rowCount = Math.min(rows.length, available);
    this.selected = Math.min(this.selected, Math.max(0, rows.length - 1));

    if (rows.length) {
      this.offset = Math.max(0, Math.min(this.offset, this.selected));
      if (this.selected >= this.offset + available) this.offset = this.selected - available + 1;
      for (const [index, row] of rows.slice(this.offset, this.offset + available).entries()) {
        const position = this.offset + index;
        const text = this.fitRow(row, Math.max(1, width - 3));
        lines.push(position === this.selected
          ? this.color("accent", ` ❯ ${text}`)
          : `   ${text}`);
      }
    } else if (state.tab === "activity") {
      const message = state.data.gap === true
        ? " Activity history is incomplete · r reloads"
        : " No activity recorded in this authorized scope";
      lines.push(this.line(message, width, state.data.gap === true ? "warning" : "muted"));
    } else {
      const projection = Object.fromEntries(
        Object.entries(state.data).filter(
          ([name]) => name !== "native_context" && (state.tab !== "summary" || name !== "totals" || !state.data.totals),
        ),
      );
      const body = Object.keys(projection).length
        ? JSON.stringify(projection, null, 2).split("\n")
        : [" Nothing in this authorized view."];
      this.offset = Math.min(this.offset, Math.max(0, body.length - available));
      for (const line of body.slice(this.offset, this.offset + available)) {
        lines.push(this.line(` ${line}`, width));
      }
    }

    if (state.error) lines.push(this.line(` ${state.error}`, width, "warning"));
    for (const line of inspectorSummaryLines(this.controller)) {
      lines.push(this.line(` ${this.color("muted", line)}`, width));
    }
    lines.push(this.divider(width));
    const search = inspectorCanSearch(this.controller) ? " · / filter" : "";
    const full = `↑↓ move · ↵ actions${search} · ⇥ section · 1-${TABS.length} jump · r reload · c compact · esc close`;
    const compact = `↑↓ · ↵${search} · ⇥ · r · c · esc`;
    const minimal = "↑↓ ↵ ⇥ esc";
    const help = visibleWidth(full) + 1 <= width ? full : visibleWidth(compact) + 1 <= width ? compact : minimal;
    lines.push(this.line(` ${help}`, width, "muted"));
    // Every line owns exactly one terminal row; short rows are padded here so
    // the host never paints stale cells from a previous frame.
    return lines.map((line) => this.line(line, Math.max(1, width)));
  }

  invalidate() {
    this.tabRanges = [];
    this.rowCount = 0;
  }

  /** Focus hooks: a custom overlay may be asked to take or yield input. */
  focus() {
    this.repaint();
  }

  blur() {}

}
