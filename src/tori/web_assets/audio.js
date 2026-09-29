"use strict";

(function initializeToriAudio() {
  const ACTIVATION_ERROR =
    "Browser audio is not active. Tap Auto speech or Speak and try again.";
  const SESSION_ERROR =
    "Browser could not configure speech playback. Check Silent mode or browser audio support and try again.";
  let context = null;
  let activatedContext = null;

  function configurePlaybackSession() {
    let audioSession;
    try {
      audioSession = window.navigator && window.navigator.audioSession;
    } catch (_error) {
      throw new Error(SESSION_ERROR);
    }
    if (!audioSession) {
      return;
    }
    try {
      audioSession.type = "playback";
      if (audioSession.type !== "playback") {
        throw new Error("playback session was rejected");
      }
    } catch (_error) {
      throw new Error(SESSION_ERROR);
    }
  }

  function audioContext() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      throw new Error("This browser cannot play Tori's streaming speech.");
    }
    if (!context || context.state === "closed") {
      context = new AudioContextClass();
      activatedContext = null;
    }
    return context;
  }

  async function activate() {
    // Output-only TTS is intentional media playback. On supporting WebKit
    // versions this keeps it audible when the iPhone Ring/Silent switch is
    // set to Silent. Browsers without the Audio Session API keep the existing
    // Web Audio path.
    configurePlaybackSession();
    const current = audioContext();
    if (activatedContext === current && current.state === "running") {
      return current;
    }

    // iOS/WebKit may accept resume() without unlocking later buffer playback.
    // Start one inaudible sample while this function is still in the trusted
    // gesture, before awaiting the resume promise or any network operation.
    const silentBuffer = current.createBuffer(
      1,
      1,
      current.sampleRate || 24_000
    );
    const silentSource = current.createBufferSource();
    silentSource.buffer = silentBuffer;
    silentSource.connect(current.destination);
    silentSource.start(0);

    try {
      if (current.state !== "running") {
        await current.resume();
      }
    } catch (_error) {
      activatedContext = null;
      throw new Error(ACTIVATION_ERROR);
    }
    if (current.state !== "running") {
      activatedContext = null;
      throw new Error(ACTIVATION_ERROR);
    }
    activatedContext = current;
    return current;
  }

  function requireActive() {
    if (!context || activatedContext !== context || context.state !== "running") {
      throw new Error(ACTIVATION_ERROR);
    }
    return context;
  }

  function isActive() {
    return Boolean(
      context && activatedContext === context && context.state === "running"
    );
  }

  function reset() {
    // A context may report `running` while its playback clock/source is stuck.
    // Detach it before closing so the next user gesture always builds and
    // unlocks a fresh context instead of reusing the poisoned one.
    const previous = context;
    context = null;
    activatedContext = null;
    if (previous && previous.state !== "closed") {
      try {
        Promise.resolve(previous.close()).catch(() => {});
      } catch (_error) {
        // Replacing the owned reference is the recovery boundary.
      }
    }
  }

  window.ToriAudio = Object.freeze({activate, isActive, requireActive, reset});
}());
