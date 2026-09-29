"use strict";

const assert = require("assert");
const path = require("path");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.className = "";
    this.value = "";
    this.isConnected = true;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    for (const child of this.children) child.isConnected = false;
    this.children = [...children];
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  focus() {}

  dispatch(name, event = {}) {
    const callback = this.listeners.get(name);
    if (callback) return callback(event);
    return undefined;
  }
}

const identifiers = [
  "checkpoint-form", "checkpoint-list", "checkpoint-name",
  "invalid-registration-list", "knowledge-form", "knowledge-list",
  "knowledge-path", "management-cancel", "management-confirm",
  "management-confirmation", "management-confirmation-heading",
  "management-confirmation-message", "management-confirmation-target",
  "memory-form", "memory-list", "memory-text", "message",
  "operational-history", "operational-history-summary",
  "operational-history-toggle", "reminder-history-list", "reminder-list",
  "project-form", "project-list", "project-objective", "project-title",
  "scheduled-run-history", "scheduled-work-active", "scheduled-work-date",
  "scheduled-work-edit-cancel", "scheduled-work-form",
  "scheduled-work-history", "scheduled-work-missed",
  "scheduled-work-paused", "scheduled-work-submit", "scheduled-work-time",
  "scheduled-work-title", "task-description", "task-form",
  "task-history-list", "task-list",
];
const elements = new Map(identifiers.map((identifier) => [identifier, new Element()]));
const documentListeners = new Map();
const windowListeners = new Map();
const intervals = [];
let scheduledRequests = 0;
let scheduledQueue = [];
const confirmationRequests = [];
const proposalRequests = [];
const postRequests = [];
let proposalToken = "scheduled-secret-token";
const reviewProposal = {
  operation: "create",
  title: "Phase 7 <script>alert(1)</script>",
  capability_id: "tori.backup",
  capability_contract_version: 1,
  arguments: {
    nested: {enabled: true, count: 2, empty: null},
    labels: ["<b>literal</b>", false, 3, null],
  },
  schedule: {
    timezone: "America/Chicago",
    occurrence_utc: "2026-08-12T03:20:00Z",
    kind: "one_shot",
  },
  scheduled_mode: "one_shot",
  missed_policy: "run_when_available",
  persistent_permission: true,
  dst_policy: null,
  application_lifetime: "Runs only while Tori's application process exists; startup recovery applies after downtime.",
};

function definition({
  revision = 1,
  status = "active",
  title = "Back up Tori",
  occurrenceUtc = "2026-08-13T05:10:00Z",
  timezoneName = "America/Chicago",
} = {}) {
  return {
    identifier: "work-stable",
    revision,
    title,
    capability_id: "tori.backup",
    capability_contract_version: 1,
    schedule_kind: "one_shot",
    scheduled_mode: "one_shot",
    timezone_name: timezoneName,
    missed_policy: "run_when_available",
    status,
    current_authorization_id: "authorization-stable",
    next_occurrence_utc: status === "active" ? occurrenceUtc : null,
    updated_at_utc: `2026-08-12T00:00:0${revision}Z`,
    arguments: {},
    schedule: {
      kind: "one_shot",
      timezone: timezoneName,
      occurrence_utc: occurrenceUtc,
    },
  };
}

function scheduledState(revision, definitions = [definition({revision})]) {
  return {scheduled_work_revision: revision, definitions, authorizations: [], runs: []};
}

let currentScheduled = scheduledState(1);

global.document = {
  hidden: false,
  activeElement: null,
  createElement: (tagName) => new Element(tagName),
  getElementById: (identifier) => elements.get(identifier),
  querySelectorAll: () => [],
  addEventListener: (name, callback) => documentListeners.set(name, callback),
};

global.window = {
  ToriUI: {
    createElement(tagName, className = "", text = "") {
      const element = new Element(tagName);
      element.className = className;
      element.textContent = String(text);
      return element;
    },
    requestJson(requestPath, options = {}) {
      if (options.method === "POST") {
        postRequests.push({path: requestPath, body: options.body});
      }
      if (requestPath === "/api/scheduled-work") {
        scheduledRequests += 1;
        if (scheduledQueue.length) return scheduledQueue.shift();
        return Promise.resolve(currentScheduled);
      }
      if (requestPath === "/api/checkpoints") {
        return Promise.resolve({busy: false, checkpoints: []});
      }
      if (requestPath === "/api/projects") {
        return Promise.resolve({busy: false, projects: [], active_project_id: null});
      }
      if (requestPath === "/api/memories") {
        return Promise.resolve({busy: false, memories: []});
      }
      if (requestPath === "/api/knowledge") {
        return Promise.resolve({busy: false, sources: [], invalid_registrations: []});
      }
      if (requestPath === "/api/tasks") return Promise.resolve({tasks: []});
      if (requestPath === "/api/reminders") return Promise.resolve({reminders: []});
      if (requestPath === "/api/scheduled-work/propose-backup") {
        proposalRequests.push(options.body);
        return Promise.resolve({
          confirmation: {
            token: proposalToken,
            action: "scheduled_work.authorize",
            message: "Authorize this exact persistent scheduled work?",
            proposal: reviewProposal,
          },
        });
      }
      if (requestPath === "/api/confirm") {
        confirmationRequests.push(options.body);
        return Promise.resolve(
          options.body.decision === "confirm" ?
            {action: "scheduled_work.authorize", scheduled_work_revision: 6} :
            {action: "scheduled_work.authorize"}
        );
      }
      throw new Error(`Unexpected request: ${requestPath}`);
    },
    currentView: () => "scheduled-work",
    showError() {},
    setStatus() {},
    setBusy() {},
    openDialog() {},
    closeDialog() {},
    navigate() {},
  },
  setInterval(callback, milliseconds) {
    intervals.push({callback, milliseconds});
  },
  addEventListener(name, callback) {
    windowListeners.set(name, callback);
  },
};

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function firstCard(container) {
  return container.children.find((child) => child.tagName === "ARTICLE");
}

function detailsAndActions(card) {
  return {details: card.children[2], actions: card.children[3]};
}

async function main() {
  require(path.join(__dirname, "..", "src", "tori", "web_assets", "manage.js"));
  await flush();
  await flush();

  assert.strictEqual(intervals.length, 2);
  assert.strictEqual(intervals[0].milliseconds, 1500);
  const active = elements.get("scheduled-work-active");
  const paused = elements.get("scheduled-work-paused");
  let card = firstCard(active);
  assert.ok(card);
  let {details, actions} = detailsAndActions(card);
  assert.strictEqual(details.hidden, true);
  const postsBeforeEdit = proposalRequests.length;
  const allPostsBeforeEdit = postRequests.length;
  actions.children[1].dispatch("click");
  assert.strictEqual(elements.get("scheduled-work-title").value, "Back up Tori");
  assert.strictEqual(elements.get("scheduled-work-date").value, "2026-08-13");
  assert.strictEqual(elements.get("scheduled-work-time").value, "00:10");
  assert.strictEqual(elements.get("scheduled-work-missed").value, "run_when_available");
  assert.strictEqual(proposalRequests.length, postsBeforeEdit);
  assert.strictEqual(postRequests.length, allPostsBeforeEdit);
  elements.get("scheduled-work-edit-cancel").dispatch("click");
  assert.strictEqual(proposalRequests.length, postsBeforeEdit);
  assert.strictEqual(postRequests.length, allPostsBeforeEdit);

  actions.children[1].dispatch("click");
  elements.get("scheduled-work-form").dispatch("submit", {preventDefault() {}});
  await flush();
  assert.deepStrictEqual(proposalRequests.at(-1), {
    title: "Back up Tori",
    local_date: "2026-08-13",
    local_time: "00:10",
    missed_policy: "run_when_available",
    identifier: "work-stable",
    expected_revision: 1,
  });
  actions.children[1].dispatch("click");
  elements.get("scheduled-work-time").value = "01:25";
  elements.get("scheduled-work-form").dispatch("submit", {preventDefault() {}});
  await flush();
  assert.strictEqual(proposalRequests.at(-1).local_date, "2026-08-13");
  assert.strictEqual(proposalRequests.at(-1).local_time, "01:25");
  actions.children[1].dispatch("click");
  elements.get("scheduled-work-date").value = "2026-08-14";
  elements.get("scheduled-work-form").dispatch("submit", {preventDefault() {}});
  await flush();
  assert.strictEqual(proposalRequests.at(-1).local_date, "2026-08-14");
  assert.strictEqual(proposalRequests.at(-1).local_time, "00:10");
  elements.get("scheduled-work-edit-cancel").dispatch("click");

  currentScheduled = scheduledState(2, [definition({
    revision: 2,
    occurrenceUtc: "2026-08-13T04:30:00Z",
  })]);
  intervals[0].callback();
  await flush();
  card = firstCard(active);
  detailsAndActions(card).actions.children[1].dispatch("click");
  assert.strictEqual(elements.get("scheduled-work-date").value, "2026-08-12");
  assert.strictEqual(elements.get("scheduled-work-time").value, "23:30");

  currentScheduled = scheduledState(3, [definition({
    revision: 3,
    occurrenceUtc: "2026-08-13T05:00:00Z",
  })]);
  intervals[0].callback();
  await flush();
  card = firstCard(active);
  detailsAndActions(card).actions.children[1].dispatch("click");
  assert.strictEqual(elements.get("scheduled-work-date").value, "2026-08-13");
  assert.strictEqual(elements.get("scheduled-work-time").value, "00:00");

  currentScheduled = scheduledState(4, [definition({
    revision: 4,
    occurrenceUtc: "2026-08-13T18:15:00Z",
    timezoneName: "Asia/Kathmandu",
  })]);
  intervals[0].callback();
  await flush();
  card = firstCard(active);
  detailsAndActions(card).actions.children[1].dispatch("click");
  assert.strictEqual(elements.get("scheduled-work-date").value, "2026-08-14");
  assert.strictEqual(elements.get("scheduled-work-time").value, "00:00");
  elements.get("scheduled-work-edit-cancel").dispatch("click");
  ({details, actions} = detailsAndActions(card));

  const closedCard = card;
  intervals[0].callback();
  await flush();
  assert.strictEqual(firstCard(active), closedCard);
  assert.strictEqual(details.hidden, true);
  actions.children[0].dispatch("click");
  assert.strictEqual(details.hidden, false);

  const selectedNode = details;
  const requestsBeforeSameRevision = scheduledRequests;
  intervals[0].callback();
  await flush();
  assert.strictEqual(scheduledRequests, requestsBeforeSameRevision + 1);
  assert.strictEqual(firstCard(active), card);
  assert.strictEqual(card.children[2], selectedNode);
  assert.strictEqual(details.hidden, false);

  currentScheduled = scheduledState(10, [definition({revision: 10, status: "paused"})]);
  intervals[0].callback();
  await flush();
  card = firstCard(paused);
  assert.ok(card);
  ({details, actions} = detailsAndActions(card));
  assert.strictEqual(details.hidden, false);
  assert.deepStrictEqual(
    actions.children.map((button) => button.textContent),
    ["Hide Details", "Edit", "Resume", "Cancel"],
  );

  currentScheduled = scheduledState(11, []);
  intervals[0].callback();
  await flush();
  assert.strictEqual(firstCard(active), undefined);
  assert.strictEqual(firstCard(paused), undefined);

  currentScheduled = scheduledState(12, [definition({revision: 12})]);
  intervals[0].callback();
  await flush();
  card = firstCard(active);
  assert.ok(card);
  assert.strictEqual(card.children[2].hidden, true);

  let resolveOlder;
  let resolveNewer;
  scheduledQueue = [
    new Promise((resolve) => { resolveOlder = resolve; }),
    new Promise((resolve) => { resolveNewer = resolve; }),
  ];
  intervals[0].callback();
  intervals[0].callback();
  resolveNewer(scheduledState(14, [definition({revision: 14, title: "Newer"})]));
  await flush();
  resolveOlder(scheduledState(13, [definition({revision: 13, title: "Older"})]));
  await flush();
  assert.strictEqual(firstCard(active).children[0].textContent, "Newer");

  const beforeFocus = scheduledRequests;
  windowListeners.get("focus")();
  await flush();
  assert.strictEqual(scheduledRequests, beforeFocus + 1);
  const beforeVisibility = scheduledRequests;
  documentListeners.get("visibilitychange")();
  await flush();
  assert.strictEqual(scheduledRequests, beforeVisibility + 1);

  const proposalBeforeRendering = JSON.stringify(reviewProposal);
  const form = elements.get("scheduled-work-form");
  form.dispatch("submit", {preventDefault() {}});
  await flush();
  const reviewText = elements.get("management-confirmation-target").textContent;
  assert.ok(reviewText.includes("Capability: tori.backup v1"));
  assert.ok(reviewText.includes("Arguments:"));
  assert.ok(reviewText.includes('"nested": {"count": 2, "empty": null, "enabled": true}'));
  assert.ok(reviewText.includes('["<b>literal</b>", false, 3, null]'));
  assert.ok(reviewText.includes('Schedule kind: one_shot'));
  assert.ok(reviewText.includes("Occurrence UTC: 2026-08-12T03:20:00Z"));
  assert.ok(reviewText.includes("Timezone: America/Chicago"));
  assert.ok(reviewText.includes("Mode: one_shot"));
  assert.ok(reviewText.includes("Missed-run policy: run_when_available"));
  assert.ok(reviewText.includes("Persistent permission: YES"));
  assert.ok(reviewText.includes("Runs only while Tori's application process exists"));
  assert.ok(reviewText.includes("<script>alert(1)</script>"));
  assert.ok(!reviewText.includes("[object Object]"));
  assert.ok(!reviewText.includes(proposalToken));
  assert.strictEqual(elements.get("management-confirmation-target").children.length, 0);
  assert.strictEqual(JSON.stringify(reviewProposal), proposalBeforeRendering);

  elements.get("management-confirm").dispatch("click");
  await flush();
  assert.deepStrictEqual(confirmationRequests[0], {
    token: "scheduled-secret-token",
    decision: "confirm",
  });

  proposalToken = "scheduled-cancel-token";
  reviewProposal.arguments = {};
  const emptyArgumentsProposal = JSON.stringify(reviewProposal);
  form.dispatch("submit", {preventDefault() {}});
  await flush();
  assert.ok(
    elements.get("management-confirmation-target").textContent.includes(
      "Arguments: {}"
    )
  );
  elements.get("management-cancel").dispatch("click");
  await flush();
  assert.deepStrictEqual(confirmationRequests[1], {
    token: "scheduled-cancel-token",
    decision: "cancel",
  });
  assert.strictEqual(JSON.stringify(reviewProposal), emptyArgumentsProposal);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
