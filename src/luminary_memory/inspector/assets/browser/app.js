// src/luminary_memory/integrations/assets/common/console-contract.ts
var TABS = [
  { id: "memories", label: "Memories", operation: "browse" },
  { id: "activity", label: "Activity", operation: "events" },
  { id: "evidence", label: "Evidence & History", operation: "browse" },
  { id: "relations", label: "Relations", operation: "graph" },
  { id: "maintenance", label: "Review & Maintenance", operation: "browse" },
  { id: "sharing", label: "Sharing & Workspaces", operation: "browse" },
  { id: "settings", label: "Settings & Diagnostics", operation: "get_settings" },
  { id: "transfer", label: "Data Transfer", operation: "browse" },
  { id: "summary", label: "Summary", operation: "summary" }
];

// src/luminary_memory/integrations/assets/common/console-controller.ts
var InspectorController = class {
  constructor(transport) {
    this.transport = transport;
  }
  transport;
  state = { tab: "memories", status: "empty", busy: false, data: {} };
  epoch = 0;
  serial = 0;
  active;
  disposed = false;
  listeners = /* @__PURE__ */ new Set();
  query = {};
  selectionHandle;
  proposal;
  get contextVersion() {
    return this.epoch;
  }
  get activeContext() {
    return !this.disposed;
  }
  async registerFile(path, mode) {
    if (!this.transport.registerFile || this.disposed) throw new Error("Trusted native file registration unavailable");
    const epoch = this.epoch;
    const handle = await this.transport.registerFile(path, mode);
    if (epoch !== this.epoch || this.disposed) throw new Error("File selection belongs to an expired native context");
    return handle;
  }
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  publish(patch) {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener(this.state);
  }
  invalidate() {
    this.epoch++;
    this.serial++;
    this.active?.abort();
    this.active = void 0;
    this.proposal = void 0;
  }
  switchContext(transport) {
    this.invalidate();
    this.transport = transport;
    this.query = {};
    this.selectionHandle = void 0;
    this.publish({ data: {}, preview: void 0, error: void 0, busy: false, status: "empty", context_epoch: void 0, policy_revision: void 0, as_of: void 0 });
  }
  selectProject(selectionHandle) {
    this.invalidate();
    this.selectionHandle = selectionHandle;
    this.query = {};
    this.publish({ data: {}, preview: void 0, error: void 0, busy: false, status: "empty", context_epoch: void 0, policy_revision: void 0, as_of: void 0 });
  }
  cancel() {
    const writing = this.state.busy && this.writing;
    this.invalidate();
    this.publish({ busy: false, status: writing ? "unknown_outcome" : "cancelled", preview: void 0, error: writing ? "Commit outcome unknown. Refresh Activity before attempting another change; this write was not replayed." : void 0 });
  }
  dispose() {
    this.invalidate();
    this.listeners.clear();
    this.state = { tab: "memories", data: {}, busy: false, status: "cancelled" };
    this.disposed = true;
  }
  writing = false;
  async execute(operation, args = {}, writing = false) {
    if (this.disposed) return;
    this.proposal = void 0;
    this.active?.abort();
    const active = new AbortController();
    this.active = active;
    const epoch = this.epoch;
    const serial = ++this.serial;
    this.writing = writing;
    this.publish({ busy: true, preview: void 0, error: void 0 });
    const request = { operation, arguments: args, selection_handle: this.selectionHandle, request_id: `inspector-${epoch}-${serial}` };
    try {
      const response = await this.transport.request(request, active.signal);
      if (this.disposed || epoch !== this.epoch || serial !== this.serial) return;
      if (response.request_id !== request.request_id) throw new Error("Mismatched inspector response");
      if (response.status === "denied") {
        this.invalidate();
        this.publish({ data: {}, preview: void 0, busy: false, status: "denied", error: response.error?.message, as_of: response.as_of, context_epoch: response.context_epoch, policy_revision: response.policy_revision });
        return response;
      }
      const changedPolicy = this.state.policy_revision !== void 0 && response.policy_revision !== this.state.policy_revision;
      const changedContext = this.state.context_epoch !== void 0 && response.context_epoch !== this.state.context_epoch;
      if (changedPolicy || changedContext) {
        this.invalidate();
        this.publish({ data: {}, preview: void 0 });
      }
      this.publish({ busy: false, status: response.status, data: response.status === "ok" || response.status === "empty" ? response.data ?? {} : {}, error: response.error?.message, as_of: response.as_of, policy_revision: response.policy_revision, context_epoch: response.context_epoch });
      return response;
    } catch {
      if (this.disposed || epoch !== this.epoch || serial !== this.serial) return;
      this.publish({ busy: false, data: {}, status: writing ? "unknown_outcome" : active.signal.aborted ? "cancelled" : "unavailable", error: writing ? "Commit outcome unknown. Refresh activity before attempting another change; this write was not replayed." : "Inspector transport unavailable." });
    } finally {
      if (this.active === active) this.active = void 0;
    }
  }
  async selectTab(tab) {
    this.proposal = void 0;
    this.query = {};
    this.publish({ tab, data: {}, preview: void 0 });
    return this.load();
  }
  load(args = {}) {
    this.query = { ...this.query, ...args };
    if (this.state.tab === "activity" && (this.state.data.snapshot_required === true || args.since_event_id === void 0 && args.replay_context === void 0 && args.cursor === void 0)) {
      delete this.query.since_event_id;
      delete this.query.replay_context;
      delete this.query.cursor;
    }
    const tab = TABS.find((t) => t.id === this.state.tab);
    return this.execute(tab.operation, { view: tab.id, ...this.query });
  }
  detail(memory_id) {
    return this.execute("detail", { memory_id });
  }
  async preview(operation, args, commitOperation) {
    this.proposal = void 0;
    this.publish({ preview: void 0 });
    const epoch = this.epoch;
    const response = await this.execute(operation, args);
    if (epoch !== this.epoch || response?.status !== "ok" || !response.data || typeof response.data.preview_id !== "string") return;
    const commit = commitOperation ?? ({ maintenance_preview: "maintenance_commit", transfer_preview: "transfer_commit" }[operation] || "mutate");
    this.proposal = { operation: commit, epoch, preview: response.data, deciding: false };
    this.publish({ preview: response.data });
  }
  async commit(decide) {
    const proposal = this.proposal;
    if (!proposal || this.disposed || proposal.deciding) return;
    proposal.deciding = true;
    const valid = () => !this.disposed && this.proposal === proposal && this.epoch === proposal.epoch;
    let accepted;
    try {
      accepted = await decide(proposal.preview);
    } catch {
      if (valid()) {
        this.proposal = void 0;
        this.publish({ preview: void 0, status: "cancelled" });
      }
      return;
    }
    if (!valid()) return;
    if (!accepted) {
      this.proposal = void 0;
      this.publish({ preview: void 0, status: "cancelled" });
      return;
    }
    if (!this.transport.confirm) {
      this.proposal = void 0;
      this.publish({ preview: void 0, status: "unsupported", error: "Native owner confirmation is unavailable on this transport." });
      return;
    }
    const active = new AbortController();
    this.active?.abort();
    this.active = active;
    this.writing = false;
    this.publish({ busy: true });
    let confirmation;
    try {
      confirmation = await this.transport.confirm(String(proposal.preview.preview_id), active.signal);
    } catch {
      if (valid()) {
        this.proposal = void 0;
        this.publish({ busy: false, status: "unavailable", error: "Owner confirmation could not be delivered.", preview: void 0 });
      }
      return;
    } finally {
      if (this.active === active) this.active = void 0;
    }
    if (!valid()) return;
    const receipt = confirmation.data?.confirmation_receipt;
    this.proposal = void 0;
    this.publish({ preview: void 0, busy: false });
    if (confirmation.status !== "ok" || typeof receipt !== "string") {
      this.publish({ data: {}, status: confirmation.status === "ok" ? "unavailable" : confirmation.status, error: confirmation.error?.message || "No owner confirmation receipt." });
      return;
    }
    return this.execute(proposal.operation, { ...proposal.operation === "explain" ? { phase: "commit" } : {}, preview_id: proposal.preview.preview_id, confirmation_receipt: receipt }, true);
  }
};

// src/luminary_memory/integrations/assets/common/console-actions.ts
var base = ["Refresh", "View projection", "Search / filters", "Next page", "Select project"];
var resourceBase = ["Refresh", "View projection", "Next page", "Select project"];
function inspectorCanSearch(controller2) {
  return controller2.state.tab === "memories" || controller2.state.tab === "evidence" || controller2.state.tab === "maintenance";
}
function inspectorRows(controller2) {
  const data = controller2.state.data;
  if (data.memory && typeof data.memory === "object") return [data.memory];
  const rows = data.items ?? data.nodes ?? data.changes ?? data.projects ?? data.grants;
  return Array.isArray(rows) ? rows.filter((r) => !!r && typeof r === "object") : [];
}
function inspectorContextLine(controller2) {
  const native = controller2.state.data.native_context;
  if (!native || typeof native !== "object") return "";
  return `Agent ${native.agent_id} \xB7 profile ${native.profile_id} \xB7 store ${String(native.store_id).slice(0, 12)} \xB7 host ${native.host_id}`.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ");
}
function inspectorActions(controller2, row) {
  switch (controller2.state.tab) {
    case "memories":
      return [...base, "Create memory", ...row?.id !== void 0 ? ["Inspect", "History", "Expand evidence", "Expand source episodes", "Claims / conflicts", "Lineage", ...row.permissions?.edit ? ["Correct", "Tags", "Core designation", ...row.claim_key ? ["Resolve conflict"] : []] : [], ...row.permissions?.retract ? ["Retract"] : []] : []];
    case "activity":
      return [...resourceBase, ...typeof controller2.state.data.replay_context === "string" ? ["Check new activity"] : [], "Event details"];
    case "evidence":
      return [...base, ...row?.id !== void 0 ? ["Inspect", "History", "Expand evidence", "Expand source episodes", "Claims / conflicts", "Lineage"] : []];
    case "relations":
      return [...resourceBase, "Explore entity", "All relations", "Adjacency details", ...typeof row?.memory_id === "number" ? ["Inspect supporting memory"] : []];
    case "maintenance":
      return [...base, "Preview maintenance", ...row?.id !== void 0 ? ["Inspect", ...row.permissions?.edit && row.claim_key ? ["Resolve conflict"] : []] : []];
    case "sharing":
      return [...resourceBase, "Project information", ...!controller2.selectionHandle ? ["Grant rights", "Revoke rights", "Bind location"] : []];
    case "settings":
      return ["Refresh", "View projection", "Change setting", "Readiness / diagnostics"];
    case "transfer":
      return ["Refresh", "View projection", "Export records", "Import records", "Backup limitations"];
    case "summary":
      return ["Refresh", "View projection", "Explain with AI"];
  }
}
async function replayActivity(controller2, dialogs2) {
  const data = controller2.state.data;
  const boundary = data.next_event_id ?? data.snapshot_boundary;
  if (typeof boundary !== "number" || typeof data.replay_context !== "string") {
    await dialogs2.show("Activity", "Refresh to load a current activity snapshot first.");
    return;
  }
  await controller2.load({ since_event_id: boundary, replay_context: data.replay_context, cursor: void 0 });
}
async function runInspectorAction(controller2, nativeDialogs, action2, row, registerFile) {
  registerFile ??= (path, mode) => controller2.registerFile(path, mode);
  const epoch = controller2.contextVersion;
  const live = () => controller2.activeContext && controller2.contextVersion === epoch;
  const dialogs2 = {
    input: async (title, value) => {
      const answer = await nativeDialogs.input(title, value);
      return live() ? answer : void 0;
    },
    select: async (title, choices) => {
      const answer = await nativeDialogs.select(title, choices);
      return live() ? answer : void 0;
    },
    confirm: async (title, message) => {
      const answer = await nativeDialogs.confirm(title, message);
      return live() && answer;
    },
    show: async (title, message) => {
      if (live()) await nativeDialogs.show(title, message);
    }
  };
  const input = (title, value) => dialogs2.input(title, value);
  const candidate = row?.id ?? row?.memory_id;
  const memory = typeof candidate === "number" || typeof candidate === "string" ? candidate : void 0;
  const revision = row?.revision;
  const change = async (kind, fields2, operation = "preview_change", commit) => {
    if (!live()) return;
    await controller2.preview(operation, { kind, ...memory !== void 0 ? { memory_id: memory, expected_revision: revision } : {}, ...fields2 }, commit);
    if (!live()) return;
    if (!controller2.state.preview) return;
    const result = await controller2.commit((preview) => dialogs2.confirm("Confirm Luminary change", JSON.stringify(preview, null, 2)));
    if (result?.status === "ok" && kind === "correct" && typeof result.data?.memory_id === "number" && live()) await controller2.detail(result.data.memory_id);
  };
  switch (action2) {
    case "Refresh":
      await controller2.load();
      break;
    case "Check new activity":
      await replayActivity(controller2, dialogs2);
      break;
    case "Search / filters": {
      if (!inspectorCanSearch(controller2)) {
        await dialogs2.show("Memory search", "Search is available in Memories, Evidence & History, and Review & Maintenance. No filter was applied to this view.");
        return;
      }
      const query = await input("Search memory (empty clears)");
      if (query === void 0) return;
      const tags = await input("Filter tags (comma separated; empty clears)");
      if (tags === void 0) return;
      const status = await dialogs2.select("Status", ["active", "candidate", "conflicted", "superseded", "expired", "deleted", "all"]);
      if (!status) return;
      const statuses = status === "all" ? ["active", "candidate", "conflicted", "superseded", "expired", "deleted"] : [status];
      await controller2.load({ query, tags: tags.split(",").map((t) => t.trim()).filter(Boolean), statuses, cursor: void 0 });
      break;
    }
    case "Next page":
      if (controller2.state.tab === "activity" && controller2.state.data.replayed && controller2.state.data.has_more) await replayActivity(controller2, dialogs2);
      else if (controller2.state.data.next_cursor) await controller2.load({ cursor: controller2.state.data.next_cursor });
      else await dialogs2.show("Pagination", "No further page.");
      break;
    case "Select project": {
      controller2.selectProject(void 0);
      const version = controller2.contextVersion;
      const result = await controller2.execute("browse", { view: "projects" });
      const projects = Array.isArray(result?.data?.projects) ? result.data.projects : [];
      if (!controller2.activeContext || controller2.contextVersion !== version) return;
      const labels = projects.map((p, index) => `${index + 1}. ${p.workspace_id ?? p.project_id}`);
      const selected2 = await nativeDialogs.select("Explicit project resource", ["Own native project", ...labels]);
      if (!selected2 || !controller2.activeContext || controller2.contextVersion !== version) return;
      if (selected2 !== "Own native project") {
        const project = projects[labels.indexOf(selected2)];
        if (typeof project?.selection_handle !== "string") return;
        controller2.selectProject(project.selection_handle);
      }
      await controller2.load();
      break;
    }
    case "Create memory": {
      const content = await input("New durable memory");
      if (content?.trim()) await change("create", { content });
      break;
    }
    case "Inspect":
      if (memory !== void 0) {
        await controller2.detail(memory);
        await dialogs2.show("Memory ownership, permissions and detail", JSON.stringify(controller2.state.data, null, 2));
      }
      break;
    case "Correct": {
      if (memory === void 0) return;
      const detail = await controller2.detail(memory);
      const current = detail?.data?.memory;
      if (!live() || detail?.status !== "ok" || !current) return;
      const content = await input("Versioned correction", String(current.content ?? ""));
      if (content?.trim()) await change("correct", { content, expected_revision: current.revision });
      break;
    }
    case "Tags": {
      const value = await input("Tags (comma separated)", Array.isArray(row?.tags) ? row.tags.join(", ") : "");
      if (value !== void 0) await change("tag", { tags: value.split(",").map((t) => t.trim()).filter(Boolean) });
      break;
    }
    case "Core designation": {
      const value = await dialogs2.select("Core memory", ["Core", "Ordinary"]);
      if (value) await change("core", { pinned: value === "Core" });
      break;
    }
    case "Retract":
      await change("retract", {});
      break;
    case "History": {
      if (memory === void 0) return;
      let cursor;
      while (live()) {
        const page = await controller2.execute("history", { memory_id: memory, limit: 50, ...cursor ? { cursor } : {} });
        if (!live() || !page) return;
        await dialogs2.show("Durable memory history", JSON.stringify({ status: page.status, ...page.data, error: page.error }, null, 2));
        cursor = page.data?.next_cursor;
        if (!cursor || await dialogs2.select("History pages", ["Next page", "Back"]) !== "Next page") break;
      }
      if (live()) await controller2.load();
      break;
    }
    case "Expand evidence":
      if (memory !== void 0) {
        await controller2.execute("detail", { memory_id: memory, expand: "evidence", limit: 50 });
        await dialogs2.show("Evidence expansion", JSON.stringify(controller2.state.data, null, 2));
      }
      break;
    case "Expand source episodes":
      if (memory !== void 0) {
        await controller2.execute("detail", { memory_id: memory, expand: "episodes", limit: 50 });
        await dialogs2.show("Explicit source episode expansion", JSON.stringify(controller2.state.data, null, 2));
      }
      break;
    case "Claims / conflicts":
      if (memory !== void 0) {
        await controller2.execute("detail", { memory_id: memory, expand: "claims", limit: 50 });
        await dialogs2.show("Claims and conflicts", JSON.stringify(controller2.state.data, null, 2));
      }
      break;
    case "Lineage":
      if (memory !== void 0) {
        await controller2.execute("detail", { memory_id: memory, expand: "lineage", limit: 50 });
        await dialogs2.show("Correction lineage", JSON.stringify(controller2.state.data, null, 2));
      }
      break;
    case "Explore entity": {
      const nodes = Array.isArray(controller2.state.data.nodes) ? controller2.state.data.nodes : [];
      const choices = nodes.map((node2, index) => `${index + 1}. ${node2.label ?? node2.id}`.replace(/[\u0000-\u001f\u007f-\u009f]/g, " "));
      if (!choices.length) {
        await dialogs2.show("Relations", "This authorized page has no entities.");
        break;
      }
      const selected2 = await dialogs2.select("Explore authorized entity", choices);
      const node = selected2 ? nodes[choices.indexOf(selected2)] : void 0;
      if (node && typeof node.id === "number" && live()) await controller2.load({ entity_id: node.id, cursor: void 0 });
      break;
    }
    case "All relations":
      await controller2.load({ entity_id: void 0, cursor: void 0 });
      break;
    case "Inspect supporting memory":
      if (typeof row?.memory_id === "number") {
        await controller2.detail(row.memory_id);
        await dialogs2.show("Supporting memory and recorded evidence", JSON.stringify(controller2.state.data, null, 2));
        if (live()) await controller2.load();
      }
      break;
    case "View projection":
    case "Event details":
    case "Adjacency details":
      await dialogs2.show(action2, JSON.stringify(action2 === "View projection" ? controller2.state.data : row ?? controller2.state.data, null, 2));
      break;
    case "Preview maintenance": {
      const kind = await dialogs2.select("Manual maintenance proposal", ["prune", "cleanup_expired"]);
      if (kind) await change(kind, {}, "maintenance_preview");
      break;
    }
    case "Resolve conflict": {
      if (memory === void 0) return;
      const detail = await controller2.detail(memory);
      const current = detail?.data?.memory;
      const token = detail?.data?.conflict_set_token;
      if (!live() || detail?.status !== "ok" || typeof token !== "string" || !current) return;
      await change("resolve_conflict", { memory_id: memory, expected_revision: current.revision, expected_conflict_set_token: token });
      break;
    }
    case "Project information": {
      const result = await controller2.execute("browse", { view: "sharing" });
      if (live() && result?.status === "ok") await dialogs2.show("Project information and explicit rights", JSON.stringify(result.data, null, 2));
      break;
    }
    case "Grant rights": {
      const recipient_agent_id = await input("Agent receiving explicit project rights");
      if (!recipient_agent_id) return;
      const capabilities = [];
      for (const right of ["read", "contribute", "edit", "retract"]) {
        if (await dialogs2.confirm(`Grant ${right}?`, `Independently grant ${right} to ${recipient_agent_id} in this project?`)) capabilities.push(right);
        if (!live()) return;
      }
      if (!capabilities.length) {
        await dialogs2.show("No rights selected", "No grant was proposed. Existing rights are unchanged.");
        return;
      }
      await change("grant", { recipient_agent_id, capabilities }, "preview_change", "grant");
      break;
    }
    case "Revoke rights": {
      const recipient_agent_id = await input("Agent to revoke");
      if (recipient_agent_id) await change("revoke", { recipient_agent_id }, "preview_change", "revoke");
      break;
    }
    case "Bind location": {
      const host_id = await input("Explicit host ID");
      if (!host_id) return;
      const profile_id = await input("Explicit profile ID");
      if (!profile_id) return;
      const workspace = await input("Absolute project location on that host");
      if (workspace) await change("bind_location", { location: { host_id, profile_id, workspace } });
      break;
    }
    case "Change setting": {
      const settings = controller2.state.data;
      const keys = Array.isArray(settings.editable) ? settings.editable.filter((key2) => typeof key2 === "string") : [];
      if (!keys.length) {
        await dialogs2.show("Settings", "This host exposes no editable settings. Saving configuration is unchanged.");
        return;
      }
      const key = await dialogs2.select("Editable setting", keys);
      if (!key) return;
      const values = settings.values;
      const value = await input(`New ${key} value (JSON)`, values?.[key] === void 0 ? void 0 : JSON.stringify(values[key]));
      if (value === void 0) return;
      let parsed;
      try {
        parsed = JSON.parse(value);
      } catch {
        await dialogs2.show("Invalid setting", "Enter a JSON string, number, boolean, array or object.");
        return;
      }
      await change("set_settings", { changes: { [key]: parsed }, expected_revision: settings.revision }, "preview_change", "set_settings");
      break;
    }
    case "Readiness / diagnostics":
      await controller2.execute("get_settings", { diagnostics: true });
      break;
    case "Export records":
    case "Import records": {
      if (!registerFile) {
        await dialogs2.show("Data transfer unavailable", "This host has no trusted file-selection transport. No file was read or written.");
        return;
      }
      const direction = action2 === "Import records" ? "import" : "export";
      const path = await input(direction === "import" ? "Select existing memory-record file (absolute path)" : "Select output memory-record file (absolute path)");
      if (!path) return;
      try {
        const file_handle = await registerFile(path, direction === "import" ? "read" : "write");
        await change("transfer", { direction, file_handle }, "transfer_preview");
      } catch {
        await dialogs2.show("File selection failed", "The native server could not register this file. No transfer was committed.");
      }
      break;
    }
    case "Backup limitations":
      await dialogs2.show("Data transfer", "Memory-record export is not a full store backup. It does not back up backend configuration, secrets, raw source episodes or native host state. The preview reports exact authorized coverage.");
      break;
    case "Explain with AI":
      if (await dialogs2.confirm("Optional AI explanation", "Request a disclosure preview for this authorized Summary? No model call runs until you confirm that disclosure.")) await change("explain", { phase: "preview" }, "explain", "explain");
      break;
  }
}

// ui/browser/app.ts
var tabs = document.querySelector("#tabs");
var view = document.querySelector("#view");
var toolbar = document.querySelector("#toolbar");
var connection = document.querySelector("#connection");
var modal = document.querySelector("#dialog");
var csrf = sessionStorage.getItem("luminary-inspector-csrf") || "";
var selected;
var controller;
var permissionSnapshot;
var overviewVersion = 0;
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== void 0) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(text, action2, primary = false) {
  const node = element("button", text, primary ? "primary" : "");
  node.type = "button";
  node.addEventListener("click", () => {
    Promise.resolve(action2()).catch(() => {
      connection.textContent = "Operation unavailable. No successful change is claimed; inspect Activity before retrying.";
    });
  });
  return node;
}
async function json(path, body) {
  const response = await fetch(path, { method: "POST", headers: {
    "Content-Type": "application/json",
    "X-Luminary-CSRF": csrf
  }, body: JSON.stringify(body), credentials: "same-origin" });
  if (!response.ok) throw new Error("Authenticated inspector request failed");
  return response.json();
}
function dialog(title, content, choices, cancelled) {
  const { promise, resolve } = Promise.withResolvers();
  document.querySelector("#dialog-title").textContent = title;
  document.querySelector("#dialog-body").replaceChildren(content);
  const actions = document.querySelector("#dialog-actions");
  const cancel = (event) => {
    event.preventDefault();
    finish(cancelled);
  };
  const finish = (value) => {
    modal.removeEventListener("cancel", cancel);
    modal.close();
    resolve(value);
  };
  actions.replaceChildren(...choices.map((choice) => button(choice.label, () => finish(choice.value), choice.primary)));
  modal.addEventListener("cancel", cancel);
  modal.showModal();
  return promise;
}
var dialogs = {
  async input(title, value) {
    const input = element("textarea");
    input.value = value || "";
    input.setAttribute("aria-label", title);
    const answer = await dialog(title, input, [{ label: "Cancel", value: false }, { label: "Continue", value: true, primary: true }], false);
    return answer ? input.value : void 0;
  },
  async select(title, choices) {
    const select = element("select");
    select.setAttribute("aria-label", title);
    for (const choice of choices) {
      const option = element("option", choice);
      option.value = choice;
      select.append(option);
    }
    const answer = await dialog(title, select, [{ label: "Cancel", value: false }, { label: "Select", value: true, primary: true }], false);
    return answer ? select.value : void 0;
  },
  confirm: (title, message) => dialog(title, element("pre", message), [{ label: "Cancel", value: false }, { label: "Confirm", value: true, primary: true }], false),
  async show(title, message) {
    await dialog(title, element("pre", message), [{ label: "Close", value: true }], true);
  }
};
async function transfer(direction) {
  let body = "";
  if (direction === "import") {
    const input = element("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.setAttribute("aria-label", "Memory-record export file");
    if (!await dialog("Select a memory-record file", input, [{ label: "Cancel", value: false }, { label: "Preview import", value: true, primary: true }], false)) return;
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      await dialogs.show("File too large", "Transfer accepts at most 4 MiB; no file was uploaded.");
      return;
    }
    body = file;
  }
  const response = await fetch("/api/file?mode=" + (direction === "import" ? "read" : "write"), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/octet-stream", "X-Luminary-CSRF": csrf },
    body
  });
  if (!response.ok) throw new Error("File selection failed");
  const registered = await response.json();
  const handle = registered.data?.file_handle;
  if (registered.status !== "ok" || typeof handle !== "string") {
    await dialogs.show("File unavailable", registered.error?.message || registered.status);
    return;
  }
  await controller.preview("transfer_preview", { direction, file_handle: handle }, "transfer_commit");
  const result = await controller.commit((preview) => dialogs.confirm("Confirm data transfer", JSON.stringify(preview, null, 2)));
  if (direction === "export" && result?.status === "ok") {
    const downloaded = await fetch("/api/download/" + encodeURIComponent(handle), { headers: { "X-Luminary-CSRF": csrf }, credentials: "same-origin" });
    if (!downloaded.ok) throw new Error("Export was not downloadable");
    const url = URL.createObjectURL(await downloaded.blob());
    const anchor = element("a");
    anchor.href = url;
    anchor.download = "luminary-memories.json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1e3);
  }
}
async function loadCompact() {
  const version = ++overviewVersion, selection = controller.selectionHandle;
  permissionSnapshot = void 0;
  const result = await controller.execute("browse", { view: "memories", limit: 5 });
  if (!result || !controller.activeContext || version !== overviewVersion || !document.body.classList.contains("compact") || selection !== controller.selectionHandle || result.status !== "ok" && result.status !== "empty") return;
  const items = result.data?.items;
  if (Array.isArray(items)) permissionSnapshot = { rows: items, epoch: result.context_epoch, policy: result.policy_revision, selection };
  await controller.selectTab("activity");
}
async function action(name, row) {
  if (name === "Refresh" && document.body.classList.contains("compact")) await loadCompact();
  else if (name === "Import records" || name === "Export records") await transfer(name === "Import records" ? "import" : "export");
  else {
    await runInspectorAction(controller, dialogs, name, row);
    if (name === "Select project" && document.body.classList.contains("compact")) await loadCompact();
  }
}
function fields(values) {
  const list = element("dl", void 0, "fields");
  for (const [name, value] of Object.entries(values)) {
    list.append(element("dt", name.replaceAll("_", " ")), element("dd", typeof value === "string" ? value : JSON.stringify(value)));
  }
  return list;
}
function render() {
  const state = controller.state;
  const compact = document.body.classList.contains("compact");
  connection.textContent = `${state.busy ? "Loading" : state.status} \xB7 ${controller.selectionHandle ? "Explicit shared project" : "Own native project"} \xB7 policy ${state.policy_revision ?? "\u2014"} \xB7 ${state.as_of || ""}${state.error ? " \xB7 " + state.error : ""}`;
  for (const node of tabs.querySelectorAll("button")) {
    const active = node.dataset.tab === state.tab;
    node.setAttribute("aria-selected", String(active));
    node.tabIndex = active ? 0 : -1;
  }
  toolbar.replaceChildren(...inspectorActions(controller, selected).filter((name) => name !== "View projection").map((name) => button(name, () => action(name, selected))));
  view.replaceChildren();
  if (state.error) view.append(element("p", state.error, "notice warning"));
  const data = state.data;
  if (data.native_context) view.append(element("p", inspectorContextLine(controller), "muted"));
  if (compact && permissionSnapshot && permissionSnapshot.epoch === state.context_epoch && permissionSnapshot.policy === state.policy_revision && permissionSnapshot.selection === controller.selectionHandle) {
    const permissions = element("section", void 0, "record");
    permissions.setAttribute("aria-label", "Permissions on visible records");
    permissions.append(element("h2", "Permissions on visible records"));
    for (const row of permissionSnapshot.rows) permissions.append(element("p", `#${row.id}: read ${row.permissions?.read ? "\u2713" : "\u2014"} \xB7 contribute ${row.permissions?.contribute ? "\u2713" : "\u2014"} \xB7 edit ${row.permissions?.edit ? "\u2713" : "\u2014"} \xB7 retract ${row.permissions?.retract ? "\u2713" : "\u2014"}`));
    view.append(permissions);
  }
  if (data.gap === true) view.append(element("p", "Activity history is incomplete. Refresh to load a new snapshot.", "notice warning"));
  else if (data.replayed === true) view.append(element("p", `${Array.isArray(data.items) && data.items.length ? "Showing new activity only." : "No new activity since the checkpoint."} Refresh loads recent history.`, "notice"));
  if (state.tab === "summary" && data.totals && typeof data.totals === "object") {
    const metrics = element("div", void 0, "metrics");
    for (const [name, value] of Object.entries(data.totals)) {
      const card = element("div", void 0, "metric");
      card.append(element("strong", String(value)), element("span", name));
      metrics.append(card);
    }
    view.append(metrics, element("p", String(data.count_basis || ""), "muted"));
    if (data.time_range && typeof data.time_range === "object") {
      const panel = element("section", void 0, "record");
      panel.append(element("h2", "Stored timestamp bounds (UTC)"), fields(data.time_range));
      view.append(panel);
    }
  }
  if (state.tab === "settings") {
    for (const key of ["values", "secret_presence", "readiness"]) if (data[key] && typeof data[key] === "object") {
      const panel = element("section", void 0, "record");
      panel.append(element("h2", key.replaceAll("_", " ")), fields(data[key]));
      view.append(panel);
    }
  }
  if (state.tab === "relations" && data.label) view.append(element("p", String(data.label), "notice"));
  if (state.tab === "sharing") view.append(element("p", "Select a project explicitly. Read, contribute, edit and retract are separate rights; matching paths do not establish sharing.", "notice"));
  if (state.tab === "transfer") view.append(element("p", "Memory-record transfer is not a full backup of evidence, episodes, audit, settings or grants. Every transfer shows a preview before confirmation.", "notice"));
  const rows = inspectorRows(controller);
  for (let index = 0, count = compact ? Math.min(rows.length, 5) : rows.length; index < count; index++) {
    const row = rows[index];
    const card = element("article", void 0, "record");
    card.append(element("h3", row.kind === "native_recall" ? "Recall activity" : row.kind === "hermes_operation" ? "Hermes activity" : row.id !== void 0 ? `Memory #${row.id} \xB7 ${row.status ?? ""} \xB7 revision ${row.revision ?? "\u2014"}` : String(row.kind ?? row.label ?? row.event_id ?? "Record")));
    if (row.operation && typeof row.operation === "object") {
      const operation = row.operation;
      card.append(
        element("p", String(operation.summary)),
        element("small", `Source ${row.source ?? "unknown"} \xB7 session ${operation.session_id ?? "unknown"} \xB7 operation ${operation.id} \xB7 ${row.created_at ?? ""}`)
      );
    }
    if (row.content) card.append(element("p", String(row.content)));
    else if (row.source && row.target) card.append(element("p", `${row.source} \u2192 ${row.target} \xB7 ${row.kind || "co-occurrence"}`));
    else if (!row.operation) card.append(fields(row));
    if (row.permissions) card.append(element("small", "Allowed: " + Object.keys(row.permissions).filter((key) => row.permissions?.[key]).join(", ")));
    const actions = element("div", void 0, "record-actions");
    actions.append(button("Actions", async () => {
      selected = row;
      const choice = await dialogs.select("Record actions", inspectorActions(controller, row));
      if (choice) await action(choice, row);
    }));
    if (row.id !== void 0) actions.append(button("Inspect", () => controller.detail(row.id)));
    card.append(actions);
    view.append(card);
  }
  for (const key of ["evidence", "claims", "lineage", "episodes", "issues"]) {
    const value = data[key];
    if (Array.isArray(value) && value.length) {
      const section = element("details", void 0, "record");
      section.append(element("summary", key), element("pre", JSON.stringify(value, null, 2)));
      view.append(section);
    }
  }
  if (data.audit === "committed") {
    const receipt = element("article", void 0, "record");
    receipt.setAttribute("aria-label", "Operation receipt");
    receipt.append(element("h2", "Confirmed operation committed"));
    if (typeof data.stored === "number") receipt.append(element("p", `${data.stored} saved \xB7 ${data.duplicates ?? 0} duplicates skipped.`));
    if (typeof data.memory_id === "number") receipt.append(element("p", `Memory #${data.memory_id} \xB7 revision ${data.revision ?? "\u2014"}`), button("Inspect memory", () => controller.detail(data.memory_id)));
    if (data.coverage) receipt.append(element("p", String(data.coverage)));
    view.append(receipt);
  }
  if (typeof data.text === "string") {
    const answer = element("article", void 0, "record");
    answer.append(element("h2", "AI explanation \xB7 untrusted interpretation"), element("p", data.text), fields({ references: data.references, model: data.model, usage: data.usage, cost: data.cost }));
    view.append(answer);
  }
  if (!view.children.length) view.append(element("p", state.busy ? "Loading authorized data\u2026" : "No records in this authorized view.", "notice"));
}
async function start() {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("token");
  history.replaceState(null, "", location.pathname);
  if (token) {
    const response = await json("/api/bootstrap", { token });
    csrf = response.csrf_token;
    sessionStorage.setItem("luminary-inspector-csrf", csrf);
  }
  if (!csrf) throw new Error("Launch the companion again for a one-use owner sign-in link.");
  const transport = {
    async request(request, signal) {
      const response = await fetch("/api/request", {
        method: "POST",
        credentials: "same-origin",
        signal,
        headers: { "Content-Type": "application/json", "X-Luminary-CSRF": csrf },
        body: JSON.stringify(request)
      });
      if (!response.ok) throw new Error("Inspector session unavailable");
      return response.json();
    },
    confirm: (preview_id) => json("/api/confirm", { preview_id })
  };
  controller = new InspectorController(transport);
  for (const tab of TABS) {
    const node = button(tab.label, async () => {
      selected = void 0;
      await controller.selectTab(tab.id);
    });
    node.dataset.tab = tab.id;
    node.setAttribute("role", "tab");
    tabs.append(node);
  }
  tabs.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = TABS.findIndex((tab2) => tab2.id === controller.state.tab);
    const index = event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length;
    const tab = tabs.querySelector(`[data-tab="${TABS[index].id}"]`);
    tab.click();
    tab.focus();
  });
  controller.subscribe(render);
  document.querySelector("#compact").addEventListener("click", () => {
    const compact = document.body.classList.toggle("compact");
    document.querySelector("#compact").textContent = compact ? "Full inspector" : "Compact view";
    if (compact) void loadCompact();
    else {
      overviewVersion++;
      permissionSnapshot = void 0;
      void controller.selectTab("memories");
    }
  });
  document.querySelector("#signout").addEventListener("click", async () => {
    await json("/api/sign-out", {});
    sessionStorage.removeItem("luminary-inspector-csrf");
    controller.dispose();
    view.replaceChildren(element("p", "Signed out. Launch the companion again to inspect memory.", "notice"));
    tabs.replaceChildren();
    toolbar.replaceChildren();
  });
  window.addEventListener("pagehide", () => controller.dispose(), { once: true });
  await controller.load();
}
start().catch((error) => {
  connection.textContent = error instanceof Error ? error.message : "Inspector unavailable";
});
