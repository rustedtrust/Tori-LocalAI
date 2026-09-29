"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const assetRoot = path.join(__dirname, "..", "src", "tori", "web_assets");
const registrySource = fs.readFileSync(path.join(assetRoot, "view_modules.js"), "utf8");
const settingsSource = fs.readFileSync(path.join(assetRoot, "settings.js"), "utf8");

const elements = new Map();

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.attributes = {};
    this.className = "";
    this.textContent = "";
    this.disabled = false;
    this.hidden = false;
    this.value = "";
    this.checked = false;
    this.title = "";
    this.open = false;
    this.isConnected = true;
    this._id = "";
  }

  get id() { return this._id; }
  set id(value) {
    this._id = String(value);
    elements.set(this._id, this);
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "id") this.id = value;
    if (name === "disabled") this.disabled = true;
    if (name === "hidden") this.hidden = true;
    if (name === "value") this.value = String(value);
    if (name === "type") this.type = String(value);
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
      this.dataset[key] = String(value);
    }
  }
  removeAttribute(name) { delete this.attributes[name]; }
  querySelector(selector) {
    if (selector.startsWith("#")) return elements.get(selector.slice(1)) || null;
    if (selector === "h2") return this.querySelectorAll("h2")[0] || null;
    return null;
  }
  querySelectorAll(selector) {
    const all = this.children.flatMap((child) => child instanceof FakeElement ? [child, ...child.querySelectorAll("*")] : []);
    if (selector === "*") return all;
    if (selector === "h2") return all.filter((element) => element.tagName === "H2");
    const match = selector.match(/^\[([^\]]+)\]$/);
    return match ? all.filter((element) => Object.hasOwn(element.attributes, match[1])) : [];
  }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() {}
  reset() {}
}

const root = new FakeElement();
root.dataset.viewModuleRoot = "settings";
const head = new FakeElement("head");
const dispatched = [];
const document = {
  head,
  createElement(tagName) { return new FakeElement(tagName); },
  createTextNode(text) { return {textContent: String(text)}; },
  getElementById(identifier) { return elements.get(identifier) || null; },
  querySelector(selector) {
    return selector === '[data-view-module-root="settings"]' ? root : null;
  },
  dispatchEvent(event) { dispatched.push(event); },
  addEventListener() {},
};
const localStorage = {
  values: new Map(),
  getItem(key) { return this.values.get(key) || null; },
  setItem(key, value) { this.values.set(key, String(value)); },
  removeItem(key) { this.values.delete(key); },
};

const requests = [];
let nextTTSFailure = null;
let ttsGetUnavailable = false;
let ttsIdentifier = 1;
let ttsProfiles = [{
  identifier: "tts-primary",
  display_name: "Primary speech",
  provider_type: "openai_compatible",
  endpoint: "http://192.168.1.50:8000/v1",
  model: "future-model",
  voice: "tori",
  enabled: true,
  connect_timeout_seconds: 3,
  read_timeout_seconds: 30,
  authentication_mode: "none",
  provider_options: {},
  status: {
    configured: true,
    availability: "unknown",
    reason_code: "not_checked",
    observed_at: null,
  },
  revision: 1,
  created_at: "2026-08-22T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
}];
let ttsSelection = {
  profile_identifier: null,
  revision: 1,
  updated_at: "2026-08-22T12:00:00Z",
};
let nightOwlCategories = [
  "local_models", "voice", "image_generation", "coding_agents",
  "mcp_infrastructure", "skills_tori_tools",
];
let nightOwlRevision = 4;
const capabilityDocument = () => ({
  web_search: {
    administrator_permitted: true,
    user_enabled: true,
    effective_enabled: true,
  },
  speech_output: {
    administrator_permitted: true,
    user_enabled: true,
    effective_enabled: true,
  },
  operator_activity_log: {
    administrator_permitted: true,
    user_enabled: true,
    effective_enabled: true,
  },
  remote_chat: {
    configured: true,
    administrator_permitted: true,
    enabled: true,
    effective_enabled: true,
    state: "connected",
    restart_required: false,
    mutable: true,
  },
  night_owl: {
    available: true,
    enabled: true,
    revision: nightOwlRevision,
    categories: [...nightOwlCategories],
    category_options: [
      ["local_models", "Local models"],
      ["voice", "Voice / TTS / STT"],
      ["image_generation", "Image generation"],
      ["coding_agents", "Coding and agent tooling"],
      ["mcp_infrastructure", "MCP infrastructure"],
      ["skills_tori_tools", "Skills and Tori-relevant tools"],
      ["security", "Security intelligence"],
    ].map(([id, name]) => ({id, name, enabled: nightOwlCategories.includes(id)})),
    authorization: "Bounded public research authorized for selected categories",
    status: {
      running: false,
      last_run_outcome: "partial",
      last_run_time: "2026-09-18T12:00:00Z",
      findings_count: 1,
      reviewable_count: 0,
      unseen_count: 0,
      last_run_errors: ["github_source_dns_resolution_failed"],
    },
    schedule: {mode: "nightly", local_time: "02:00", weekday: 6, status: "active", next_run: "2026-09-19T07:00:00Z"},
    runs: [{
      budget_used: {searches: 18, search_results: 72, github_fetches: 4, skills_inspections: 0, model_calls: 0},
      details: {
        duration_millis: 6600,
        aggregate: {findings_changed: 0, source_policy_rejected: 70, relevance_rejected: 0, corroboration_failures: 2, corroboration_budget_skipped: 0, github_hosted_results: 3, github_eligible_leads: 2, canonical_repositories_queued: 2, repositories_inspected: 1, skills_catalog_candidates: 0, skills_catalog_attempts: 0, skills_catalog_successes: 0, skills_catalog_failures: 0},
        categories: {voice: {searches_executed: 3, results_considered: 12, github_hosted_results: 0, github_eligible_leads: 0, source_policy_rejected: 12, canonical_repositories_queued: 0, repositories_inspected: 0, relevance_rejected: 0, findings_retained: 0}},
      },
    }],
    findings: [{
      id: "finding-1", revision: 1, category: "voice", category_name: "Voice / TTS / STT",
      title: "example/voice-tool", source_description: "A local speech project with an HTTP API.",
      relevance_reasons: ["protocol_fit"], risks: [], unknowns: ["license_unknown"],
      suggested_next_step: "Review compatibility.", state: "new",
      first_observed: "2026-09-18T12:00:00Z", last_observed: "2026-09-18T12:00:00Z",
      version: "v1", sources: [{kind: "github_page", url: "https://github.com/example/voice-tool", title: "example/voice-tool"}],
      analysis: null, promotion: null, improve_options: [],
    }],
    budget_profile: {searches: 18, search_results: 72, github_fetches: 24, skills_inspections: 6, model_calls: 6},
  },
});
const ui = {
  createElement(tagName, className, text) {
    const element = new FakeElement(tagName);
    element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  },
  async requestJson(requestPath, options = {}) {
    requests.push({path: requestPath, options});
    if (requestPath.startsWith("/api/tts-profiles") && nextTTSFailure) {
      const failure = nextTTSFailure;
      nextTTSFailure = null;
      const error = new Error(failure.message);
      error.code = failure.code;
      throw error;
    }
    if (requestPath.startsWith("/api/tts-profiles") && ttsGetUnavailable && !options.method) {
      const error = new Error("TTS profile management has not been initialized.");
      error.code = "tts_profiles_unavailable";
      throw error;
    }
    if (requestPath === "/api/tts-profiles") {
      return {ok: true, profiles: ttsProfiles.map((profile) => ({...profile}))};
    }
    if (requestPath === "/api/tts-profiles/active") {
      return {
        ok: true,
        selection: {...ttsSelection},
        profile: ttsProfiles.find((profile) => profile.identifier === ttsSelection.profile_identifier) || null,
      };
    }
    if (requestPath === "/api/tts-profiles/create") {
      const profile = {
        ...options.body,
        provider_type: "openai_compatible",
        identifier: `tts-created-${ttsIdentifier++}`,
        revision: 1,
        created_at: "2026-08-22T12:10:00Z",
        updated_at: "2026-08-22T12:10:00Z",
      };
      ttsProfiles.push(profile);
      return {ok: true, profile: {...profile}};
    }
    if (requestPath === "/api/tts-profiles/update") {
      const index = ttsProfiles.findIndex((profile) => profile.identifier === options.body.identifier);
      ttsProfiles[index] = {
        ...ttsProfiles[index],
        ...options.body,
        revision: options.body.expected_revision + 1,
        updated_at: "2026-08-22T12:20:00Z",
      };
      delete ttsProfiles[index].expected_revision;
      return {ok: true, profile: {...ttsProfiles[index]}};
    }
    if (requestPath === "/api/tts-profiles/select") {
      ttsSelection = {
        profile_identifier: options.body.identifier,
        revision: options.body.expected_revision + 1,
        updated_at: "2026-08-22T12:30:00Z",
      };
      return {ok: true, selection: {...ttsSelection}};
    }
    if (requestPath === "/api/tts-profiles/delete") {
      ttsProfiles = ttsProfiles.filter((profile) => profile.identifier !== options.body.identifier);
      return {ok: true};
    }
    if (requestPath === "/api/settings/night-owl") {
      assert.equal(options.body.expected_revision, nightOwlRevision);
      nightOwlCategories = [...options.body.categories];
      nightOwlRevision += 1;
      return {ok: true, night_owl: {...capabilityDocument().night_owl, enabled: options.body.enabled}};
    }
    if (requestPath === "/api/settings" || requestPath.startsWith("/api/settings/")) {
      return capabilityDocument();
    }
    if (requestPath === "/api/backups") {
      return {destination: "/tmp/backups", in_progress: false, latest: {
        verification: "not_rechecked", completed_at: "2026-09-07T12:00:00Z",
        directory: "/tmp/backups/published", total_regular_bytes: 1024,
      }};
    }
    if (requestPath === "/api/restores") {
      return {ok: true, restore_pending: false, backups: [{
        identifier: "Tori_20260907_120000_aaaaaaaaaaaaaaaa",
        completed_at: "2026-09-07T12:00:00Z",
        source_commit: "a".repeat(40),
        total_regular_bytes: 1024,
        verification: "not_rechecked",
        compatibility: "Eligible for verification",
        selectable: true,
      }]};
    }
    if (requestPath === "/api/restores/propose") {
      return {ok: true, confirmation: {
        token: "one-use-restore",
        message: "Tori will stop temporarily; tori.toml is preserved; Finance, Radicale, Knowledge are excluded; a safety backup is required.",
      }};
    }
    if (requestPath === "/api/restores/confirm") {
      return {ok: true, handoff: true};
    }
    if (requestPath === "/api/model-providers") {
      return {initialized: true, profiles: []};
    }
    throw new Error(`Unexpected request: ${requestPath}`);
  },
  showError(element, message) {
    element.textContent = message;
    element.hidden = !message;
  },
  setStatus(element, message, state) {
    element.textContent = message;
    element.dataset.state = state;
  },
  setBusy(element, busy) { element.setAttribute("aria-busy", Boolean(busy)); },
};
const window = {ToriUI: ui};
const sandbox = {
  CustomEvent: class {
    constructor(type, options = {}) { this.type = type; this.detail = options.detail; }
  },
  document,
  localStorage,
  window,
};

vm.runInNewContext(registrySource, sandbox, {filename: "view_modules.js"});
vm.runInNewContext(settingsSource, sandbox, {filename: "settings.js"});

const settle = () => new Promise((resolve) => setImmediate(resolve));
function descendants(node) {
  return [node, ...node.children.flatMap((child) =>
    child instanceof FakeElement ? descendants(child) : []
  )];
}

function buttonWithText(node, text) {
  return descendants(node).find((element) =>
    element.tagName === "BUTTON" && element.textContent === text
  );
}

(async () => {
  assert.equal(head.children.length, 1);
  assert.equal(head.children[0].href, "/assets/settings.css");

  window.ToriViewModules.activate("settings");
  await settle();
  await settle();

  assert.equal(root.className, "settings-module");
  const voiceButton = elements.get("toggle-voice-input");
  const voiceMode = elements.get("voice-input-ptt-mode");
  assert.ok(voiceButton);
  assert.ok(voiceMode);
  voiceButton.listeners.click();
  assert.equal(dispatched.at(-1).type, "tori:voiceinputtoggle");
  voiceMode.value = "toggle";
  voiceMode.listeners.change();
  assert.equal(dispatched.at(-1).type, "tori:voiceinputmode");
  assert.equal(dispatched.at(-1).detail.mode, "toggle");
  dispatched.length = 0;
  assert.ok(root.children.length > 0);
  assert.equal(elements.get("settings-heading").textContent, "Settings");
  assert.ok(elements.has("toggle-web-search"));
  assert.ok(elements.has("toggle-operator-activity-log"));
  assert.ok(elements.has("toggle-remote-chat"));
  assert.ok(elements.has("model-provider-dialog"));
  assert.ok(elements.has("tts-profile-dialog"));
  for (const identifier of [
    "local_models", "voice", "image_generation", "coding_agents",
    "mcp_infrastructure", "skills_tori_tools",
  ]) {
    assert.equal(elements.get(`night-owl-category-${identifier}`).checked, true);
  }
  const securityCheckbox = elements.get("night-owl-category-security");
  const categoriesButton = elements.get("save-night-owl-categories");
  assert.equal(securityCheckbox.checked, false, "Security starts unselected without a grant");
  securityCheckbox.checked = true;
  await categoriesButton.listeners.click();
  await settle();
  assert.ok(nightOwlCategories.includes("security"), "Security can be enabled in Settings");
  await elements.get("refresh-settings").listeners.click();
  await settle();
  assert.equal(securityCheckbox.checked, true, "an enabled Security grant loads as selected");
  const originalCategories = [...nightOwlCategories];
  await categoriesButton.listeners.click();
  await settle();
  assert.deepEqual(nightOwlCategories, originalCategories, "saving an existing grant must preserve Security");
  await elements.get("refresh-settings").listeners.click();
  await settle();
  assert.equal(securityCheckbox.checked, true, "Security must remain selected after reload");
  securityCheckbox.checked = false;
  await categoriesButton.listeners.click();
  await settle();
  assert.equal(nightOwlCategories.includes("security"), false, "explicit deselection must remove Security");
  assert.deepEqual(nightOwlCategories, originalCategories.filter((name) => name !== "security"),
    "other categories must remain selected");
  await elements.get("refresh-settings").listeners.click();
  await settle();
  assert.equal(securityCheckbox.checked, false);
  securityCheckbox.checked = true;
  await categoriesButton.listeners.click();
  await settle();
  assert.deepEqual(nightOwlCategories, originalCategories, "normal Settings must enable Security again");
  await elements.get("refresh-settings").listeners.click();
  await settle();
  assert.equal(securityCheckbox.checked, true);
  assert.equal(elements.get("night-owl-schedule-mode").value, "nightly");
  assert.equal(elements.get("night-owl-schedule-time").value, "02:00");
  assert.ok(elements.get("night-owl-last-run-details").children.length > 0);
  assert.ok(descendants(elements.get("night-owl-last-run-details")).some((element) =>
    element.textContent === "GitHub-hosted results"
  ));
  assert.ok(descendants(elements.get("night-owl-last-run-details")).some((element) =>
    element.textContent.includes("Searches 3")
  ));
  const findingCard = descendants(root).find((element) =>
    element.className === "record-card night-owl-finding"
  );
  assert.ok(findingCard);
  const detailsButton = buttonWithText(findingCard, "Details");
  assert.ok(detailsButton);
  assert.ok(descendants(findingCard).some((element) => element.textContent === "What it is"));
  const detailsPanel = descendants(findingCard).find((element) =>
    element.className === "night-owl-finding-details"
  );
  const requestCountBeforeDetails = requests.length;
  detailsButton.listeners.click();
  assert.equal(detailsPanel.hidden, false);
  assert.equal(requests.length, requestCountBeforeDetails);
  const mountedElements = descendants(root);
  const labels = new Set(
    mountedElements
      .filter((element) => element.tagName === "LABEL")
      .map((element) => element.attributes.for)
  );
  for (const control of mountedElements.filter((element) =>
    ["INPUT", "SELECT"].includes(element.tagName)
  )) {
    assert.ok(labels.has(control.id), `${control.id} must have a visible label`);
  }
  for (const dialog of mountedElements.filter((element) =>
    element.tagName === "DIALOG"
  )) {
    assert.ok(dialog.attributes["aria-labelledby"]);
    assert.ok(dialog.attributes["aria-describedby"]);
  }
  for (const requestPath of [
    "/api/backups", "/api/restores", "/api/model-providers", "/api/settings",
    "/api/tts-profiles", "/api/tts-profiles/active",
  ]) {
    assert.ok(requests.some((request) => request.path === requestPath), `${requestPath} must load`);
  }

  const restoreButton = buttonWithText(elements.get("restore-list"), "Restore Backup");
  assert.ok(restoreButton);
  assert.ok(descendants(elements.get("backup-state")).some((element) =>
    element.textContent === "Not rechecked since publication"));
  const restoreCard = elements.get("restore-list").children[0];
  assert.ok(descendants(restoreCard).some((element) =>
    element.textContent === "Not rechecked · verifies before restore"));
  assert.ok(descendants(restoreCard).some((element) =>
    element.textContent === "Eligible for verification"));
  const restoreRows = descendants(restoreCard).filter((element) =>
    element.className === "restore-metadata-row"
  );
  assert.equal(restoreRows.length, 5);
  assert.ok(restoreRows.every((row) => row.children.length === 2));
  const sourceIdentity = descendants(restoreCard).find((element) =>
    element.className === "restore-metadata-value restore-source-identity"
  );
  assert.equal(sourceIdentity.textContent, "aaaaaaa");
  assert.equal(sourceIdentity.attributes.title, "a".repeat(40));
  await restoreButton.listeners.click();
  await settle();
  assert.equal(elements.get("restore-confirm-dialog").open, true);
  assert.match(elements.get("restore-confirm-backup").textContent, /Tori_20260907_120000_aaaaaaaaaaaaaaaa/);
  assert.match(elements.get("restore-confirm-description").textContent, /tori\.toml.*Finance.*Radicale.*Knowledge/s);
  await elements.get("restore-confirm-form").listeners.submit({preventDefault() {}});
  await settle();
  assert.ok(requests.some((request) =>
    request.path === "/api/restores/confirm" &&
    request.options.body.token === "one-use-restore" &&
    request.options.body.decision === "restore"
  ));
  elements.get("toggle-remote-chat").listeners.click();
  await settle();
  assert.ok(requests.some((request) =>
    request.path === "/api/settings/remote-chat" &&
    request.options.body.enabled === false
  ));
  elements.get("toggle-operator-activity-log").listeners.click();
  await settle();
  assert.ok(requests.some((request) =>
    request.path === "/api/settings/operator-activity-log" &&
    request.options.body.enabled === false
  ));

  const profileList = elements.get("tts-profiles-list");
  assert.ok(descendants(profileList).some((element) => element.textContent === "Primary speech"));
  await buttonWithText(profileList, "Select").listeners.click();
  await settle();
  assert.equal(elements.get("tts-active-profile-heading").textContent, "Primary speech");
  assert.ok(requests.some((request) =>
    request.path === "/api/tts-profiles/select" &&
    request.options.body.expected_revision === 1
  ));

  elements.get("add-tts-profile").listeners.click();
  assert.equal(elements.get("tts-profile-dialog").open, true);
  elements.get("tts-profile-name").value = "Studio voice";
  elements.get("tts-profile-endpoint").value = "http://192.168.1.50:8880/v1";
  elements.get("tts-profile-model").value = "model-a";
  elements.get("tts-profile-voice").value = "af_heart";
  elements.get("tts-profile-connect-timeout").value = "2";
  elements.get("tts-profile-read-timeout").value = "20";
  elements.get("tts-profile-enabled").checked = true;
  await elements.get("tts-profile-form").listeners.submit({preventDefault() {}});
  await settle();
  const createRequest = requests.find((request) => request.path === "/api/tts-profiles/create");
  assert.equal(Object.hasOwn(createRequest.options.body, "provider_type"), false);
  assert.equal(createRequest.options.body.authentication_mode, "none");
  assert.equal(Object.keys(createRequest.options.body.provider_options).length, 0);
  assert.ok(descendants(profileList).some((element) => element.textContent === "Studio voice"));

  const createdCard = profileList.children.find((card) =>
    descendants(card).some((element) => element.textContent === "Studio voice")
  );
  buttonWithText(createdCard, "Edit").listeners.click();
  elements.get("tts-profile-name").value = "Updated studio voice";
  await elements.get("tts-profile-form").listeners.submit({preventDefault() {}});
  await settle();
  assert.ok(requests.some((request) =>
    request.path === "/api/tts-profiles/update" &&
    request.options.body.display_name === "Updated studio voice" &&
    !Object.hasOwn(request.options.body, "provider_type")
  ));

  const updatedCard = profileList.children.find((card) =>
    descendants(card).some((element) => element.textContent === "Updated studio voice")
  );
  nextTTSFailure = {code: "stale_revision", message: "stale"};
  await buttonWithText(updatedCard, "Select").listeners.click();
  await settle();
  assert.match(elements.get("tts-profiles-error").textContent, /changed in another client/);
  assert.equal(ttsSelection.profile_identifier, "tts-primary", "stale selection must not be retried");

  buttonWithText(updatedCard, "Delete").listeners.click();
  await elements.get("delete-tts-profile-form").listeners.submit({preventDefault() {}});
  await settle();
  assert.ok(requests.some((request) =>
    request.path === "/api/tts-profiles/delete" && request.options.body.confirmed === true
  ));
  assert.equal(ttsProfiles.length, 1);

  ttsProfiles[0].status = {
    configured: true,
    availability: "unavailable",
    reason_code: "provider_unreachable",
    observed_at: "2026-08-22T12:45:00Z",
  };
  await elements.get("refresh-settings").listeners.click();
  await settle();
  assert.ok(descendants(profileList).some((element) =>
    element.textContent === "Unavailable"
  ));
  assert.match(elements.get("tts-active-profile-detail").textContent, /provider unreachable/);

  ttsGetUnavailable = true;
  await elements.get("refresh-settings").listeners.click();
  await settle();
  assert.match(elements.get("tts-profiles-error").textContent, /unavailable/);
  assert.ok(descendants(profileList).some((element) =>
    element.textContent.includes("No local substitute")
  ));
  ttsGetUnavailable = false;

  elements.get("toggle-web-search").listeners.click();
  await settle();
  assert.ok(requests.some((request) =>
    request.path === "/api/settings/web-search" &&
    request.options.body.enabled === false
  ));

  window.ToriViewModules.activate("conversation");
  assert.equal(root.children.length, 0);
  window.ToriViewModules.activate("settings");
  await settle();
  assert.equal(elements.get("settings-heading").textContent, "Settings");

  assert.equal(dispatched.length, 0, "loading Settings must not claim cross-view authority");
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
