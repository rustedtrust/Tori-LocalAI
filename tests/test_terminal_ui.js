"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function element() {
  const classes = new Set();
  return {
    hidden: false, disabled: false, value: "", textContent: "", children: [],
    listeners: {}, attributes: {},
    classList: {contains: (name) => classes.has(name), toggle(name) {
      if (classes.has(name)) { classes.delete(name); return false; }
      classes.add(name); return true;
    }},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { this.listeners[name] = callback; },
    click() { this.listeners.click?.(); },
    showModal() { this.open = true; },
    close() { this.open = false; this.listeners.close?.(); },
    append(item) { this.children.push(item); },
    replaceChildren() { this.children = []; },
  };
}

async function harness(local, ownedSessions = [{
  id: "term-" + "a".repeat(32), state: "running", scope: "HOST_USER", cwd: "/tmp",
}]) {
  const ids = new Map();
  const byId = (id) => {
    if (!ids.has(id)) ids.set(id, element());
    if (id === "terminal-drawer" && !ids.get(id)._initialized) {
      ids.get(id).hidden = true;
      ids.get(id)._initialized = true;
    }
    if (id === "terminal-status" && !ids.get(id)._tracked) {
      let text = "";
      Object.defineProperty(ids.get(id), "textContent", {
        get() { return text; }, set(value) { text = value; transitions.push("render " + value); },
      });
      ids.get(id)._tracked = true;
    }
    if (id === "terminal-drawer" && !ids.get(id)._tracked) {
      let hidden = ids.get(id).hidden;
      Object.defineProperty(ids.get(id), "hidden", {
        get() { return hidden; }, set(value) { hidden = value; transitions.push("drawer " + value); },
      });
      ids.get(id)._tracked = true;
    }
    return ids.get(id);
  };
  const sockets = [];
  const requests = [];
  const transitions = [];
  const documentListeners = new Map();
  let poll = null;
  let dataHandler = null;
  let resizeObserver = null;
  let confirmKill = false;
  let requestGate = null;
  class FakeTerminal {
    constructor() { this.rows = 24; this.cols = 80; this.writes = []; FakeTerminal.instance = this; }
    loadAddon(addon) { this.addon = addon; }
    open() {}
    onData(callback) { dataHandler = callback; }
    write(data) { this.writes.push(Buffer.from(data).toString()); }
    reset() { this.writes = []; transitions.push("viewport reset"); }
    focus() { this.focused = true; }
  }
  class FakeSocket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this);
      transitions.push("websocket open " + url); }
    open() { this.readyState = 1; this.onopen(); }
    send(data) { this.sent.push(data); }
    close() { this.readyState = 3; transitions.push("websocket close"); this.onclose?.(); }
    message(data) { this.onmessage({data}); }
  }
  const scope = {
    document: {getElementById: byId, createElement: element,
      addEventListener(name, callback) { documentListeners.set(name, callback); },
      querySelector: () => ({content: "csrf-test"})},
    window: {Terminal: FakeTerminal, FitAddon: {FitAddon: class {fit() {}}},
      confirm: () => confirmKill, addEventListener() {}},
    location: {host: "127.0.0.1:8765"}, WebSocket: FakeSocket,
    ResizeObserver: class {constructor(callback) { resizeObserver = callback; } observe() {}},
    TextEncoder, Uint8Array, ArrayBuffer, Buffer,
    setTimeout, clearTimeout, setInterval: (callback) => { poll = callback; return 0; },
    fetch: async (url, options) => {
      requests.push({url, options});
      transitions.push("fetch " + url);
      if (url.endsWith("availability")) return {ok: true, json: async () => ({available: local})};
      if (url.endsWith("sessions")) return {ok: true, json: async () => ({sessions: ownedSessions.map((item) => ({...item}))})};
      if (url.endsWith("attach-ticket")) return {ok: true, json: async () => ({ticket: "secret-ticket"})};
      if (url.endsWith("terminal/request")) {
        if (requestGate) await requestGate;
        const proposed = JSON.parse(options.body);
        if (proposed.command === "/bin/echo white") {
          return {ok: true, json: async () => ({policy: "WHITELIST", session_id: "term-" + "a".repeat(32)})};
        }
        if (proposed.command === "/bin/echo white-next") {
          return {ok: true, json: async () => ({policy: "WHITELIST", session_id: "term-" + "b".repeat(32)})};
        }
        if (proposed.command === "/bin/echo blocked") {
          return {ok: true, json: async () => ({policy: "BLACKLIST", reason: "Exact rule matched."})};
        }
        if (proposed.command === "/bin/echo always") {
          return {ok: true, json: async () => ({policy: "ALWAYS_ASK", proposal_token: "proposal-always",
            command: proposed.command, cwd: proposed.cwd, scope: proposed.scope,
            reason: "Exact rule matched."})};
        }
        return {ok: true, json: async () => ({policy: "DEFAULT_ASK", proposal_token: "proposal-secret",
          command: proposed.command, cwd: proposed.cwd, scope: proposed.scope,
          reason: "No enabled exact rule matched."})};
      }
      if (url.endsWith("terminal/decide")) return {ok: true, json: async () => ({session_id: "term-" + "a".repeat(32)})};
      throw new Error(`Unexpected fetch ${url}`);
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "src/tori/web_assets/terminal_ui.js"), "utf8"), scope);
  for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setImmediate(resolve));
  return {byId, sockets, requests, transitions, poll: () => poll(),
    dataHandler: () => dataHandler, terminal: () => FakeTerminal.instance,
    resize: () => resizeObserver(),
    dispatch(name, detail) { documentListeners.get(name)?.({detail}); },
    holdRequest(promise) { requestGate = promise; },
    setConfirm(value) { confirmKill = value; }};
}

async function main() {
  const firstId = "term-" + "a".repeat(32);
  const secondId = "term-" + "b".repeat(32);
  const owned = [];
  const completed = await harness(true, owned);
  assert.equal(completed.sockets.length, 0);
  owned.push({id: firstId, state: "running", scope: "HOST_USER", cwd: "/tmp", started_at: 1});
  completed.byId("terminal-command").value = "/bin/echo white";
  completed.byId("terminal-cwd").value = "/tmp";
  completed.byId("terminal-scope").value = "HOST_USER";
  await completed.byId("terminal-request-form").listeners.submit({preventDefault() {}});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(completed.sockets.length, 1);
  const finishedSocket = completed.sockets[0];
  finishedSocket.open();
  finishedSocket.message(JSON.stringify({v: 1, type: "ready", session: owned[0]}));
  finishedSocket.message(new TextEncoder().encode("ls output\r\n").buffer);
  completed.byId("terminal-minimize").click();
  owned[0] = {...owned[0], state: "exited", exit_code: 0, termination_reason: "exited"};
  const beforeExit = completed.transitions.length;
  finishedSocket.message(JSON.stringify({v: 1, type: "exit", session: owned[0]}));
  finishedSocket.close();
  assert.deepEqual(completed.transitions.slice(beforeExit), ["render HOST_USER · exited · exit 0", "websocket close"]);
  const stableAt = completed.transitions.length;
  await new Promise((resolve) => setTimeout(resolve, 1350));
  for (let i = 0; i < 3; i += 1) {
    await completed.poll();
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(completed.requests.filter((item) => item.url.endsWith("terminal/request")).length, 1);
  assert.equal(completed.requests.filter((item) => item.url.endsWith("attach-ticket")).length, 1,
    completed.transitions.join("\n"));
  assert.equal(completed.sockets.length, 1, completed.transitions.join("\n"));
  assert.deepEqual(completed.transitions.slice(stableAt), [
    "fetch /api/terminal/sessions", "fetch /api/terminal/sessions", "fetch /api/terminal/sessions",
  ]);
  assert.equal(completed.byId("terminal-drawer").hidden, true);
  completed.dispatch("tori:terminalrequest", {policy: "BLACKLIST", reason: "blocked"});
  assert.equal(completed.byId("terminal-drawer").hidden, true);
  assert.equal(completed.byId("terminal-sessions").value, firstId);
  assert.match(completed.byId("terminal-status").textContent, /exit 0/);
  assert.deepEqual(completed.terminal().writes, ["ls output\r\n"]);
  for (const id of ["terminal-take-control", "terminal-release-control", "terminal-interrupt",
    "terminal-terminate", "terminal-force-kill"]) {
    assert.equal(completed.byId(id).disabled, true);
  }
  owned.push({id: secondId, state: "running", scope: "HOST_USER", cwd: "/tmp", started_at: 2});
  completed.byId("terminal-command").value = "/bin/echo white-next";
  await completed.byId("terminal-request-form").listeners.submit({preventDefault() {}});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(completed.byId("terminal-sessions").value, secondId);
  assert.equal(completed.sockets.length, 2);
  assert.equal(completed.requests.filter((item) => item.url.endsWith("terminal/request")).length, 2);
  completed.byId("terminal-sessions").value = firstId;
  completed.byId("terminal-sessions").listeners.change();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(completed.sockets.length, 3);
  completed.sockets[2].open();
  completed.sockets[2].message(JSON.stringify({v: 1, type: "ready", session: owned[0]}));
  const readyRenders = completed.transitions.filter((item) => item === "render HOST_USER · exited · exit 0").length;
  completed.sockets[2].message(JSON.stringify({v: 1, type: "exit", session: owned[0]}));
  assert.equal(completed.transitions.filter((item) => item === "render HOST_USER · exited · exit 0").length, readyRenders);
  completed.sockets[2].close();
  await new Promise((resolve) => setTimeout(resolve, 1350));
  assert.equal(completed.sockets.length, 3);

  const historical = await harness(true, [{id: firstId, state: "exited", scope: "HOST_USER",
    cwd: "/tmp", started_at: 1, exit_code: 0}]);
  assert.equal(historical.byId("terminal-sessions").value, firstId);
  assert.equal(historical.sockets.length, 0);
  historical.byId("terminal-sessions").listeners.change();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(historical.sockets.length, 1);
  historical.sockets[0].open();
  historical.sockets[0].message(JSON.stringify({v: 1, type: "ready", session: owned[0]}));
  historical.sockets[0].message(new TextEncoder().encode("inspected snapshot\r\n").buffer);
  historical.sockets[0].close();
  await new Promise((resolve) => setTimeout(resolve, 1350));
  assert.equal(historical.sockets.length, 1);
  assert.deepEqual(historical.terminal().writes, ["inspected snapshot\r\n"]);

  const polledSessions = [{id: firstId, state: "running", scope: "HOST_USER",
    cwd: "/tmp", started_at: 1}];
  const polled = await harness(true, polledSessions);
  polled.sockets[0].open();
  polled.sockets[0].message(JSON.stringify({v: 1, type: "ready", session: {
    id: firstId, state: "running", scope: "HOST_USER", cwd: "/tmp", started_at: 1,
  }}));
  // A poll can discover exit before the WebSocket's exit frame or close arrives.
  polled.sockets[0].close();
  polled.byId("terminal-minimize").click();
  polledSessions[0] = {...polledSessions[0], state: "exited", exit_code: 0};
  const beforePollExit = polled.transitions.length;
  await new Promise((resolve) => setTimeout(resolve, 1350));
  assert.equal(polled.sockets.length, 1, polled.transitions.join("\n"));
  assert.equal(polled.requests.filter((item) => item.url.endsWith("attach-ticket")).length, 1);
  assert.match(polled.byId("terminal-status").textContent, /exit 0/);
  assert.equal(polled.byId("terminal-drawer").hidden, true);
  assert.equal(polled.transitions.slice(beforePollExit).filter((item) => /^render .* · exit 0$/.test(item)).length, 1);

  const sandboxExit = await harness(true, [{id: firstId, state: "exited",
    scope: "PROJECT_SANDBOX", cwd: "/tmp", started_at: 1, exit_code: 9}]);
  sandboxExit.byId("terminal-scope").value = "HOST_USER";
  assert.equal(sandboxExit.byId("terminal-status").textContent, "PROJECT_SANDBOX · Exited · exit 9");
  assert.equal(sandboxExit.sockets.length, 0);

  const delayedSessions = [];
  const delayed = await harness(true, delayedSessions);
  let resolveRequest;
  delayed.holdRequest(new Promise((resolve) => { resolveRequest = resolve; }));
  delayed.byId("terminal-command").value = "/bin/echo white";
  const submitting = delayed.byId("terminal-request-form").listeners.submit({preventDefault() {}});
  delayed.byId("terminal-minimize").click();
  delayedSessions.push({id: firstId, state: "exited", scope: "HOST_USER", cwd: "/tmp",
    started_at: 1, exit_code: 0});
  resolveRequest();
  await submitting;
  assert.equal(delayed.byId("terminal-drawer").hidden, true);
  assert.equal(delayed.byId("terminal-sessions").value, firstId);
  assert.equal(delayed.requests.filter((item) => item.url.endsWith("terminal/request")).length, 1);

  const reconnect = await harness(true, [
    {id: "term-" + "b".repeat(32), state: "exited", scope: "HOST_USER",
      cwd: "/tmp", started_at: 1},
    {id: "term-" + "c".repeat(32), state: "running", scope: "HOST_USER",
      cwd: "/tmp", started_at: 2},
  ]);
  assert.equal(reconnect.byId("terminal-sessions").value, "term-" + "c".repeat(32));
  assert.equal(reconnect.sockets.length, 1);
  assert.ok(reconnect.sockets[0].url.endsWith("term-" + "c".repeat(32)));
  const local = await harness(true);
  local.dispatch("tori:terminalrequest", {policy: "DEFAULT_ASK", command: "/bin/echo model",
    cwd: "/tmp", scope: "HOST_USER", reason: "Default Ask",
    proposal_token: "model-proposal"});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(local.byId("terminal-approval-dialog").open, true);
  assert.match(local.byId("terminal-approval-details").textContent, /\/bin\/echo model/);
  local.byId("terminal-approval-dialog").close();
  local.byId("terminal-toggle").click();
  assert.equal(local.sockets.length, 1);
  const socket = local.sockets[0];
  assert.equal(socket.url, "ws://127.0.0.1:8765/api/terminal/ws/term-" + "a".repeat(32));
  assert.ok(!socket.url.includes("secret-ticket"));
  local.dataHandler()("no authority\n");
  assert.equal(socket.sent.length, 0);
  socket.open();
  assert.deepEqual(JSON.parse(socket.sent[0]), {v: 1, type: "attach", ticket: "secret-ticket"});
  socket.message(JSON.stringify({v: 1, type: "ready", session: {
    id: "term-" + "a".repeat(32), state: "running", scope: "HOST_USER", cwd: "/tmp",
  }}));
  socket.message(new TextEncoder().encode("visible output\r\n").buffer);
  assert.deepEqual(local.terminal().writes, ["visible output\r\n"]);
  local.dataHandler()("still blocked\n");
  assert.equal(socket.sent.filter((item) => item instanceof Uint8Array).length, 0);
  local.byId("terminal-take-control").click();
  assert.equal(JSON.parse(socket.sent.at(-1)).type, "take_control");
  socket.message(JSON.stringify({v: 1, type: "state", human_control: true}));
  local.dataHandler()("human input\r");
  assert.equal(Buffer.from(socket.sent.at(-1)).toString(), "human input\r");
  local.byId("terminal-enter-private").click();
  assert.equal(JSON.parse(socket.sent.at(-1)).type, "enter_private");
  assert.equal(local.byId("terminal-exit-private").hidden, true);
  socket.message(JSON.stringify({v: 1, type: "state", human_control: true, private_input: true}));
  assert.equal(local.byId("terminal-exit-private").hidden, false);
  socket.close();
  assert.equal(local.byId("terminal-exit-private").hidden, false);
  await new Promise((resolve) => setTimeout(resolve, 1350));
  const privateReconnect = local.sockets.at(-1);
  privateReconnect.open();
  privateReconnect.message(JSON.stringify({v: 1, type: "ready", session: {
    id: "term-" + "a".repeat(32), state: "running", scope: "HOST_USER", cwd: "/tmp",
    private_input: true,
  }}));
  const inputCount = privateReconnect.sent.length;
  local.dataHandler()("still no control");
  assert.equal(privateReconnect.sent.length, inputCount);
  local.byId("terminal-take-control").click();
  privateReconnect.message(JSON.stringify({v: 1, type: "state", human_control: true, private_input: true}));
  local.byId("terminal-exit-private").click();
  assert.equal(JSON.parse(privateReconnect.sent.at(-1)).type, "exit_private");
  privateReconnect.message(JSON.stringify({v: 1, type: "state", human_control: true, private_input: false, model_capture_locked: true}));
  assert.equal(local.byId("terminal-exit-private").hidden, true);
  assert.match(local.byId("terminal-control-notice").textContent, /will not read further output/);
  local.byId("terminal-release-control").click();
  privateReconnect.message(JSON.stringify({v: 1, type: "state", human_control: false, private_input: false}));
  const before = privateReconnect.sent.length;
  local.dataHandler()("blocked again");
  assert.equal(privateReconnect.sent.length, before);
  for (const [id, type] of [["terminal-interrupt", "interrupt"], ["terminal-terminate", "terminate"]]) {
    local.byId(id).click();
    assert.equal(JSON.parse(privateReconnect.sent.at(-1)).type, type);
  }
  const count = privateReconnect.sent.length;
  local.byId("terminal-force-kill").click();
  assert.equal(privateReconnect.sent.length, count);
  local.setConfirm(true);
  local.byId("terminal-force-kill").click();
  assert.equal(JSON.parse(privateReconnect.sent.at(-1)).type, "force_kill");
  local.byId("terminal-toggle").click();
  assert.equal(local.byId("terminal-drawer").hidden, false);
  local.byId("terminal-expand").click();
  assert.equal(local.byId("terminal-drawer").classList.contains("is-expanded"), true);
  local.byId("terminal-expand").click();
  assert.equal(local.byId("terminal-drawer").classList.contains("is-expanded"), false);
  local.resize();
  await new Promise((resolve) => setTimeout(resolve, 130));
  assert.ok(privateReconnect.sent.some((item) => typeof item === "string" && JSON.parse(item).type === "resize"));
  local.byId("terminal-minimize").click();
  assert.equal(local.byId("terminal-drawer").hidden, true);
  privateReconnect.close();
  assert.equal(local.byId("terminal-control-notice").textContent.includes("Observe only"), true);
  await new Promise((resolve) => setTimeout(resolve, 1350));
  assert.equal(local.sockets.length, 3);
  local.sockets[2].open();
  assert.equal(JSON.parse(local.sockets[2].sent[0]).ticket, "secret-ticket");
  local.sockets[2].message(JSON.stringify({v: 1, type: "ready", session: {
    id: "term-" + "a".repeat(32), state: "exited", scope: "HOST_USER", cwd: "/tmp", exit_code: 0,
  }}));
  local.sockets[2].message(new TextEncoder().encode("bounded snapshot\r\n").buffer);
  assert.deepEqual(local.terminal().writes, ["bounded snapshot\r\n"]);
  assert.ok(local.byId("terminal-status").textContent.includes("exit 0"));
  assert.ok(local.requests.some((entry) => entry.url === "/api/terminal/attach-ticket"
    && entry.options.headers["X-Tori-CSRF"] === "csrf-test"));
  const approval = await harness(true);
  approval.byId("terminal-command").value = "/bin/echo proposed";
  approval.byId("terminal-cwd").value = "/tmp";
  approval.byId("terminal-scope").value = "HOST_USER";
  await approval.byId("terminal-request-form").listeners.submit({preventDefault() {}});
  assert.equal(approval.byId("terminal-approval-dialog").open, true);
  assert.ok(approval.byId("terminal-approval-details").textContent.includes("/bin/echo proposed"));
  assert.equal(approval.requests.some((item) => item.url.endsWith("terminal/decide")), false);
  assert.equal(approval.byId("terminal-whitelist-exact").hidden, false);
  approval.byId("terminal-approve-once").click();
  for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setImmediate(resolve));
  assert.equal(JSON.parse(approval.requests.find((item) => item.url.endsWith("terminal/decide")).options.body).decision, "approve");
  const whitelisted = await harness(true);
  whitelisted.byId("terminal-command").value = "/bin/echo white";
  whitelisted.byId("terminal-cwd").value = "/tmp";
  whitelisted.byId("terminal-scope").value = "HOST_USER";
  await whitelisted.byId("terminal-request-form").listeners.submit({preventDefault() {}});
  assert.notEqual(whitelisted.byId("terminal-approval-dialog").open, true);
  assert.equal(whitelisted.requests.some((item) => item.url.endsWith("terminal/decide")), false);
  const always = await harness(true);
  always.byId("terminal-command").value = "/bin/echo always";
  always.byId("terminal-cwd").value = "/tmp";
  always.byId("terminal-scope").value = "HOST_USER";
  await always.byId("terminal-request-form").listeners.submit({preventDefault() {}});
  assert.equal(always.byId("terminal-approval-dialog").open, true);
  assert.equal(always.byId("terminal-whitelist-exact").hidden, true);
  const blocked = await harness(true);
  blocked.byId("terminal-command").value = "/bin/echo blocked";
  blocked.byId("terminal-cwd").value = "/tmp";
  blocked.byId("terminal-scope").value = "HOST_USER";
  await blocked.byId("terminal-request-form").listeners.submit({preventDefault() {}});
  assert.notEqual(blocked.byId("terminal-approval-dialog").open, true);
  assert.equal(blocked.requests.some((item) => item.url.endsWith("terminal/decide")), false);
  const remote = await harness(false);
  assert.equal(remote.sockets.length, 0);
  assert.equal(remote.byId("terminal-unavailable").hidden, false);
  assert.equal(remote.requests.some((entry) => entry.url.includes("attach-ticket")), false);
  console.log("Terminal UI tests passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
