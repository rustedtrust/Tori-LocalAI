"use strict";

(function initializeTerminalPolicy() {
  const byId = (id) => document.getElementById(id);
  const root = byId("terminal-policy-settings");
  if (!root) return;
  const unavailable = byId("terminal-policy-unavailable");
  const body = byId("terminal-policy-body");
  const form = byId("terminal-policy-form");
  const identifier = byId("terminal-policy-id");
  const command = byId("terminal-policy-command");
  const cwd = byId("terminal-policy-cwd");
  const scope = byId("terminal-policy-scope");
  const policyClass = byId("terminal-policy-class");
  const enabled = byId("terminal-policy-enabled");
  const save = byId("terminal-policy-save");
  const feedback = byId("terminal-policy-feedback");
  const list = byId("terminal-policy-rules");
  const csrf = document.querySelector('meta[name="tori-csrf"]')?.content || "";

  async function post(action, payload) {
    const response = await fetch(`/api/terminal/policy/${action}`, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: {"Content-Type": "application/json", "X-Tori-CSRF": csrf},
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error("Policy change denied. Check the exact rule and any Always Ask conflict.");
  }
  function reset() {
    identifier.value = "";
    command.value = "";
    policyClass.value = "WHITELIST";
    enabled.checked = true;
    save.textContent = "Add exact rule";
  }
  function edit(rule) {
    identifier.value = rule.id;
    command.value = rule.matcher.command;
    cwd.value = rule.matcher.cwd;
    scope.value = rule.matcher.scope;
    policyClass.value = rule.class;
    enabled.checked = rule.enabled;
    save.textContent = "Update exact rule";
    command.focus();
  }
  async function refresh() {
    const response = await fetch("/api/terminal/policy", {credentials: "same-origin", cache: "no-store"});
    if (!response.ok) throw new Error("Terminal policy is unavailable.");
    const policyDocument = await response.json();
    list.replaceChildren();
    for (const rule of policyDocument.rules) {
      const article = document.createElement("article");
      article.className = "terminal-policy-rule";
      const description = document.createElement("p");
      description.textContent = `${rule.class} · ${rule.enabled ? "Enabled" : "Disabled"} · ${rule.matcher.command} · ${rule.matcher.cwd} · ${rule.matcher.scope} · ${rule.source}`;
      article.append(description);
      if (rule.source === "user") {
        const editButton = document.createElement("button");
        editButton.type = "button";
        editButton.className = "button secondary";
        editButton.textContent = "Edit";
        editButton.setAttribute("aria-label", `Edit ${rule.class} rule`);
        editButton.addEventListener("click", () => edit(rule));
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "button danger";
        removeButton.textContent = "Remove";
        removeButton.setAttribute("aria-label", `Remove ${rule.class} rule`);
        removeButton.addEventListener("click", async () => {
          if (!window.confirm("Remove this exact terminal rule?")) return;
          try { await post("remove", {id: rule.id}); feedback.textContent = "Rule removed."; await refresh(); }
          catch (error) { feedback.textContent = error.message; }
        });
        article.append(editButton, removeButton);
      }
      list.append(article);
    }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const updating = Boolean(identifier.value);
    const payload = {command: command.value, cwd: cwd.value, scope: scope.value,
      class: policyClass.value, enabled: enabled.checked};
    if (updating) payload.id = identifier.value;
    save.disabled = true;
    try {
      await post(updating ? "update" : "create", payload);
      feedback.textContent = updating ? "Exact rule updated." : "Exact rule added.";
      reset();
      await refresh();
    } catch (error) { feedback.textContent = error.message; }
    finally { save.disabled = false; }
  });
  byId("terminal-policy-reset").addEventListener("click", reset);
  // Settings is a client-side view: the script runs at page load, often
  // before a rule is added from Conversation. Refresh on each visit.
  document.addEventListener("tori:viewchange", (event) => {
    if (event.detail?.view !== "settings" || body.hidden) return;
    void refresh().catch(() => { feedback.textContent = "Terminal policy could not be refreshed."; });
  });
  void (async () => {
    try {
      const response = await fetch("/api/terminal/availability", {credentials: "same-origin", cache: "no-store"});
      const available = response.ok && (await response.json()).available === true;
      unavailable.hidden = available;
      body.hidden = !available;
      if (available) await refresh();
    } catch (_) { unavailable.hidden = false; body.hidden = true; }
  })();
})();
