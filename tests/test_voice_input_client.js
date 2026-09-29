"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "voice_input.js"), "utf8"
);

class Element {
  constructor() {
    this.listeners = new Map();
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.value = "";
    this.attributes = new Map();
  }
  addEventListener(type, callback) { this.listeners.set(type, callback); }
  setAttribute(name, value) { this.attributes.set(name, value); }
  replaceChildren() {}
  append() {}
  setPointerCapture() {}
}

const elements = new Map([
  ["voice-input-status", new Element()],
  ["voice-microphone", new Element()],
  ["voice-ptt", new Element()],
]);
const documentListeners = new Map();
const dispatched = [];
const document = {
  visibilityState: "visible",
  getElementById(id) { return elements.get(id); },
  createElement() { return new Element(); },
  addEventListener(type, callback) { documentListeners.set(type, callback); },
  dispatchEvent(event) { dispatched.push(event); },
};

let lastWorklet = null;
let workletInstances = 0;
class FakeAudioContext {
  constructor() {
    this.sampleRate = 48000;
    this.destination = {};
    this.audioWorklet = {addModule: async () => {}};
  }
  createMediaStreamSource() { return {connect: (next) => next, disconnect() {}}; }
  createGain() { return {gain: {value: 1}, connect: (next) => next, disconnect() {}}; }
  async resume() {}
  async close() {}
}
class FakeAudioWorkletNode {
  constructor() {
    this.port = {};
    lastWorklet = this;
    workletInstances += 1;
  }
  connect(next) { return next; }
  disconnect() {}
}

const trackListeners = new Map();
const track = {
  addEventListener(type, callback) { trackListeners.set(type, callback); },
  getSettings() { return {deviceId: "test-microphone"}; },
  stop() { trackListeners.get("ended")?.(); },
};
const stream = {getAudioTracks: () => [track], getTracks: () => [track]};
const requestedCaptureConstraints = [];
const navigator = {mediaDevices: {
  getUserMedia: async (constraints) => {
    requestedCaptureConstraints.push(constraints);
    return stream;
  },
  enumerateDevices: async () => [{kind: "audioinput", deviceId: "test-microphone", label: "Test microphone"}],
}};

const requests = [];
let audioRequests = 0;
const audioResolvers = [];
const audioBindings = [];
let failNextAudio = false;
let eventSignal;
const owner = {epoch: "epoch", lease: "lease", lease_generation: 1, revision: 2,
  session_id: "session", state: "ready", segment: 0};
const ui = {
  csrfToken: "csrf",
  async requestJson(url, options) {
    requests.push({url, options});
    if (url.endsWith("/acquire")) return {...owner};
    if (url.endsWith("/begin")) return {...owner, revision: 3, state: "listening_ptt",
      utterance_id: "utterance", segment: 1};
    if (url.endsWith("/finalize")) return {...owner, revision: 4, state: "finalizing",
      utterance_id: "utterance", segment: 1};
    if (url.endsWith("/cancel")) return {...owner, revision: 4, state: "ready", utterance_id: null};
    if (url.endsWith("/heartbeat")) return {...owner, revision: 3};
    throw new Error(`unexpected request: ${url}`);
  },
};
function fetch(url, options) {
  if (url.endsWith("/events")) {
    eventSignal = options.signal;
    return Promise.resolve({ok: true, body: {getReader: () => ({
      read: () => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("The operation was aborted.")));
      }),
      releaseLock() {},
    })}});
  }
  assert.equal(url, "/api/voice-input/audio");
  audioRequests += 1;
  audioBindings.push(JSON.parse(options.headers["X-Tori-Voice-Binding"]));
  if (failNextAudio) {
    failNextAudio = false;
    return Promise.resolve({ok: false, json: async () => ({error: "temporary audio transport failure"})});
  }
  return new Promise((resolve) => {
    audioResolvers.push(() => resolve({
      ok: true,
      json: async () => ({...owner, revision: 3, state: "listening_ptt",
        utterance_id: "utterance", segment: 1}),
    }));
  });
}

const windowListeners = new Map();
const diagnostics = [];
const diagnosticConsole = {
  info(...args) { diagnostics.push({level: "info", args}); },
  warn(...args) { diagnostics.push({level: "warn", args}); },
};
let voiceBegins = 0;
let discardPreRollOnBegin = false;
const sandbox = {
  window: {ToriUI: ui, ToriConversation: {
    isBusy: () => true,
    canStartVoiceTurn: () => true,
    beginVoiceTurn: async () => {
      voiceBegins += 1;
      return {allowed: true, discardPreRoll: discardPreRollOnBegin};
    },
  },
    setInterval: () => 1, clearInterval() {}, addEventListener(type, callback) { windowListeners.set(type, callback); }},
  document, navigator, fetch, AudioContext: FakeAudioContext, AudioWorkletNode: FakeAudioWorkletNode,
  AbortController, TextDecoder, CustomEvent: class CustomEvent { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } },
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}}, console: diagnosticConsole,
};
vm.runInNewContext(source, sandbox, {filename: "voice_input.js"});

const tick = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
  const bottomControl = elements.get("voice-input-status");
  bottomControl.listeners.get("click")();
  await tick();
  await tick();
  assert.equal(sandbox.window.ToriVoiceInput.state(), "ready");
  assert.equal(elements.get("voice-ptt").disabled, false,
    "a cancellable Conversation generation does not block manual PTT");
  assert.equal(bottomControl.attributes.get("aria-pressed"), "true");
  const captureRequest = requestedCaptureConstraints[0].audio;
  assert.equal(captureRequest.channelCount, 1);
  assert.equal(captureRequest.sampleRate, 48000);
  assert.equal(captureRequest.autoGainControl, true);
  assert.equal(captureRequest.echoCancellation, false);
  assert.equal(captureRequest.noiseSuppression, false);
  const ptt = elements.get("voice-ptt");

  // Thirty seconds in Ready must retain only the 0.50-second local pre-roll,
  // not queue historical microphone PCM for the next utterance.
  for (let count = 0; count < 120; count += 1) {
    lastWorklet.port.onmessage({data: new Int16Array(12_000).buffer});
  }
  assert.equal(audioRequests, 0, "Ready never forwards microphone PCM");
  failNextAudio = true;
  ptt.listeners.get("pointerdown")({preventDefault() {}, pointerId: 1});
  await tick();
  assert.equal(voiceBegins, 1, "PTT delegates playback interruption to Conversation");
  await tick();
  await tick();
  assert.equal(sandbox.window.ToriVoiceInput.state(), "ready");
  assert.equal(eventSignal.aborted, false);
  assert.equal(requests.some((request) => request.url.endsWith("/cancel")), true);
  assert.equal(requests.some((request) => request.url.endsWith("/release")), false);
  const errorCount = dispatched.filter((event) => event.type === "tori:voiceerror").length;

  lastWorklet.port.onmessage({data: new Int16Array(12_000).buffer});
  lastWorklet.port.onmessage({data: new Int16Array(12_000).buffer});
  discardPreRollOnBegin = true;
  ptt.listeners.get("pointerdown")({preventDefault() {}, pointerId: 2});
  await tick();
  assert.equal(audioRequests, 1,
    "PTT interruption discards speaker-contaminated Ready pre-roll");
  discardPreRollOnBegin = false;
  for (let count = 0; count < 40; count += 1) {
    lastWorklet.port.onmessage({data: new Int16Array(12_000).buffer});
    await tick();
    audioResolvers.shift()();
    await tick();
  }
  assert.equal(audioRequests, 41, "ten seconds at 48 kHz uses four 250 ms chunks per second");
  assert.deepEqual(audioBindings.slice(1).map((binding) => binding.sequence),
    Array.from({length: 40}, (_unused, index) => index + 1));

  lastWorklet.port.onmessage({data: new Int16Array(12_000).buffer});
  await tick();
  assert.equal(audioRequests, 42);

  ptt.listeners.get("pointerup")({pointerId: 2});
  for (let count = 0; count < 12; count += 1) {
    lastWorklet.port.onmessage({data: new Int16Array(12_000).buffer});
  }
  assert.equal(sandbox.window.ToriVoiceInput.state(), "listening_ptt");
  assert.equal(eventSignal.aborted, false);
  assert.equal(dispatched.filter((event) => event.type === "tori:voiceerror").length, errorCount);

  audioResolvers.shift()();
  await tick();
  await tick();
  assert.ok(requests.some((request) => request.url.endsWith("/finalize")));
  assert.equal(requests.some((request) => request.url.endsWith("/release")), false);
  assert.equal(eventSignal.aborted, false);

  // A real bounded overload fences only this turn. The existing in-flight POST
  // may finish, but stale queued PCM is discarded and the session stays Ready.
  await sandbox.window.ToriVoiceInput.disable();
  await sandbox.window.ToriVoiceInput.enable();
  assert.equal(workletInstances, 2);
  assert.equal(sandbox.window.ToriVoiceInput.state(), "ready");
  const releasesBeforeOverload = requests.filter((request) => request.url.endsWith("/release")).length;
  ptt.listeners.get("pointerdown")({preventDefault() {}, pointerId: 3});
  await tick();
  for (let count = 0; count < 6; count += 1) {
    lastWorklet.port.onmessage({data: new Int16Array(12_000).buffer});
  }
  audioResolvers.shift()();
  await tick();
  await tick();
  assert.equal(sandbox.window.ToriVoiceInput.state(), "ready");
  assert.equal(eventSignal.aborted, false);
  assert.equal(requests.filter((request) => request.url.endsWith("/release")).length,
    releasesBeforeOverload);

  // A later explicit Off tears down the old producer. Re-enabling creates one
  // fresh producer rather than retaining duplicate worklet/listener instances.
  await sandbox.window.ToriVoiceInput.disable();
  await sandbox.window.ToriVoiceInput.enable();
  assert.equal(workletInstances, 3);
  assert.equal(sandbox.window.ToriVoiceInput.state(), "ready");
  bottomControl.listeners.get("click")();
  await tick();
  assert.equal(sandbox.window.ToriVoiceInput.state(), "off");
  assert.equal(bottomControl.attributes.get("aria-pressed"), "false");
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
