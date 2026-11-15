import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { build } from "esbuild";

// The Pi host supplies these at runtime; the unit under test only needs the
// width helpers, so a faithful stub keeps the test host-free.
const STUB = `export const visibleWidth = (text) => [...text.replace(/\\u001b\\[[0-9;]*m/g, "")].length;
export const truncateToWidth = (text, width) => visibleWidth(text) <= width ? text : [...text.replace(/\\u001b\\[[0-9;]*m/g, "")].slice(0, Math.max(0, width)).join("");
export const matchesKey = () => false;
`;

async function buildModule(entry, outName) {
  const directory = await mkdtemp(join(tmpdir(), "luminary-pi-ui-"));
  const stub = join(directory, "pi-tui.mjs");
  await writeFile(stub, STUB, "utf8");
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const outfile = join(directory, outName);
  await build({
    entryPoints: [join(root, "src/luminary_memory/integrations/assets/pi", entry)],
    outfile,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node22",
    alias: { "@earendil-works/pi-tui": stub },
  });
  const module = await import(pathToFileURL(outfile).href);
  return { module, cleanup: () => rm(directory, { recursive: true, force: true }) };
}

async function loadView() {
  const directory = await mkdtemp(join(tmpdir(), "luminary-pi-ui-"));
  const stub = join(directory, "pi-tui.mjs");
  await writeFile(stub, STUB, "utf8");
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const outfile = join(directory, "view.mjs");
  await build({
    entryPoints: [join(root, "src/luminary_memory/integrations/assets/pi/zentui-view.ts")],
    outfile,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node22",
    alias: { "@earendil-works/pi-tui": stub },
  });
  const module = await import(pathToFileURL(outfile).href);
  return { module, cleanup: () => rm(directory, { recursive: true, force: true }) };
}

function controller(state) {
  const selectedTabs = [];
  return {
    state,
    selectionHandle: undefined,
    selectTab: async (tab) => {
      selectedTabs.push(tab);
      state.tab = tab;
    },
    selectedTabs,
  };
}

const plain = (_role, text) => text;
const cut = (text, width) => [...text].slice(0, Math.max(0, width)).join("");

function makeView(View, state, height = 24) {
  const intents = [];
  const owner = controller(state);
  const view = new View(
    owner,
    () => false,
    cut,
    plain,
    (intent) => intents.push(intent),
    () => {},
    () => height,
  );
  return { view, intents, owner };
}

test("draws one ledger: title, divider, numbered sections and a selected row", async () => {
  const { module, cleanup } = await loadView();
  try {
    const { view } = makeView(module.ZentuiInspectorView, {
      tab: "memories",
      status: "ok",
      busy: false,
      data: { items: [{ id: 7, content: "deploy target is staging", permissions: { read: true } }] },
      policy_revision: 3,
      as_of: "2026-01-01T00:00:00Z",
    });
    const lines = view.render(80);

    assert.match(lines[0], /^ 🌙 Luminary · Memories · ok/);
    assert.match(lines[0], /policy 3 · native$/);
    assert.equal(lines[1], "─".repeat(80));
    assert.match(lines[2], /▎1 Memories/);
    assert.equal(lines[3], "─".repeat(80));
    assert.equal(lines.some((line) => /^ ❯ +7  deploy target is staging/.test(line)), true);
    assert.equal(lines.some((line) => line.includes("esc")), true);
    assert.equal(lines.some((line) => line.includes("│") || line.includes("╭")), false);
  } finally {
    await cleanup();
  }
});

test("keeps every line inside the terminal width", async () => {
  const { module, cleanup } = await loadView();
  try {
    const { view } = makeView(module.ZentuiInspectorView, {
      tab: "memories",
      status: "ok",
      busy: false,
      data: { items: [{ id: 1, content: "x".repeat(400) }] },
    });
    for (const width of [20, 40, 80]) {
      const lines = view.render(width);
      assert.equal(lines.every((line) => [...line].length === width), true, `width ${width}`);
      assert.equal(lines[1], "─".repeat(width), `divider ${width}`);
      assert.equal(lines.at(-1).includes("esc"), true, `help ${width}`);
    }
  } finally {
    await cleanup();
  }
});

test("reports an unavailable state instead of an empty healthy view", async () => {
  const { module, cleanup } = await loadView();
  try {
    const { view } = makeView(module.ZentuiInspectorView, {
      tab: "activity",
      status: "error",
      busy: false,
      data: {},
      error: "backend unavailable",
    });
    const lines = view.render(70);

    assert.equal(lines.some((line) => line.includes("backend unavailable")), true);
    assert.equal(lines.some((line) => line.includes("No activity recorded")), true);
  } finally {
    await cleanup();
  }
});

test("raw terminal sequences control selection, sections and actions", async () => {
  const { module, cleanup } = await loadView();
  try {
    const { view, intents, owner } = makeView(module.ZentuiInspectorView, {
      tab: "memories",
      status: "ok",
      busy: false,
      data: { items: [{ id: 1, content: "one" }, { id: 2, content: "two" }] },
    });
    view.render(80);

    assert.equal(view.handleInput("\u001b[B"), true);
    assert.equal(view.selected, 1);
    view.handleInput("\r");
    assert.deepEqual(intents.at(-1), { type: "actions", row: { id: 2, content: "two" } });

    view.handleInput("2");
    assert.equal(owner.selectedTabs.at(-1), "activity");

    view.handleInput("\u001b[Z");
    assert.equal(owner.selectedTabs.at(-1), "memories");

    view.handleInput("q");
    assert.equal(intents.at(-1).type, "close");
  } finally {
    await cleanup();
  }
});

test("mouse clicks select rows and sections", async () => {
  const { module, cleanup } = await loadView();
  try {
    const { view, intents, owner } = makeView(module.ZentuiInspectorView, {
      tab: "memories",
      status: "ok",
      busy: false,
      data: { items: [{ id: 1, content: "one" }, { id: 2, content: "two" }] },
    });
    view.render(80);

    view.handleMouse({ type: "click", button: "left", x: 2, y: 2 });
    assert.equal(owner.selectedTabs.at(-1), "memories");

    view.handleMouse({ type: "click", button: "left", x: 3, y: 5, clickCount: 2 });
    assert.deepEqual(intents.at(-1), { type: "actions", row: { id: 1, content: "one" } });
  } finally {
    await cleanup();
  }
});

test("host keybindings drive navigation when the TUI matcher cannot", async () => {
  const { module, cleanup } = await buildModule("host-keys.ts", "keys.mjs");
  try {
    const keybindings = {
      matches: (data, action) =>
        (action === "tui.select.down" && data === "\u001b[B") ||
        (action === "tui.select.cancel" && data === "\u001b") ||
        (action === "tui.select.confirm" && data === "\r"),
    };
    const key = module.createHostKeyMatcher(keybindings, () => false);

    assert.equal(key("\u001b[B", "down"), true);
    assert.equal(key("\u001b", "escape"), true);
    assert.equal(key("\r", "enter"), true);
    assert.equal(key("x", "down"), false);

    // An older host that throws for an unknown action must still navigate.
    const strict = module.createHostKeyMatcher({
      matches: () => { throw new Error("unknown action"); },
    }, (data, name) => data === "j" && name === "down");
    assert.equal(strict("j", "down"), true);
    assert.equal(strict("x", "down"), false);
  } finally {
    await cleanup();
  }
});
