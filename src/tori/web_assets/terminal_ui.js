"use strict";

(function initializeTerminal() {
  const byId = (id) => document.getElementById(id);
  const drawer = byId("terminal-drawer");
  if (!drawer) return;
  const toggle = byId("terminal-toggle");
  const body = byId("terminal-body");
  const unavailable = byId("terminal-unavailable");
  const selector = byId("terminal-sessions");
  const status = byId("terminal-status");
  const meta = byId("terminal-meta");
  const notice = byId("terminal-control-notice");
  const viewport = byId("terminal-viewport");
  const requestForm = byId("terminal-request-form");
  const commandInput = byId("terminal-command");
  const cwdInput = byId("terminal-cwd");
  const scopeInput = byId("terminal-scope");
  const requestButton = byId("terminal-request");
  const requestFeedback = byId("terminal-request-feedback");
  const approvalDialog = byId("terminal-approval-dialog");
  const approvalDetails = byId("terminal-approval-details");
  const approveOnce = byId("terminal-approve-once");
  const whitelistExact = byId("terminal-whitelist-exact");
  const cancelApproval = byId("terminal-cancel-approval");
  const expand = byId("terminal-expand");
  const minimize = byId("terminal-minimize");
  const take = byId("terminal-take-control");
  const release = byId("terminal-release-control");
  const enterPrivate = byId("terminal-enter-private");
  const exitPrivate = byId("terminal-exit-private");
  const interrupt = byId("terminal-interrupt");
  const terminate = byId("terminal-terminate");
  const kill = byId("terminal-force-kill");
  const csrf = document.querySelector('meta[name="tori-csrf"]')?.content || "";
  const terminal = new window.Terminal({
    cursorBlink: true, scrollback: 4000, convertEol: false,
    theme: { background: "#090b0e", foreground: "#f4f0e9", cursor: "#48a8ff" },
  });
  const fitAddon = new window.FitAddon.FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(viewport);

  let available = false;
  let sessions = [];
  let selected = null;
  let socket = null;
  let attached = false;
  let humanControl = false;
  let privateInput = false;
  let modelCaptureLocked = false;
  let generation = 0;
  let retryTimer = null;
  let resizeTimer = null;
  let minimized = false;
  let proposalToken = null;
  let proposalBusy = false;

  function showStatus(label) { status.textContent = label; }
  function selectedSession() { return sessions.find((item) => item.id === selected) || null; }
  function render() {
    const session = selectedSession();
    const running = Boolean(session && session.state === "running");
    const connected = Boolean(socket && socket.readyState === WebSocket.OPEN && attached);
    body.hidden = !available;
    unavailable.hidden = available;
    selector.disabled = !available || sessions.length === 0;
    requestButton.disabled = !available || proposalBusy;
    meta.textContent = session ? `${session.scope} · ${session.cwd} · Tori launched · ${session.id}` : "No terminal session yet.";
    if (session && session.state === "exited") {
      showStatus(`${session.scope} · ${session.termination_reason || "Exited"} · exit ${session.exit_code ?? "unknown"}`);
    } else if (!session) {
      showStatus(available ? "No session" : "Local only");
    } else if (!connected) {
      showStatus("Disconnected · reconnecting");
    } else {
      showStatus(humanControl ? "Running · You have control" : "Running · Observe only");
    }
    take.hidden = humanControl;
    release.hidden = !humanControl;
    take.disabled = !connected || !running;
    release.disabled = !connected || !running;
    enterPrivate.hidden = privateInput;
    exitPrivate.hidden = !privateInput;
    enterPrivate.disabled = !connected || !humanControl || !running;
    exitPrivate.disabled = !connected || !humanControl || !running;
    for (const button of [interrupt, terminate, kill]) button.disabled = !connected || !running;
    notice.textContent = privateInput
      ? (humanControl ? "Private Input active. Terminal output is withheld from Tori."
        : "Private Input remains active. Take Control again to end it deliberately.")
      : modelCaptureLocked
        ? "Private Input ended. Tori will not read further output from this process."
        : (humanControl ? "You have control. Use Private Input before entering sensitive text. After use, Tori will not read further output from this process."
          : "Observe only. Human keyboard input is disabled until you take control.");
    toggle.setAttribute("aria-expanded", String(!drawer.hidden));
    expand.textContent = drawer.classList.contains("is-expanded") ? "Collapse" : "Expand";
    expand.setAttribute("aria-label", expand.textContent + " terminal");
  }
  function fit() {
    if (drawer.hidden || minimized || !available) return;
    try {
      fitAddon.fit();
      if (selectedSession()?.state === "running" && attached && socket?.readyState === WebSocket.OPEN
          && terminal.rows >= 2 && terminal.rows <= 200
          && terminal.cols >= 2 && terminal.cols <= 400) {
        socket.send(JSON.stringify({v: 1, type: "resize", rows: terminal.rows, columns: terminal.cols}));
      }
    } catch (_) { /* A hidden or zero-size container is retried on open. */ }
  }
  function scheduleFit() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(fit, 100);
  }
  function sendControl(type) {
    if (attached && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({v: 1, type}));
  }
  function detach() {
    generation += 1;
    clearTimeout(retryTimer);
    attached = false;
    humanControl = false;
    const previous = socket;
    socket = null;
    if (previous) previous.close();
    render();
  }
  function populateSessions() {
    const previous = selected;
    selector.replaceChildren();
    for (const session of sessions) {
      const option = document.createElement("option");
      option.value = session.id;
      option.textContent = `${session.id.slice(-8)} · ${session.state} · ${session.scope}`;
      selector.append(option);
    }
    if (!sessions.some((item) => item.id === selected)) {
      // After a browser reload, prefer the newest process still running.
      // An older completed session may remain in the selector for review.
      const running = sessions.filter((item) => item.state === "running");
      const candidates = running.length ? running : sessions;
      selected = candidates.reduce((latest, item) =>
        !latest || item.started_at > latest.started_at ? item : latest, null)?.id || null;
    }
    selector.value = selected || "";
    if (selected !== previous) {
      detach();
      privateInput = false;
      modelCaptureLocked = false;
      terminal.reset();
      if (selectedSession()?.state === "running") void attach();
    }
    render();
  }
  async function refreshSessions() {
    if (!available) return;
    try {
      const response = await fetch("/api/terminal/sessions", {credentials: "same-origin", cache: "no-store"});
      if (!response.ok) throw new Error("Session discovery unavailable");
      const data = await response.json();
      if (!Array.isArray(data.sessions)) throw new Error("Invalid session list");
      if (JSON.stringify(data.sessions) === JSON.stringify(sessions)) return;
      sessions = data.sessions;
      if (selectedSession()?.state === "exited") {
        clearTimeout(retryTimer);
        humanControl = false;
      }
      populateSessions();
    } catch (_) {
      if (selected) showStatus("Disconnected · session discovery unavailable");
    }
  }
  async function terminalPost(path, document) {
    const response = await fetch(path, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: {"Content-Type": "application/json", "X-Tori-CSRF": csrf},
      body: JSON.stringify(document),
    });
    if (!response.ok) throw new Error("Terminal request was denied or unavailable.");
    return response.json();
  }
  async function showLaunched(id) {
    detach();
    selected = id;
    await refreshSessions();
    if (selected === id) {
      selector.value = id;
      void attach({allowExited: true});
      render();
      scheduleFit();
    }
  }
  function retry(expectedGeneration) {
    if (expectedGeneration !== generation || selectedSession()?.state !== "running" || !available) return;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(async () => {
      if (expectedGeneration !== generation || selectedSession()?.state !== "running") return;
      await refreshSessions();
      if (expectedGeneration === generation && selectedSession()?.state === "running") void attach();
    }, 1200);
  }
  async function attach({allowExited = false} = {}) {
    if (!selected || !available || (!allowExited && selectedSession()?.state !== "running")) return;
    const id = selected;
    const attempt = ++generation;
    attached = false;
    humanControl = false;
    render();
    let ticket = null;
    try {
      const response = await fetch("/api/terminal/attach-ticket", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: {"Content-Type": "application/json", "X-Tori-CSRF": csrf},
        body: JSON.stringify({session_id: id}),
      });
      if (!response.ok) throw new Error("Attach ticket unavailable");
      ticket = (await response.json()).ticket;
      if (typeof ticket !== "string" || attempt !== generation || selected !== id) return;
      if (!allowExited && selectedSession()?.state !== "running") return;
      const ws = new WebSocket(`ws://${location.host}/api/terminal/ws/${encodeURIComponent(id)}`);
      ws.binaryType = "arraybuffer";
      socket = ws;
      ws.onopen = () => {
        if (attempt !== generation) { ws.close(); return; }
        ws.send(JSON.stringify({v: 1, type: "attach", ticket}));
        ticket = null;
      };
      ws.onmessage = (event) => {
        if (attempt !== generation) return;
        if (event.data instanceof ArrayBuffer) {
          if (attached) terminal.write(new Uint8Array(event.data));
          return;
        }
        let message;
        try { message = JSON.parse(event.data); } catch (_) { ws.close(); return; }
        if (message.v !== 1) { ws.close(); return; }
        if (message.type === "ready") {
          // Repaint the bounded snapshot from a clean viewport. This avoids
          // duplicate text after refresh without storing a raw transcript.
          terminal.reset();
          attached = true;
          humanControl = false;
          privateInput = message.session.private_input === true;
          modelCaptureLocked = message.session.model_capture_locked === true;
          const index = sessions.findIndex((item) => item.id === id);
          if (index >= 0) sessions[index] = message.session;
          render();
          scheduleFit();
        } else if (message.type === "state") {
          humanControl = message.human_control === true;
          privateInput = message.private_input === true;
          modelCaptureLocked = message.model_capture_locked === true;
          render();
          if (humanControl) terminal.focus();
        } else if (message.type === "exit") {
          const index = sessions.findIndex((item) => item.id === id);
          const unchanged = index >= 0 && JSON.stringify(sessions[index]) === JSON.stringify(message.session);
          if (index >= 0) sessions[index] = message.session;
          humanControl = false;
          privateInput = message.session.private_input === true;
          modelCaptureLocked = message.session.model_capture_locked === true;
          clearTimeout(retryTimer);
          if (!unchanged) render();
        } else if (message.type === "superseded" || message.type === "error") {
          ws.close();
        }
      };
      ws.onclose = () => {
        if (attempt !== generation) return;
        attached = false;
        humanControl = false;
        socket = null;
        if (selectedSession()?.state === "running") render();
        retry(attempt);
      };
      ws.onerror = () => ws.close();
    } catch (_) {
      ticket = null;
      if (attempt === generation) retry(attempt);
    }
  }

  terminal.onData((data) => {
    if (!humanControl || !attached || socket?.readyState !== WebSocket.OPEN) return;
    const bytes = new TextEncoder().encode(data);
    for (let offset = 0; offset < bytes.length; offset += 4096) {
      socket.send(bytes.slice(offset, offset + 4096));
    }
  });
  toggle.addEventListener("click", () => {
    drawer.hidden = !drawer.hidden;
    minimized = drawer.hidden;
    body.hidden = !available;
    render();
    scheduleFit();
  });
  minimize.addEventListener("click", () => {
    minimized = true;
    drawer.hidden = true;
    render();
  });
  expand.addEventListener("click", () => {
    drawer.classList.toggle("is-expanded");
    render();
    scheduleFit();
  });
  selector.addEventListener("change", () => {
    detach();
    selected = selector.value;
    privateInput = false;
    modelCaptureLocked = false;
    terminal.reset();
    if (selected) void attach({allowExited: true});
  });
  async function handleTerminalRequest(result) {
    if (!minimized) drawer.hidden = false;
    if (result.policy === "BLACKLIST") {
      requestFeedback.textContent = `Blocked by policy: ${result.reason}`;
    } else if (result.session_id) {
      requestFeedback.textContent = "Whitelisted command started.";
      await showLaunched(result.session_id);
    } else if (result.proposal_token) {
      proposalToken = result.proposal_token;
      whitelistExact.hidden = result.policy !== "DEFAULT_ASK";
      approvalDetails.textContent = `Command: ${result.command}\nCwd: ${result.cwd}\nScope: ${result.scope}\nPolicy: ${result.policy}\nRule: ${result.rule_id || "default"}\nReason: ${result.reason}`;
      approvalDialog.showModal();
      requestFeedback.textContent = "Approval required for this execution.";
    }
    render();
    scheduleFit();
  }
  requestForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!available || proposalBusy) return;
    drawer.hidden = false;
    minimized = false;
    proposalBusy = true;
    requestFeedback.textContent = "Checking execution policy…";
    render();
    try {
      const result = await terminalPost("/api/terminal/request", {
        command: commandInput.value.trim(), cwd: cwdInput.value.trim(), scope: scopeInput.value,
      });
      await handleTerminalRequest(result);
    } catch (_) {
      requestFeedback.textContent = "The terminal request could not be prepared or started.";
    } finally {
      proposalBusy = false;
      render();
    }
  });
  approveOnce.addEventListener("click", async () => {
    if (!proposalToken || proposalBusy) return;
    const token = proposalToken;
    proposalToken = null;
    proposalBusy = true;
    approvalDialog.close();
    drawer.hidden = false;
    minimized = false;
    render();
    try {
      const result = await terminalPost("/api/terminal/decide", {proposal_token: token, decision: "approve"});
      requestFeedback.textContent = "Approved terminal command started.";
      await showLaunched(result.session_id);
    } catch (_) {
      requestFeedback.textContent = "The one-use approval expired or the command could not start.";
    } finally {
      proposalBusy = false;
      render();
    }
  });
  whitelistExact.addEventListener("click", async () => {
    if (!proposalToken || proposalBusy || whitelistExact.hidden) return;
    const token = proposalToken;
    proposalToken = null;
    proposalBusy = true;
    approvalDialog.close();
    drawer.hidden = false;
    minimized = false;
    render();
    try {
      const result = await terminalPost("/api/terminal/decide", {proposal_token: token, decision: "whitelist"});
      requestFeedback.textContent = "Exact command whitelisted and started.";
      await showLaunched(result.session_id);
    } catch (_) { requestFeedback.textContent = "The exact whitelist decision was denied or expired."; }
    finally { proposalBusy = false; render(); }
  });
  cancelApproval.addEventListener("click", async () => {
    const token = proposalToken;
    proposalToken = null;
    approvalDialog.close();
    requestFeedback.textContent = "Terminal execution cancelled.";
    if (token) {
      try { await terminalPost("/api/terminal/decide", {proposal_token: token, decision: "cancel"}); }
      catch (_) { /* Expiry also prevents execution. */ }
    }
  });
  approvalDialog.addEventListener("close", () => { proposalToken = null; });
  take.addEventListener("click", () => sendControl("take_control"));
  release.addEventListener("click", () => sendControl("release_control"));
  enterPrivate.addEventListener("click", () => sendControl("enter_private"));
  exitPrivate.addEventListener("click", () => sendControl("exit_private"));
  interrupt.addEventListener("click", () => sendControl("interrupt"));
  terminate.addEventListener("click", () => sendControl("terminate"));
  kill.addEventListener("click", () => {
    if (window.confirm("Force kill this terminal process and its process group?")) sendControl("force_kill");
  });
  new ResizeObserver(scheduleFit).observe(viewport);
  window.addEventListener("resize", scheduleFit);
  document.addEventListener("tori:conversationchanged", () => {
    detach();
    selected = null;
    sessions = [];
    privateInput = false;
    modelCaptureLocked = false;
    terminal.reset();
    populateSessions();
    void refreshSessions();
  });
  document.addEventListener("tori:terminalrequest", (event) => {
    if (available && event.detail) void handleTerminalRequest(event.detail);
  });
  render();
  void (async () => {
    try {
      const response = await fetch("/api/terminal/availability", {credentials: "same-origin", cache: "no-store"});
      available = response.ok && (await response.json()).available === true;
    } catch (_) { available = false; }
    render();
    if (available) {
      await refreshSessions();
      setInterval(refreshSessions, 3000);
    }
  })();
})();
