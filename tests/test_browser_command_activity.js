"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "app.js"),
  "utf8"
);
const audioSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "audio.js"),
  "utf8"
);
const audiblePCM = Buffer.alloc(16 * 1024);
for (let index = 0; index < audiblePCM.length / 2; index += 1) {
  audiblePCM.writeInt16LE(Math.round(6000 * Math.sin(index * Math.PI / 24)), index * 2);
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.textContent = "";
    this.value = "";
    this.dataset = {};
    this.children = [];
    this.listeners = {};
    this.focusCount = 0;
    this.classList = {add() {}, remove() {}, toggle() {}};
  }

  addEventListener(name, listener) {
    this.listeners[name] = listener;
  }

  append(...children) {
    this.children.push(...children);
  }

  prepend(...children) {
    this.children.unshift(...children);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  querySelectorAll() {
    return [];
  }

  querySelector(selector) {
    const wanted = selector.toLowerCase();
    const pending = [...this.children];
    while (pending.length) {
      const item = pending.shift();
      if (item?.id === wanted) return item;
      if (Array.isArray(item?.children)) pending.push(...item.children);
    }
    return null;
  }

  get lastElementChild() {
    return this.children[this.children.length - 1];
  }

  setAttribute(name, value) {
    this[name] = String(value);
  }

  removeAttribute(name) {
    delete this[name];
  }

  focus() { this.focusCount += 1; }
  close() { this.open = false; }
  showModal() { this.open = true; }
}

function baseCommand(overrides) {
  return {
    invocation_id: "invocation-1",
    command: "printf fixture",
    workspace: "/tmp/authorized-workspace",
    status: "succeeded",
    environment: "sanitized application-owned environment",
    isolation: "test isolation",
    timeout_seconds: 30,
    stdout_limit_bytes: 65536,
    stderr_limit_bytes: 65536,
    exit_code: 0,
    termination_reason: null,
    stdout: "",
    stderr: "",
    stdout_truncated: false,
    stderr_truncated: false,
    ...overrides,
  };
}

async function loadApplication(command, scenario = {}) {
  let currentCommand = command;
  let serverBusy = false;
  let activeChatId = "chat-a";
  let transcriptRevision = 7;
  let transcript = [
    {role: "user", text: "Earlier"},
    {role: "assistant", text: "Earlier answer"},
  ];
  let memoryConfirmation = null;
  let companionEventId = null;
  let nextStreamTranscript = null;
  let sessionLoads = 0;
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, new FakeElement(id));
    }
    return elements.get(id);
  };
  const timers = [];
  const requests = [];
  const navigations = [];
  const audioSources = [];
  const audioContexts = [];
  const audioContext = {
    currentTime: 0, destination: {},
    createBuffer(_channels, length, sampleRate) {
      return {duration: length / sampleRate, copyToChannel() {}};
    },
    createBufferSource() {
      const source = {
        stopped: false, listeners: {},
        context: this,
        connect() {},
        start(when) { if (when > 0) audioSources.push(this); },
        stop() { this.stopped = true; },
        addEventListener(name, callback) { this.listeners[name] = callback; },
        end() { this.listeners.ended?.(); },
      };
      return source;
    },
  };
  let activeView = scenario.initialView || "conversation";
  const selectedModel = {
    provider: "fixture",
    model: "fixture",
    qualified_name: "fixture/fixture",
    status: "available",
  };
  const documentListeners = new Map();
  const windowListeners = new Map();
  const document = {
    hidden: false,
    getElementById: element,
    querySelector: () => new FakeElement("query"),
    querySelectorAll: () => [],
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (text) => ({textContent: text}),
    addEventListener(name, listener) {
      const listeners = documentListeners.get(name) || [];
      listeners.push(listener);
      documentListeners.set(name, listeners);
    },
    dispatchEvent(event) {
      for (const listener of documentListeners.get(event.type) || []) {
        listener(event);
      }
      return true;
    },
  };
  const ui = {
    csrfToken: "csrf",
    requestJson: async (requestPath, options = {}) => {
      if (options.method === "POST") {
        requests.push({path: requestPath, options});
        if (requestPath === "/api/new-session") {
          if (options.body.confirmed === false && scenario.newSession === "confirmation") {
            const error = new Error("Confirmation required");
            error.code = "new_session_confirmation_required";
            throw error;
          }
          if (scenario.newSession === "failure") throw new Error("New chat unavailable");
          return {ok: true, transcript: [], selected_model: selectedModel, project: null};
        }
        if (requestPath === "/api/speech/replay") {
          return {ok: true, speech_session: "speech-session"};
        }
        return {
          ok: true, busy: true, transcript: [], command: currentCommand,
        };
      }
      if (requestPath === "/api/session") {
        sessionLoads += 1;
        return {
          active_chat_id: activeChatId,
          transcript_revision: transcriptRevision,
          transcript: transcript.map((entry) => ({...entry})),
          selected_model: selectedModel, command: currentCommand,
          companion_initiative: {
            current_event_id: companionEventId,
            settings_revision: 1,
          },
          busy: serverBusy || ["authorized", "starting", "running"].includes(
            currentCommand.status
          ),
        };
      }
      if (requestPath === "/api/attention") {
        return {
          busy: serverBusy,
          active_chat_id: activeChatId,
          operational_revision: 0,
          active_reminder: null,
          queued_count: 0,
          next_due_utc: null,
          transcript_revision: transcriptRevision,
          memory_confirmation: memoryConfirmation,
          memory_attention_revision: memoryConfirmation?.revision || 0,
          companion_initiative: {
            current_event_id: companionEventId,
            settings_revision: 1,
          },
        };
      }
      if (requestPath === "/api/models") {
        return {selected_model: selectedModel, models: []};
      }
      if (requestPath === "/api/speech") {
        return {enabled: true, available: true, error: null};
      }
      if (requestPath === "/api/commands/active") {
        return {command: currentCommand};
      }
      if (requestPath === "/api/chats") {
        return {ok: true, chats: typeof scenario.chats === "function" ? scenario.chats() :
          (scenario.chats || []), active_chat_id: activeChatId};
      }
      if (requestPath === "/api/projects/labels") {
        return typeof scenario.projectLabels === "function" ? scenario.projectLabels() :
          (scenario.projectLabels || {ok: true, projects: []});
      }
      throw new Error(`unexpected request: ${requestPath}`);
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
    navigate(view, options = {}) {
      activeView = view;
      navigations.push({view, options});
    },
  };
  const window = {
    ToriUI: ui,
    ToriAudio: {
      activate: async () => audioContext,
      isActive: () => scenario.playback === true,
      requireActive: () => audioContext,
    },
    confirm: () => scenario.confirm === true,
    setTimeout(callback, delay) {
      timers.push({callback, delay});
      return timers.length;
    },
    clearTimeout() {},
    addEventListener(name, listener) {
      const listeners = windowListeners.get(name) || [];
      listeners.push(listener);
      windowListeners.set(name, listeners);
    },
  };
  if (scenario.realAudio) {
    window.navigator = {};
    window.AudioContext = class FakeAudioContext {
      constructor() {
        this.state = "running";
        this.currentTime = 0; // Simulate a context that reports running but never advances.
        this.sampleRate = 48000;
        this.destination = {};
        this.sourceCount = 0;
        audioContexts.push(this);
      }
      createBuffer(...args) { return audioContext.createBuffer(...args); }
      createBufferSource() {
        if (scenario.failFirstPlaybackSource && this === audioContexts[0] && this.sourceCount >= 1) {
          throw new Error("Browser source setup failed");
        }
        this.sourceCount += 1;
        return audioContext.createBufferSource.call(this);
      }
      async resume() { this.state = "running"; }
      async close() { this.state = "closed"; }
    };
    vm.runInNewContext(audioSource, {window}, {filename: "audio.js"});
  }
  const fetch = async (requestPath, options) => {
    requests.push({path: requestPath, options});
    if (requestPath === "/api/speech/stream" && scenario.playback) {
      const speechEvents = scenario.speechEvents || [
        {type: "start", sample_rate: 24000, channels: 1, sample_width: 2},
        {type: "audio", data: audiblePCM.toString("base64")},
        {type: "complete"},
      ];
      const encoded = new TextEncoder().encode(speechEvents.map((item) => JSON.stringify(item)).join("\n") + "\n");
      let delivered = false;
      return {
        ok: true,
        body: {getReader: () => ({
          read: async () => {
            if (delivered) return {value: undefined, done: true};
            delivered = true;
            return {value: encoded, done: false};
          },
          releaseLock() {},
        })},
      };
    }
    if (requestPath === "/api/message/stream" && nextStreamTranscript !== null) {
      const events = [
        ...(scenario.playback ? [{type: "speech", session: "auto-session"}] : []),
        ...(scenario.modelReply ? [{type: "delta", text: scenario.modelReply}] : []),
        {type: "complete", transcript: nextStreamTranscript},
      ];
      const encoded = new TextEncoder().encode(events.map((item) => JSON.stringify(item)).join("\n") + "\n");
      let delivered = false;
      return {
        ok: true,
        headers: {get: (name) => name === "Content-Type" ? "application/x-ndjson" : null},
        body: {getReader: () => ({
          read: async () => {
            if (delivered) return {value: undefined, done: true};
            delivered = true;
            return {value: encoded, done: false};
          },
          cancel: async () => {},
          releaseLock() {},
        })},
      };
    }
    return {
      ok: true,
      json: async () => ({ok: true, busy: true, command: currentCommand}),
    };
  };
  const instrumentedSource = source.replace(
    "\n}());\n",
    "\nwindow.__toriTestRevisionState = () => ({\n" +
      "  renderedChatId, renderedTranscriptRevision,\n" +
      "  pendingTranscriptChatId, pendingTranscriptRevision,\n" +
      "});\n}());\n"
  );
  vm.runInNewContext(
    instrumentedSource,
    {
      window, document, fetch, TextDecoder, TextEncoder, AbortController, atob, console,
      CustomEvent: class CustomEvent {
        constructor(type, options = {}) {
          this.type = type;
          this.detail = options.detail;
        }
      },
    },
    {filename: "app.js"}
  );
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  return {
    element,
    requests,
    navigations,
    activeView() { return activeView; },
    timers,
    audioSources,
    audioContexts,
    runPlaybackDeadline() {
      const timer = timers.findLast(({delay}) => delay >= 2000 && delay < 10000);
      assert.ok(timer, "completed playback must have a bounded recovery deadline");
      timer.callback();
    },
    revisionState() { return window.__toriTestRevisionState(); },
    setCommand(value) { currentCommand = value; },
    setMemoryConfirmation(value) { memoryConfirmation = value; },
    setStreamTranscript(value) {
      nextStreamTranscript = value.map((entry) => ({...entry}));
      transcript = nextStreamTranscript.map((entry) => ({...entry}));
      transcriptRevision += 1;
    },
    sessionLoads() { return sessionLoads; },
    setServerBusy(value, {
      advanceTranscript = false,
      nextTranscript = null,
      nextChatId = undefined,
      nextCompanionEventId = undefined,
    } = {}) {
      serverBusy = value;
      if (nextChatId !== undefined) {
        activeChatId = nextChatId;
      }
      if (advanceTranscript) {
        transcriptRevision += 1;
      }
      if (nextTranscript !== null) {
        transcript = nextTranscript.map((entry) => ({...entry}));
      }
      if (nextCompanionEventId !== undefined) {
        companionEventId = nextCompanionEventId;
      }
    },
    async setVisible(value) {
      document.hidden = !value;
      for (const listener of documentListeners.get("visibilitychange") || []) {
        listener();
      }
      await new Promise((resolve) => setImmediate(resolve));
      await new Promise((resolve) => setImmediate(resolve));
    },
  };
}

(async () => {
  const failed = await loadApplication(baseCommand({
    status: "failed",
    exit_code: 7,
    termination_reason: "nonzero_exit",
    stdout: "stdout test",
    stderr: "stderr test",
  }));
  assert.equal(failed.element("command-activity").hidden, false);
  assert.equal(failed.element("command-label").textContent, "printf fixture");
  assert.equal(failed.element("command-status").textContent, "Failed · exit 7");
  assert.equal(failed.element("command-stdout").textContent, "stdout test");
  assert.equal(failed.element("command-stderr").textContent, "stderr test");
  assert.equal(
    failed.element("command-details").open,
    false,
    "failed output must not expand without the user's Details choice"
  );
  assert.equal(failed.element("stop-command").hidden, true);
  assert.equal(failed.element("dismiss-command").hidden, false);
  await failed.element("command-details").listeners.click();
  assert.equal(failed.element("command-details-dialog").open, true);
  assert.equal(failed.requests.length, 0, "Details must remain presentation-only");
  failed.element("command-details-dialog").close();
  assert.equal(failed.element("command-details-dialog").open, false);

  const empty = await loadApplication(baseCommand({command: "git status --short"}));
  assert.equal(
    empty.element("command-status").textContent,
    "Completed · exit 0 · no output"
  );
  assert.equal(empty.element("command-stdout").textContent, "No stdout output.");
  assert.equal(empty.element("command-stderr").textContent, "No stderr output.");
  assert.equal(empty.element("command-details-dialog").open, false);

  const timedOut = await loadApplication(baseCommand({
    status: "timed_out",
    exit_code: -15,
    termination_reason: "timeout",
  }));
  assert.equal(timedOut.element("command-status").textContent, "Timed out · exit -15");
  assert.equal(timedOut.element("command-details-dialog").open, false);
  assert.ok(
    timedOut.element("command-metadata").children.some(
      (child) => child.textContent === "timeout"
    ),
    "timeout termination reason must be rendered"
  );

  const stopped = await loadApplication(baseCommand({
    status: "stopped",
    exit_code: -15,
    termination_reason: "stopped_by_user",
  }));
  assert.equal(stopped.element("command-status").textContent, "Stopped · exit -15");
  assert.notEqual(stopped.element("command-status").textContent, "Completed");

  const inertOutput = "/run touch must-not-execute";
  const running = await loadApplication(baseCommand({
    command: "sleep 60",
    status: "running",
    exit_code: null,
    stdout: undefined,
    stderr: undefined,
  }));
  assert.equal(running.element("command-status").textContent, "Running");
  assert.equal(running.element("stop-command").hidden, false);
  assert.equal(running.element("dismiss-command").hidden, true);
  await running.element("command-details").listeners.click();
  assert.equal(running.element("command-details-dialog").open, true);
  running.element("command-details-dialog").close();
  assert.equal(running.element("command-activity").hidden, false);
  assert.equal(running.element("stop-command").hidden, false);
  running.element("dismiss-command").listeners.click();
  assert.equal(running.element("command-activity").hidden, false);
  assert.equal(running.requests.length, 0);
  assert.ok(running.timers.length > 0, "running activity must schedule observation");
  await running.element("stop-command").listeners.click();
  assert.equal(running.requests.length, 1);
  assert.equal(running.requests[0].path, "/api/commands/stop");
  assert.equal(
    running.requests[0].options.body.invocation_id,
    "invocation-1"
  );
  assert.equal(Object.keys(running.requests[0].options.body).length, 1);

  const untrusted = await loadApplication(baseCommand({stdout: inertOutput}));
  assert.equal(untrusted.element("command-stdout").textContent, inertOutput);
  assert.equal(untrusted.requests.length, 0, "rendered output must remain inert");

  const dismissible = await loadApplication(baseCommand({status: "failed", exit_code: 2}));
  dismissible.element("dismiss-command").listeners.click();
  assert.equal(dismissible.element("command-activity").hidden, true);
  assert.equal(dismissible.requests.length, 0, "dismiss must remain presentation-only");
  dismissible.setCommand(baseCommand({
    invocation_id: "invocation-2",
    command: "printf later",
    status: "proposed",
    exit_code: null,
  }));
  dismissible.element("message").value = "/run printf later";
  await dismissible.element("composer").listeners.submit({preventDefault() {}});
  assert.equal(
    dismissible.element("command-activity").hidden,
    false,
    "a later invocation must restore command activity"
  );
  assert.equal(dismissible.element("command-label").textContent, "printf later");

  const observer = await loadApplication(baseCommand({status: "succeeded"}));
  const initialSessionLoads = observer.sessionLoads();
  observer.element("model-controls-dialog").open = true;
  observer.element("message").value = "preserved desktop draft";
  observer.setServerBusy(true);
  await observer.setVisible(true);
  assert.equal(observer.element("send").disabled, true);
  assert.equal(observer.element("conversation").busy, true);
  assert.equal(observer.element("status").textContent, "Tori is working…");

  const completedTranscript = [
    {role: "user", text: "Earlier"},
    {role: "assistant", text: "Earlier answer"},
    {role: "user", text: "New phone message"},
    {role: "assistant", text: "New phone answer"},
  ];
  observer.setServerBusy(true, {
    advanceTranscript: true,
    nextTranscript: completedTranscript,
  });
  for (let busyPoll = 0; busyPoll < 24; busyPoll += 1) {
    await observer.setVisible(true);
    const state = observer.revisionState();
    assert.equal(
      state.renderedTranscriptRevision,
      7,
      `busy poll ${busyPoll + 1} must not advance the actually-rendered revision`
    );
    assert.equal(state.renderedChatId, "chat-a");
    assert.equal(state.pendingTranscriptChatId, "chat-a");
    assert.equal(state.pendingTranscriptRevision, 8);
    assert.equal(
      observer.sessionLoads(),
      initialSessionLoads,
      "busy observations must not reload the session"
    );
    assert.equal(observer.element("conversation").children.length, 2);
  }

  observer.setServerBusy(false);
  await observer.setVisible(false);
  assert.equal(
    observer.element("send").disabled,
    true,
    "a backgrounded client retains its last state until visibility reconciliation"
  );
  await observer.setVisible(true);
  assert.equal(observer.element("send").disabled, false);
  assert.equal(observer.element("conversation").busy, false);
  assert.equal(observer.element("status").textContent, "Connected locally");
  assert.equal(observer.sessionLoads(), initialSessionLoads + 1);
  assert.equal(observer.revisionState().renderedTranscriptRevision, 8);
  assert.equal(observer.revisionState().renderedChatId, "chat-a");
  assert.equal(observer.revisionState().pendingTranscriptChatId, null);
  assert.equal(observer.revisionState().pendingTranscriptRevision, 0);
  assert.equal(observer.element("conversation").children.length, 4);
  assert.equal(
    observer.element("conversation").children[2].children[1].textContent,
    "New phone message"
  );
  assert.equal(
    observer.element("conversation").children[3].children[1].textContent,
    "New phone answer"
  );
  assert.equal(observer.element("model-controls-dialog").open, true);
  assert.equal(observer.element("message").value, "preserved desktop draft");
  await observer.setVisible(true);
  assert.equal(
    observer.sessionLoads(),
    initialSessionLoads + 1,
    "a rendered terminal revision must not trigger repeated session reloads"
  );

  observer.setServerBusy(true);
  await observer.setVisible(true);
  assert.equal(observer.element("send").disabled, true);
  observer.setServerBusy(false);
  await observer.setVisible(true);
  assert.equal(
    observer.element("send").disabled,
    false,
    "provider failure or initiating-client disconnect clears without a transcript revision"
  );
  assert.equal(observer.sessionLoads(), initialSessionLoads + 1);

  observer.setServerBusy(true, {
    advanceTranscript: true,
    nextChatId: "chat-b",
    nextTranscript: [
      {role: "user", text: "Different chat"},
      {role: "assistant", text: "Must not be injected"},
    ],
  });
  await observer.setVisible(true);
  observer.setServerBusy(false);
  await observer.setVisible(true);
  assert.equal(observer.element("send").disabled, false);
  assert.equal(observer.sessionLoads(), initialSessionLoads + 1);
  assert.equal(observer.element("conversation").children.length, 4);
  assert.equal(
    observer.element("conversation").children[3].children[1].textContent,
    "New phone answer",
    "a different active chat must not replace the browser's same-chat transcript"
  );

  const oneBusyPoll = await loadApplication(baseCommand({status: "succeeded"}));
  const oneBusyInitialLoads = oneBusyPoll.sessionLoads();
  oneBusyPoll.setServerBusy(true, {
    advanceTranscript: true,
    nextTranscript: completedTranscript,
  });
  await oneBusyPoll.setVisible(true);
  assert.equal(oneBusyPoll.revisionState().renderedTranscriptRevision, 7);
  oneBusyPoll.setServerBusy(false);
  await oneBusyPoll.setVisible(true);
  assert.equal(oneBusyPoll.sessionLoads(), oneBusyInitialLoads + 1);
  assert.equal(oneBusyPoll.revisionState().renderedTranscriptRevision, 8);

  const directIdle = await loadApplication(baseCommand({status: "succeeded"}));
  const directIdleInitialLoads = directIdle.sessionLoads();
  directIdle.setServerBusy(false, {
    advanceTranscript: true,
    nextTranscript: completedTranscript,
  });
  await directIdle.setVisible(true);
  assert.equal(directIdle.sessionLoads(), directIdleInitialLoads + 1);
  assert.equal(directIdle.revisionState().renderedTranscriptRevision, 8);
  assert.equal(directIdle.element("conversation").children.length, 4);

  const proactive = await loadApplication(baseCommand({status: "succeeded"}));
  const proactiveInitialLoads = proactive.sessionLoads();
  const initiativeEventId = "event-11111111111111111111111111111111";
  proactive.setServerBusy(false, {
    advanceTranscript: true,
    nextCompanionEventId: initiativeEventId,
    nextTranscript: [
      {role: "user", text: "Earlier"},
      {role: "assistant", text: "Earlier answer"},
      {
        role: "assistant",
        text: "Good morning. Want to ease into the day?",
        application_event: {type: "companion_initiative", id: initiativeEventId},
      },
    ],
  });
  await proactive.setVisible(true);
  assert.equal(proactive.sessionLoads(), proactiveInitialLoads + 1);
  assert.equal(proactive.element("conversation").children.length, 3);
  assert.equal(
    proactive.element("conversation").children[2].children[0].children[0].textContent,
    "Tori · Check-in"
  );
  assert.equal(
    proactive.element("conversation").children[2].children[2].children.length,
    3,
    "the check-in footer retains Dismiss and both pause controls"
  );
  assert.equal(proactive.element("conversation").children[1].children.length, 2,
    "an ordinary reply has metadata and content, without a Speak-only footer");
  const headerSpeak = proactive.element("conversation").children[2].children[0]
    .children.find(child => child.textContent === "Speak");
  assert.ok(headerSpeak, "Speak remains available in the message header");
  assert.equal(headerSpeak.dataset.entryIndex, "2");
  const requestsBeforeSpeak = proactive.requests.length;
  await headerSpeak.listeners.click();
  const speakRequests = proactive.requests.slice(requestsBeforeSpeak)
    .map((item) => item.path);
  assert.deepEqual(
    speakRequests,
    ["/api/speech/replay", "/api/speech/stream"],
    "Speak uses only the existing manual playback route"
  );
  await proactive.setVisible(true);
  assert.equal(proactive.sessionLoads(), proactiveInitialLoads + 1);
  assert.equal(
    proactive.element("conversation").children.length,
    3,
    "later polls must not duplicate the archived check-in"
  );
  assert.equal(
    proactive.element("conversation").children[2].children[2].children.length,
    3,
    "Speak and ordinary rerendering must preserve all initiative controls"
  );
  const requestsBeforePause = proactive.requests.length;
  await proactive.element("conversation").children[2]
    .children[2].children[1].listeners.click();
  const pauseRequest = proactive.requests.slice(requestsBeforePause)
    .find((item) => item.path === "/api/companion-initiative/pause");
  assert.equal(pauseRequest.options.body.duration, "one_day");
  assert.equal(pauseRequest.options.body.expected_revision, 1);
  assert.equal(
    pauseRequest.options.body.application_event_id,
    initiativeEventId,
    "Pause from a check-in is bound to that exact application event"
  );

  const storedFindings = await loadApplication(baseCommand({status: "succeeded"}));
  const storedFindingsTranscript = [
    {role: "user", text: "Earlier"},
    {role: "assistant", text: "Earlier answer"},
    {
      role: "assistant",
      text: "I found something useful earlier.",
      application_event: {type: "companion_initiative", id: initiativeEventId},
    },
    {role: "user", text: "What did Night Owl find?"},
    {role: "assistant", text: "Night Owl has no reviewable stored findings yet."},
  ];
  storedFindings.setStreamTranscript(storedFindingsTranscript);
  storedFindings.element("message").value = "What did Night Owl find?";
  await storedFindings.element("composer").listeners.submit({preventDefault() {}});
  assert.equal(
    storedFindings.element("message").value,
    "",
    storedFindings.element("error").textContent
  );
  assert.equal(storedFindings.element("error").hidden, true);
  assert.equal(
    storedFindings.element("status").textContent,
    "Response complete · Connected locally"
  );
  assert.equal(storedFindings.element("conversation").children.length, 5);

  const differentDuringPending = await loadApplication(
    baseCommand({status: "succeeded"})
  );
  const differentPendingInitialLoads = differentDuringPending.sessionLoads();
  differentDuringPending.setServerBusy(true, {
    advanceTranscript: true,
    nextTranscript: completedTranscript,
  });
  await differentDuringPending.setVisible(true);
  assert.equal(differentDuringPending.revisionState().pendingTranscriptRevision, 8);
  differentDuringPending.setServerBusy(false, {
    nextChatId: "chat-b",
    nextTranscript: [
      {role: "user", text: "Different terminal chat"},
      {role: "assistant", text: "Must stay isolated"},
    ],
  });
  await differentDuringPending.setVisible(true);
  assert.equal(differentDuringPending.sessionLoads(), differentPendingInitialLoads);
  assert.equal(differentDuringPending.revisionState().renderedChatId, "chat-a");
  assert.equal(differentDuringPending.revisionState().renderedTranscriptRevision, 7);
  assert.equal(differentDuringPending.element("conversation").children.length, 2);

  const memoryObserver = await loadApplication(
    baseCommand({status: "succeeded"})
  );
  const memoryInitialLoads = memoryObserver.sessionLoads();
  memoryObserver.element("model-controls-dialog").open = true;
  memoryObserver.element("message").value = "draft survives memory proposal";
  memoryObserver.setMemoryConfirmation({
    extraction_id: "extract-11111111111111111111111111111111",
    revision: 3,
    token: "durable-memory-token",
    action: "memory.proposal.create",
    message: "Remember this proposed understanding: concise answers",
  });
  await memoryObserver.setVisible(true);
  assert.equal(memoryObserver.element("confirmation").open, true);
  assert.equal(memoryObserver.element("conversation").busy, false);
  assert.equal(memoryObserver.element("message").value, "draft survives memory proposal");
  memoryObserver.element("accept-confirmation").listeners.click({preventDefault() {}});
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(memoryObserver.element("conversation").busy, false);
  assert.equal(memoryObserver.element("send").disabled, false);
  assert.equal(memoryObserver.sessionLoads(), memoryInitialLoads);
  assert.equal(memoryObserver.element("conversation").children.length, 2);
  assert.equal(memoryObserver.element("model-controls-dialog").open, true);
  assert.equal(memoryObserver.element("message").value, "draft survives memory proposal");
  assert.ok(
    memoryObserver.requests.some((request) => request.path === "/api/confirm"),
    "a durable memory decision must use the one-use confirmation endpoint"
  );

  for (const initialView of ["home", "settings", "conversation"]) {
    const session = await loadApplication(baseCommand({status: "succeeded"}), {initialView});
    const before = session.element("message").focusCount;
    await session.element("new-session").listeners.click();
    assert.equal(session.activeView(), "conversation");
    assert.equal(session.navigations.length, 1);
    assert.equal(session.navigations[0].options.focus, false);
    assert.equal(session.element("message").focusCount, before + 1);
    assert.equal(session.element("conversation").children.length, 0);
    assert.equal(session.requests.filter((request) => request.path === "/api/new-session").length, 1);
  }
  const cancelled = await loadApplication(baseCommand({status: "succeeded"}), {
    initialView: "settings", newSession: "confirmation", confirm: false,
  });
  await cancelled.element("new-session").listeners.click();
  assert.equal(cancelled.activeView(), "settings");
  assert.equal(cancelled.navigations.length, 0);
  assert.equal(cancelled.requests.filter((request) => request.path === "/api/new-session").length, 1);

  const confirmed = await loadApplication(baseCommand({status: "succeeded"}), {
    initialView: "home", newSession: "confirmation", confirm: true,
  });
  await confirmed.element("new-session").listeners.click();
  assert.equal(confirmed.activeView(), "conversation");
  assert.deepEqual(confirmed.requests.filter((request) => request.path === "/api/new-session")
    .map((request) => request.options.body.confirmed), [false, true]);

  const rejected = await loadApplication(baseCommand({status: "succeeded"}), {
    initialView: "home", newSession: "failure",
  });
  await rejected.element("new-session").listeners.click();
  assert.equal(rejected.activeView(), "home");
  assert.equal(rejected.navigations.length, 0);
  assert.equal(rejected.element("error").textContent, "New chat unavailable");

  let releaseLabels;
  const labels = new Promise((resolve) => { releaseLabels = resolve; });
  const badges = await loadApplication(baseCommand({status: "succeeded"}), {
    chats: [{
      identifier: "chat-1", label: "Archived", revision: 1,
      project_id: "project-1", completed_turn_count: 0,
      updated_at: "2026-09-26T00:00:00Z",
    }],
    projectLabels: labels,
  });
  assert.equal(badges.element("chat-list").children.length, 0,
    "the chat row must not appear with a temporary or incorrect Project label");
  releaseLabels({ok: true, projects: [{identifier: "project-1", title: "Canonical title"}]});
  await new Promise((resolve) => setImmediate(resolve));
  const card = badges.element("chat-list").children[0];
  assert.equal(card.children[0].children[2].textContent, "Canonical title");
  assert.equal(card.children[0].children[2].className, "chat-project-badge");

  let releaseOldLabels;
  const oldLabels = new Promise((resolve) => { releaseOldLabels = resolve; });
  let reads = 0;
  const refreshed = await loadApplication(baseCommand({status: "succeeded"}), {
    chats() {
      reads += 1;
      return [{identifier: "chat-1", label: "Archived", revision: reads,
        project_id: reads === 1 ? "project-old" : "project-new",
        completed_turn_count: 0, updated_at: "2026-09-26T00:00:00Z"}];
    },
    projectLabels() {
      return reads === 1 ? oldLabels :
        {ok: true, projects: [{identifier: "project-new", title: "Current"}]};
    },
  });
  await refreshed.element("refresh-chats").listeners.click();
  assert.equal(refreshed.element("chat-list").children[0].children[0].children[2].textContent,
    "Current");
  releaseOldLabels({ok: true, projects: [{identifier: "project-old", title: "Stale"}]});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(refreshed.element("chat-list").children[0].children[0].children[2].textContent,
    "Current", "late responses must not attach a stale Project badge");

  const settle = () => new Promise((resolve) => setImmediate(resolve));
  const directSpeech = await loadApplication(baseCommand({status: "succeeded"}), {playback: true});
  await directSpeech.element("auto-speech").listeners.click();
  directSpeech.setStreamTranscript([
    {role: "user", text: "Can you listen to me or use voice input?"},
    {role: "assistant", text: "I use push-to-talk voice input."},
  ]);
  directSpeech.element("message").value = "Can you listen to me or use voice input?";
  await directSpeech.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(directSpeech.requests.filter(({path}) => path === "/api/speech/stream").length, 1);
  assert.equal(directSpeech.element("speech-status").textContent, "Speaking…");
  directSpeech.audioSources[0].end();
  assert.equal(directSpeech.element("speech-status").textContent, "Speech complete.");
  directSpeech.runPlaybackDeadline();
  assert.equal(directSpeech.element("speech-status").textContent, "Speech complete.",
    "a late recovery timer must not override completed playback");
  await directSpeech.setVisible(true);
  assert.equal(directSpeech.requests.filter(({path}) => path === "/api/speech/stream").length, 1,
    "reconciliation must not replay the completed response");
  const reloadedSpeech = await loadApplication(baseCommand({status: "succeeded"}), {playback: true});
  assert.equal(reloadedSpeech.requests.filter(({path}) => path === "/api/speech/stream").length, 0,
    "a new browser must not auto-play archived assistant messages");

  const stalledSpeech = await loadApplication(baseCommand({status: "succeeded"}), {playback: true});
  await stalledSpeech.element("auto-speech").listeners.click();
  stalledSpeech.setStreamTranscript([
    {role: "user", text: "Can you run a command for me?"},
    {role: "assistant", text: "I can use my supervised Terminal."},
  ]);
  stalledSpeech.element("message").value = "Can you run a command for me?";
  await stalledSpeech.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(stalledSpeech.element("speech-status").textContent, "Speaking…");
  stalledSpeech.runPlaybackDeadline();
  assert.equal(stalledSpeech.element("speech-status").dataset.state, "warning");
  assert.match(stalledSpeech.element("speech-status").textContent, /did not finish/);
  assert.equal(stalledSpeech.audioSources[0].stopped, true);
  stalledSpeech.audioSources[0].end();
  assert.equal(stalledSpeech.element("speech-status").dataset.state, "warning",
    "late audio completion must not claim playback succeeded");
  stalledSpeech.setStreamTranscript([
    {role: "user", text: "How's your evening going?"},
    {role: "assistant", text: "I'm here and ready to talk."},
  ]);
  stalledSpeech.element("message").value = "How's your evening going?";
  await stalledSpeech.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(stalledSpeech.requests.filter(({path}) => path === "/api/speech/stream").length, 2,
    "a later answer must play without reloading the browser");
  stalledSpeech.audioSources[1].end();
  assert.equal(stalledSpeech.element("speech-status").textContent, "Speech complete.");

  const ordinarySpeech = await loadApplication(baseCommand({status: "succeeded"}),
    {playback: true, modelReply: "An ordinary streamed answer."});
  await ordinarySpeech.element("auto-speech").listeners.click();
  ordinarySpeech.setStreamTranscript([
    {role: "user", text: "How are you?"},
    {role: "assistant", text: "An ordinary streamed answer."},
  ]);
  ordinarySpeech.element("message").value = "How are you?";
  await ordinarySpeech.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  ordinarySpeech.audioSources[0].end();
  assert.equal(ordinarySpeech.element("speech-status").textContent, "Speech complete.");

  const failedSpeech = await loadApplication(baseCommand({status: "succeeded"}), {
    playback: true,
    realAudio: true,
    speechEvents: [
      {type: "start", sample_rate: 24000, channels: 1, sample_width: 2},
      {type: "audio", data: audiblePCM.toString("base64")},
      {type: "error", error: "Speech is unavailable right now."},
    ],
  });
  await failedSpeech.element("auto-speech").listeners.click();
  failedSpeech.setStreamTranscript([
    {role: "user", text: "Do you have a Security Center?"},
    {role: "assistant", text: "I can review security intelligence."},
  ]);
  failedSpeech.element("message").value = "Do you have a Security Center?";
  await failedSpeech.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(failedSpeech.element("speech-status").dataset.state, "warning");
  assert.equal(failedSpeech.element("speech-status").textContent, "Speech is unavailable right now.");
  assert.equal(failedSpeech.audioContexts[0].state, "closed");
  failedSpeech.audioSources[0].end();
  assert.equal(failedSpeech.element("speech-status").dataset.state, "warning");

  const cancelledSpeech = await loadApplication(baseCommand({status: "succeeded"}), {playback: true});
  await cancelledSpeech.element("auto-speech").listeners.click();
  cancelledSpeech.setStreamTranscript([
    {role: "user", text: "Can you speak responses out loud?"},
    {role: "assistant", text: "Yes, using a local speech profile."},
  ]);
  cancelledSpeech.element("message").value = "Can you speak responses out loud?";
  await cancelledSpeech.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  cancelledSpeech.element("stop-speech").listeners.click();
  assert.equal(cancelledSpeech.element("speech-status").textContent, "Speech stopped.");
  cancelledSpeech.runPlaybackDeadline();
  cancelledSpeech.audioSources[0].end();
  assert.equal(cancelledSpeech.element("speech-status").textContent, "Speech stopped.");
  const speak = cancelledSpeech.element("conversation").children.at(-1).children[0]
    .children.find((child) => child.textContent === "Speak");
  await speak.listeners.click();
  await settle();
  assert.ok(cancelledSpeech.requests.some(({path}) => path === "/api/speech/replay"));
  cancelledSpeech.audioSources[1].end();
  assert.equal(cancelledSpeech.element("speech-status").textContent, "Speech complete.");

  // Same browser and real audio.js controller throughout: a context that
  // claims to be running but produces no `ended` must not poison the next
  // ordinary Auto Voice or manual Speak. A refresh is deliberately unavailable.
  const poisoned = await loadApplication(baseCommand({status: "succeeded"}),
    {playback: true, realAudio: true});
  await poisoned.element("auto-speech").listeners.click();
  poisoned.setStreamTranscript([
    {role: "user", text: "Can you listen to me or use voice input?"},
    {role: "assistant", text: "I can use push-to-talk voice input."},
  ]);
  poisoned.element("message").value = "Can you listen to me or use voice input?";
  await poisoned.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(poisoned.audioContexts.length, 1);
  assert.equal(poisoned.audioSources[0].context, poisoned.audioContexts[0]);
  poisoned.runPlaybackDeadline();
  assert.equal(poisoned.audioContexts[0].state, "closed",
    "a failed playback must retire its poisoned AudioContext, not only its source");
  poisoned.setStreamTranscript([
    {role: "user", text: "How's your evening going?"},
    {role: "assistant", text: "I'm doing well."},
  ]);
  poisoned.element("message").value = "How's your evening going?";
  await poisoned.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(poisoned.audioContexts.length, 2, "Auto Voice needs a fresh browser audio controller");
  assert.equal(poisoned.audioSources[1].context, poisoned.audioContexts[1]);
  poisoned.audioSources[1].end();
  assert.equal(poisoned.element("speech-status").textContent, "Speech complete.");
  const manual = poisoned.element("conversation").children.at(-1).children[0]
    .children.find((child) => child.textContent === "Speak");
  await manual.listeners.click();
  await settle();
  assert.equal(poisoned.audioSources[2].context, poisoned.audioContexts[1]);
  poisoned.audioSources[2].end();
  assert.equal(poisoned.element("speech-status").textContent, "Speech complete.");

  const early = await loadApplication(baseCommand({status: "succeeded"}),
    {playback: true, realAudio: true});
  await early.element("auto-speech").listeners.click();
  early.setStreamTranscript([
    {role: "user", text: "Do you have a Security Center?"},
    {role: "assistant", text: "I can discuss intelligence."},
  ]);
  early.element("message").value = "Do you have a Security Center?";
  await early.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  early.setStreamTranscript([
    {role: "user", text: "Tell me something interesting."},
    {role: "assistant", text: "Here's a thought."},
  ]);
  early.element("message").value = "Tell me something interesting.";
  await early.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(early.audioContexts.length, 2,
    "a new user gesture must retire unfinished playback before reactivation");
  assert.equal(early.audioContexts[0].state, "closed");
  assert.equal(early.audioSources[1].context, early.audioContexts[1]);
  const busyBeforeOldEnd = early.element("speech-status").textContent;
  early.audioSources[0].end();
  assert.equal(early.element("speech-status").textContent, busyBeforeOldEnd,
    "a late callback from the old context must not complete the new speech");
  early.audioSources[1].end();
  assert.equal(early.element("speech-status").textContent, "Speech complete.");

  const manualRecovery = await loadApplication(baseCommand({status: "succeeded"}),
    {playback: true, realAudio: true});
  await manualRecovery.element("auto-speech").listeners.click();
  manualRecovery.setStreamTranscript([
    {role: "user", text: "Can you listen to me?"},
    {role: "assistant", text: "Push-to-talk is available when configured."},
  ]);
  manualRecovery.element("message").value = "Can you listen to me?";
  await manualRecovery.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  const retrySpeak = manualRecovery.element("conversation").children.at(-1).children[0]
    .children.find((child) => child.textContent === "Speak");
  await retrySpeak.listeners.click();
  await settle();
  assert.equal(manualRecovery.audioContexts[0].state, "closed",
    "manual Speak must retire unfinished Auto Voice before reactivation");
  assert.equal(manualRecovery.audioSources[1].context, manualRecovery.audioContexts[1]);
  manualRecovery.audioSources[0].end();
  assert.equal(manualRecovery.element("speech-status").textContent, "Speaking…");
  manualRecovery.audioSources[1].end();
  assert.equal(manualRecovery.element("speech-status").textContent, "Speech complete.");

  const badSource = await loadApplication(baseCommand({status: "succeeded"}),
    {playback: true, realAudio: true, failFirstPlaybackSource: true});
  await badSource.element("auto-speech").listeners.click();
  badSource.setStreamTranscript([
    {role: "user", text: "Can you speak responses out loud?"},
    {role: "assistant", text: "Yes, when speech is available."},
  ]);
  badSource.element("message").value = "Can you speak responses out loud?";
  await badSource.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(badSource.element("speech-status").dataset.state, "warning");
  assert.equal(badSource.audioContexts[0].state, "closed");
  badSource.setStreamTranscript([
    {role: "user", text: "How's your evening going?"},
    {role: "assistant", text: "Better now."},
  ]);
  badSource.element("message").value = "How's your evening going?";
  await badSource.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(badSource.audioContexts.length, 2);
  badSource.audioSources[0].end();
  assert.equal(badSource.element("speech-status").textContent, "Speech complete.");

  const earlyTerminalScenario = {playback: true, realAudio: true,
    speechEvents: [{type: "start", sample_rate: 24000, channels: 1, sample_width: 2},
      {type: "complete"}, {type: "audio", data: audiblePCM.toString("base64")}]};
  const earlyTerminal = await loadApplication(baseCommand({status: "succeeded"}), earlyTerminalScenario);
  await earlyTerminal.element("auto-speech").listeners.click();
  earlyTerminal.setStreamTranscript([
    {role: "user", text: "Can you restore a backup?"},
    {role: "assistant", text: "A verified backup can be restored after confirmation."},
  ]);
  earlyTerminal.element("message").value = "Can you restore a backup?";
  await earlyTerminal.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(earlyTerminal.element("speech-status").dataset.state, "warning");
  assert.equal(earlyTerminal.audioContexts[0].state, "closed");
  earlyTerminalScenario.speechEvents = null;
  earlyTerminal.setStreamTranscript([
    {role: "user", text: "How are you?"},
    {role: "assistant", text: "Ready to help."},
  ]);
  earlyTerminal.element("message").value = "How are you?";
  await earlyTerminal.element("composer").listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(earlyTerminal.audioContexts.length, 2);
  earlyTerminal.audioSources[0].end();
  assert.equal(earlyTerminal.element("speech-status").textContent, "Speech complete.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
