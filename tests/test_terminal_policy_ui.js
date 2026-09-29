"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function element() {
  return {
    hidden: false, disabled: false, checked: false, value: "", textContent: "",
    children: [], listeners: {},
    addEventListener(name, handler) { this.listeners[name] = handler; },
    append(...items) { this.children.push(...items); },
    replaceChildren() { this.children = []; },
    setAttribute() {}, focus() {},
  };
}

async function run(local) {
  const elements = new Map();
  const byId = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const calls = [];
  let rules = [];
  const documentListeners = {};
  const scope = {
    document: {getElementById: byId, createElement: element,
      querySelector: () => ({content: "csrf-test"}),
      addEventListener(name, handler) { documentListeners[name] = handler; }},
    window: {confirm: () => true},
    fetch: async (url, options = {}) => {
      calls.push({url, options});
      if (url === "/api/terminal/availability")
        return {ok: true, json: async () => ({available: local})};
      if (!local) throw new Error("Remote browser attempted policy access");
      if (url === "/api/terminal/policy")
        return {ok: true, json: async () => ({default: "DEFAULT_ASK", rules})};
      const body = JSON.parse(options.body);
      if (url.endsWith("/create")) rules = [{id: "rule-1", source: "user", enabled: body.enabled,
        class: body.class, matcher: {command: body.command, cwd: body.cwd, scope: body.scope}}];
      if (url.endsWith("/update")) rules[0] = {...rules[0], class: body.class};
      if (url.endsWith("/remove")) rules = [];
      return {ok: true, json: async () => ({ok: true})};
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "src/tori/web_assets/terminal_policy_ui.js"), "utf8"), scope);
  for (let i = 0; i < 4; i++) await new Promise((resolve) => setImmediate(resolve));
  return {byId, calls, rules: () => rules, documentListeners};
}

async function main() {
  const remote = await run(false);
  assert.equal(remote.byId("terminal-policy-body").hidden, true);
  assert.equal(remote.calls.some((call) => call.url === "/api/terminal/policy"), false);
  const local = await run(true);
  assert.equal(local.byId("terminal-policy-body").hidden, false);
  local.byId("terminal-policy-command").value = "/bin/echo exact";
  local.byId("terminal-policy-cwd").value = "/tmp";
  local.byId("terminal-policy-scope").value = "HOST_USER";
  local.byId("terminal-policy-class").value = "ALWAYS_ASK";
  local.byId("terminal-policy-enabled").checked = true;
  await local.byId("terminal-policy-form").listeners.submit({preventDefault() {}});
  assert.equal(local.rules()[0].class, "ALWAYS_ASK");
  const previousRefreshes = local.calls.filter((call) => call.url === "/api/terminal/policy").length;
  local.documentListeners["tori:viewchange"]({detail: {view: "settings"}});
  for (let i = 0; i < 4; i++) await new Promise((resolve) => setImmediate(resolve));
  assert.ok(local.calls.filter((call) => call.url === "/api/terminal/policy").length > previousRefreshes);
  assert.equal(local.calls.find((call) => call.url.endsWith("/create")).options.headers["X-Tori-CSRF"], "csrf-test");
  const [description, editButton, removeButton] = local.byId("terminal-policy-rules").children[0].children;
  assert.ok(description.textContent.includes("/bin/echo exact"));
  editButton.listeners.click();
  local.byId("terminal-policy-class").value = "BLACKLIST";
  await local.byId("terminal-policy-form").listeners.submit({preventDefault() {}});
  assert.equal(local.rules()[0].class, "BLACKLIST");
  await local.byId("terminal-policy-rules").children[0].children[2].listeners.click();
  assert.equal(local.rules().length, 0);
  assert.equal(removeButton.textContent, "Remove");
  console.log("Terminal policy UI tests passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
