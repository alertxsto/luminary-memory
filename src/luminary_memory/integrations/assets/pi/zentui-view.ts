// Pi inspector surface styled after Zentui (github.com/lmilojevicc/pi-zentui, MIT):
// framed cards, an accent rail on the selected row, a numbered section strip and
// a compact key-help footer. The layout is written here, not copied: Zentui's
// components own Pi's editor, transcript and footer, while this view renders one
// overlay and must never take over those host surfaces.
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

/** Zentui-style frame for the Luminary inspector. One card, one accent rail. */
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

  handleInput(data: string) {
    const rows = inspectorRows(this.controller);
    if (this.key(data, "escape") || this.key(data, "ctrl+c")) this.finish({ type: "close" });
    else if (this.key(data, "tab") || this.key(data, "right") || this.key(data, "shift+tab") || this.key(data, "left")) {
      const direction = this.key(data, "shift+tab") || this.key(data, "left") ? -1 : 1;
      const index = TABS.findIndex((tab) => tab.id === this.controller.state.tab);
      this.selected = 0;
      this.offset = 0;
      void this.controller.selectTab(TABS[(index + direction + TABS.length) % TABS.length].id);
    } else if (this.key(data, "up") || data === "k") {
      if (rows.length) this.selected = Math.max(0, this.selected - 1);
      else this.offset = Math.max(0, this.offset - 1);
    } else if (this.key(data, "down") || data === "j") {
      if (rows.length) this.selected = Math.min(Math.max(0, rows.length - 1), this.selected + 1);
      else this.offset++;
    } else if (this.key(data, "pageUp")) {
      if (rows.length) this.selected = Math.max(0, this.selected - 10);
      else this.offset = Math.max(0, this.offset - 10);
    } else if (this.key(data, "pageDown")) {
      if (rows.length) this.selected = Math.min(Math.max(0, rows.length - 1), this.selected + 10);
      else this.offset += 10;
    } else if (this.key(data, "enter") || data === "a") this.finish({ type: "actions", row: rows[this.selected] });
    else if (data === "/") this.finish({ type: "search" });
    else if (data === "r") this.finish({ type: "refresh" });
    else if (data === "t") this.finish({ type: "tabs" });
    else if (data === "c") this.finish({ type: "compact" });
    this.repaint();
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
    if (event.y === 1) {
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

  private inner(line: string, width: number, role: ColorRole = "muted"): string {
    const body = Math.max(1, width - 2);
    const text = this.truncate(line, body);
    const padding = " ".repeat(Math.max(0, body - visibleWidth(text)));
    return this.color(role, "│") + text + padding + this.color(role, "│");
  }

  private rule(left: string, right: string, width: number, corner: [string, string]): string {
    const body = Math.max(1, width - 2);
    const tail = right ? ` ${right} ─` : "─";
    const lead = `─ ${left} `;
    if (visibleWidth(lead) + visibleWidth(tail) > body) {
      const text = this.truncate(`─ ${left}`, Math.max(0, body - 1));
      return this.color(
        "muted",
        corner[0] + text + "─".repeat(Math.max(0, body - visibleWidth(text))) + corner[1],
      );
    }
    return this.color(
      "muted",
      corner[0] + lead + "─".repeat(body - visibleWidth(lead) - visibleWidth(tail)) + tail + corner[1],
    );
  }

  private tabStrip(width: number): string {
    const body = Math.max(1, width - 2);
    let line = "";
    this.tabRanges = [];
    // Inner text starts at screen column 1; this string opens with one space.
    let column = 2;
    for (const [index, tab] of TABS.entries()) {
      const label = `${index + 1} ${tab.label}`;
      const active = tab.id === this.controller.state.tab;
      const rendered = active ? this.color("accent", `▎${label}`) : `  ${label}`;
      const size = visibleWidth(rendered);
      if (column + size > body + 1) break;
      this.tabRanges.push({ start: column, end: column + size, index });
      line += rendered + " ";
      column += size + 1;
    }
    return ` ${line.trimEnd()}`;
  }

  render(width: number): string[] {
    const state = this.controller.state;
    const tab = TABS.find((item) => item.id === state.tab)!;
    const lines: string[] = [];
    const status = state.busy ? "loading" : state.status;
    lines.push(this.rule(`Luminary · ${tab.label}`, status, width, ["╭", "╮"]));

    const project = this.controller.selectionHandle ? "shared selection" : "native project";
    lines.push(this.inner(` ${project} · policy ${state.policy_revision ?? "—"} · ${state.as_of ?? ""}`, width));
    const context = inspectorContextLine(this.controller);
    if (context) lines.push(this.inner(` ${this.color("muted", context)}`, width));
    lines.push(this.inner("", width));
    lines.push(this.inner(this.tabStrip(width), width));
    lines.push(this.inner("", width));

    const rows = inspectorRows(this.controller);
    const chrome = lines.length + 3;
    const available = Math.max(1, this.height() - chrome);
    this.rowStart = lines.length;
    this.rowCount = Math.min(rows.length, available);
    this.selected = Math.min(this.selected, Math.max(0, rows.length - 1));

    if (rows.length) {
      this.offset = Math.max(0, Math.min(this.offset, this.selected));
      if (this.selected >= this.offset + available) this.offset = this.selected - available + 1;
      for (const [index, row] of rows.slice(this.offset, this.offset + available).entries()) {
        const position = this.offset + index;
        const permissions = row.permissions
          ? ` [${Object.keys(row.permissions).filter((name) => row.permissions?.[name]).join(",")}]`
          : "";
        const label = ` ${row.id ?? row.event_id ?? ""} ${inspectorRowContent(row)}${permissions}`;
        lines.push(position === this.selected ? this.inner(this.color("accent", `▎${label}`), width) : this.inner(label, width));
      }
    } else if (state.tab === "activity") {
      lines.push(this.inner(state.data.gap === true ? " Activity history is incomplete. r: reload" : " No activity recorded in this authorized scope.", width, state.data.gap === true ? "warning" : "muted"));
    } else {
      const projection = Object.fromEntries(
        Object.entries(state.data).filter(
          ([name]) => name !== "native_context" && (state.tab !== "summary" || name !== "totals" || !state.data.totals),
        ),
      );
      const body = Object.keys(projection).length
        ? JSON.stringify(projection, null, 2).split("\n")
        : [" No records in this authorized view."];
      this.offset = Math.min(this.offset, Math.max(0, body.length - available));
      for (const line of body.slice(this.offset, this.offset + available)) lines.push(this.inner(line, width));
    }

    if (state.error) lines.push(this.inner(` ${state.error}`, width, "warning"));
    for (const line of inspectorSummaryLines(this.controller)) lines.push(this.inner(` ${this.color("muted", line)}`, width));
    lines.push(this.inner("", width));
    const search = inspectorCanSearch(this.controller) ? " · / search" : "";
    const full = `↑↓ select · Enter actions${search} · Tab sections · r refresh · c compact · Esc close`;
    const compact = `↑↓ · Enter${inspectorCanSearch(this.controller) ? " · /" : ""} · Tab · r · c · Esc`;
    const help = visibleWidth(` ${full}`) <= Math.max(1, width - 2) ? full : compact;
    lines.push(this.inner(` ${this.color("muted", help)}`, width));
    lines.push(this.color("muted", "╰" + "─".repeat(Math.max(1, width - 2)) + "╯"));
    return lines.map((line) => this.truncate(line, Math.max(1, width)));
  }

  invalidate() {
    this.tabRanges = [];
    this.rowCount = 0;
  }
}
