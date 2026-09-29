"use strict";

const assert = require("node:assert");
const path = require("node:path");

function setConnected(node, value) {
  node.isConnected = value;
  for (const child of node.children ?? []) setConnected(child, value);
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parent = null;
    this.listeners = new Map();
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.isConnected = false;
  }

  get classList() {
    const self = this;
    return {add(name) { self.className += ` ${name}`; }};
  }

  append(...nodes) {
    for (const node of nodes) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1);
      node.parent = this;
      setConnected(node, true);
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    for (const child of [...this.children]) {
      setConnected(child, false);
      child.parent = null;
    }
    this.children = [];
    this.append(...nodes);
  }

  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }

  dispatch(name, event = {}) {
    for (const listener of this.listeners.get(name) ?? []) listener(event);
  }

  setAttribute(_name, _value) {}

  focus() {
    document.activeElement = this;
  }

  closest(selector) {
    let node = this;
    while (node !== null) {
      if (selector === ".project-link-form" &&
          String(node.className).split(/\s+/).includes("project-link-form")) {
        return node;
      }
      node = node.parent;
    }
    return null;
  }
}

const identifiers = [
  "projects-heading", "project-list", "project-form", "project-title",
  "project-objective", "checkpoint-form", "checkpoint-name", "checkpoint-list",
  "memory-form", "memory-text", "memory-list", "knowledge-form",
  "knowledge-path", "knowledge-list", "invalid-registration-list",
  "management-confirmation", "management-confirmation-heading",
  "management-confirmation-message", "management-confirmation-target",
  "management-confirm", "management-cancel", "task-list", "reminder-list",
  "operational-history-toggle", "operational-history",
  "operational-history-summary", "task-history-list", "reminder-history-list",
  "scheduled-work-form", "scheduled-work-title", "scheduled-work-date",
  "scheduled-work-time", "scheduled-work-missed", "scheduled-work-submit",
  "scheduled-work-edit-cancel", "scheduled-work-active",
  "scheduled-work-paused", "scheduled-work-history", "scheduled-run-history",
];

const elements = new Map(identifiers.map((id) => [id, new Element("div")]));
elements.get("project-list").isConnected = true;
const refreshButton = new Element("button");
refreshButton.className = "secondary refresh-management";
refreshButton.isConnected = true;

globalThis.window = {
  ToriUI: null,
  confirm: () => globalThis.__confirmResult,
  setInterval(callback) {
    window.__intervals.push({callback});
    return window.__intervals.length;
  },
  addEventListener() {},
  __intervals: [],
};

globalThis.document = {
  activeElement: null,
  hidden: false,
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) ?? null,
  querySelectorAll(selector) {
    if (selector === ".refresh-management") return [refreshButton];
    return [];
  },
  addEventListener() {},
  dispatchEvent() {},
};

globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};

const findingId = "finding-" + "a".repeat(32);
const backupWorkId = "work-" + "b".repeat(32);
const planningWorkId = "work-" + "c".repeat(32);
const knowledgeId = "knowledge-" + "d".repeat(32);

function home(revision, links = []) {
  return {
    project: {
      identifier: "project-" + "a".repeat(32),
      title: "Continuity acceptance",
      objective: "Verify the final Project link UX.",
      status: "active",
      revision,
    },
    workspace_state: null,
    where_we_are: {
      objective: "Verify the final Project link UX.",
      status: "active", phase: "Not yet recorded",
      current_focus: "Not yet recorded", checkpoint: "Not yet recorded",
      structured_state_present: false, next_planned_step: null,
      active_plan_items: [], blocked_plan_items: [], open_questions: [],
      open_question_count: 0, deferred_question_count: 0,
      last_updated_at: "2026-09-23T12:00:00Z",
    },
    active_decisions: [], superseded_decisions: [],
    active_questions: [], closed_questions: [], plan_items: [],
    conversations: [],
    legacy_continuity: {text: "", present: false},
    freshness: {
      project_revision: revision,
      project_updated_at: "2026-09-23T12:00:00Z",
      structured_updated_at: null, conversations_updated_at: null,
    },
    related_work: null,
    links,
  };
}

let projects = {
  active_project_id: "project-" + "a".repeat(32),
  project_homes: [home(1)],
};
const linkTargetResponses = [];
const projectResponses = [];
const posts = [];
let projectRequests = 0;
let linkTargetRequests = 0;

window.ToriUI = {
  currentView: () => "projects",
  showError() {},
  setStatus() {},
  setBusy() {},
  navigate() {},
  createElement(tagName, className, text) {
    const element = new Element(tagName);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  },
  async requestJson(requestPath, options = {}) {
    if (options.method === "POST") {
      posts.push({path: requestPath, body: options.body});
      if (requestPath === "/api/projects/link") {
        projects = {...projects, project_homes: [home(3)]};
        return {};
      }
      if (requestPath === "/api/projects/unlink") {
        projects = {...projects, project_homes: [home(4)]};
        return {};
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    }
    if (requestPath === "/api/projects") {
      projectRequests += 1;
      return projectResponses.shift() || Promise.resolve(projects);
    }
    if (requestPath === "/api/projects/link-targets") {
      linkTargetRequests += 1;
      return Promise.resolve(linkTargetResponses.shift() ?? {
        ok: true, busy: false, sources: {
          night_owl_finding: {available: true, items: [
            {identifier: findingId, title: "Night Owl research review"},
          ]},
          scheduled_work_definition: {available: true, items: [
            {identifier: backupWorkId, title: "Back up Tori"},
            {identifier: planningWorkId, title: "Planning reminder: Planning acceptance event"},
          ]},
          knowledge_source: {available: true, items: [
            {identifier: knowledgeId, title: "notes.md"},
          ]},
        },
      });
    }
    if (requestPath === "/api/checkpoints") return {checkpoints: [], busy: false};
    if (requestPath === "/api/memories") return {memories: [], busy: false};
    if (requestPath === "/api/knowledge") return {sources: [], invalid_registrations: []};
    if (requestPath === "/api/tasks") return {tasks: []};
    if (requestPath === "/api/reminders") return {reminders: []};
    if (requestPath === "/api/scheduled-work") {
      return {scheduled_work_revision: 1, definitions: [], runs: []};
    }
    throw new Error(`Unexpected request ${requestPath}`);
  },
};

require(path.join(__dirname, "..", "src", "tori", "web_assets", "manage.js"));

function find(root, predicate) {
  if (root === null || root === undefined) return null;
  if (predicate(root)) return root;
  for (const child of root.children ?? []) {
    const match = find(child, predicate);
    if (match !== null) return match;
  }
  return null;
}

function linkForm() {
  return find(elements.get("project-list"), (element) =>
    String(element.className).includes("project-link-form"));
}

function formSelect(form, name) {
  return find(form, (element) => element.tagName === "SELECT" && element.name === name);
}

async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
}

async function waitFor(predicate, label) {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    if (predicate()) return;
    await flush();
  }
  assert.fail(`Timed out waiting for ${label}`);
}

(async () => {
  globalThis.__confirmResult = false;
  await flush();
  await flush();

  const openButton = find(elements.get("project-list"), (element) => element.textContent === "Open Project");
  assert.notStrictEqual(openButton, null, "Project landing card offers Open Project");
  openButton.dispatch("click");
  let form = linkForm();
  assert.notStrictEqual(form, null, "Project Home renders the link form");

  // The manual target-ID text field is gone: only selectors remain.
  assert.strictEqual(find(form, (element) => element.tagName === "INPUT"), null);
  const typeSelect = formSelect(form, "project-link-type");
  const itemSelect = formSelect(form, "project-link-item");
  assert.notStrictEqual(typeSelect, null, "source-type selector is present");
  assert.notStrictEqual(itemSelect, null, "item selector is present");
  const linkButton = find(form, (element) => element.textContent === "Link" && element.type === "submit");
  assert.notStrictEqual(linkButton, null, "Link submit button is present");

  // Night Owl options arrive from the source-owned read API.
  await waitFor(() => itemSelect.children.length > 1, "Night Owl item options");
  const findingOption = itemSelect.children.at(-1);
  assert.strictEqual(findingOption.textContent, "Night Owl research review");
  assert.strictEqual(findingOption.value, findingId);
  assert.strictEqual(linkButton.disabled, true, "Link stays disabled until an item is chosen");

  // Selecting by title carries the stable ID internally.
  itemSelect.value = findingId;
  itemSelect.dispatch("change");
  const idMeta = find(form, (element) => String(element.className).includes("project-link-id-meta"));
  assert.strictEqual(idMeta.textContent, `Stable ID: ${findingId}`);
  assert.strictEqual(linkButton.disabled, false);

  // Declining the confirmation changes nothing and keeps the draft.
  await form.dispatch("submit", {preventDefault() {}});
  assert.strictEqual(posts.length, 0);
  assert.strictEqual(form.isConnected, true);

  const cancel = find(form, (element) => element.textContent === "Cancel link");
  cancel.dispatch("click");
  await flush();
  form = linkForm();
  assert.strictEqual(formSelect(form, "project-link-item").value, "");

  // Confirmed Link posts the stable ID with the current Project revision.
  globalThis.__confirmResult = true;
  const firstItemSelect = formSelect(form, "project-link-item");
  firstItemSelect.value = findingId;
  firstItemSelect.dispatch("change");
  await form.dispatch("submit", {preventDefault() {}});
  await flush();
  assert.strictEqual(posts.length, 1);
  assert.deepStrictEqual(posts.at(-1), {
    path: "/api/projects/link",
    body: {
      project_id: home(1).project.identifier,
      expected_project_revision: 1,
      target_type: "night_owl_finding",
      target_id: findingId,
      confirmed: true,
    },
  });
  assert.strictEqual(form.isConnected, false, "successful Link re-renders the Project Home");

  // Scheduled Work options are populated from source-owned records.
  form = linkForm();
  const nextTypeSelect = formSelect(form, "project-link-type");
  const nextItemSelect = formSelect(form, "project-link-item");
  nextTypeSelect.value = "scheduled_work_definition";
  nextTypeSelect.dispatch("change");
  assert.strictEqual(nextItemSelect.children.length, 3);
  assert.deepStrictEqual(
    nextItemSelect.children.slice(1).map((option) => [option.textContent, option.value]),
    [
      ["Back up Tori", backupWorkId],
      ["Planning reminder: Planning acceptance event", planningWorkId],
    ],
  );

  // Knowledge options are populated from registered source filenames.
  nextTypeSelect.value = "knowledge_source";
  nextTypeSelect.dispatch("change");
  assert.strictEqual(nextItemSelect.children.length, 2);
  assert.strictEqual(nextItemSelect.children.at(-1).textContent, "notes.md");
  assert.strictEqual(nextItemSelect.children.at(-1).value, knowledgeId);

  // A poll that resolves while the user is editing must not replace the form.
  find(form, (element) => element.textContent === "Cancel link").dispatch("click");
  await flush();
  form = linkForm();
  const pollItemSelect = formSelect(form, "project-link-item");
  let finishPoll;
  projectResponses.push(new Promise((resolve) => { finishPoll = resolve; }));
  const requestsBeforeEdit = projectRequests;
  window.__intervals[1].callback();
  await flush();
  assert.strictEqual(projectRequests, requestsBeforeEdit + 1, "poll fetch started while idle");

  form.dispatch("focusin");
  pollItemSelect.focus();
  pollItemSelect.value = findingId;
  pollItemSelect.dispatch("change");
  projects = {...projects, project_homes: [home(2)]};
  finishPoll(projects);
  await flush();
  assert.strictEqual(form.isConnected, true, "editing form survives a late poll");
  assert.strictEqual(pollItemSelect.value, findingId, "selection survives polling");
  assert.strictEqual(document.activeElement, pollItemSelect);

  window.__intervals[1].callback();
  await flush();
  assert.strictEqual(projectRequests, requestsBeforeEdit + 1, "polling pauses while editing");

  // Confirmation and revision behavior are unchanged.
  globalThis.__confirmResult = false;
  await form.dispatch("submit", {preventDefault() {}});
  assert.strictEqual(posts.length, 1);
  find(form, (element) => element.textContent === "Cancel link").dispatch("click");
  await flush();

  // Manual refresh reloads options and shows truthful unavailable/empty states.
  linkTargetResponses.push({
    ok: true, busy: false, sources: {
      night_owl_finding: {available: true, items: [
        {identifier: findingId, title: "Night Owl research review"},
      ]},
      scheduled_work_definition: {available: false},
      knowledge_source: {available: true, items: []},
    },
  });
  refreshButton.dispatch("click");
  await waitFor(() => linkTargetRequests >= 2, "second options load");
  await flush();
  form = linkForm();
  const refreshedType = formSelect(form, "project-link-type");
  const refreshedItem = formSelect(form, "project-link-item");
  const refreshedLink = find(form, (element) => element.textContent === "Link" && element.type === "submit");
  assert.strictEqual(refreshedItem.children.length, 2);
  assert.strictEqual(refreshedItem.children.at(-1).value, findingId);

  refreshedType.value = "scheduled_work_definition";
  refreshedType.dispatch("change");
  assert.strictEqual(refreshedItem.disabled, true);
  assert.strictEqual(refreshedItem.children.length, 1);
  assert.strictEqual(refreshedItem.children.at(0).textContent, "Source unavailable");
  assert.strictEqual(refreshedLink.disabled, true, "unavailable source disables linking");
  await form.dispatch("submit", {preventDefault() {}});
  assert.strictEqual(posts.length, 1, "unavailable source cannot be linked");

  refreshedType.value = "knowledge_source";
  refreshedType.dispatch("change");
  assert.strictEqual(refreshedItem.disabled, true);
  assert.strictEqual(refreshedItem.children.at(0).textContent, "No available items");
  assert.strictEqual(refreshedLink.disabled, true);

  // Existing links keep their confirmation and revision-protected Unlink.
  // Release the editing draft first: an active edit is preserved by design,
  // so a refresh while editing would (correctly) not re-render.
  find(form, (element) => element.textContent === "Cancel link").dispatch("click");
  await flush();
  const linkId = "project-link-" + "f".repeat(32);
  projects = {
    active_project_id: home(1).project.identifier,
    project_homes: [home(1, [{
      identifier: linkId, target_type: "night_owl_finding",
      target_id: findingId, revision: 1,
    }])],
  };
  refreshButton.dispatch("click");
  await waitFor(() => find(elements.get("project-list"), (element) => element.textContent === "Unlink") !== null, "unlink button");
  const unlink = find(elements.get("project-list"), (element) => element.textContent === "Unlink");

  globalThis.__confirmResult = false;
  unlink.dispatch("click");
  await flush();
  assert.strictEqual(posts.length, 1);

  globalThis.__confirmResult = true;
  unlink.dispatch("click");
  await flush();
  assert.deepStrictEqual(posts.at(-1), {
    path: "/api/projects/unlink",
    body: {
      project_id: home(1).project.identifier,
      link_id: linkId,
      expected_project_revision: 1,
      expected_link_revision: 1,
    },
  });

  console.log("Project link selector tests passed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
