"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function makeElement(tag) {
  const element = {
    tagName: tag.toUpperCase(),
    children: [],
    dataset: {},
    hidden: false,
    textContent: "",
    className: "",
    type: "",
    value: "",
    style: {},
    listeners: {},
    append(...nodes) {
      this.children.push(...nodes);
    },
    replaceChildren(...nodes) {
      this.children = nodes;
    },
    addEventListener(name, handler) {
      (this.listeners[name] ||= []).push(handler);
    },
    removeEventListener() {},
    click() {
      for (const handler of this.listeners.click || []) {
        Promise.resolve().then(() => handler({}));
      }
    },
    scrollIntoView() {},
    focus() {},
    blur() {},
    querySelectorAll() {
      return [];
    },
  };
  Object.defineProperty(element, "innerHTML", {
    set(value) {
      element.textContent = String(value);
    },
    get() {
      return element.textContent;
    },
  });
  return element;
}

function subtreeText(node) {
  if (typeof node === "string") {
    return node;
  }
  const own = typeof node.textContent === "string" ? node.textContent : "";
  return [own, ...node.children.map(subtreeText)].join("\n");
}

function buttonsFor(article) {
  return article.children
    .filter((child) => child.tagName === "DIV")
    .flatMap((actions) => actions.children)
    .map((button) => button.textContent);
}

async function main() {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "tori", "web_assets", "app.js"),
    "utf8"
  );
  if (!source.includes("\n}());\n")) {
    throw new Error("unexpected app.js IIFE closing marker");
  }
  const instrumented = source.replace(
    "\n}());\n",
    "\nwindow.__toriTestRenderCompanionAttention = (body, security) => renderCompanionAttention(body, security);\n}());\n"
  );

  const elementsById = new Map();
  const documentShim = {
    createElement: (tag) => makeElement(tag),
    getElementById(id) {
      if (!elementsById.has(id)) {
        elementsById.set(id, makeElement("div"));
      }
      return elementsById.get(id);
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
    dispatchEvent() {
      return true;
    },
    activeElement: null,
  };

  class CustomEventShim {
    constructor(type, options = {}) {
      this.type = type;
      this.detail = options.detail;
    }
  }

  const actionRequests = [];
  const navigations = [];
  const uiShim = {
    csrfToken: "test-csrf",
    requestJson(requestPath, options = {}) {
      if (options.method === "POST") {
        if (requestPath !== "/api/companion-attention/action") {
          throw new Error(`unexpected POST ${requestPath}`);
        }
        actionRequests.push(
          typeof options.body === "string" ? JSON.parse(options.body) : options.body
        );
        return Promise.resolve({items: [], active_count: 0});
      }
      if (requestPath === "/api/companion-attention") {
        return Promise.resolve({items: [], active_count: 0});
      }
      throw new Error(`unexpected request ${requestPath}`);
    },
    closeDialog(dialog) { dialog.open = false; },
    openDialog(dialog) { dialog.open = true; },
    setBusy(target, value) { target.busy = value; },
    setStatus(target, text, state) {
      target.textContent = text;
      target.dataset.state = state;
    },
    showError(target, text) {
      target.textContent = text;
      target.hidden = !text;
    },
    navigate(view) { navigations.push(view); },
  };
  const windowShim = {
    ToriUI: uiShim,
    ToriAudio: null,
    confirm() {
      return false;
    },
    setTimeout() {
      return 0;
    },
    clearTimeout() {},
    addEventListener() {},
  };

  const context = vm.createContext({
    window: windowShim,
    document: documentShim,
    navigator: {},
    CustomEvent: CustomEventShim,
    Date,
    Intl,
    Math,
    JSON,
    Promise,
    Set,
    Map,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Error,
    TypeError,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
  });
  context.window = windowShim;
  vm.runInContext(instrumented, context, {filename: "app.js"});

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setTimeout(resolve, 25));

  const render = context.window.__toriTestRenderCompanionAttention;
  if (typeof render !== "function") {
    throw new Error("renderCompanionAttention was not exposed");
  }

  const longSummary =
    "Night Owl reviewed forty-two sources across the repository and produced a detailed multi-paragraph finding about dependency drift, including every file path, version delta, and recommendation that would dominate a narrow rail if rendered in full.";
  render({
    items: [
      {
        identifier: "att-night-owl",
        revision: 4,
        source: "night_owl",
        state: "open",
        attention_class: "needs_attention",
        title: "Dependency drift detected",
        summary: longSummary,
        deferred_until_utc: null,
      },
      {
        identifier: "att-research",
        revision: 7,
        source: "research",
        state: "deferred",
        attention_class: "worth_reviewing",
        title: "Research digest ready",
        summary: longSummary,
        deferred_until_utc: "2026-09-24T12:00:00Z",
      },
      {
        identifier: "att-reviewed",
        revision: 2,
        source: "research",
        state: "reviewed",
        attention_class: "worth_reviewing",
        title: "Reviewed item",
        summary: longSummary,
        deferred_until_utc: null,
      },
    ],
    active_count: 2,
  });

  const card = documentShim.getElementById("utility-attention-card");
  const count = documentShim.getElementById("utility-attention-count");
  const groups = documentShim.getElementById("utility-attention-groups");
  const empty = documentShim.getElementById("utility-attention-empty");

  if (card.hidden) {
    throw new Error("attention card should be visible with items");
  }
  if (count.textContent !== "2") {
    throw new Error(`expected attention count 2, got ${JSON.stringify(count.textContent)}`);
  }
  if (empty.hidden !== true) {
    throw new Error("empty state should be hidden while items are active");
  }

  const rendered = subtreeText(groups);
  for (const fragment of [
    "forty-two sources",
    "multi-paragraph finding",
    "every file path, version delta",
  ]) {
    if (rendered.includes(fragment)) {
      throw new Error(`long summary leaked into the rail: ${fragment}`);
    }
  }

  const sections = groups.children;
  if (sections.length !== 3) {
    throw new Error(`expected 3 attention groups, got ${sections.length}`);
  }
  const headings = sections.map((section) => section.children[0].textContent);
  if (JSON.stringify(headings) !== JSON.stringify(["Needs attention", "Worth reviewing", "Recently resolved"])) {
    throw new Error(`unexpected group headings: ${JSON.stringify(headings)}`);
  }

  const nightOwlItem = sections[0].children[1];
  const researchItem = sections[1].children[1];
  const reviewedItem = sections[2].children[1];
  if (nightOwlItem.children[0].textContent !== "Dependency drift detected") {
    throw new Error("attention item title was not preserved");
  }
  if (nightOwlItem.children[1].className !== "attention-workspace-meta") {
    throw new Error("compact meta line is missing its class");
  }
  if (nightOwlItem.children[1].textContent !== "Night Owl · open") {
    throw new Error(`unexpected night owl meta line: ${JSON.stringify(nightOwlItem.children[1].textContent)}`);
  }
  if (researchItem.children[1].textContent !== "Research · deferred") {
    throw new Error(`unexpected research meta line: ${JSON.stringify(researchItem.children[1].textContent)}`);
  }
  const deferredLine = researchItem.children.find((child) => child.tagName === "SMALL");
  if (!deferredLine || !deferredLine.textContent.startsWith("Deferred until ")) {
    throw new Error("deferred-until line is missing or malformed");
  }

  for (const [item, label] of [[nightOwlItem, "open"], [researchItem, "deferred"]]) {
    const labels = buttonsFor(item);
    if (JSON.stringify(labels) !== JSON.stringify(["Review", "Later", "Dismiss"])) {
      throw new Error(`${label} item actions changed: ${JSON.stringify(labels)}`);
    }
  }
  if (buttonsFor(reviewedItem).length !== 0) {
    throw new Error("resolved items must not expose disposition controls");
  }

  const reviewButton = nightOwlItem.children
    .filter((child) => child.tagName === "DIV")
    .flatMap((actions) => actions.children)[0];
  reviewButton.click();
  await new Promise((resolve) => setTimeout(resolve, 25));
  if (actionRequests.length !== 1) {
    throw new Error(`expected one attention action request, got ${actionRequests.length}`);
  }
  const sent = actionRequests[0];
  if (JSON.stringify(sent) !== JSON.stringify({
    identifier: "att-night-owl",
    expected_revision: 4,
    action: "review",
  })) {
    throw new Error(`unexpected attention action body: ${JSON.stringify(sent)}`);
  }
  if (JSON.stringify(navigations) !== JSON.stringify(["settings"])) {
    throw new Error(`expected review navigation to settings, got ${JSON.stringify(navigations)}`);
  }

  const laterButton = researchItem.children
    .filter((child) => child.tagName === "DIV")
    .flatMap((actions) => actions.children)[1];
  laterButton.click();
  await new Promise((resolve) => setTimeout(resolve, 25));
  if (actionRequests.length !== 2) {
    throw new Error(`expected a second attention action request, got ${actionRequests.length}`);
  }
  const deferredSent = actionRequests[1];
  if (JSON.stringify(deferredSent) !== JSON.stringify({
    identifier: "att-research",
    expected_revision: 7,
    action: "later",
  })) {
    throw new Error(`unexpected later body: ${JSON.stringify(deferredSent)}`);
  }

  const dismissButton = researchItem.children
    .filter((child) => child.tagName === "DIV")
    .flatMap((actions) => actions.children)[2];
  dismissButton.click();
  await new Promise((resolve) => setTimeout(resolve, 25));
  if (actionRequests.length !== 3) {
    throw new Error(`expected a third attention action request, got ${actionRequests.length}`);
  }
  const dismissedSent = actionRequests[2];
  if (JSON.stringify(dismissedSent) !== JSON.stringify({
    identifier: "att-research",
    expected_revision: 7,
    action: "dismiss",
  })) {
    throw new Error(`unexpected dismiss body: ${JSON.stringify(dismissedSent)}`);
  }

  render({items: []}, {attention_count: 2});
  if (card.hidden || count.textContent !== "2" || groups.children.length !== 1 ||
      !subtreeText(groups).includes("Security — 2 new high-interest threat intelligence findings")) {
    throw new Error("security attention should use one compact row when noteworthy");
  }
  groups.children[0].children[1].click();
  await new Promise((resolve) => setImmediate(resolve));
  if (navigations[navigations.length - 1] !== "security") {
    throw new Error("security review must navigate to Security workspace");
  }
  render({items: []}, {attention_count: 0});
  if (!card.hidden || groups.children.length !== 0) {
    throw new Error("no security attention should appear without noteworthy new intelligence");
  }

  console.log("PASS: companion attention rail stays compact with disposition controls");
}

main().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
