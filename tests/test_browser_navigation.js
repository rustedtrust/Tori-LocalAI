"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "ui.js"),
  "utf8"
);
const modulesSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "view_modules.js"),
  "utf8"
);

class FakeElement {
  constructor({viewLink = null, viewPanel = null, heading = null} = {}) {
    this.dataset = {};
    if (viewLink) this.dataset.viewLink = viewLink;
    if (viewPanel) this.dataset.viewPanel = viewPanel;
    this.heading = heading;
    this.hidden = false;
    this.open = false;
    this.listeners = {};
    this.attributes = {};
    this.isConnected = true;
    this.href = viewLink === "conversation" ? "/" : `/manage#${viewLink}`;
  }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  append(...children) { for (const child of children) child.parentElement = this; }
  insertBefore(child) { child.parentElement = this; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  focus() {}
  querySelector(selector) {
    if (selector === "h1") return this.heading;
    if (selector === "[data-utility-module-root]") return this.utilityModule;
    return null;
  }
}

const views = [
  "home",
  "conversation", "projects", "tasks", "scheduled-work", "memories",
  "knowledge", "commands", "settings",
  "skills-mcp",
];
const headings = new Map(views.map((view) => [view, {textContent: view, setAttribute() {}, focus() {}}]));
const panels = views.map((view) => new FakeElement({viewPanel: view, heading: headings.get(view)}));
const links = views.map((view) => new FakeElement({viewLink: view}));
const moduleRoots = new Map(views.map((view) => [view, new FakeElement()]));
const utilityModule = new FakeElement();
const utilityRail = new FakeElement();
utilityRail.utilityModule = utilityModule;
const sidebarConversations = new FakeElement();
const mobileNavTrigger = new FakeElement();
const mobileNavClose = new FakeElement();
const mobileUtilityToggle = new FakeElement();
const mobileUtilityClose = new FakeElement();
const elements = new Map([
  ["home-overview-slot", new FakeElement()],
  ["home-session-slot", new FakeElement()],
  ["home-hero-session", new FakeElement()],
  ["home-work-stack", new FakeElement()],
  ["home-support-stack", new FakeElement()],
  ...["utility-status-card", "utility-host-card", "utility-attention-card",
    "utility-coding-work-card", "utility-research-card", "utility-upcoming-card",
    "utility-activity-card"].map(id => [id, new FakeElement()]),
  ["view-conversation", panels.find(p => p.dataset.viewPanel === "conversation")],
  ["session-model-controls", new FakeElement()],
  ["active-project", new FakeElement()],
  ["mobile-menu-panel", new FakeElement()],
  ["mobile-navigation-slot", new FakeElement()],
  ["mobile-history-slot", new FakeElement()],
  ["mobile-utility-panel", new FakeElement()],
  ["mobile-utility-slot", new FakeElement()],
  ["utility-rail", utilityRail],
  ["new-session", new FakeElement()],
  ["auto-speech", new FakeElement()],
  ["stop-speech", new FakeElement()],
]);
const location = {pathname: "/", hash: "", origin: "http://tori.test", href: "http://tori.test/"};
const history = {
  pushState(_state, _unused, destination) { setLocation(destination); },
  replaceState(_state, _unused, destination) { setLocation(destination); },
};
const windowListeners = {};
function setLocation(destination) {
  const url = new URL(destination, location.href);
  location.pathname = url.pathname;
  location.hash = url.hash;
  location.href = url.href;
}
const document = {
  title: "",
  body: {dataset: {initialView: "conversation"}},
  activeElement: null,
  querySelector(selector) {
    if (selector === 'meta[name="tori-csrf"]') return {content: "csrf"};
    if (selector === ".primary-nav" || selector === ".sidebar" ||
        selector === ".local-boundary" || selector === ".conversation-view .view-actions") {
      return new FakeElement();
    }
    if (selector === ".mobile-nav-trigger") return mobileNavTrigger;
    if (selector === ".mobile-panel-close") return mobileNavClose;
    if (selector === "[data-utility-toggle]") return mobileUtilityToggle;
    if (selector === ".mobile-utility-close") return mobileUtilityClose;
    if (selector === ".sidebar-conversations") return sidebarConversations;
    const match = selector.match(/^\[data-view-panel="([^"]+)"\] h1$/);
    if (match) return headings.get(match[1]);
    const rootMatch = selector.match(/^\[data-view-module-root="([^"]+)"\]$/);
    return rootMatch ? moduleRoots.get(rootMatch[1]) : null;
  },
  querySelectorAll(selector) {
    if (selector === "[data-view-panel]") return panels;
    if (selector === "[data-view-link]") return links;
    if (selector === "[data-settings-shortcut]") return [];
    return [];
  },
  getElementById(identifier) { return elements.get(identifier); },
  dispatchEvent() {},
};
const window = {
  location,
  history,
  addEventListener(name, listener) { windowListeners[name] = listener; },
  matchMedia() { return layout; },
};
const layout = {matches: false, addEventListener(_name, listener) { this.listener = listener; }};
const context = {
  CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  URL,
  document,
  fetch: async () => { throw new Error("unexpected fetch"); },
  window,
};
vm.runInNewContext(modulesSource, context);
vm.runInNewContext(source, context);

function click(view) {
  const link = links.find((candidate) => candidate.dataset.viewLink === view);
  link.listeners.click({
    defaultPrevented: false, button: 0, metaKey: false, ctrlKey: false,
    shiftKey: false, altKey: false, preventDefault() {},
  });
}
function assertOnly(view) {
  assert.equal(document.body.dataset.activeView, view);
  for (const panel of panels) assert.equal(panel.hidden, panel.dataset.viewPanel !== view);
}

assertOnly("conversation");
click("home");
assertOnly("home");
assert.equal(location.href, "http://tori.test/#home");
assert.equal(utilityModule.parentElement, elements.get("home-overview-slot"));
assert.equal(elements.get("session-model-controls").parentElement, elements.get("home-session-slot"));
assert.equal(elements.get("utility-status-card").parentElement, elements.get("home-hero-session"));
assert.equal(elements.get("utility-host-card").parentElement, elements.get("home-support-stack"));
assert.equal(elements.get("utility-coding-work-card").parentElement, elements.get("home-work-stack"));
layout.matches = true;
layout.listener();
assert.equal(utilityModule.parentElement, elements.get("home-overview-slot"));
click("conversation");
assert.equal(utilityModule.parentElement, elements.get("mobile-utility-slot"));
assert.equal(elements.get("session-model-controls").parentElement, elements.get("view-conversation"));
assert.equal(elements.get("active-project").parentElement, elements.get("view-conversation"));
for (const id of ["utility-status-card", "utility-host-card", "utility-attention-card",
  "utility-coding-work-card", "utility-research-card", "utility-upcoming-card", "utility-activity-card"]) {
  assert.equal(elements.get(id).parentElement, utilityModule);
}
layout.matches = false;
layout.listener();
assert.equal(utilityModule.parentElement, utilityRail);
setLocation("/#home");
windowListeners.popstate();
assertOnly("home");
click("projects");
assertOnly("projects");
assert.equal(location.pathname, "/manage");
assert.equal(location.hash, "#projects");
click("conversation");
assertOnly("conversation");
setLocation("/manage#projects");
windowListeners.popstate();
assertOnly("projects");
setLocation("/manage#unknown");
windowListeners.popstate();
assertOnly("memories");
for (const view of views.slice(2)) {
  click(view);
  assertOnly(view);
}
click("skills-mcp");
assert.equal(location.pathname, "/skills");
assert.equal(location.hash, "");
let deepLinkMounts = 0;
window.ToriViewModules.register({
  id: "skills-mcp",
  mount(root) {
    assert.equal(root, moduleRoots.get("skills-mcp"));
    deepLinkMounts += 1;
    return {};
  },
});
assert.equal(deepLinkMounts, 1);
