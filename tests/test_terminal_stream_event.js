"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "src/tori/web_assets/app.js"), "utf8");
const start = source.indexOf("function validTerminalRequest(");
const end = source.indexOf("function validActionOutcome(", start);
assert.ok(start > 0 && end > start);
const context = {
  exactFields(record, expected) {
    const actual = Object.keys(record).sort();
    return actual.length === expected.length && actual.every((field, index) => field === expected[index]);
  },
  validTranscript(entries) { return Array.isArray(entries); },
};
vm.runInNewContext(source.slice(start, end) + "\nthis.parseStreamEvent = parseStreamEvent;", context);

const common = {
  command: "/bin/echo accepted", cwd: "/tmp", scope: "HOST_USER",
  reason: "Exact decision.", rule_id: null, source: "default",
};
for (const terminalRequest of [
  {...common, policy: "DEFAULT_ASK", proposal_token: "a".repeat(43), expires_in_seconds: 60},
  {...common, policy: "ALWAYS_ASK", proposal_token: "b".repeat(43), expires_in_seconds: 60},
  {...common, policy: "WHITELIST", session_id: "term-" + "a".repeat(32)},
  {...common, policy: "BLACKLIST"},
]) {
  const event = context.parseStreamEvent(JSON.stringify({type: "complete", transcript: [],
                                                         terminal_request: terminalRequest}));
  assert.equal(event.terminal_request.policy, terminalRequest.policy);
}
for (const terminalRequest of [
  {...common, policy: "WHITELIST", session_id: "not-a-session"},
  {...common, policy: "DEFAULT_ASK", proposal_token: "short", expires_in_seconds: 60},
  {...common, policy: "BLACKLIST", proposal_token: "a".repeat(43)},
]) {
  assert.throws(() => context.parseStreamEvent(JSON.stringify({type: "complete", transcript: [],
                                                                terminal_request: terminalRequest})));
}
console.log("PASS: versioned terminal completion events validate all four policy outcomes");
