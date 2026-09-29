"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "audio.js"),
  "utf8"
);

function loadAudio(FakeAudioContext, audioSession) {
  const navigator = {};
  if (audioSession !== undefined) {
    navigator.audioSession = audioSession;
  }
  const sandbox = {window: {AudioContext: FakeAudioContext, navigator}};
  vm.runInNewContext(source, sandbox, {filename: "audio.js"});
  return sandbox.window.ToriAudio;
}

function makeAudioSession({assignment = "success"} = {}) {
  let currentType = "ambient";
  let assignments = 0;
  const session = {};
  Object.defineProperty(session, "type", {
    get() {
      return currentType;
    },
    set(value) {
      assignments += 1;
      assert.equal(value, "playback");
      if (assignment === "throw") {
        throw new Error("unsupported category");
      }
      if (assignment === "success") {
        currentType = value;
      }
    },
  });
  session.assignmentCount = () => assignments;
  return session;
}

function makeAudioContext({resume = "success", initialState = "suspended"} = {}) {
  return class FakeAudioContext {
    static instances = [];

    constructor() {
      this.state = initialState;
      this.sampleRate = 48_000;
      this.destination = {};
      this.silentStarts = 0;
      this.resumeCalls = 0;
      this.closeCalls = 0;
      this.constructor.instances.push(this);
    }

    createBuffer(channels, length, sampleRate) {
      assert.equal(channels, 1);
      assert.equal(length, 1);
      assert.equal(sampleRate, this.sampleRate);
      return {channels, length, sampleRate};
    }

    createBufferSource() {
      return {
        connect: (destination) => assert.equal(destination, this.destination),
        start: () => {
          this.silentStarts += 1;
        },
      };
    }

    async resume() {
      this.resumeCalls += 1;
      assert.equal(
        this.silentStarts,
        this.resumeCalls,
        "the inaudible unlock source must start before resume is awaited"
      );
      if (resume === "throw") {
        throw new Error("blocked");
      }
      if (resume === "success") {
        this.state = "running";
      }
    }

    async close() {
      this.closeCalls += 1;
      this.state = "closed";
    }
  };
}

(async () => {
  const playbackSession = makeAudioSession();
  const SuccessfulContext = makeAudioContext();
  const audio = loadAudio(SuccessfulContext, playbackSession);
  assert.equal(SuccessfulContext.instances.length, 0);

  const context = await audio.activate();
  assert.equal(playbackSession.type, "playback");
  assert.equal(playbackSession.assignmentCount(), 1);
  assert.equal(context.state, "running");
  assert.equal(context.resumeCalls, 1);
  assert.equal(context.silentStarts, 1);
  assert.equal(audio.requireActive(), context);
  assert.equal(audio.isActive(), true);

  assert.equal(await audio.activate(), context);
  assert.equal(playbackSession.assignmentCount(), 2);
  assert.equal(SuccessfulContext.instances.length, 1);
  assert.equal(context.silentStarts, 1, "an active context is not unlocked twice");

  context.state = "suspended";
  assert.throws(() => audio.requireActive(), /Tap Auto speech or Speak/);
  assert.equal(audio.isActive(), false);
  await audio.activate();
  assert.equal(context.resumeCalls, 2);
  assert.equal(context.silentStarts, 2);
  audio.reset();
  assert.equal(context.closeCalls, 1);
  assert.equal(audio.isActive(), false);
  assert.throws(() => audio.requireActive(), /Tap Auto speech or Speak/);
  const recovered = await audio.activate();
  assert.notEqual(recovered, context);
  assert.equal(SuccessfulContext.instances.length, 2);
  assert.equal(recovered.state, "running");

  const UnsupportedContext = makeAudioContext();
  const unsupported = loadAudio(UnsupportedContext);
  assert.equal((await unsupported.activate()).state, "running");
  assert.equal(UnsupportedContext.instances.length, 1);

  for (const assignment of ["throw", "rejected"]) {
    const SessionFailureContext = makeAudioContext();
    const sessionFailure = loadAudio(
      SessionFailureContext,
      makeAudioSession({assignment})
    );
    await assert.rejects(
      sessionFailure.activate(),
      /Check Silent mode or browser audio support/
    );
    assert.equal(sessionFailure.isActive(), false);
    assert.equal(
      SessionFailureContext.instances.length,
      0,
      "a rejected playback category must not create an AudioContext"
    );
  }

  const RefusedContext = makeAudioContext({resume: "refused"});
  const refused = loadAudio(RefusedContext);
  await assert.rejects(refused.activate(), /Tap Auto speech or Speak/);
  assert.equal(refused.isActive(), false);
  assert.throws(() => refused.requireActive(), /Tap Auto speech or Speak/);

  const FailedContext = makeAudioContext({resume: "throw"});
  const failed = loadAudio(FailedContext);
  await assert.rejects(failed.activate(), /Tap Auto speech or Speak/);
  assert.equal(failed.isActive(), false);
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
