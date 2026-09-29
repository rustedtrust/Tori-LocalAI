"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "utility.js"),
  "utf8"
);

class FakeElement {
  constructor(identifier = "") {
    this.id = identifier;
    this.dataset = {};
    this.listeners = {};
    this.textContent = "";
    this.children = [];
    this.hidden = false;
  }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  setAttribute(name, value) { this[name] = value; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
}

const identifiers = [
  "utility-status-card", "utility-status-label", "utility-status-detail",
  "utility-host-cpu", "utility-host-memory", "utility-host-gpu",
  "utility-host-vram", "utility-host-vram-row",
  "utility-host-freshness",
  "utility-activity-card", "utility-activity-label",
  "utility-activity-detail", "utility-upcoming-empty", "utility-upcoming-list",
  "utility-coding-work-card", "utility-coding-work-label",
  "utility-coding-work-state", "utility-coding-work-latest",
  "utility-coding-work-workspace", "utility-coding-work-updated",
  "utility-coding-work-objective", "utility-coding-work-authority",
  "utility-coding-work-overview", "utility-coding-work-acceptance",
  "utility-coding-work-related-row", "utility-coding-work-related",
  "utility-coding-work-paths", "utility-coding-work-paths-empty",
  "utility-coding-work-activity", "utility-coding-work-activity-empty",
  "utility-coding-work-verification", "utility-coding-work-verification-empty",
  "utility-coding-work-result-group", "utility-coding-work-result",
  "utility-coding-work-error", "utility-coding-work-cancel",
];
const elements = new Map(identifiers.map((identifier) => [identifier, new FakeElement(identifier)]));
const root = new FakeElement("overview");
root.querySelector = (selector) => {
  return elements.get(selector.slice(1)) || null;
};
root.querySelectorAll = () => [];
const document = {
  createElement(tagName) { return new FakeElement(tagName); },
  querySelector(selector) {
    return selector === '[data-utility-module-root="overview"]' ? root : null;
  },
  dispatchEvent() {},
};
let nextTimer = 0;
const timers = new Map();
const window = {
  setTimeout(callback, delay) { assert.equal(delay, 15000); timers.set(++nextTimer, callback); return nextTimer; },
  clearTimeout(id) { timers.delete(id); },
};
vm.runInNewContext(source, {
  CustomEvent: class {
    constructor(name, options) { this.type = name; this.detail = options.detail; }
  },
  document,
  window,
});

async function main() {
  assert.ok(window.ToriUtilityRail);

window.ToriUtilityRail.setApplicationStatus("Generation in progress", "busy");
assert.equal(elements.get("utility-status-card").dataset.state, "busy");
assert.equal(elements.get("utility-status-label").textContent, "Tori is working");
assert.equal(elements.get("utility-status-detail").textContent, "Generation in progress");
assert.equal(elements.get("utility-activity-label").textContent, "Current operation");
assert.equal(elements.get("utility-activity-card").hidden, false);

window.ToriUtilityRail.setHostStatus({
  cpu: {available: true, utilization_percent: 12.5},
  memory: {available: true, used_bytes: 5 * 1024 ** 3, total_bytes: 16 * 1024 ** 3, used_percent: 31.25},
  gpus: [{utilization_percent: 25, memory_used_bytes: 4 * 1024 ** 3, memory_total_bytes: 24 * 1024 ** 3}],
});
assert.equal(elements.get("utility-host-cpu").textContent, "13%");
assert.equal(elements.get("utility-host-memory").textContent, "5.0 / 16 GB · 31%");
assert.equal(elements.get("utility-host-gpu").textContent, "25%");
assert.equal(elements.get("utility-host-vram").textContent, "4.0 / 24 GB");
assert.equal(elements.get("utility-host-vram-row").hidden, false);
assert.equal(elements.get("utility-host-cpu").dataset.state, "available");
timers.get(nextTimer)();
assert.equal(elements.get("utility-host-cpu").dataset.state, "stale");
assert.match(elements.get("utility-host-freshness").textContent, /Stale/);
window.ToriUtilityRail.setHostStatus({cpu: {}, memory: {}, gpus: []});
assert.equal(elements.get("utility-host-gpu").textContent, "Unavailable");
assert.equal(elements.get("utility-host-vram-row").hidden, true);
assert.equal(elements.get("utility-host-cpu").dataset.state, "unavailable");
assert.equal(timers.size, 0);
window.ToriUtilityRail.setApplicationStatus("Connected locally", "success");
assert.equal(elements.get("utility-status-detail").hidden, true);

window.ToriUtilityRail.setActivity("Voice output", "Speaking…", "busy", "speech");
assert.equal(elements.get("utility-activity-card").dataset.source, "speech");
assert.equal(elements.get("utility-activity-label").textContent, "Voice output");
window.ToriUtilityRail.setActivity();
assert.equal(elements.get("utility-activity-card").hidden, true);

window.ToriUtilityRail.setUpcoming({items: [{
  kind: "reminder",
  label: "Call the clinic",
  scheduled_at_utc: "2026-08-22T21:00:00Z",
  timezone: "America/Chicago",
}]});
assert.equal(elements.get("utility-upcoming-empty").hidden, true);
assert.equal(elements.get("utility-upcoming-list").hidden, false);
assert.ok(elements.get("utility-upcoming-list").children.length >= 2);

window.ToriUtilityRail.setCodingWork({work: []});
assert.equal(elements.get("utility-coding-work-card").hidden, true);

function codingWorkItem(identifier, state, revision) {
  return {
    identifier,
    revision,
    objective: "Create a startup script",
    workspace: "/temporary/github_project",
    state,
    needs_authorization: false,
    updated_at_utc: "2026-08-24T12:00:00Z",
    latest_activity: "Analyzing project structure",
    changed_paths: ["startup.sh"],
    recent_activity: [{summary: "Read the project files."}],
    result_summary: null,
    can_cancel: state === "running",
  };
}

const historicalTerminal = codingWorkItem(
  "coding-work-00000000000000000000000000000009", "completed", 3
);
window.ToriUtilityRail.setCodingWork({
  active: false, current_work_id: null, work: [historicalTerminal],
});
assert.equal(elements.get("utility-coding-work-card").hidden, false);
assert.equal(elements.get("utility-coding-work-state").textContent, "Complete");

window.ToriUtilityRail.setCodingWork({
  active: true,
  current_work_id: "coding-work-00000000000000000000000000000001",
  work: [{
  identifier: "coding-work-00000000000000000000000000000001",
  revision: 4,
  objective: "Create a startup script",
  workspace: "/temporary/github_project",
  state: "running",
  needs_authorization: false,
  updated_at_utc: "2026-08-24T12:00:00Z",
  latest_activity: "Analyzing project structure",
  changed_paths: ["startup.sh"],
  recent_activity: [{summary: "Read the project files."}],
  result_summary: null,
  can_cancel: true,
}],
});
assert.equal(elements.get("utility-coding-work-card").hidden, false);
assert.equal(elements.get("utility-coding-work-label").textContent, "github_project");
assert.equal(elements.get("utility-coding-work-state").textContent, "Running");
assert.equal(elements.get("utility-coding-work-paths").children[0].textContent, "startup.sh");
assert.equal(elements.get("utility-coding-work-cancel").hidden, false);

const terminalItem = {
  ...codingWorkItem("coding-work-00000000000000000000000000000001", "failed", 5),
  result_summary: "A bounded recorded failure is available.",
  can_cancel: false,
};
window.ToriUtilityRail.setCodingWork({
  active: false,
  current_work_id: null,
  work: [terminalItem],
});
assert.equal(elements.get("utility-coding-work-card").hidden, false);
assert.equal(elements.get("utility-coding-work-state").textContent, "Failed");
assert.equal(
  elements.get("utility-coding-work-latest").textContent,
  "Delegated Work failed. Open the details for the durable receipt."
);
assert.equal(elements.get("utility-coding-work-result").textContent,
  "A bounded recorded failure is available.");
assert.equal(elements.get("utility-coding-work-cancel").hidden, true);

// Repeated polls are idempotent: one visible terminal card, not a new notice.
window.ToriUtilityRail.setCodingWork({active: false, current_work_id: null, work: [terminalItem]});
assert.equal(elements.get("utility-coding-work-card").hidden, false);

const completedItem = codingWorkItem(
  "coding-work-00000000000000000000000000000002", "running", 6
);
window.ToriUtilityRail.setCodingWork({
  active: true, current_work_id: completedItem.identifier, work: [completedItem],
});
window.ToriUtilityRail.setCodingWork({
  active: false, current_work_id: null,
  work: [{...completedItem, state: "completed", revision: 7, can_cancel: false}],
});
assert.equal(elements.get("utility-coding-work-latest").textContent,
  "Delegated Work completed for /temporary/github_project.");

const cancelledItem = codingWorkItem(
  "coding-work-00000000000000000000000000000003", "running", 8
);
window.ToriUtilityRail.setCodingWork({
  active: true, current_work_id: cancelledItem.identifier, work: [cancelledItem],
});
window.ToriUtilityRail.setCodingWork({
  active: false, current_work_id: null,
  work: [{...cancelledItem, state: "cancelled", revision: 9, can_cancel: false}],
});
assert.equal(elements.get("utility-coding-work-latest").textContent,
  "Delegated Work was cancelled.");

let cancelTarget = null;
window.ToriUtilityRail.setCodingWorkCancelHandler(async (target) => {
  cancelTarget = target;
  return {
    current_work_id: null,
    work: [],
  };
});
window.ToriUtilityRail.setCodingWork({
  active: true,
  current_work_id: "coding-work-00000000000000000000000000000001",
  work: [{
    identifier: "coding-work-00000000000000000000000000000001",
    revision: 19,
    objective: "Create a startup script",
    workspace: "/temporary/github_project",
    state: "waiting",
    needs_authorization: false,
    updated_at_utc: "2026-08-24T12:05:00Z",
    latest_activity: "The restored worker is waiting.",
    changed_paths: [],
    recent_activity: [],
    result_summary: null,
    can_cancel: true,
  }],
});
await elements.get("utility-coding-work-cancel").listeners.click();
assert.equal(cancelTarget.identifier, "coding-work-00000000000000000000000000000001");
assert.equal(cancelTarget.expectedRevision, 19);
assert.equal(elements.get("utility-coding-work-cancel").disabled, false);

window.ToriUtilityRail.setCodingWork({
  active: true,
  current_work_id: "coding-work-00000000000000000000000000000001",
  work: [{
    identifier: "coding-work-00000000000000000000000000000001",
    revision: 20,
    objective: "Create a startup script",
    workspace: "/temporary/github_project",
    state: "waiting",
    needs_authorization: false,
    updated_at_utc: "2026-08-24T12:06:00Z",
    latest_activity: "The restored worker is waiting.",
    changed_paths: [],
    recent_activity: [],
    result_summary: null,
    can_cancel: true,
  }],
});
window.ToriUtilityRail.setCodingWorkCancelHandler(async () => {
  throw new Error("The Coding Work revision changed.");
});
await elements.get("utility-coding-work-cancel").listeners.click();
assert.equal(elements.get("utility-coding-work-error").hidden, false);
assert.equal(
  elements.get("utility-coding-work-error").textContent,
  "The Coding Work revision changed."
);
assert.equal(elements.get("utility-coding-work-cancel").disabled, false);
window.ToriUtilityRail.setCodingWork({
  active: true,
  current_work_id: "coding-work-00000000000000000000000000000001",
  work: [{
    identifier: "coding-work-00000000000000000000000000000001",
    revision: 20,
    objective: "Create a startup script",
    workspace: "/temporary/github_project",
    state: "waiting",
    needs_authorization: false,
    updated_at_utc: "2026-08-24T12:06:00Z",
    latest_activity: "The restored worker is waiting.",
    changed_paths: [],
    recent_activity: [],
    result_summary: null,
    can_cancel: true,
  }],
});
assert.equal(elements.get("utility-coding-work-error").hidden, false);
assert.equal(
  elements.get("utility-coding-work-error").textContent,
  "The Coding Work revision changed."
);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
