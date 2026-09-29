"use strict";

(function initializeSkillsManagement() {
  const ui = window.ToriUI;

  function element(name, className, text) {
    return ui.createElement(name, className || "", text);
  }

  function addFact(list, label, value) {
    const term = element("dt", "", label);
    const detail = element("dd", "", value === undefined || value === null ? "—" : value);
    list.append(term, detail);
  }

  function permissionList(permissions) {
    if (!permissions.length) return "None";
    return permissions.map((item) => item.kind).join(", ");
  }

  function privacyList(privacy) {
    const list = element("dl", "capability-privacy");
    for (const [label, key] of [
      ["Tori Memory access", "tori_memory"],
      ["Conversation-history access", "conversation_history"],
      ["Local filesystem access", "local_filesystem"],
      ["Internet", "internet"],
      ["Writes", "writes"],
      ["Background access", "background_access"],
      ["Secrets", "secrets"],
    ]) addFact(list, label, privacy[key]);
    return list;
  }

  function confirmationText(proposal) {
    return Object.entries(proposal || {}).map(([key, value]) => {
      const rendered = typeof value === "object" ? JSON.stringify(value) : String(value);
      return `${key}: ${rendered}`;
    }).join("\n");
  }

  function mount(root) {
    root.replaceChildren();
    const header = element("header", "view-header");
    const headingGroup = document.createElement("div");
    headingGroup.append(element("p", "eyebrow", "Local capability authority"));
    const heading = element("h1", "", "Skills & MCP");
    heading.id = "skills-mcp-heading";
    headingGroup.append(heading);
    const refresh = element("button", "button secondary", "Refresh");
    refresh.type = "button";
    header.append(headingGroup, refresh);
    const intro = element(
      "p", "view-intro",
      "Inspect lifecycle, provenance, permissions, network access, and approved MCP tools. Catalog and server text remain untrusted data."
    );
    const status = element("p", "status management-status", "Loading local capability state…");
    status.setAttribute("role", "status");
    const error = element("p", "error management-error");
    error.setAttribute("role", "alert");
    error.hidden = true;

    const growth = element("section", "capability-management-section capability-growth-section");
    const growthHeading = element("h2", "", "Capability Growth");
    const growthIntro = element(
      "p", "view-intro",
      "Application-owned operational evidence, known-good baselines, and advisory FIX / IMPROVE / EXPAND recommendations. This is separate from curated Memory."
    );
    const reviewControls = element("div", "record-actions capability-review-actions");
    const runReview = element("button", "button secondary", "Run Skills Review");
    runReview.type = "button";
    const reviewTopic = document.createElement("input");
    reviewTopic.id = "skills-review-topic";
    reviewTopic.maxLength = 200;
    reviewTopic.setAttribute("aria-label", "Skills Review capability topic");
    reviewTopic.placeholder = "Optional: Excel files, Discord, image generation…";
    const runDirectedReview = element("button", "button secondary", "Review topic");
    runDirectedReview.type = "button";
    reviewControls.append(runReview, reviewTopic, runDirectedReview);
    const inventorySummary = element("p", "status", "Capability inventory is loading…");
    const findingList = element("div", "record-list capability-growth-list");
    findingList.id = "capability-growth-findings";
    const recommendationList = element("div", "record-list capability-growth-list");
    recommendationList.id = "capability-growth-recommendations";
    const baselineList = element("div", "record-list capability-growth-list");
    baselineList.id = "capability-growth-baselines";
    const historyList = element("div", "record-list capability-growth-list");
    historyList.id = "capability-growth-history";
    const reviewList = element("div", "record-list capability-growth-list");
    reviewList.id = "capability-growth-reviews";
    growth.append(
      growthHeading, growthIntro, reviewControls, inventorySummary,
      element("h3", "", "Open findings"), findingList,
      element("h3", "", "Recommendations"), recommendationList,
      element("h3", "", "Known-good baselines"), baselineList,
      element("h3", "", "Resolved and dismissed history"), historyList,
      element("h3", "", "Recent Skills Reviews"), reviewList
    );

    const discovery = element("section", "capability-management-section");
    discovery.append(element("h2", "", "Find or add an Agent Skill"));
    const searchForm = element("form", "management-form surface-card capability-search-form");
    const searchLabel = element("label", "", "Search skills.sh");
    searchLabel.htmlFor = "skill-search-query";
    const searchInput = document.createElement("input");
    searchInput.id = "skill-search-query";
    searchInput.maxLength = 200;
    searchInput.required = true;
    searchInput.placeholder = "PDFs, documentation, image metadata…";
    const searchButton = element("button", "button secondary", "Search");
    searchButton.type = "submit";
    searchForm.append(searchLabel, searchInput, searchButton);
    const candidateList = element("div", "record-list");
    candidateList.id = "skill-discovery-results";

    const githubForm = element("form", "management-form surface-card capability-search-form");
    const githubLabel = element("label", "", "Public GitHub Agent Skill URL");
    githubLabel.htmlFor = "github-skill-url";
    const githubInput = document.createElement("input");
    githubInput.id = "github-skill-url";
    githubInput.type = "url";
    githubInput.maxLength = 4096;
    githubInput.required = true;
    githubInput.placeholder = "https://github.com/owner/repo/tree/revision/path/to/skill";
    const inspectButton = element("button", "button secondary", "Inspect safely");
    inspectButton.type = "submit";
    githubForm.append(githubLabel, githubInput, inspectButton);
    const inspectionResult = element("div", "record-list");
    inspectionResult.id = "github-skill-inspection";
    discovery.append(searchForm, candidateList, githubForm, inspectionResult);

    const skillsSection = element("section", "capability-management-section");
    skillsSection.append(element("h2", "", "Installed Skills"));
    const skillList = element("div", "record-list");
    skillList.id = "skills-management-list";
    skillsSection.append(skillList);

    const mcpSection = element("section", "capability-management-section");
    mcpSection.append(element("h2", "", "MCP servers"));
    const mcpList = element("div", "record-list");
    mcpList.id = "mcp-management-list";
    mcpSection.append(mcpList);

    const dialog = document.getElementById("skills-confirmation");
    const dialogMessage = document.getElementById("skills-confirmation-message");
    const dialogTarget = document.getElementById("skills-confirmation-target");
    const dialogConfirm = document.getElementById("skills-confirm");
    const dialogCancel = document.getElementById("skills-cancel");
    let pendingToken = null;

    root.append(header, intro, status, error, growth, discovery, skillsSection, mcpSection);

    function setBusy(value, message) {
      ui.setBusy(root, value);
      for (const control of root.querySelectorAll("button, input")) control.disabled = value;
      if (message) ui.setStatus(status, message);
    }

    function showError(message) {
      ui.showError(error, message || "");
    }

    function showConfirmation(value) {
      pendingToken = value.token;
      dialogMessage.textContent = value.message;
      dialogTarget.textContent = confirmationText(value.proposal);
      ui.openDialog(dialog, {returnFocus: document.activeElement, initialFocus: dialogCancel});
    }

    async function request(path, body) {
      showError("");
      return ui.requestJson(path, body === undefined ? {} : {method: "POST", body});
    }

    function renderSkill(skill) {
      const card = element("article", "record-card capability-record");
      const title = element("h3", "", skill.display_name);
      const badge = element("span", `capability-badge ${skill.enabled ? "enabled" : "disabled"}`, skill.state.replaceAll("_", " "));
      const facts = document.createElement("dl");
      addFact(facts, "Identity", skill.canonical_identity);
      addFact(facts, "Version", skill.version);
      addFact(facts, "Compatibility", skill.compatibility);
      addFact(facts, "Scope", skill.location_label);
      addFact(facts, "Access", skill.external_access_label);
      addFact(facts, "Requested permissions", permissionList(skill.requested_permissions));
      addFact(facts, "Granted permissions", permissionList(skill.granted_permissions));
      addFact(facts, "Components", skill.components.join(", ") || "None");
      addFact(facts, "Bundled scripts", skill.scripts_status);
      addFact(facts, "Health", skill.health);
      const details = document.createElement("details");
      details.append(element("summary", "", "Provenance and privacy"));
      const provenance = document.createElement("dl");
      addFact(provenance, "Source", skill.source.locator);
      addFact(provenance, "Pinned revision", skill.pinned_revision || "Local immutable package");
      addFact(provenance, "Digest", skill.digest);
      addFact(provenance, "Inspected", skill.inspected_at);
      details.append(provenance, privacyList(skill.privacy));
      const actions = element("div", "record-actions");
      if (skill.controls.enable) actions.append(actionButton("Enable", () => proposeSkill("enable", skill)));
      if (skill.controls.disable) actions.append(actionButton("Disable", () => proposeSkill("disable", skill)));
      const uninstall = actionButton(
        skill.controls.uninstall ? "Uninstall…" : "Uninstalled",
        () => proposeSkill("uninstall", skill)
      );
      uninstall.disabled = !skill.controls.uninstall;
      uninstall.title = skill.controls.uninstall_reason || "Removes only this exact managed package after confirmation; unrelated user data remains.";
      actions.append(uninstall);
      card.append(title, badge, facts, details, actions);
      return card;
    }

    function renderMcp(server) {
      const card = element("article", "record-card capability-record");
      card.append(element("h3", "", server.display_name || server.server_id));
      card.append(element("span", `capability-badge ${server.enabled ? "enabled" : "disabled"}`, server.enabled ? "enabled" : "disabled"));
      const facts = document.createElement("dl");
      addFact(facts, "Transport", server.transport_label);
      addFact(facts, "Running / ready", server.running ? "Yes" : `No (${server.process_state || "unknown"})`);
      addFact(facts, "Protocol", server.protocol_version || "Not negotiated");
      addFact(facts, "Server version", server.server_version);
      addFact(facts, "External access", server.external_access_label);
      addFact(facts, "Authority profile", server.read_write_classification);
      addFact(facts, "File read", server.access.file_read ? "Selected file only" : "No");
      addFact(facts, "File write", server.access.file_write ? "New approved output only" : "No");
      addFact(facts, "Process execution", server.access.process_execution ? "Exact approved executable" : "No");
      addFact(facts, "Secret use", server.access.secret_use || server.credential_required ? "Credential boundary only" : "No");
      addFact(facts, "Credential", server.credential_status);
      addFact(facts, "Discovered tools", server.tool_count);
      addFact(facts, "Permitted tools", server.permitted_tool_count);
      addFact(facts, "Discovered, unapproved", server.discovered_unapproved_tool_count);
      addFact(facts, "Schema drift", server.schema_drift_count ? `${server.schema_drift_count} tool(s)` : "None");
      addFact(facts, "Health", server.health);
      addFact(facts, "Last error", server.last_error || "None");
      card.append(facts);
      const details = document.createElement("details");
      details.append(element("summary", "", "Tools, provenance, and privacy"));
      const provenance = document.createElement("dl");
      addFact(provenance, "Executable", server.executable);
      addFact(provenance, "Executable digest", server.executable_digest);
      addFact(provenance, "Configuration digest", server.configuration_digest);
      addFact(provenance, "Sandbox", server.sandboxed ? "Bubblewrap" : "None");
      addFact(provenance, "Network", server.network_access ? "Enabled" : "Denied");
      addFact(provenance, "Read-only filesystem scope", server.filesystem_scope.length ? server.filesystem_scope.join(", ") : "None");
      details.append(provenance, privacyList(server.privacy));
      const tools = element("div", "mcp-tool-list");
      for (const tool of server.tools) {
        const item = element("article", "mcp-tool-record");
        item.append(element("h4", "", tool.name));
        item.append(element("p", "untrusted-description", `Untrusted server description: ${tool.description || "None supplied."}`));
        const toolFacts = document.createElement("dl");
        addFact(toolFacts, "State", tool.approved ? "Approved" : "Discovered — not approved");
        addFact(toolFacts, "Trusted classification", tool.classification);
        addFact(toolFacts, "Input fields", tool.input_fields.join(", ") || "None");
        addFact(toolFacts, "Required", tool.required_fields.join(", ") || "None");
        addFact(toolFacts, "Schema drift", tool.schema_drift ? "Reapproval required" : "No");
        item.append(toolFacts);
        tools.append(item);
      }
      if (!server.tools.length) tools.append(element("p", "empty-state", "No inspected tools."));
      details.append(tools);
      card.append(details);
      const actions = element("div", "record-actions");
      if (server.controls.enable) actions.append(actionButton("Enable", () => proposeMcp("enable", server)));
      if (server.controls.disable) actions.append(actionButton("Disable", () => proposeMcp("disable", server)));
      const unavailable = actionButton("Tool approvals unavailable", () => {});
      unavailable.disabled = true;
      unavailable.title = server.controls.unavailable_reason;
      actions.append(unavailable);
      card.append(actions);
      return card;
    }

    function renderFinding(finding) {
      const card = element("article", "record-card capability-record");
      card.append(element("span", `capability-badge lane-${finding.lane.toLowerCase()}`, finding.lane));
      card.append(element("h4", "", `${finding.capability_id} — ${finding.evidence_kind}`));
      const facts = document.createElement("dl");
      addFact(facts, "Area", finding.capability_area.replaceAll("_", " "));
      addFact(facts, "Verified count", finding.count);
      addFact(facts, "Priority", finding.priority);
      addFact(facts, "Severity", finding.severity);
      addFact(facts, "Operation", finding.operation_id);
      addFact(facts, "Component", `${finding.component.identifier} ${finding.component.version}`);
      addFact(facts, "Error code", finding.error_code || "None");
      addFact(facts, "Lifecycle", finding.status);
      card.append(facts);
      const actions = element("div", "record-actions");
      for (const next of finding.status === "open" ? ["monitoring", "resolved"] : ["open", "resolved"]) {
        actions.append(actionButton(next === "open" ? "Reopen" : `Mark ${next}`, () => updateGrowth("finding", finding, next)));
      }
      card.append(actions);
      return card;
    }

    function renderRecommendation(recommendation, historical) {
      const card = element("article", "record-card capability-record");
      card.append(element("span", `capability-badge lane-${recommendation.lane.toLowerCase()}`, recommendation.lane));
      card.append(element("h4", "", recommendation.title));
      card.append(element("p", "", recommendation.rationale));
      const facts = document.createElement("dl");
      addFact(facts, "Classification", recommendation.classification_label);
      addFact(facts, "Required authority", recommendation.required_authority.join(", "));
      addFact(facts, "Evidence", recommendation.evidence);
      addFact(facts, "Status", recommendation.status);
      if (recommendation.candidate) {
        addFact(facts, "Skill", recommendation.candidate.skill_id);
        addFact(facts, "Repository", recommendation.candidate.repository);
        addFact(facts, "Immutable commit", recommendation.candidate.commit || "Not inspected");
        addFact(facts, "Digest", recommendation.candidate.digest || "Not inspected");
      }
      card.append(facts);
      if (!historical) {
        const actions = element("div", "record-actions");
        if (recommendation.status === "open") {
          actions.append(actionButton("Mark accepted (advisory)", () => updateGrowth("recommendation", recommendation, "accepted")));
          actions.append(actionButton("Dismiss", () => updateGrowth("recommendation", recommendation, "dismissed")));
        }
        actions.append(actionButton("Resolve", () => updateGrowth("recommendation", recommendation, "resolved")));
        card.append(actions);
      }
      return card;
    }

    function renderGrowth(state) {
      if (!state.available) {
        inventorySummary.textContent = state.message;
        for (const list of [findingList, recommendationList, baselineList, historyList, reviewList]) {
          list.replaceChildren(element("p", "empty-state", state.message));
        }
        return;
      }
      const counts = state.inventory.counts;
      inventorySummary.textContent = `Current application inventory: ${counts.native} native, ${counts.skills} Skill, and ${counts.mcp} MCP entries. Model claims are not inventory evidence.`;
      findingList.replaceChildren(...state.findings.map(renderFinding));
      if (!state.findings.length) findingList.append(element("p", "empty-state", "No open findings."));
      recommendationList.replaceChildren(...state.recommendations.map((item) => renderRecommendation(item, false)));
      if (!state.recommendations.length) recommendationList.append(element("p", "empty-state", "No open recommendations."));
      baselineList.replaceChildren(...state.baselines.map((baseline) => {
        const card = element("article", "record-card");
        card.append(element("h4", "", `${baseline.capability_id} / ${baseline.operation_id}`));
        card.append(element("p", "", `${baseline.verified_successes} verified successes, ${baseline.recent_failures} recent failures.`));
        return card;
      }));
      if (!state.baselines.length) baselineList.append(element("p", "empty-state", "No verified success baseline yet."));
      historyList.replaceChildren(...state.history.map((item) => renderRecommendation(item, true)));
      if (!state.history.length) historyList.append(element("p", "empty-state", "No resolved or dismissed recommendations."));
      reviewList.replaceChildren(...state.reviews.map((review) => {
        const card = element("article", "record-card");
        card.append(element("h4", "", `${review.scope.replaceAll("_", " ")} — ${review.status}`));
        card.append(element("p", "", `${review.searches} searches · ${review.candidates} candidates · ${review.inspections} inspection attempts · ${review.recommendation_count} recommendations`));
        return card;
      }));
      if (!state.reviews.length) reviewList.append(element("p", "empty-state", "No Skills Review has run yet."));
    }

    function actionButton(label, handler) {
      const button = element("button", "button secondary mutation", label);
      button.type = "button";
      button.addEventListener("click", handler);
      return button;
    }

    async function load() {
      setBusy(true, "Refreshing application-owned capability state…");
      try {
        const [skills, mcp, growthState] = await Promise.all([
          request("/api/skills"), request("/api/mcp"), request("/api/capability-growth")
        ]);
        skillList.replaceChildren(...skills.skills.map(renderSkill));
        if (!skills.skills.length) skillList.append(element("p", "empty-state", skills.message || "No Skills are installed."));
        mcpList.replaceChildren(...mcp.servers.map(renderMcp));
        if (!mcp.servers.length) mcpList.append(element("p", "empty-state", mcp.message || "No MCP servers are configured."));
        renderGrowth(growthState);
        ui.setStatus(status, "Skills and MCP authority state is current.", "success");
      } catch (failure) {
        showError(failure.message);
        ui.setStatus(status, "Capability state could not be loaded.");
      } finally {
        setBusy(false);
      }
    }

    async function proposeSkill(action, skill) {
      setBusy(true, `Preparing exact Skill ${action} proposal…`);
      try {
        const result = await request("/api/skills/lifecycle", {
          action, skill_id: skill.canonical_identity, version: skill.version,
          digest: skill.digest, expected_revision: skill.revision,
        });
        showConfirmation(result.confirmation);
      } catch (failure) { showError(failure.message); }
      finally { setBusy(false); }
    }

    async function proposeMcp(action, server) {
      setBusy(true, `Preparing exact MCP ${action} proposal…`);
      try {
        const result = await request("/api/mcp/lifecycle", {action, server_id: server.server_id});
        showConfirmation(result.confirmation);
      } catch (failure) { showError(failure.message); }
      finally { setBusy(false); }
    }

    async function updateGrowth(kind, item, nextStatus) {
      setBusy(true, "Updating advisory lifecycle state…");
      try {
        const result = await request("/api/capability-growth/lifecycle", {
          kind, identifier: item.identifier, status: nextStatus,
          expected_revision: item.revision,
        });
        renderGrowth(result.state);
        ui.setStatus(status, "Capability Growth lifecycle state updated.", "success");
      } catch (failure) { showError(failure.message); }
      finally { setBusy(false); }
    }

    async function runSkillsReview(scope, topic) {
      setBusy(true, "Running bounded read-only Skills Review…");
      try {
        const result = await request("/api/capability-growth/review", {scope, topic});
        renderGrowth(result.state);
        ui.setStatus(status, `Skills Review ${result.review.status}: ${result.inspection_attempts} immutable inspection attempts; ${result.successful_inspections} successful, ${result.failed_inspections} failed; nothing was installed, enabled, granted, or executed.`, "success");
      } catch (failure) { showError(failure.message); }
      finally { setBusy(false); }
    }

    function renderInspection(inspection) {
      inspectionResult.replaceChildren();
      const card = element("article", "record-card capability-record");
      card.append(element("h3", "", inspection.name));
      const facts = document.createElement("dl");
      addFact(facts, "Repository", inspection.repository);
      addFact(facts, "Exact commit", inspection.commit);
      addFact(facts, "Package path", inspection.package_path);
      addFact(facts, "Version", inspection.version);
      addFact(facts, "Compatibility", inspection.compatibility);
      addFact(facts, "Digest", inspection.digest);
      addFact(facts, "License", inspection.license || "Not declared");
      addFact(facts, "Requested permissions", permissionList(inspection.requested_permissions));
      addFact(facts, "Components", Object.entries(inspection.inventory).map(([key, count]) => `${key}: ${count}`).join(", "));
      addFact(facts, "Risks", inspection.risk_notes.join(" · ") || "No additional findings");
      const propose = actionButton("Review installation", async () => {
        setBusy(true, "Reacquiring and binding exact bytes for an installation proposal…");
        try {
          const result = await request("/api/skills/github/propose-install", {url: githubInput.value});
          showConfirmation(result.confirmation);
        } catch (failure) { showError(failure.message); }
        finally { setBusy(false); }
      });
      card.append(facts, propose);
      inspectionResult.append(card);
    }

    searchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      setBusy(true, "Searching untrusted skills.sh discovery metadata…");
      try {
        const result = await request("/api/skills/search", {query: searchInput.value});
        candidateList.replaceChildren();
        for (const candidate of result.candidates) {
          const card = element("article", "record-card");
          card.append(element("h3", "", candidate.name));
          card.append(element("p", "untrusted-description", `Untrusted catalog description: ${candidate.description || "None supplied."}`));
          const facts = document.createElement("dl");
          addFact(facts, "Upstream", candidate.source);
          addFact(facts, "Skill path", candidate.skill_path);
          addFact(facts, "Catalog installs", candidate.installs);
          addFact(facts, "Path mapping", candidate.path_mapping);
          const choose = actionButton("Inspect through GitHub", async () => {
            githubInput.value = candidate.github_source_input;
            githubForm.requestSubmit();
          });
          card.append(facts, choose);
          candidateList.append(card);
        }
        if (!result.candidates.length) candidateList.append(element("p", "empty-state", "No compatible GitHub candidates returned."));
        ui.setStatus(status, "Discovery results are untrusted candidates; nothing was installed.", "success");
      } catch (failure) { showError(failure.message); }
      finally { setBusy(false); }
    });

    githubForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      setBusy(true, "Resolving an immutable commit and inspecting quarantined bytes…");
      try {
        const result = await request("/api/skills/github/inspect", {url: githubInput.value});
        renderInspection(result.inspection);
        ui.setStatus(status, "Inspection complete. Nothing was installed or enabled.", "success");
      } catch (failure) { showError(failure.message); inspectionResult.replaceChildren(); }
      finally { setBusy(false); }
    });

    async function decide(decision) {
      const token = pendingToken;
      pendingToken = null;
      ui.closeDialog(dialog);
      if (!token) return;
      setBusy(true, decision === "confirm" ? "Applying the confirmed local change…" : "Cancelling…");
      try {
        const result = await request("/api/confirm", {token, decision});
        if (result.confirmation) showConfirmation(result.confirmation);
        await load();
      } catch (failure) { showError(failure.message); }
      finally { setBusy(false); }
    }

    const confirmDecision = () => decide("confirm");
    const cancelDecision = () => decide("cancel");
    const cancelDialog = (event) => { event.preventDefault(); decide("cancel"); };
    dialogConfirm.addEventListener("click", confirmDecision);
    dialogCancel.addEventListener("click", cancelDecision);
    dialog.addEventListener("cancel", cancelDialog);
    refresh.addEventListener("click", load);
    runReview.addEventListener("click", () => runSkillsReview("general", ""));
    runDirectedReview.addEventListener("click", () => {
      if (!reviewTopic.value.trim()) {
        showError("Enter a specific capability topic first.");
        reviewTopic.focus();
        return;
      }
      runSkillsReview("user_directed", reviewTopic.value);
    });

    load();
    return {refresh: load, unmount() {
      pendingToken = null;
      dialogConfirm.removeEventListener("click", confirmDecision);
      dialogCancel.removeEventListener("click", cancelDecision);
      dialog.removeEventListener("cancel", cancelDialog);
    }};
  }

  window.ToriViewModules.register({id: "skills-mcp", mount});
}());
