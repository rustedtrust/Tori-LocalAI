"use strict";

(function initializeSecurityCenter() {
  const ui = window.ToriUI;
  const root = document.getElementById("view-security");
  const findingsNode = document.getElementById("security-findings");
  const watchNode = document.getElementById("security-watch");
  const feedback = document.getElementById("security-feedback");
  const lastRun = document.getElementById("security-last-run");
  const runButton = document.getElementById("security-run");
  let pending = false;
  let generation = 0;

  function button(label, action) {
    const item = ui.createElement("button", "button secondary", label);
    item.type = "button";
    item.addEventListener("click", action);
    return item;
  }

  function safeSource(url) {
    try {
      const value = new URL(url);
      if (value.protocol !== "https:" || value.username || value.password ||
          value.port || value.search || value.hash || value.href !== url) return null;
      const paths = {
        "ubuntu.com": /^\/security\/notices\/USN-\d+-\d+\/?$/,
        "www.nvidia.com": /^\/en-us\/security\/(?!archive\/?$)[a-zA-Z0-9._/-]{1,180}\/?$/,
        "nvidia.custhelp.com": /^\/app\/answers\/detail\/a_id\/[1-9]\d{2,6}\/~\/security-bulletin(?::|%3[Aa])[-a-z0-9]{1,140}\/?$/,
        "www.cisa.gov": /^\/(?:known-exploited-vulnerabilities-catalog|news-events\/(?:alerts|cybersecurity-advisories)\/(?:20\d\d\/(?:0[1-9]|1[0-2])\/(?:0[1-9]|[12]\d|3[01])\/)?[a-z0-9-]{1,180})\/?$/,
        "www.mozilla.org": /^\/en-US\/security\/advisories\/mfsa\d{4}-\d+\/?$/,
      };
      return paths[value.hostname]?.test(value.pathname) ? value.href : null;
    } catch (_error) {
      return null;
    }
  }

  function renderFinding(finding) {
    const card = ui.createElement("article", "record-card security-finding");
    const heading = ui.createElement("div", "security-section-heading");
    heading.append(ui.createElement("h3", "", finding.title),
      ui.createElement("span", "availability-badge", `${finding.relevance} · ${finding.state}`));
    card.append(heading, ui.createElement("p", "", finding.summary));
    const details = ui.createElement("div", "security-evidence");
    details.hidden = true;
    for (const [label, value] of [
      ["Finding", finding.id], ["Exploitation evidence", finding.exploitation],
      ["Environment Watch match", (finding.matched_watch || []).join(", ") || "None verified"],
      ["CVEs", (finding.cves || []).join(", ") || "None identified"],
      ["Observed", `${finding.first_observed} · latest ${finding.last_observed}`],
      ["Local evidence", "None; no external alert sources configured"],
    ]) details.append(ui.createElement("p", "record-meta", `${label}: ${value}`));
    const sources = ui.createElement("div", "security-sources");
    sources.append(ui.createElement("h4", "", "Primary evidence"));
    for (const source of finding.sources || []) {
      const safe = safeSource(source.url);
      const link = safe ? document.createElement("a") : ui.createElement("span", "", source.title);
      if (safe) {
        link.textContent = `${source.title} · ${source.evidence_level}`;
        link.href = safe;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      sources.append(link);
    }
    details.append(sources);
    const actions = ui.createElement("div", "record-actions");
    actions.append(button("Details", () => { details.hidden = !details.hidden; }));
    if (finding.state === "new") actions.append(button("Review", () => update(finding, "reviewed")));
    if (finding.state !== "dismissed") actions.append(button("Dismiss", () => update(finding, "dismissed")));
    actions.append(button("Discuss with Tori", () => discuss(finding)));
    card.append(details, actions);
    return card;
  }

  function render(state) {
    watchNode.replaceChildren(...(state.environment_watch || []).map((watch) =>
      ui.createElement("span", "availability-badge", watch.label)));
    runButton.disabled = pending || !state.security_research_enabled;
    const run = state.last_run;
    lastRun.textContent = run ? `Last Security research: ${run.state} · ${run.at}` :
      "No Security research run recorded.";
    const items = (state.findings || []).filter((item) => !["stale", "superseded"].includes(item.state));
    findingsNode.replaceChildren();
    for (const [name, selected] of [
      ["High-interest", items.filter((item) => item.relevance === "Relevant" && item.state === "new")],
      ["Watch", items.filter((item) => item.relevance === "Watch" && item.state === "new")],
      ["Recent", items.filter((item) => item.state !== "new" || item.relevance === "General")],
    ]) {
      if (!selected.length) continue;
      findingsNode.append(ui.createElement("h3", "security-group-label", name),
        ...selected.map(renderFinding));
    }
    if (!items.length) findingsNode.append(ui.createElement("p", "empty-state",
      "No Security intelligence findings yet. This does not describe local security conditions."));
    ui.setStatus(feedback, state.security_research_enabled ?
      "Security research is enabled in Night Owl. Findings are advisory only." :
      "Enable Security in Night Owl settings to research primary advisories.");
  }

  async function refresh() {
    const current = ++generation;
    try {
      const state = await ui.requestJson("/api/security");
      if (current === generation) render(state);
    } catch (_error) {
      if (current === generation) ui.setStatus(feedback, "Security intelligence is unavailable; no local status was inferred.", "warning");
    }
  }

  async function update(finding, action) {
    if (pending) return;
    pending = true;
    try {
      await ui.requestJson("/api/night-owl/findings/review", {method: "POST", body: {
        identifier: finding.id, expected_revision: finding.revision, action,
      }});
      document.dispatchEvent(new Event("tori:securitychanged"));
      await refresh();
    } catch (_error) {
      ui.setStatus(feedback, "That finding could not be changed; refresh and try again.", "warning");
    } finally { pending = false; }
  }

  async function discuss(finding) {
    if (pending) return;
    pending = true;
    try {
      await ui.requestJson("/api/security/discuss", {method: "POST", body: {
        identifier: finding.id, expected_revision: finding.revision,
      }});
      ui.navigate("conversation");
      const composer = document.getElementById("message");
      if (!composer.value.trim()) composer.value = "Let's discuss this security intelligence finding. What does the evidence establish, and what remains unverified?";
      composer.focus();
    } catch (_error) {
      ui.setStatus(feedback, "The finding changed or discussion context is unavailable.", "warning");
    } finally { pending = false; }
  }

  runButton.addEventListener("click", async () => {
    if (pending) return;
    pending = true;
    runButton.disabled = true;
    try {
      await ui.requestJson("/api/night-owl/run", {method: "POST", body: {}});
      ui.setStatus(feedback, "Night Owl is researching all enabled categories, including Security.", "busy");
      window.setTimeout(refresh, 1500);
    } catch (_error) {
      ui.setStatus(feedback, "Night Owl could not start; check its settings and current run.", "warning");
    } finally { pending = false; }
  });
  document.getElementById("security-refresh").addEventListener("click", refresh);
  document.getElementById("security-settings").addEventListener("click", () => ui.navigate("settings"));
  window.ToriViewModules.register({id: "security", mount: () => {
    refresh();
    return {refresh};
  }});
}());
