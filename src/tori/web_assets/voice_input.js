"use strict";

(function initializeVoiceInput() {
  const ui = window.ToriUI;
  const status = document.getElementById("voice-input-status");
  const ptt = document.getElementById("voice-ptt");
  const DEVICE_KEY = "tori.voice-input.microphone";
  const MODE_KEY = "tori.voice-input.ptt-mode";
  const PRE_ROLL_SECONDS = 0.5;
  const MAX_QUEUE_SECONDS = 1;
  let owner = null;
  let microphone = null;
  let microphoneDevices = [];
  let activeMicrophoneId = "";
  let stream = null;
  let context = null;
  let source = null;
  let worklet = null;
  let silentGain = null;
  let eventsAbort = null;
  let heartbeat = null;
  let preRoll = [];
  let preRollBytes = 0;
  let queue = [];
  let queuedBytes = 0;
  let inFlightBytes = 0;
  let queueSending = false;
  let sequence = 0;
  let state = "off";
  let mode = "hold";
  let pendingFinalize = false;
  let pendingCancel = false;
  let captureEnding = false;
  let beginPending = false;
  let deferredEnd = null;
  let captureGeneration = 0;
  let recoveringTurn = false;
  let recovery = null;
  let pendingFinal = null;
  let statusDetail = {state: "off", message: "Voice input: Off", enabled: false, mode};

  function localPreference(key) {
    try { return localStorage.getItem(key); } catch (_error) { return null; }
  }

  function savePreference(key, value) {
    try {
      if (value) localStorage.setItem(key, value);
      else localStorage.removeItem(key);
    } catch (_error) {
      // A browser that blocks local storage can still use its current device.
    }
  }

  mode = localPreference(MODE_KEY) === "toggle" ? "toggle" : "hold";

  function updateStatus(next, message) {
    state = next;
    const labels = {
      off: "Voice input: Off", preparing: "Voice input: Starting…",
      ready: "Voice input: Ready", listening_ptt: "Voice input: Listening…",
      finalizing: "Voice input: Finalizing…", error: "Voice input: Unavailable",
    };
    status.textContent = message || labels[next] || "Voice input: Unavailable";
    status.dataset.state = next === "listening_ptt" ? "listening" : next === "error" ? "error" : "";
    const active = next === "ready" || next === "listening_ptt" || next === "finalizing";
    status.disabled = !["off", "ready", "error"].includes(next);
    status.setAttribute("aria-pressed", String(active));
    if (microphone) {
      microphone.disabled = !active || state === "listening_ptt" || state === "finalizing";
    }
    ptt.hidden = !active;
    const blocked = window.ToriConversation?.canStartVoiceTurn?.() === false;
    ptt.disabled = !active || state !== "ready" || blocked;
    ptt.textContent = mode === "toggle" ? "Start talking" : "Hold to talk";
    statusDetail = {state: next, message: status.textContent, enabled: active, mode};
    document.dispatchEvent(new CustomEvent("tori:voiceinputstate", {detail: statusDetail}));
  }

  function renderMicrophoneControl() {
    if (!microphone) return;
    microphone.replaceChildren();
    const fallback = document.createElement("option");
    fallback.value = "";
    fallback.textContent = "Default microphone";
    microphone.append(fallback);
    for (const device of microphoneDevices) {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || "Microphone";
      microphone.append(option);
    }
    microphone.value = activeMicrophoneId || "";
    microphone.disabled = !["ready", "listening_ptt", "finalizing"].includes(state) ||
      state === "listening_ptt" || state === "finalizing";
  }

  function bindMicrophoneControl(control) {
    if (!control || control === microphone) return;
    microphone = control;
    microphone.addEventListener("change", async () => {
      if (state !== "ready") return;
      savePreference(DEVICE_KEY, microphone.value);
      await disable();
      await enable();
    });
    renderMicrophoneControl();
  }

  function binding(turn = false) {
    if (!owner) throw new Error("Voice Input is not ready.");
    const result = {
      epoch: owner.epoch, lease: owner.lease,
      lease_generation: owner.lease_generation, revision: owner.revision,
    };
    if (turn) result.utterance_id = owner.utterance_id;
    return result;
  }

  function adopt(documentBody) {
    if (!owner || !documentBody || typeof documentBody.revision !== "number") return;
    if (documentBody.revision < owner.revision) return;
    owner = {...owner, ...documentBody};
  }

  async function request(operation, documentBody = {}) {
    const result = await ui.requestJson(`/api/voice-input/${operation}`, {
      method: "POST", body: documentBody,
    });
    adopt(result);
    return result;
  }

  async function sendAudio(pcm) {
    inFlightBytes = pcm.byteLength;
    try {
    const headers = {
      "Content-Type": "application/octet-stream",
      "X-Tori-CSRF": ui.csrfToken,
      "X-Tori-Voice-Binding": JSON.stringify({...binding(true), sequence: sequence + 1}),
    };
    const response = await fetch("/api/voice-input/audio", {
      method: "POST", headers, body: pcm, cache: "no-store", credentials: "same-origin",
    });
    const documentBody = await response.json();
    if (!response.ok) {
      const error = new Error(documentBody.error || "Voice audio was rejected.");
      error.code = typeof documentBody.code === "string" ? documentBody.code : "";
      throw error;
    }
    sequence += 1;
    adopt(documentBody);
    } finally { inFlightBytes = 0; }
  }

  async function flushAudio() {
    if (queueSending) return;
    queueSending = true;
    try {
      while (queue.length && state === "listening_ptt") {
        const pcm = queue.shift();
        queuedBytes -= pcm.byteLength;
        await sendAudio(pcm);
      }
    } catch (error) {
      if (runtimeFailure(error)) await fail(error);
      else await recoverTurn(error, "Voice input: Ready — microphone transport paused");
    } finally {
      queueSending = false;
      if (recoveringTurn) {
        await completeTurnRecovery();
      } else if (pendingCancel && state === "listening_ptt") {
        await cancelTurn();
      } else if (pendingFinalize && !queue.length && state === "listening_ptt") {
        await finalize();
      }
    }
  }

  function acceptPcm(buffer) {
    const pcm = new Int16Array(buffer);
    const bytes = pcm.byteLength;
    if (!context || !bytes) return;
    if (state === "ready") {
      preRoll.push(buffer);
      preRollBytes += bytes;
      const limit = context.sampleRate * 2 * PRE_ROLL_SECONDS;
      while (preRollBytes > limit && preRoll.length) {
        preRollBytes -= preRoll.shift().byteLength;
      }
      return;
    }
    if (state !== "listening_ptt" || captureEnding || recoveringTurn) return;
    queue.push(buffer);
    queuedBytes += bytes;
    if (queuedBytes > context.sampleRate * 2 * MAX_QUEUE_SECONDS) {
      void recoverTurn(new Error("Voice Input could not keep up with the microphone."),
        "Voice input: Ready — microphone transport paused");
      return;
    }
    flushAudio();
  }

  async function startCapture() {
    const saved = localPreference(DEVICE_KEY);
    const constraints = {
      channelCount: 1, sampleRate: 48000, autoGainControl: true,
      echoCancellation: false, noiseSuppression: false,
    };
    if (saved) constraints.deviceId = {exact: saved};
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: constraints});
    } catch (error) {
      if (saved && error.name === "OverconstrainedError") {
        stream = await navigator.mediaDevices.getUserMedia({audio: {
          channelCount: 1, sampleRate: 48000, autoGainControl: true,
          echoCancellation: false, noiseSuppression: false,
        }});
        savePreference(DEVICE_KEY, null);
      } else {
        throw error;
      }
    }
    const track = stream.getAudioTracks()[0];
    const generation = ++captureGeneration;
    track.addEventListener("ended", () => {
      if (generation === captureGeneration) {
        void fail(new Error("The selected microphone is unavailable."),
          "Voice input: Unavailable — selected microphone is unavailable");
      }
    });
    context = new AudioContext();
    if (![44100, 48000].includes(context.sampleRate)) {
      throw new Error("This microphone sample rate is not supported by Voice Input.");
    }
    await context.audioWorklet.addModule("/assets/voice_capture_worklet.js");
    source = context.createMediaStreamSource(stream);
    worklet = new AudioWorkletNode(context, "tori-voice-capture", {
      channelCount: 1, channelCountMode: "explicit", channelInterpretation: "speakers",
    });
    silentGain = context.createGain();
    silentGain.gain.value = 0;
    source.connect(worklet).connect(silentGain).connect(context.destination);
    worklet.port.onmessage = (event) => acceptPcm(event.data);
    await context.resume();
    microphoneDevices = (await navigator.mediaDevices.enumerateDevices()).filter(
      (item) => item.kind === "audioinput"
    );
    activeMicrophoneId = track.getSettings?.().deviceId || "";
    renderMicrophoneControl();
  }

  function closeCapture() {
    captureGeneration += 1;
    preRoll = [];
    preRollBytes = 0;
    queue = [];
    queuedBytes = 0;
    inFlightBytes = 0;
    pendingFinalize = false;
    pendingCancel = false;
    captureEnding = false;
    beginPending = false;
    deferredEnd = null;
    recoveringTurn = false;
    recovery = null;
    pendingFinal = null;
    document.dispatchEvent(new CustomEvent("tori:voicepartial", {detail: null}));
    try { worklet?.disconnect(); } catch (_error) {}
    try { source?.disconnect(); } catch (_error) {}
    try { silentGain?.disconnect(); } catch (_error) {}
    worklet = source = silentGain = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    if (context) context.close().catch(() => {});
    context = null;
  }

  function parseEventLine(line) {
    const event = JSON.parse(line);
    if (!event || typeof event !== "object" || typeof event.kind !== "string") {
      throw new Error("Voice Input returned an invalid event.");
    }
    return event;
  }

  async function consumeEvents(signal) {
    const response = await fetch("/api/voice-input/events", {
      method: "POST", headers: {"Content-Type": "application/json", "X-Tori-CSRF": ui.csrfToken},
      body: JSON.stringify(binding()), cache: "no-store", credentials: "same-origin", signal,
    });
    if (!response.ok || !response.body) throw new Error("Voice Input event stream is unavailable.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8", {fatal: true});
    let pending = "";
    try {
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        pending += decoder.decode(value, {stream: true});
        let newline;
        while ((newline = pending.indexOf("\n")) >= 0) {
          const line = pending.slice(0, newline); pending = pending.slice(newline + 1);
          if (line) await receiveEvent(parseEventLine(line));
        }
      }
    } finally { reader.releaseLock(); }
  }

  async function receiveEvent(event) {
    if (event.kind === "heartbeat") return;
    if (event.kind === "state") {
      adopt(event);
      updateStatus(event.state);
      if (event.state === "ready" && pendingFinal) {
        const final = pendingFinal; pendingFinal = null;
        // Conversation streaming must not block this controller's recognition
        // event reader; a later PTT final may need to cancel that exact stream.
        void admit(final);
      }
      return;
    }
    if (event.kind === "partial" && event.segment === owner?.segment) {
      document.dispatchEvent(new CustomEvent("tori:voicepartial", {detail: event}));
      return;
    }
    if (event.kind === "final") {
      document.dispatchEvent(new CustomEvent("tori:voicepartial", {detail: null}));
      pendingFinal = event;
      return;
    }
    if (event.kind === "no_speech") {
      document.dispatchEvent(new CustomEvent("tori:voicepartial", {detail: null}));
      updateStatus("ready", "Voice input: Ready — no speech detected");
    }
  }

  async function admit(event) {
    try {
      await window.ToriConversation.submitVoiceFinal({
        ...binding(), segment: event.segment, event_sequence: event.event_sequence, text: event.text,
      });
    } catch (error) {
      updateStatus("ready", "Voice input: Ready — transcript was not submitted");
      document.dispatchEvent(new CustomEvent("tori:voiceerror", {detail: error.message}));
    }
  }

  async function enable() {
    if (state !== "off" && state !== "error") return;
    updateStatus("preparing");
    try {
      owner = await request("acquire");
      const controller = new AbortController();
      eventsAbort = controller;
      consumeEvents(controller.signal).then(
        () => {
          if (!controller.signal.aborted && eventsAbort === controller) {
            void fail(new Error("Voice Input event stream ended unexpectedly."));
          }
        },
        (error) => {
          if (!controller.signal.aborted && eventsAbort === controller) void fail(error);
        }
      );
      await startCapture();
      heartbeat = window.setInterval(() => request("heartbeat", binding()).catch(fail), 2000);
      updateStatus("ready");
    } catch (error) {
      if (error?.code === "controller_busy") {
        owner = null;
        updateStatus("error", "Voice input: Active in another browser tab");
        document.dispatchEvent(new CustomEvent("tori:voiceerror", {detail: "Voice Input is active in another browser tab."}));
      } else {
        await fail(error);
      }
    }
  }

  async function disable() {
    const oldOwner = owner;
    closeCapture();
    if (heartbeat) window.clearInterval(heartbeat);
    heartbeat = null;
    eventsAbort?.abort(); eventsAbort = null;
    owner = null;
    if (oldOwner) {
      try {
        await ui.requestJson("/api/voice-input/release", {method: "POST", body: bindingFrom(oldOwner)});
      } catch (_error) { /* a closed event stream already safely revokes the lease */ }
    }
    updateStatus("off");
  }

  function bindingFrom(documentBody) {
    return {epoch: documentBody.epoch, lease: documentBody.lease,
      lease_generation: documentBody.lease_generation, revision: documentBody.revision};
  }

  function runtimeFailure(error) {
    return ["runtime_unavailable", "runtime_exited", "communication_failed", "startup_failed",
      "readiness_timeout", "finalization_timeout"].includes(error?.code);
  }

  async function fail(error, message = "Voice input: Unavailable — local speech runtime is not ready") {
    if (state === "off") return;
    closeCapture();
    if (heartbeat) window.clearInterval(heartbeat);
    heartbeat = null;
    eventsAbort?.abort(); eventsAbort = null;
    owner = null;
    updateStatus("error", message);
    document.dispatchEvent(new CustomEvent("tori:voiceerror", {detail: error?.message || "Voice Input failed."}));
  }

  async function begin() {
    if (state !== "ready" || beginPending ||
        window.ToriConversation?.canStartVoiceTurn?.() === false) return;
    beginPending = true;
    try {
      const coordination = await window.ToriConversation?.beginVoiceTurn?.();
      if (coordination === false) return;
      if (coordination?.discardPreRoll === true) {
        preRoll = [];
        preRollBytes = 0;
      }
      const next = await request("begin", {...binding(), sample_rate: context.sampleRate,
        channels: 1, encoding: "pcm_s16le"});
      const injectedPreRollBytes = preRollBytes;
      owner = next; sequence = 0; queue = preRoll; preRoll = [];
      queuedBytes = injectedPreRollBytes;
      preRollBytes = 0;
      captureEnding = false;
      pendingFinalize = false;
      pendingCancel = false;
      recoveringTurn = false;
      recovery = null;
      updateStatus("listening_ptt");
      flushAudio();
      if (deferredEnd) {
        const ending = deferredEnd;
        deferredEnd = null;
        await end(ending);
      }
    } catch (error) { await fail(error); }
    finally { beginPending = false; }
  }

  async function finalize() {
    if (state !== "listening_ptt") return;
    pendingFinalize = false;
    try {
      const next = await request("finalize", {...binding(true), last_sequence: sequence});
      owner = next;
      updateStatus("finalizing");
    } catch (error) { await fail(error); }
  }

  async function end({cancel = false} = {}) {
    if (state === "ready" && beginPending) {
      deferredEnd = {cancel};
      return;
    }
    if (state !== "listening_ptt") return;
    captureEnding = true;
    if (cancel) {
      pendingFinalize = false;
      pendingCancel = true;
      queue = [];
      queuedBytes = 0;
      if (!queueSending) await cancelTurn();
      return;
    }
    pendingFinalize = true;
    if (!queueSending && !queue.length) await finalize();
  }

  async function cancelTurn() {
    if (state !== "listening_ptt") return;
    pendingCancel = false;
    try {
      owner = await request("cancel", binding(true));
      captureEnding = false;
      updateStatus("ready");
    } catch (error) { await fail(error); }
  }

  async function recoverTurn(error, message) {
    if (recoveringTurn || state !== "listening_ptt" || !owner) return;
    recoveringTurn = true;
    captureEnding = true;
    pendingFinalize = false;
    pendingCancel = false;
    queue = [];
    queuedBytes = 0;
    recovery = {error, message};
    if (!queueSending) await completeTurnRecovery();
  }

  async function completeTurnRecovery() {
    if (!recoveringTurn || state !== "listening_ptt" || !owner) return;
    const problem = recovery;
    recovery = null;
    try {
      owner = await request("cancel", binding(true));
      captureEnding = false;
      updateStatus("ready", problem.message);
      document.dispatchEvent(new CustomEvent("tori:voiceerror", {
        detail: problem.error?.message || problem.message,
      }));
    } catch (cancelError) {
      await fail(cancelError);
    } finally {
      recoveringTurn = false;
    }
  }

  ptt.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    if (mode === "toggle") { state === "ready" ? begin() : end(); return; }
    ptt.setPointerCapture?.(event.pointerId); begin();
  });
  ptt.addEventListener("pointerup", (event) => { if (mode === "hold") end(); });
  ptt.addEventListener("pointercancel", () => { if (mode === "hold") end({cancel: true}); });
  status.addEventListener("click", () => {
    if (state === "off" || state === "error") enable();
    else if (state === "ready") disable();
  });
  window.addEventListener("blur", () => { if (state === "listening_ptt") end({cancel: true}); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" && state !== "off") disable();
  });
  window.addEventListener("beforeunload", () => closeCapture());
  document.addEventListener("tori:voiceinputtoggle", () => state === "off" || state === "error" ? enable() : disable());
  document.addEventListener("tori:voiceinputmode", (event) => {
    mode = event.detail?.mode === "toggle" ? "toggle" : "hold";
    savePreference(MODE_KEY, mode); updateStatus(state);
  });
  document.addEventListener("tori:conversationbusy", () => updateStatus(state));
  bindMicrophoneControl(document.getElementById("voice-microphone"));
  updateStatus("off");
  window.ToriVoiceInput = Object.freeze({bindMicrophoneControl, enable, disable, state: () => state,
    statusDetail: () => ({...statusDetail})});
}());
