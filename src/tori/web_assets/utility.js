"use strict";

(function initializeUtilityRail() {
  const root = document.querySelector('[data-utility-module-root="overview"]');
  if (!root) return;

  const statusCard = root.querySelector("#utility-status-card");
  const statusLabel = root.querySelector("#utility-status-label");
  const statusDetail = root.querySelector("#utility-status-detail");
  const hostCpu = root.querySelector("#utility-host-cpu");
  const hostMemory = root.querySelector("#utility-host-memory");
  const hostGpu = root.querySelector("#utility-host-gpu");
  const hostVram = root.querySelector("#utility-host-vram");
  const hostVramRow = root.querySelector("#utility-host-vram-row");
  const hostFreshness = root.querySelector("#utility-host-freshness");
  let hostStaleTimer = null;
  const codingWorkCard = root.querySelector("#utility-coding-work-card");
  const codingWorkLabel = root.querySelector("#utility-coding-work-label");
  const codingWorkState = root.querySelector("#utility-coding-work-state");
  const codingWorkOverview = root.querySelector("#utility-coding-work-overview");
  const codingWorkLatest = root.querySelector("#utility-coding-work-latest");
  const codingWorkWorkspace = root.querySelector("#utility-coding-work-workspace");
  const codingWorkUpdated = root.querySelector("#utility-coding-work-updated");
  const codingWorkObjective = root.querySelector("#utility-coding-work-objective");
  const codingWorkAuthority = root.querySelector("#utility-coding-work-authority");
  const codingWorkAcceptance = root.querySelector("#utility-coding-work-acceptance");
  const codingWorkRelatedRow = root.querySelector("#utility-coding-work-related-row");
  const codingWorkRelated = root.querySelector("#utility-coding-work-related");
  const codingWorkPaths = root.querySelector("#utility-coding-work-paths");
  const codingWorkPathsEmpty = root.querySelector("#utility-coding-work-paths-empty");
  const codingWorkActivity = root.querySelector("#utility-coding-work-activity");
  const codingWorkActivityEmpty = root.querySelector("#utility-coding-work-activity-empty");
  const codingWorkVerification = root.querySelector("#utility-coding-work-verification");
  const codingWorkVerificationEmpty = root.querySelector("#utility-coding-work-verification-empty");
  const codingWorkResultGroup = root.querySelector("#utility-coding-work-result-group");
  const codingWorkResult = root.querySelector("#utility-coding-work-result");
  const codingWorkError = root.querySelector("#utility-coding-work-error");
  const codingWorkCancel = root.querySelector("#utility-coding-work-cancel");
  const researchCard = root.querySelector("#utility-research-card");
  const researchTitle = root.querySelector("#utility-research-title");
  const researchState = root.querySelector("#utility-research-state");
  const researchProgress = root.querySelector("#utility-research-progress");
  const researchPhase = root.querySelector("#utility-research-phase");
  const researchSources = root.querySelector("#utility-research-sources");
  const researchLimits = root.querySelector("#utility-research-limits");
  const researchObjective = root.querySelector("#utility-research-objective");
  const researchValidation = root.querySelector("#utility-research-validation");
  const researchReport = root.querySelector("#utility-research-report");
  const researchSourceList = root.querySelector("#utility-research-source-list");
  const researchError = root.querySelector("#utility-research-error");
  const researchCancel = root.querySelector("#utility-research-cancel");
  const upcomingEmpty = root.querySelector("#utility-upcoming-empty");
  const upcomingList = root.querySelector("#utility-upcoming-list");
  const activityCard = root.querySelector("#utility-activity-card");
  const activityLabel = root.querySelector("#utility-activity-label");
  const activityDetail = root.querySelector("#utility-activity-detail");
  let currentCodingWork = null;
  let codingWorkItems = [];
  let codingWorkCancelHandler = null;
  let currentResearch = null;
  let researchCancelHandler = null;
  root.addEventListener("click", (event) => {
    const action = event.target.closest?.("[data-utility-action]")?.dataset.utilityAction;
    if (action) {
      document.dispatchEvent(new CustomEvent("tori:utilityaction", {detail: {action}}));
    }
  });

  codingWorkCancel?.addEventListener("click", async () => {
    const selected = currentCodingWork;
    if (!selected || selected.can_cancel !== true ||
        typeof selected.identifier !== "string" ||
        !Number.isInteger(selected.revision)) {
      setCodingWorkError("Coding Work cancellation is not available for the current item.");
      return;
    }
    if (typeof codingWorkCancelHandler !== "function") {
      setCodingWorkError("Coding Work cancellation is temporarily unavailable.");
      return;
    }
    setCodingWorkError();
    setCodingWorkPending(true);
    try {
      const result = await codingWorkCancelHandler(Object.freeze({
        identifier: selected.identifier,
        expectedRevision: selected.revision,
      }));
      setCodingWork(result);
      setCodingWorkError();
    } catch (error) {
      setCodingWorkError(error?.message || "Coding Work could not be cancelled.");
    } finally {
      setCodingWorkPending(false);
    }
  });

  codingWorkOverview?.addEventListener("click", (event) => {
    const button = event.target.closest?.("button[data-work-id]");
    if (!button) return;
    const selected = codingWorkItems.find((item) => item.identifier === button.dataset.workId);
    if (selected) renderCodingWork(selected);
  });

  researchCancel?.addEventListener("click", async () => {
    if (!currentResearch?.can_cancel || typeof researchCancelHandler !== "function") return;
    researchCancel.disabled = true;
    try {
      await researchCancelHandler({
        identifier: currentResearch.identifier,
        expectedRevision: currentResearch.revision,
      });
    } catch (error) {
      researchError.textContent = error?.message || "Research could not be cancelled.";
      researchError.hidden = false;
    } finally {
      researchCancel.disabled = false;
    }
  });

  function setApplicationStatus(message, state = "neutral") {
    const labels = {
      busy: "Tori is working",
      success: "Connected locally",
      warning: "Needs attention",
      neutral: "Connected locally",
    };
    statusCard.dataset.state = state;
    statusLabel.textContent = labels[state] || labels.neutral;
    statusDetail.textContent = message || "Application state is available locally.";
    statusDetail.hidden = statusDetail.textContent === statusLabel.textContent;
    if (state === "busy") {
      setActivity("Current operation", message || "Tori is working.", "busy");
    } else if (activityCard.dataset.state === "busy" &&
               activityCard.dataset.source === "application") {
      setActivity();
    }
  }

  function formatBytePair(used, total) {
    if (!Number.isFinite(used) || used < 0 || !Number.isFinite(total) || total <= 0) return null;
    const units = ["B", "KB", "MB", "GB", "TB"];
    let divisor = 1;
    let index = 0;
    while (total / divisor >= 1024 && index < units.length - 1) {
      divisor *= 1024;
      index += 1;
    }
    const render = (value) => {
      const amount = value / divisor;
      return amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1);
    };
    return `${render(used)} / ${render(total)} ${units[index]}`;
  }

  function formatPercent(value) {
    return Number.isFinite(value) && value >= 0 && value <= 100 ? `${Math.round(value)}%` : null;
  }

  function setHostStatus(documentBody) {
    if (hostStaleTimer !== null) window.clearTimeout(hostStaleTimer);
    const cpu = documentBody?.cpu;
    const memory = documentBody?.memory;
    const gpus = Array.isArray(documentBody?.gpus) ? documentBody.gpus : [];
    hostCpu.textContent = cpu?.available === true ?
      (formatPercent(cpu.utilization_percent) || "Unavailable") : "Unavailable";
    const memoryPair = formatBytePair(memory?.used_bytes, memory?.total_bytes);
    const memoryPercent = formatPercent(memory?.used_percent);
    hostMemory.textContent = memory?.available === true && memoryPair ?
      `${memoryPair}${memoryPercent ? ` · ${memoryPercent}` : ""}` : "Unavailable";
    const gpuLabels = gpus.map((gpu, index) => {
      const label = formatPercent(gpu?.utilization_percent) || "Unavailable";
      return gpus.length > 1 ? `GPU ${index + 1}: ${label}` : label;
    });
    hostGpu.textContent = gpuLabels.length ? gpuLabels.join(" · ") : "Unavailable";
    const vramLabels = gpus.map((gpu, index) => {
      const pair = formatBytePair(gpu?.memory_used_bytes, gpu?.memory_total_bytes);
      if (!pair) return null;
      return gpus.length > 1 ? `GPU ${index + 1}: ${pair}` : pair;
    }).filter(Boolean);
    hostVramRow.hidden = vramLabels.length === 0;
    hostVram.textContent = vramLabels.join(" · ");
    for (const metric of [hostCpu, hostMemory, hostGpu, hostVram]) {
      metric.dataset.state = metric.textContent && !metric.textContent.includes("Unavailable") ?
        "available" : "unavailable";
    }
    const hasReadings = [hostCpu, hostMemory, hostGpu, hostVram].some(metric => metric.dataset.state === "available");
    if (hostFreshness) hostFreshness.textContent = hasReadings ? "Live readings · refreshed locally" : "Readings unavailable";
    if (hasReadings && typeof window.setTimeout === "function") {
      hostStaleTimer = window.setTimeout(() => {
        if (hostFreshness) hostFreshness.textContent = "Stale · no update received for 15 seconds";
        for (const metric of [hostCpu, hostMemory, hostGpu, hostVram]) {
          if (metric.dataset.state === "available") metric.dataset.state = "stale";
        }
      }, 15000);
    }
  }

  // The shell moves the existing model/context controls and project indicator
  // between Home and Chat. These compatibility no-ops avoid a second projection
  // of those same facts in the utility cards.
  function setModel() {}
  function setContext() {}
  function setProject() {}

  function codingWorkTitle(workspace) {
    const pieces = workspace.split("/").filter(Boolean);
    return pieces[pieces.length - 1] || "Coding Work";
  }

  function codingWorkStateLabel(state) {
    return ({
      awaiting_authorization: "Needs approval",
      queued: "Queued",
      starting: "Starting",
      reconciling: "Reconciling",
      running: "Running",
      waiting: "Waiting",
      cancelling: "Cancelling",
      cancelled: "Cancelled",
      completed: "Complete",
      failed: "Failed",
    })[state] || "Unavailable";
  }

  function terminalCodingWorkMessage(item) {
    if (item.state === "completed") {
      return `Delegated Work completed for ${item.workspace}.`;
    }
    if (item.state === "failed") {
      return "Delegated Work failed. Open the details for the durable receipt.";
    }
    if (item.state === "cancelled") {
      return "Delegated Work was cancelled.";
    }
    return null;
  }

  function setCodingWork(documentBody) {
    const workItems = (Array.isArray(documentBody?.work) ? documentBody.work : []).filter((item) =>
      item && typeof item.identifier === "string" && Number.isInteger(item.revision) &&
      typeof item.objective === "string" && typeof item.workspace === "string" &&
      typeof item.state === "string");
    codingWorkItems = workItems;
    const currentIdentifier = typeof documentBody?.current_work_id === "string" ?
      documentBody.current_work_id : null;
    const item = workItems.find((candidate) => candidate.identifier === currentIdentifier) ||
      workItems.find((candidate) => candidate.identifier === currentCodingWork?.identifier) ||
      workItems[0];
    if (!item) {
      currentCodingWork = null;
      codingWorkItems = [];
      codingWorkOverview?.replaceChildren();
      codingWorkCard.hidden = true;
      return;
    }

    renderCodingWork(item);
  }

  function workCategory(item) {
    if (item.needs_authorization === true) return "Needs attention";
    if (["starting", "running", "waiting", "cancelling", "reconciling"].includes(item.state)) {
      return "Active";
    }
    return "Recent";
  }

  function renderCodingWork(item) {
    codingWorkOverview?.replaceChildren(...codingWorkItems.slice(0, 8).map((candidate) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.workId = candidate.identifier;
      button.setAttribute("aria-current", String(candidate.identifier === item.identifier));
      const objective = document.createElement("strong");
      objective.textContent = candidate.objective;
      const state = document.createElement("span");
      state.textContent = `${workCategory(candidate)} · ${codingWorkStateLabel(candidate.state)}`;
      button.append(objective, state);
      return button;
    }));

    if (currentCodingWork?.identifier !== item.identifier) {
      setCodingWorkError();
    }
    currentCodingWork = item;
    codingWorkCard.hidden = false;
    codingWorkCard.dataset.state = item.needs_authorization === true ||
      item.state === "failed" ? "warning" :
      item.state === "completed" ? "success" : "busy";
    codingWorkLabel.textContent = codingWorkTitle(item.workspace);
    codingWorkState.textContent = codingWorkStateLabel(item.state);
    codingWorkLatest.textContent = terminalCodingWorkMessage(item) ||
      item.latest_activity || item.result_summary ||
      `Canonical state: ${codingWorkStateLabel(item.state)}.`;
    codingWorkWorkspace.textContent = item.workspace;
    const updated = new Date(item.updated_at_utc);
    codingWorkUpdated.dateTime = item.updated_at_utc || "";
    codingWorkUpdated.textContent = Number.isNaN(updated.valueOf()) ?
      "Unavailable" : updated.toLocaleString();
    codingWorkObjective.textContent = item.objective;
    codingWorkAuthority.textContent = item.needs_authorization === true ?
      "Needs fresh approval" : "Bounded one-use authority recorded";
    codingWorkAcceptance.textContent = ({
      not_specified: "No explicit acceptance criteria",
      pending: "Pending",
      not_completed: "Not completed",
      not_independently_verified: "Reported complete; not independently proven in full",
    })[item.acceptance_status] || "Unavailable";
    codingWorkRelatedRow.hidden = typeof item.related_work_id !== "string";
    codingWorkRelated.textContent = item.related_work_id || "";

    const changedPaths = Array.isArray(item.changed_paths) ? item.changed_paths : [];
    codingWorkPaths.replaceChildren(...changedPaths.filter((path) =>
      typeof path === "string").map((path) => {
      const row = document.createElement("li");
      row.textContent = path;
      return row;
    }));
    codingWorkPaths.hidden = codingWorkPaths.children.length === 0;
    codingWorkPathsEmpty.hidden = codingWorkPaths.children.length !== 0;

    const recentActivity = Array.isArray(item.recent_activity) ? item.recent_activity : [];
    codingWorkActivity.replaceChildren(...recentActivity.filter((activity) =>
      typeof activity?.summary === "string").map((activity) => {
      const row = document.createElement("li");
      row.textContent = activity.summary;
      return row;
    }));
    codingWorkActivity.hidden = codingWorkActivity.children.length === 0;
    codingWorkActivityEmpty.hidden = codingWorkActivity.children.length !== 0;

    const verification = Array.isArray(item.verification) ? item.verification : [];
    codingWorkVerification.replaceChildren(...verification.map((evidence) => {
      const row = document.createElement("li");
      const kind = typeof evidence?.kind === "string" ? evidence.kind : "verification";
      const status = typeof evidence?.status === "string" ? evidence.status : "recorded";
      const summary = typeof evidence?.summary === "string" ? ` · ${evidence.summary}` : "";
      row.textContent = `${kind}: ${status}${summary}`;
      return row;
    }));
    codingWorkVerification.hidden = codingWorkVerification.children.length === 0;
    codingWorkVerificationEmpty.hidden = codingWorkVerification.children.length !== 0;

    codingWorkResultGroup.hidden = typeof item.result_summary !== "string";
    codingWorkResult.textContent = item.result_summary || "";
    codingWorkCancel.hidden = item.can_cancel !== true;
    codingWorkCancel.disabled = false;
  }

  function setCodingWorkPending(pending) {
    if (codingWorkCancel) codingWorkCancel.disabled = pending === true;
  }

  function setCodingWorkError(message) {
    if (codingWorkError) {
      codingWorkError.textContent = message || "";
      codingWorkError.hidden = !message;
    }
  }

  function setCodingWorkCancelHandler(handler) {
    codingWorkCancelHandler = typeof handler === "function" ? handler : null;
  }

  function setResearch(documentBody) {
    const jobs = Array.isArray(documentBody?.jobs) ? documentBody.jobs : [];
    const item = jobs.find((job) => ["queued", "starting", "running", "cancelling"].includes(job?.state)) || jobs[0];
    if (!item) {
      currentResearch = null;
      researchCard.hidden = true;
      return;
    }
    currentResearch = item;
    researchCard.hidden = false;
    researchCard.dataset.state = ["failed", "interrupted"].includes(item.state) ? "warning" :
      ["completed", "completed_with_limits"].includes(item.state) ? "success" : "busy";
    researchTitle.textContent = item.objective;
    researchState.textContent = item.state.replaceAll("_", " ");
    researchProgress.textContent = item.progress_message || item.failure_message || "No progress event yet.";
    researchPhase.textContent = item.phase || "Not reported";
    researchSources.textContent = `${item.source_count || 0} total · ${item.primary_source_count || 0} primary · ${item.primary_sources_used || 0} primary used`;
    const limits = item.limits && typeof item.limits === "object" ? item.limits : {};
    researchLimits.textContent = `${limits.maximum_duration_seconds || 0}s · ${limits.maximum_search_queries || 0} searches · ${limits.maximum_sources_fetched || 0} fetched`;
    researchObjective.textContent = `Objective: ${item.objective}`;
    const validation = item.validation_summary;
    researchValidation.textContent = item.ledger_status === "legacy_report_only" ?
      "Legacy report: claim evidence was not retained or verified." :
      item.ledger_status === "evidence_gated" && validation && typeof validation === "object" ?
        `Provenance: source-linked excerpts retained. Claim support is worker-classified, not independently proven. ` +
        `Supported ${validation.supported || 0} · Partial ${validation.partially_supported || 0} · ` +
        `Conflicted ${validation.conflicting || 0} · Unsupported ${validation.unsupported || 0}` :
        "Claim provenance is not available yet.";
    researchReport.textContent = item.report || "The final report is not available yet.";
    const sources = Array.isArray(item.sources) ? item.sources : [];
    researchSourceList.replaceChildren(...sources.map((source, index) => {
      const row = document.createElement("li");
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.title || source.url;
      const note = document.createElement("span");
      const provider = typeof source.search_provider === "string" ? source.search_provider : "unknown";
      note.textContent = ` · Source #${source.sequence || index + 1} · ${provider} · ${source.source_type}${source.used_in_report ? " · used" : ""}`;
      row.append(link, note);
      return row;
    }));
    researchCancel.hidden = item.can_cancel !== true;
    researchError.hidden = true;
  }

  function setResearchCancelHandler(handler) {
    researchCancelHandler = typeof handler === "function" ? handler : null;
  }

  function civilDateParts(date, timezone) {
    const options = {timeZone: timezone || undefined, year: "numeric", month: "2-digit", day: "2-digit"};
    try {
      return new Intl.DateTimeFormat("en-CA", options).format(date);
    } catch (_error) {
      return new Intl.DateTimeFormat("en-CA", {year: "numeric", month: "2-digit", day: "2-digit"}).format(date);
    }
  }

  function dayLabel(date, timezone) {
    const now = new Date();
    const tomorrow = new Date(now.valueOf() + 24 * 60 * 60 * 1000);
    const key = civilDateParts(date, timezone);
    if (key === civilDateParts(now, timezone)) return "Today";
    if (key === civilDateParts(tomorrow, timezone)) return "Tomorrow";
    try {
      return new Intl.DateTimeFormat(undefined, {
        timeZone: timezone || undefined, month: "short", day: "numeric",
      }).format(date);
    } catch (_error) {
      return date.toLocaleDateString(undefined, {month: "short", day: "numeric"});
    }
  }

  function itemTime(date, timezone) {
    try {
      return new Intl.DateTimeFormat(undefined, {
        timeZone: timezone || undefined, hour: "numeric", minute: "2-digit",
      }).format(date);
    } catch (_error) {
      return date.toLocaleTimeString(undefined, {hour: "numeric", minute: "2-digit"});
    }
  }

  function setUpcoming(documentBody) {
    const items = Array.isArray(documentBody?.items) ? documentBody.items : [];
    upcomingList.replaceChildren();
    upcomingList.hidden = items.length === 0;
    upcomingEmpty.hidden = items.length !== 0;
    upcomingEmpty.textContent = items.length === 0 ? (
      documentBody?.unavailable === true ?
        "Upcoming schedule could not be loaded." :
        "No dated Tasks, scheduled Reminders, or active Scheduled Work."
    ) : "";
    let priorDay = null;
    for (const item of items) {
      const scheduled = new Date(item.scheduled_at_utc);
      if (Number.isNaN(scheduled.valueOf())) continue;
      const day = dayLabel(scheduled, item.timezone);
      if (day !== priorDay) {
        const heading = document.createElement("p");
        heading.className = "utility-upcoming-day";
        heading.textContent = day;
        upcomingList.append(heading);
        priorDay = day;
      }
      const row = document.createElement("div");
      row.className = "utility-upcoming-item";
      const time = document.createElement("time");
      time.dateTime = item.scheduled_at_utc;
      time.textContent = itemTime(scheduled, item.timezone);
      const copy = document.createElement("div");
      const label = document.createElement("p");
      label.textContent = item.label;
      const kind = document.createElement("span");
      kind.textContent = ({task: "Task", reminder: "Reminder", scheduled_work: "Scheduled Work"})[item.kind] || "Scheduled";
      copy.append(label, kind);
      row.append(time, copy);
      upcomingList.append(row);
    }
    if (!upcomingList.children.length) {
      upcomingList.hidden = true;
      upcomingEmpty.hidden = false;
      upcomingEmpty.textContent = "Upcoming schedule data is unavailable.";
    }
  }

  function setActivity(
    label = "No active work",
    detail = "Tori is idle. No background activity is being claimed.",
    state = "neutral",
    source = "application"
  ) {
    activityCard.dataset.state = state;
    activityCard.dataset.source = source;
    activityLabel.textContent = label;
    activityDetail.textContent = detail;
    activityCard.hidden = state === "neutral";
  }

  // Planning remains available through its existing application paths, but is
  // not advertised as a completed utility-rail workspace in this release.
  function setPlanning() {}
  function setPlanningError() {}

  window.ToriUtilityRail = Object.freeze({
    setActivity,
    setApplicationStatus,
    setContext,
    setCodingWork,
    setCodingWorkCancelHandler,
    setCodingWorkError,
    setCodingWorkPending,
    setResearch,
    setResearchCancelHandler,
    setHostStatus,
    setModel,
    setProject,
    setPlanning,
    setPlanningError,
    setUpcoming,
  });
}());
