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
  return {
    state,
    selectionHandle: undefined,
    selectTab: async () => {},
    load: async () => {},
  };
}

const plain = (_role, text) => text;
const cut = (text, width) => [...text].slice(0, Math.max(0, width)).join("");

function makeView(View, state, height = 24) {
  const intents = [];
  const keyMap = new Map([["\r", "enter"], ["\u001b", "escape"], ["\t", "tab"]]);
  const key = (data, want) => keyMap.get(data) === want;
  const view = new View(
    controller(state),
    key,
    cut,
    plain,
    (intent) => intents.push(intent),
    () => {},
    () => height,
  );
  return { view, intents };
}

test("renders a framed card with numbered sections and the active rail", async () => {
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
    const lines = view.render(60);

    assert.match(lines[0], /^╭─ Luminary · Memories/);
    assert.match(lines[0], /ok/);
    assert.equal(lines.at(-1).startsWith("╰"), true);
    assert.equal(lines.every((line) => [...line].length === 60), true);
    assert.equal(lines.some((line) => line.includes("▎1 Memories")), true);
    assert.equal(lines.some((line) => line.includes("▎ 7 deploy target is staging [read]")), true);
    assert.equal(lines.some((line) => line.includes("Esc")), true);
  } finally {
    await cleanup();
  }
});

test("keeps long rows inside the terminal width", async () => {
  const { module, cleanup } = await loadView();
  try {
    const { view } = makeView(module.ZentuiInspectorView, {
      tab: "memories",
      status: "ok",
      busy: false,
      data: { items: [{ id: 1, content: "x".repeat(400) }] },
    });
    for (const width of [24, 40, 80]) {
      const lines = view.render(width);
      assert.equal(lines.every((line) => [...line].length === width), true, `width ${width}`);
      assert.equal(lines[0].startsWith("╭") && lines[0].endsWith("╮"), true, `header ${width}`);
      assert.equal(lines.at(-1).startsWith("╰") && lines.at(-1).endsWith("╯"), true, `footer ${width}`);
      assert.equal(lines.some((line) => line.includes("xxxxxxxxxx")), true, `row ${width}`);
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

test("keyboard navigation and actions stay bound to the host intents", async () => {
  const { module, cleanup } = await loadView();
  try {
    const { view, intents } = makeView(module.ZentuiInspectorView, {
      tab: "memories",
      status: "ok",
      busy: false,
      data: { items: [{ id: 1, content: "one" }, { id: 2, content: "two" }] },
    });
    view.render(60);
    view.handleInput("j");
    view.handleInput("\r");
    assert.equal(view.selected, 1);
    assert.deepEqual(intents.at(-1), { type: "actions", row: { id: 2, content: "two" } });

    view.handleInput("\u001b");
    assert.equal(intents.at(-1).type, "close");
  } finally {
    await cleanup();
  }
});
