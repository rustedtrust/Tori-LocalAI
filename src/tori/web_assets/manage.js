"use strict";

(function initializeManagement() {
const ui = window.ToriUI;
const refreshAllButtons = document.querySelectorAll(".refresh-management");
const statusAreas = document.querySelectorAll(".management-status");
const errorAreas = document.querySelectorAll(".management-error");
const managementPanels = document.querySelectorAll("[data-management-panel]");
const checkpointForm = document.getElementById("checkpoint-form");
const checkpointName = document.getElementById("checkpoint-name");
const checkpointList = document.getElementById("checkpoint-list");
const memoryForm = document.getElementById("memory-form");
const memoryText = document.getElementById("memory-text");
const memoryList = document.getElementById("memory-list");
const knowledgeForm = document.getElementById("knowledge-form");
const knowledgePath = document.getElementById("knowledge-path");
const knowledgeList = document.getElementById("knowledge-list");
const invalidRegistrationList = document.getElementById("invalid-registration-list");
const confirmationDialog = document.getElementById("management-confirmation");
const confirmationHeading = document.getElementById("management-confirmation-heading");
const confirmationMessage = document.getElementById("management-confirmation-message");
const confirmationTarget = document.getElementById("management-confirmation-target");
const confirmButton = document.getElementById("management-confirm");
const cancelButton = document.getElementById("management-cancel");
const taskList = document.getElementById("task-list");
const reminderList = document.getElementById("reminder-list");
const operationalHistoryToggle = document.getElementById("operational-history-toggle");
const operationalHistory = document.getElementById("operational-history");
const operationalHistorySummary = document.getElementById("operational-history-summary");
const taskHistoryList = document.getElementById("task-history-list");
const reminderHistoryList = document.getElementById("reminder-history-list");
const scheduledWorkForm = document.getElementById("scheduled-work-form");
const scheduledWorkTitle = document.getElementById("scheduled-work-title");
const scheduledWorkDate = document.getElementById("scheduled-work-date");
const scheduledWorkTime = document.getElementById("scheduled-work-time");
const scheduledWorkMissed = document.getElementById("scheduled-work-missed");
const scheduledWorkSubmit = document.getElementById("scheduled-work-submit");
const scheduledWorkEditCancel = document.getElementById("scheduled-work-edit-cancel");
const scheduledWorkActive = document.getElementById("scheduled-work-active");
const scheduledWorkPaused = document.getElementById("scheduled-work-paused");
const scheduledWorkHistory = document.getElementById("scheduled-work-history");
const scheduledRunHistory = document.getElementById("scheduled-run-history");
const projectForm = document.getElementById("project-form");
const projectTitle = document.getElementById("project-title");
const projectObjective = document.getElementById("project-objective");
const projectList = document.getElementById("project-list");

const HISTORY_LIMIT = 50;
const PROJECT_LINK_TYPES = [
  ["night_owl_finding", "Night Owl finding", "night_owl", "settings"],
  ["scheduled_work_definition", "Scheduled Work definition", "scheduled_work", "scheduled-work"],
  ["knowledge_source", "Knowledge source", "knowledge", "knowledge"],
];

let localMutationBusy = false;
let serverBusy = false;
let pendingConfirmationToken = null;
let pendingHistoryDelete = null;
let managementLoaded = false;
let operationalLoadGeneration = 0;
let scheduledLoadGeneration = 0;
let projectLoadGeneration = 0;
let projectLoadPromise = null;
let projectDocument = null;
let selectedProjectId = null;
let projectLinkDraft = {projectId: null, targetType: "night_owl_finding", targetId: "", editing: false};
let projectLinkTargets = null;
let projectLinkTargetGeneration = 0;
let projectLinkTargetsPromise = null;
let scheduledRevision = null;
const scheduledOpenDetails = new Set();
let scheduledEditId = "";
let scheduledEditRevision = null;

function showError(message) {
  for (const area of errorAreas) {
    ui.showError(area, message);
  }
}

function setStatus(message, state = "neutral") {
  for (const area of statusAreas) {
    ui.setStatus(area, message, state);
  }
}

function applyBusyState() {
  const disabled = localMutationBusy || serverBusy;
  for (const control of document.querySelectorAll(".mutation")) {
    control.disabled = disabled;
  }
  for (const button of refreshAllButtons) {
    button.disabled = localMutationBusy;
  }
  for (const panel of managementPanels) {
    ui.setBusy(panel, disabled);
  }
}

function beginMutation(message) {
  localMutationBusy = true;
  showError("");
  setStatus(message);
  applyBusyState();
}

function endMutation() {
  localMutationBusy = false;
  applyBusyState();
}

async function getJson(path) {
  return ui.requestJson(path);
}

async function postJson(path, body) {
  return ui.requestJson(path, {method: "POST", body});
}

function addDefinition(list, label, value) {
  const term = ui.createElement("dt", "", label);
  const detail = ui.createElement(
    "dd", "", value === null || value === undefined ? "—" : value
  );
  list.append(term, detail);
}

function emptyState(message) {
  return ui.createElement("p", "empty-state", message);
}

function recordCard() {
  return ui.createElement("article", "record-card");
}

function projectHomeSection(title) {
  const section = ui.createElement("section", "project-home-section");
  section.append(ui.createElement("h4", "", title));
  return section;
}

function projectHomeList(records, emptyMessage, describe) {
  if (!records.length) return emptyState(emptyMessage);
  const list = ui.createElement("ul", "project-home-list");
  for (const record of records) {
    list.append(ui.createElement("li", "", describe(record)));
  }
  return list;
}

function projectLinkSection(home) {
  const project = home.project;
  const section = projectHomeSection("Project links");
  section.append(ui.createElement(
    "p", "project-legacy-note",
    "Links organize existing source-owned records. They do not grant access or start work.",
  ));
  if (!home.links.length) {
    section.append(emptyState("No explicit Project links yet."));
  } else {
    const list = ui.createElement("ul", "project-link-list");
    for (const link of home.links) {
      const type = PROJECT_LINK_TYPES.find(([name]) => name === link.target_type);
      const source = type?.[2];
      const related = source && home.related_work?.[source]?.find(
        (item) => item.link_id === link.identifier,
      );
      const sourceUnavailable = source && home.related_work?.unavailable_sources.includes(source);
      const item = document.createElement("li");
      const details = ui.createElement("div", "project-link-details");
      details.append(
        ui.createElement("strong", "", type?.[1] || link.target_type),
        ui.createElement("span", "record-meta", `Source ID: ${link.target_id}`),
        ui.createElement(
          "span", "record-meta",
          sourceUnavailable ? "Source unavailable; link retained" :
            related?.availability === "missing" ? "Source record missing; link retained" :
              related ? `${related.title} · ${related.state} · source-owned` :
                "Source metadata unavailable; link retained",
        ),
      );
      const unlink = ui.createElement("button", "button secondary mutation", "Unlink");
      unlink.type = "button";
      unlink.setAttribute("aria-label", `Unlink ${type?.[1] || link.target_type} ${link.target_id}`);
      unlink.addEventListener("click", async () => {
        if (!window.confirm(
          `Remove this ${type?.[1] || link.target_type} link from “${project.title}”? The source record will remain untouched.`,
        )) return;
        await mutateProject("/api/projects/unlink", {
          project_id: project.identifier,
          link_id: link.identifier,
          expected_project_revision: project.revision,
          expected_link_revision: link.revision,
        });
      });
      item.append(details, unlink);
      list.append(item);
    }
    section.append(list);
  }

  if (projectLinkDraft.projectId !== project.identifier) {
    projectLinkDraft = {projectId: project.identifier, targetType: "night_owl_finding", targetId: "", editing: false};
  }
  const form = ui.createElement("form", "project-link-form");
  form.addEventListener("focusin", () => { projectLinkDraft.editing = true; });
  const label = ui.createElement("label", "", "Source");
  const select = document.createElement("select");
  select.className = "mutation";
  select.required = true;
  select.name = "project-link-type";
  for (const [name, title] of PROJECT_LINK_TYPES) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = title;
    select.append(option);
  }
  select.value = projectLinkDraft.targetType;
  label.append(select);
  const itemLabel = ui.createElement("label", "", "Item");
  const itemSelect = document.createElement("select");
  itemSelect.className = "mutation";
  itemSelect.required = true;
  itemSelect.name = "project-link-item";
  itemLabel.append(itemSelect);
  const idMeta = ui.createElement("span", "record-meta project-link-id-meta");
  const add = ui.createElement("button", "button secondary mutation", "Link");
  add.type = "submit";
  const cancel = ui.createElement("button", "button secondary", "Cancel link");
  cancel.type = "button";
  select.addEventListener("change", () => {
    projectLinkDraft.targetType = select.value;
    projectLinkDraft.targetId = "";
    projectLinkDraft.editing = true;
    populateLinkItemOptions(itemSelect, idMeta, add);
  });
  itemSelect.addEventListener("change", () => {
    projectLinkDraft.targetId = itemSelect.value;
    projectLinkDraft.editing = true;
    applyLinkSelectionState(idMeta, add);
  });
  cancel.addEventListener("click", () => {
    projectLinkDraft = {
      projectId: project.identifier, targetType: "night_owl_finding", targetId: "", editing: false,
    };
    renderProjects(projectDocument);
    refreshProjectCanonicalState();
  });
  form.append(label, itemLabel, idMeta, add, cancel);
  populateLinkItemOptions(itemSelect, idMeta, add);
  loadProjectLinkTargets().then(() => {
    // A late response must not replace a focused form or discard its draft.
    if (!itemSelect.isConnected || projectLinkFormIsEditing()) return;
    populateLinkItemOptions(itemSelect, idMeta, add);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const chosenType = PROJECT_LINK_TYPES.find(([name]) => name === select.value);
    const state = linkTargetStateFor(select.value);
    const chosenId = itemSelect.value;
    if (!chosenType || !state?.available || !chosenId) {
      showError("Choose a source type and an existing item to link.");
      return;
    }
    const chosenItem = state.items.find((item) => item.identifier === chosenId);
    if (!window.confirm(
      `Link “${chosenItem ? chosenItem.title : chosenId}” (${chosenType[1]}) to “${project.title}”? This only organizes the record; it grants no capability authority.`,
    )) return;
    const saved = await mutateProject("/api/projects/link", {
      project_id: project.identifier,
      expected_project_revision: project.revision,
      target_type: chosenType[0],
      target_id: chosenId,
      confirmed: true,
    });
    if (saved) {
      projectLinkDraft.targetId = "";
      projectLinkDraft.editing = false;
      renderProjects(projectDocument);
    }
  });
  section.append(form);
  return section;
}

function linkTargetStateFor(typeName) {
  const source = projectLinkTargets === null ? null : projectLinkTargets[typeName];
  if (!source || typeof source.available !== "boolean") return null;
  if (source.available && !Array.isArray(source.items)) return {available: false};
  return source;
}

function applyLinkSelectionState(metaEl, submitBtn) {
  const state = linkTargetStateFor(projectLinkDraft.targetType);
  metaEl.textContent = state === null
    ? "Loading available items…"
    : !state.available
      ? "Source unavailable; linking is disabled."
      : projectLinkDraft.targetId
        ? `Stable ID: ${projectLinkDraft.targetId}`
        : "";
  submitBtn.disabled = !(state?.available && projectLinkDraft.targetId);
}

function populateLinkItemOptions(itemSelect, metaEl, submitBtn) {
  itemSelect.replaceChildren();
  const state = linkTargetStateFor(projectLinkDraft.targetType);
  if (state === null || !state.available) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = state === null ? "Loading available items…" : "Source unavailable";
    option.disabled = true;
    itemSelect.append(option);
    itemSelect.disabled = true;
  } else if (!state.items.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No available items";
    option.disabled = true;
    itemSelect.append(option);
    itemSelect.disabled = true;
  } else {
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = "Select an existing item";
    itemSelect.append(prompt);
    for (const item of state.items) {
      const option = document.createElement("option");
      option.value = item.identifier;
      option.textContent = item.title;
      itemSelect.append(option);
    }
    if (!state.items.some((item) => item.identifier === projectLinkDraft.targetId)) {
      projectLinkDraft.targetId = "";
    }
    itemSelect.value = projectLinkDraft.targetId;
    itemSelect.disabled = false;
  }
  applyLinkSelectionState(metaEl, submitBtn);
}

function normalizedLinkTargetSources(raw) {
  const result = {};
  for (const [name] of PROJECT_LINK_TYPES) {
    const source = raw && typeof raw === "object" ? raw[name] : null;
    if (!source || source.available !== true || !Array.isArray(source.items)) {
      result[name] = {available: false};
      continue;
    }
    const seen = new Set();
    const items = [];
    for (const item of source.items) {
      if (!item || typeof item.identifier !== "string" || !item.identifier ||
          typeof item.title !== "string" || !item.title || seen.has(item.identifier)) {
        continue;
      }
      seen.add(item.identifier);
      items.push({identifier: item.identifier, title: item.title});
    }
    result[name] = {available: true, items: items.slice(0, 50)};
  }
  return result;
}

function loadProjectLinkTargets() {
  if (projectLinkTargets !== null) return Promise.resolve();
  if (projectLinkTargetsPromise !== null) return projectLinkTargetsPromise;
  const generation = ++projectLinkTargetGeneration;
  const request = (async () => {
    try {
      const result = await getJson("/api/projects/link-targets");
      if (generation === projectLinkTargetGeneration && result?.sources) {
        projectLinkTargets = normalizedLinkTargetSources(result.sources);
      }
    } catch (_error) {
      // Fail closed: no source can be confirmed available.
      if (generation === projectLinkTargetGeneration) {
        projectLinkTargets = {
          night_owl_finding: {available: false},
          scheduled_work_definition: {available: false},
          knowledge_source: {available: false},
        };
      }
    } finally {
      if (projectLinkTargetsPromise === request) projectLinkTargetsPromise = null;
    }
  })();
  projectLinkTargetsPromise = request;
  return request;
}

function renderProjectLandingCard(home, documentBody) {
  const project = home.project;
  const article = recordCard();
  article.classList.add("project-summary-card");
  const heading = document.createElement("h3");
  heading.textContent = project.title;
  const summary = document.createElement("dl");
  addDefinition(summary, "Status", project.status);
  addDefinition(summary, "Objective", project.objective);
  addDefinition(summary, "Revision", home.freshness.project_revision);
  const open = ui.createElement("button", "button primary", "Open Project");
  open.type = "button";
  open.addEventListener("click", () => {
    selectedProjectId = project.identifier;
    renderProjects(documentBody);
    document.getElementById("projects-heading")?.focus();
  });
  const actions = ui.createElement("div", "record-actions");
  actions.append(open);
  article.append(heading, summary, actions);
  return article;
}

function renderProjects(documentBody) {
  projectDocument = documentBody;
  projectList.replaceChildren();
  const homes = Array.isArray(documentBody.project_homes) ?
    documentBody.project_homes : [];
  if (!homes.length) {
    projectList.append(emptyState("No Projects have been created."));
    return;
  }
  let visibleHomes = homes;
  if (selectedProjectId !== null) {
    visibleHomes = homes.filter((home) => home.project.identifier === selectedProjectId);
    if (!visibleHomes.length) {
      selectedProjectId = null;
      visibleHomes = homes;
    }
  }
  projectForm.hidden = selectedProjectId !== null;
  if (selectedProjectId === null) {
    for (const home of visibleHomes) {
      projectList.append(renderProjectLandingCard(home, documentBody));
    }
    return;
  }
  for (const home of visibleHomes) {
    const project = home.project;
    const where = home.where_we_are;
    const article = recordCard();
    article.classList.add("project-home-card");
    const homeNavigation = ui.createElement("div", "project-home-navigation");
    const back = ui.createElement("button", "button secondary", "Back to Projects");
    back.type = "button";
    back.addEventListener("click", () => {
      selectedProjectId = null;
      renderProjects(documentBody);
      document.getElementById("projects-heading")?.focus();
    });
    homeNavigation.append(
      back,
      ui.createElement("p", "eyebrow project-home-label", "Project Home"),
    );
    const heading = document.createElement("h3");
    heading.textContent = project.title;
    const summary = document.createElement("dl");
    addDefinition(summary, "Status", project.status);
    addDefinition(summary, "Objective", project.objective);
    addDefinition(summary, "Revision", home.freshness.project_revision);

    const whereSection = projectHomeSection("Where We Are");
    if (!where.structured_state_present) {
      whereSection.append(emptyState("No structured Project state has been recorded yet."));
    }
    const whereDetails = document.createElement("dl");
    addDefinition(whereDetails, "Phase", where.phase === "Not yet recorded" ? "No phase set" : where.phase);
    addDefinition(whereDetails, "Current focus", where.current_focus === "Not yet recorded" ? "No current focus" : where.current_focus);
    addDefinition(whereDetails, "Checkpoint", where.checkpoint === "Not yet recorded" ? "No checkpoint recorded" : where.checkpoint);
    addDefinition(whereDetails, "Next planned step", where.next_planned_step ? where.next_planned_step.text : "No planned next step");
    addDefinition(whereDetails, "Open questions", where.open_question_count);
    addDefinition(whereDetails, "Deferred questions", where.deferred_question_count);
    addDefinition(whereDetails, "Last updated", where.last_updated_at);
    whereSection.append(whereDetails);

    const planSection = projectHomeSection("Current Plan");
    const currentPlan = home.plan_items.filter((item) => item.state !== "completed");
    planSection.append(projectHomeList(
      currentPlan,
      "No plan items",
      (item) => `${item.text} · ${item.state}${item.state_note ? ` — ${item.state_note}` : ""}`,
    ));

    const questionsSection = projectHomeSection("Open Questions");
    questionsSection.append(projectHomeList(
      home.active_questions,
      "No open questions",
      (question) => `${question.text} · ${question.state}`,
    ));

    const decisionsSection = projectHomeSection("Decisions");
    decisionsSection.append(projectHomeList(
      home.active_decisions,
      "No structured decisions yet",
      (decision) => `${decision.text}${decision.importance === "important" ? " · important" : ""}`,
    ));

    const conversationsSection = projectHomeSection("Conversations");
    if (!home.conversations.length) {
      conversationsSection.append(emptyState("No conversations are associated with this Project."));
    } else {
      const conversations = ui.createElement("div", "project-conversation-list");
      for (const conversation of home.conversations) {
        const open = ui.createElement("button", "project-conversation mutation");
        open.type = "button";
        open.textContent = `${conversation.label} · updated ${conversation.updated_at}`;
        open.addEventListener("click", async () => {
          beginMutation("Opening the associated conversation…");
          try {
            if (!window.ToriConversation?.openArchivedChat) {
              throw new Error("The conversation surface is unavailable.");
            }
            await window.ToriConversation.openArchivedChat(conversation);
            ui.navigate("conversation");
            setStatus("Associated conversation opened.", "success");
          } catch (error) {
            showError(error.message);
          } finally {
            endMutation();
          }
        });
        conversations.append(open);
      }
      conversationsSection.append(conversations);
    }

    const relatedSection = projectHomeSection("Related Work");
    if (home.related_work) {
      const labels = [
        ["research", "Research", "conversation"], ["coding_work", "Coding Work", "conversation"],
        ["attention", "Attention", "conversation"],
        ["night_owl", "Night Owl", "settings"],
        ["scheduled_work", "Scheduled Work", "scheduled-work"],
        ["knowledge", "Knowledge", "knowledge"],
      ];
      for (const [key, label, ownerView] of labels) {
        const subsection = document.createElement("section");
        subsection.className = "project-related-source";
        subsection.append(ui.createElement("h4", "", label));
        subsection.append(ui.createElement("p", "record-meta", `Source-owned by ${label}`));
        if (home.related_work.unavailable_sources.includes(key)) {
          const failure = home.related_work.unavailable_details.find((item) => item.source_type === key);
          subsection.append(emptyState(failure?.reason || "Source unavailable; this section may be incomplete."));
        } else {
          subsection.append(projectHomeList(
            home.related_work[key], "No related records",
            (item) => `${item.title} · ${item.state} · ${item.identifier} · updated ${item.updated_at}` +
              (item.availability === "not_checked" ? " · file availability not checked" : ""),
          ));
        }
        if (home.related_work[key]?.length) {
          const openOwner = ui.createElement("button", "button secondary project-source-open", `Open ${label} workspace`);
          openOwner.type = "button";
          openOwner.addEventListener("click", () => {
            ui.navigate(ownerView);
            if (key === "night_owl") {
              document.querySelector('[data-settings-target="night-owl"]')?.click();
            }
          });
          subsection.append(openOwner);
        }
        relatedSection.append(subsection);
      }
      const activity = projectHomeSection("Recent activity");
      activity.append(ui.createElement(
        "p", "project-legacy-note", "Current source-record updates, not a complete event history.",
      ));
      activity.append(projectHomeList(
        home.related_work.recent_activity, "No related activity to show",
        (item) => `${item.source_type} · ${item.identifier} · ${item.state} · ${item.occurred_at}`,
      ));
      if (!home.related_work.complete) {
        activity.append(emptyState("Partial view: unavailable sources are not included in this timeline."));
      }
      relatedSection.append(activity);
    } else {
      relatedSection.append(emptyState("Related work sources are not configured."));
    }

    const legacySection = projectHomeSection("Legacy Continuity");
    legacySection.classList.add("legacy-continuity");
    legacySection.append(ui.createElement(
      "p", "project-legacy-note",
      "Read-only compatibility data. It is not structured Project state.",
    ));
    legacySection.append(ui.createElement(
      "p", "project-legacy-text", home.legacy_continuity.text
    ));
    legacySection.hidden = !home.legacy_continuity.present;

    const actions = ui.createElement("div", "record-actions");
    const newChat = ui.createElement("button", "button primary mutation", "New Project Chat");
    newChat.type = "button";
    newChat.addEventListener("click", async () => {
      beginMutation("Preparing a fresh Project conversation…");
      try {
        if (!window.ToriConversation?.startProjectChat) {
          throw new Error("The conversation surface is unavailable.");
        }
        const started = await window.ToriConversation.startProjectChat(project);
        if (started) setStatus("New Project chat ready.", "success");
      } catch (error) {
        showError(error.message);
      } finally {
        endMutation();
      }
    });
    const associate = ui.createElement("button", "button secondary mutation", documentBody.active_project_id === project.identifier ? "Detach conversation" : "Use for conversation");
    associate.type = "button";
    associate.addEventListener("click", async () => {
      await mutateProject("/api/projects/associate", {
        project_id: documentBody.active_project_id === project.identifier ? null : project.identifier,
        expected_chat_revision: documentBody.transcript_revision,
      });
    });
    const lifecycle = ui.createElement("button", "button secondary mutation", project.status === "active" ? "Pause" : "Set active");
    lifecycle.type = "button";
    lifecycle.addEventListener("click", () => mutateProject("/api/projects/lifecycle", {
      identifier: project.identifier, expected_revision: project.revision,
      status: project.status === "active" ? "paused" : "active",
    }));
    const complete = ui.createElement("button", "button secondary mutation", "Complete");
    complete.type = "button";
    complete.disabled = project.status === "completed";
    complete.addEventListener("click", () => mutateProject("/api/projects/lifecycle", {
      identifier: project.identifier, expected_revision: project.revision, status: "completed",
    }));
    const edit = ui.createElement("button", "button secondary mutation", "Edit");
    edit.type = "button";
    edit.addEventListener("click", async () => {
      const title = window.prompt("Project title", project.title);
      if (title === null) return;
      const objective = window.prompt("Project objective", project.objective);
      if (objective === null) return;
      await mutateProject("/api/projects/update", {
        identifier: project.identifier,
        expected_revision: project.revision,
        title,
        objective,
      });
    });
    const remove = ui.createElement("button", "button danger mutation", "Delete permanently");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!window.confirm(`Permanently delete Project “${project.title}” and detach its conversations? Conversations will not be deleted.`)) return;
      await mutateProject("/api/projects/delete", {
        identifier: project.identifier, expected_revision: project.revision, confirmed: true,
      });
    });
    actions.append(newChat, associate, edit, lifecycle, complete, remove);
    article.append(
      homeNavigation, heading, summary, whereSection, planSection, questionsSection,
      decisionsSection, conversationsSection, relatedSection, projectLinkSection(home),
      legacySection, actions,
    );
    projectList.append(article);
  }
}

function projectLinkFormIsEditing() {
  const focusedForm = document.activeElement?.closest(".project-link-form");
  return selectedProjectId === projectLinkDraft.projectId &&
    (projectLinkDraft.editing || !!focusedForm?.isConnected);
}

async function loadProjects({afterCurrent = false, forceRender = false} = {}) {
  if (projectLoadPromise !== null) {
    await projectLoadPromise;
    if (!afterCurrent) return;
  }
  const generation = ++projectLoadGeneration;
  const request = (async () => {
    const result = await getJson("/api/projects");
    if (generation !== projectLoadGeneration) return;
    if (forceRender || !projectLinkFormIsEditing()) {
      renderProjects(result);
    } else {
      // An older poll may finish after editing begins. Keep its data without
      // replacing the focused form or discarding the user's draft.
      projectDocument = result;
    }
    serverBusy = serverBusy || result.busy;
  })();
  projectLoadPromise = request;
  try {
    await request;
  } finally {
    if (projectLoadPromise === request) projectLoadPromise = null;
  }
}

async function mutateProject(path, body) {
  beginMutation("Applying the revision-protected Project change…");
  try {
    await postJson(path, body);
    await loadProjects({afterCurrent: true, forceRender: true});
    setStatus("Project state verified and refreshed.", "success");
    return true;
  } catch (error) {
    showError(error.message);
    return false;
  } finally {
    endMutation();
  }
}

function renderCheckpoints(records) {
  checkpointList.replaceChildren();
  if (!records.length) {
    checkpointList.append(emptyState("No conversation checkpoints are saved."));
    return;
  }
  for (const checkpoint of records) {
    const article = recordCard();
    const heading = document.createElement("h3");
    heading.textContent = checkpoint.display_name || checkpoint.identifier;
    const details = document.createElement("dl");
    addDefinition(details, "Identifier", checkpoint.identifier);
    addDefinition(details, "Created", checkpoint.created_at);
    addDefinition(details, "Provider", checkpoint.provider);
    addDefinition(details, "Model", checkpoint.model);
    addDefinition(details, "Completed messages", checkpoint.message_count);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary mutation";
    remove.textContent = "Remove checkpoint";
    remove.addEventListener("click", () => requestCheckpointRemoval(checkpoint.identifier));
    article.append(heading, details, remove);
    checkpointList.append(article);
  }
  applyBusyState();
}

function renderMemories(records) {
  memoryList.replaceChildren();
  if (!records.length) {
    memoryList.append(emptyState("Tori has no canonical memories."));
    return;
  }
  for (const memory of records) {
    const article = recordCard();
    const heading = document.createElement("h3");
    heading.textContent = memory.identifier;
    const details = document.createElement("dl");
    addDefinition(details, "Category", memory.category);
    addDefinition(details, "Sensitivity", memory.sensitivity);
    addDefinition(details, "Provenance", memory.provenance);
    addDefinition(details, "Created", memory.created_at);
    addDefinition(details, "Updated", memory.updated_at);

    const label = document.createElement("label");
    const editorId = `edit-${memory.identifier}`;
    label.htmlFor = editorId;
    label.textContent = "Exact current text";
    const editor = document.createElement("textarea");
    editor.id = editorId;
    editor.rows = 3;
    editor.maxLength = 2000;
    editor.value = memory.text;

    const actions = document.createElement("div");
    actions.className = "record-actions";
    const update = document.createElement("button");
    update.type = "button";
    update.className = "mutation";
    update.textContent = "Update memory";
    update.addEventListener("click", () => updateMemory(memory, editor.value));
    const forget = document.createElement("button");
    forget.type = "button";
    forget.className = "secondary mutation";
    forget.textContent = "Forget memory";
    forget.addEventListener("click", () => requestMemoryForget(memory));
    actions.append(update, forget);
    article.append(heading, details, label, editor, actions);
    memoryList.append(article);
  }
  applyBusyState();
}

function renderKnowledge(sources, invalidRecords) {
  knowledgeList.replaceChildren();
  invalidRegistrationList.replaceChildren();
  if (!sources.length) {
    knowledgeList.append(emptyState("No local knowledge sources are registered."));
  }
  for (const source of sources) {
    const article = recordCard();
    const heading = document.createElement("h3");
    heading.textContent = source.filename;
    const details = document.createElement("dl");
    addDefinition(details, "Identifier", source.identifier);
    addDefinition(details, "Exact display path", source.display_path);
    addDefinition(details, "Type", source.file_type);
    addDefinition(details, "Registered", source.registered_at);
    addDefinition(details, "Availability", source.availability);
    addDefinition(details, "Bytes", source.byte_size);
    if (source.detail) {
      addDefinition(details, "Status detail", source.detail);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary mutation";
    remove.textContent = "Remove registration";
    remove.addEventListener("click", () => requestKnowledgeRemoval(source.identifier));
    article.append(heading, details, remove);
    knowledgeList.append(article);
  }
  if (invalidRecords.length) {
    const heading = document.createElement("h3");
    heading.textContent = "Invalid registration records";
    invalidRegistrationList.append(heading);
    for (const invalid of invalidRecords) {
      const paragraph = document.createElement("p");
      paragraph.textContent = `${invalid.filename}: ${invalid.detail}`;
      invalidRegistrationList.append(paragraph);
    }
  }
  applyBusyState();
}

function actionButton(label, callback, secondary = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `${secondary ? "secondary " : ""}mutation`;
  button.textContent = label;
  button.addEventListener("click", callback);
  return button;
}

function historyDeleteButton(kind, item) {
  const button = actionButton("Delete", () => requestHistoryDeletion(kind, item));
  button.className = "button danger mutation";
  return button;
}

function taskDetails(task) {
  const details = document.createElement("dl");
  addDefinition(details, "Status", task.status);
  addDefinition(details, "Revision", task.revision);
  addDefinition(details, "Updated", task.updated_at_utc);
  addDefinition(details, "Due", task.due_start_utc);
  return details;
}

function showTaskEditMode(article, task, normalActions) {
  const label = document.createElement("label");
  const editorId = `task-editor-${task.identifier}`;
  label.htmlFor = editorId;
  label.textContent = "Task description";
  const editor = document.createElement("input");
  editor.id = editorId;
  editor.value = task.description;
  editor.maxLength = 4000;
  const editActions = document.createElement("div");
  editActions.className = "record-actions task-edit-actions";
  const finishEditing = () => {
    editor.value = task.description;
    label.remove();
    editor.remove();
    editActions.remove();
    normalActions.hidden = false;
  };
  editActions.append(
    actionButton("Save", () => mutateOperational("/api/tasks/update", {
      identifier: task.identifier,
      expected_revision: task.revision,
      description: editor.value,
    })),
    actionButton("Cancel", finishEditing, true)
  );
  normalActions.hidden = true;
  article.append(label, editor, editActions);
  editor.focus();
}

function showReminderEditMode(article, reminder, normalActions) {
  const label = document.createElement("label");
  const editorId = `reminder-editor-${reminder.identifier}`;
  label.htmlFor = editorId;
  label.textContent = "Reminder text";
  const editor = document.createElement("input");
  editor.id = editorId;
  editor.value = reminder.reminder_text;
  editor.maxLength = 4000;
  const editActions = document.createElement("div");
  editActions.className = "record-actions reminder-edit-actions";
  const finishEditing = () => {
    editor.value = reminder.reminder_text;
    label.remove();
    editor.remove();
    editActions.remove();
    normalActions.hidden = false;
  };
  editActions.append(
    actionButton("Save", () => mutateOperational("/api/reminders/update", {
      identifier: reminder.identifier,
      expected_revision: reminder.revision,
      reminder_text: editor.value,
    })),
    actionButton("Cancel", finishEditing, true)
  );
  normalActions.hidden = true;
  article.append(label, editor, editActions);
  editor.focus();
}

function renderTasks(records, target = taskList, {history = false} = {}) {
  target.replaceChildren();
  if (!records.length) {
    target.append(emptyState(history ? "No completed or cancelled tasks." : "No open tasks."));
    return;
  }
  for (const task of records) {
    const article = recordCard();
    const heading = document.createElement("h3");
    heading.textContent = task.description;
    const actions = document.createElement("div");
    actions.className = "record-actions";
    if (!history) {
      actions.append(
        actionButton("Edit", () => showTaskEditMode(article, task, actions)),
        actionButton("Complete", () => mutateOperational("/api/tasks/complete", {identifier: task.identifier, expected_revision: task.revision})),
        actionButton("Cancel", () => mutateOperational("/api/tasks/cancel", {identifier: task.identifier, expected_revision: task.revision}), true)
      );
    } else {
      actions.append(historyDeleteButton("task", task));
    }
    actions.append(actionButton("Discuss", () => discussOperational("task", task), true));
    article.append(heading, taskDetails(task), actions);
    target.append(article);
  }
}

function renderReminders(records, target = reminderList, {history = false} = {}) {
  target.replaceChildren();
  if (!records.length) {
    target.append(emptyState(history ? "No resolved reminders." : "No scheduled or due reminders."));
    return;
  }
  for (const reminder of records) {
    const article = recordCard();
    const heading = document.createElement("h3");
    heading.textContent = reminder.reminder_text;
    const details = document.createElement("dl");
    addDefinition(details, "Status", reminder.status);
    addDefinition(details, "Schedule", reminder.scheduled_start_utc);
    addDefinition(details, "Window end", reminder.scheduled_end_utc);
    addDefinition(details, "Timezone", reminder.scheduled_timezone);
    addDefinition(details, "Linked task", reminder.task_id);
    addDefinition(details, "Revision", reminder.revision);
    const actions = document.createElement("div");
    actions.className = "record-actions";
    if (!history) {
      actions.append(
        actionButton("Edit", () => showReminderEditMode(article, reminder, actions)),
        actionButton("Done", () => mutateOperational("/api/reminders/done", {identifier: reminder.identifier, expected_revision: reminder.revision})),
        actionButton("Dismiss", () => mutateOperational("/api/reminders/dismiss", {identifier: reminder.identifier, expected_revision: reminder.revision}), true),
        actionButton("Delay 15 min", () => mutateOperational("/api/reminders/delay", {identifier: reminder.identifier, expected_revision: reminder.revision, preset: "15m"}), true),
        actionButton("Cancel reminder", () => mutateOperational("/api/reminders/cancel", {identifier: reminder.identifier, expected_revision: reminder.revision}), true)
      );
    } else {
      actions.append(historyDeleteButton("reminder", reminder));
    }
    actions.append(actionButton("Discuss", () => discussOperational("reminder", reminder), true));
    article.append(heading, details, actions);
    target.append(article);
  }
}

function newestFirst(records) {
  return [...records].sort((left, right) =>
    right.updated_at_utc.localeCompare(left.updated_at_utc) ||
    left.identifier.localeCompare(right.identifier)
  );
}

function scheduleText(schedule) {
  if (schedule.kind === "one_shot") {
    return `${schedule.occurrence_utc} (${schedule.timezone})`;
  }
  const days = schedule.kind === "weekly" ? ` · weekdays ${schedule.weekdays.join(", ")}` : "";
  return `${schedule.kind} at ${schedule.local_time} from ${schedule.start_date}${days} (${schedule.timezone})`;
}

function oneShotEditCivilValues(schedule) {
  if (!schedule || schedule.kind !== "one_shot") {
    throw new Error("Only one-shot scheduled work can use this edit form.");
  }
  const instant = new Date(schedule.occurrence_utc);
  if (Number.isNaN(instant.getTime())) {
    throw new Error("The persisted one-shot schedule is invalid.");
  }
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: schedule.timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const values = {};
  for (const part of formatter.formatToParts(instant)) {
    if (part.type !== "literal") values[part.type] = part.value;
  }
  const localDate = `${values.year}-${values.month}-${values.day}`;
  const localTime = `${values.hour}:${values.minute}`;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(localDate) || !/^\d{2}:\d{2}$/.test(localTime)) {
    throw new Error("The persisted one-shot schedule could not be displayed.");
  }
  return {localDate, localTime};
}

function resetScheduledEdit() {
  scheduledEditId = "";
  scheduledEditRevision = null;
  scheduledWorkTitle.value = "Back up Tori";
  scheduledWorkSubmit.textContent = "Review Authorization";
  scheduledWorkEditCancel.hidden = true;
}

function beginScheduledEdit(item) {
  const civil = oneShotEditCivilValues(item.schedule);
  scheduledEditId = item.identifier;
  scheduledEditRevision = item.revision;
  scheduledWorkTitle.value = item.title;
  scheduledWorkDate.value = civil.localDate;
  scheduledWorkTime.value = civil.localTime;
  scheduledWorkMissed.value = item.missed_policy;
  scheduledWorkSubmit.textContent = "Review Edited Authorization";
  scheduledWorkEditCancel.hidden = false;
  scheduledWorkTitle.focus();
}

function scheduledDefinitionCard(item, runs) {
  const article = recordCard();
  const heading = ui.createElement("h3", "", item.title);
  const summary = ui.createElement("p", "record-summary", `${item.capability_id} · ${item.status}`);
  const details = document.createElement("dl");
  const detailsKey = `definition:${item.identifier}`;
  details.hidden = !scheduledOpenDetails.has(detailsKey);
  addDefinition(details, "Identifier", item.identifier);
  addDefinition(details, "Revision", item.revision);
  addDefinition(details, "Authorization", item.current_authorization_id);
  addDefinition(details, "Capability contract", `${item.capability_id} v${item.capability_contract_version}`);
  addDefinition(details, "Schedule", scheduleText(item.schedule));
  addDefinition(details, "Timezone", item.timezone_name);
  addDefinition(details, "Next occurrence", item.next_occurrence_utc);
  addDefinition(details, "Missed policy", item.missed_policy);
  addDefinition(details, "Arguments", JSON.stringify(item.arguments));
  const latest = runs.find((run) => run.job_id === item.identifier);
  addDefinition(details, "Latest outcome", latest ? latest.status : "No runs yet");
  addDefinition(details, "Updated", item.updated_at_utc);
  const actions = ui.createElement("div", "record-actions");
  const detailsButton = actionButton("Details", () => {
    details.hidden = !details.hidden;
    if (details.hidden) {
      scheduledOpenDetails.delete(detailsKey);
    } else {
      scheduledOpenDetails.add(detailsKey);
    }
    detailsButton.textContent = details.hidden ? "Details" : "Hide Details";
  }, true);
  detailsButton.textContent = details.hidden ? "Details" : "Hide Details";
  actions.append(detailsButton);
  if (item.status === "active") {
    actions.append(
      actionButton("Edit", () => beginScheduledEdit(item), true),
      actionButton("Pause", () => mutateScheduled("pause", item), true),
      actionButton("Cancel", () => mutateScheduled("cancel", item), true)
    );
  } else if (item.status === "paused") {
    actions.append(
      actionButton("Edit", () => beginScheduledEdit(item), true),
      actionButton("Resume", () => mutateScheduled("resume", item)),
      actionButton("Cancel", () => mutateScheduled("cancel", item), true)
    );
  } else {
    actions.append(actionButton("Delete", () => requestScheduledDeletion("definition", item), true));
  }
  article.append(heading, summary, details, actions);
  return article;
}

function scheduledRunCard(run) {
  const article = recordCard();
  article.append(ui.createElement("h3", "", `${run.status}: ${run.capability_id}`));
  const details = document.createElement("dl");
  addDefinition(details, "Run", run.identifier);
  addDefinition(details, "Definition ID", run.job_id);
  addDefinition(details, "Definition revision", run.definition_revision);
  addDefinition(details, "Authorization", run.authorization_id);
  addDefinition(details, "Scheduled", run.scheduled_occurrence_utc);
  addDefinition(details, "Started", run.started_at_utc);
  addDefinition(details, "Finished", run.finished_at_utc);
  addDefinition(details, "Work started", run.work_started ? "Yes" : "No");
  addDefinition(details, "Failure", run.failure_message);
  addDefinition(details, "Missed occurrences", run.missed_occurrence_count);
  if (!["queued", "running"].includes(run.status)) {
    const actions = ui.createElement("div", "record-actions");
    actions.append(actionButton("Delete", () => requestScheduledDeletion("run", run), true));
    article.append(details, actions);
  } else {
    article.append(details);
  }
  return article;
}

function renderScheduled(documentBody) {
  const nextRevision = documentBody.scheduled_work_revision;
  if (scheduledRevision === nextRevision) {
    return false;
  }
  const survivingDetails = new Set(
    documentBody.definitions.map((item) => `definition:${item.identifier}`)
  );
  for (const detailsKey of scheduledOpenDetails) {
    if (!survivingDetails.has(detailsKey)) {
      scheduledOpenDetails.delete(detailsKey);
    }
  }
  scheduledRevision = nextRevision;
  document.dispatchEvent?.(new CustomEvent("tori:scheduledworkrevision", {
    detail: {revision: scheduledRevision},
  }));
  const groups = {
    active: scheduledWorkActive,
    paused: scheduledWorkPaused,
    history: scheduledWorkHistory,
  };
  for (const target of Object.values(groups)) target.replaceChildren();
  for (const item of documentBody.definitions) {
    const target = item.status === "active" ? groups.active : item.status === "paused" ? groups.paused : groups.history;
    target.append(scheduledDefinitionCard(item, documentBody.runs));
  }
  if (!groups.active.children.length) groups.active.append(emptyState("No active scheduled work."));
  if (!groups.paused.children.length) groups.paused.append(emptyState("No paused scheduled work."));
  if (!groups.history.children.length) groups.history.append(emptyState("No resolved scheduled-work definitions."));
  scheduledRunHistory.replaceChildren();
  for (const run of documentBody.runs) scheduledRunHistory.append(scheduledRunCard(run));
  if (!documentBody.runs.length) scheduledRunHistory.append(emptyState("No execution runs."));
  applyBusyState();
  return true;
}

async function loadScheduled() {
  const generation = ++scheduledLoadGeneration;
  const result = await getJson("/api/scheduled-work");
  if (generation !== scheduledLoadGeneration) return;
  renderScheduled(result);
}

async function mutateScheduled(action, item) {
  beginMutation(`Applying scheduled-work ${action}…`);
  try {
    await postJson(`/api/scheduled-work/${action}`, {identifier: item.identifier, expected_revision: item.revision});
    await loadScheduled();
    setStatus("Scheduled work refreshed.", "success");
  } catch (error) {
    showError(error.code === "stale_revision" ? "That scheduled work changed in another browser. It has been refreshed." : error.message);
    if (error.code === "stale_revision") await loadScheduled();
  } finally {
    endMutation();
  }
}

async function requestScheduledDeletion(kind, item) {
  beginMutation("Preparing permanent history deletion confirmation…");
  try {
    const result = await postJson("/api/scheduled-work/delete-history", {kind, identifier: item.identifier, expected_revision: item.revision});
    showConfirmation(result.confirmation);
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
}

async function loadOperational() {
  const generation = ++operationalLoadGeneration;
  const [tasks, reminders] = await Promise.all([
    getJson("/api/tasks"), getJson("/api/reminders"),
  ]);
  if (generation !== operationalLoadGeneration) {
    return;
  }
  const activeTasks = tasks.tasks.filter((task) => task.status === "open");
  const historicalTasks = newestFirst(tasks.tasks.filter((task) => ["completed", "cancelled"].includes(task.status)));
  const activeReminders = reminders.reminders.filter((reminder) => ["scheduled", "due"].includes(reminder.status));
  const historicalReminders = newestFirst(reminders.reminders.filter((reminder) => ["dismissed", "completed", "cancelled"].includes(reminder.status)));
  renderTasks(activeTasks);
  renderReminders(activeReminders);
  renderTasks(historicalTasks.slice(0, HISTORY_LIMIT), taskHistoryList, {history: true});
  renderReminders(historicalReminders.slice(0, HISTORY_LIMIT), reminderHistoryList, {history: true});
  operationalHistorySummary.textContent =
    `Showing up to ${HISTORY_LIMIT} recent records in each group · ` +
    `${historicalTasks.length} task history · ${historicalReminders.length} reminder history`;
}

async function mutateOperational(path, body) {
  beginMutation("Applying the revision-protected operational change…");
  try {
    await postJson(path, body);
    await loadOperational();
    setStatus("Tasks and reminders refreshed.", "success");
  } catch (error) {
    showError(error.code === "stale_revision" ? "That item changed in another browser. Refresh and review it before trying again." : error.message);
  } finally {
    endMutation();
  }
}

async function discussOperational(kind, item) {
  try {
    await postJson("/api/operational/discuss", {kind, identifier: item.identifier, expected_revision: item.revision});
    ui.navigate("conversation");
    document.getElementById("message").focus();
  } catch (error) {
    showError(error.message);
  }
}

async function loadCheckpoints() {
  const result = await getJson("/api/checkpoints");
  serverBusy = serverBusy || result.busy;
  renderCheckpoints(result.checkpoints);
}

async function loadMemories() {
  const result = await getJson("/api/memories");
  serverBusy = serverBusy || result.busy;
  renderMemories(result.memories);
}

async function loadKnowledge() {
  const result = await getJson("/api/knowledge");
  serverBusy = serverBusy || result.busy;
  renderKnowledge(result.sources, result.invalid_registrations);
}

async function refreshAll() {
  showError("");
  setStatus("Refreshing authoritative local data…");
  serverBusy = false;
  projectLinkTargets = null;
  try {
    await Promise.all([loadProjects(), loadMemories(), loadKnowledge(), loadOperational(), loadScheduled()]);
    managementLoaded = true;
    setStatus(
      serverBusy ? "Tori is working; management changes are temporarily unavailable." : "Local data is current.",
      serverBusy ? "warning" : "success"
    );
  } catch (error) {
    showError(error.message);
    setStatus("Some local data could not be refreshed.");
  } finally {
    applyBusyState();
  }
}

function formatReviewValue(value) {
  if (value === null) {
    return "null";
  }
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => formatReviewValue(item)).join(", ")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}: ${formatReviewValue(value[key])}`
    ).join(", ")}}`;
  }
  return "unreviewable";
}

function formatScheduledAuthorizationReview(proposal) {
  const schedule = proposal.schedule;
  const scheduleObject = schedule && typeof schedule === "object" && !Array.isArray(schedule) ? schedule : {};
  const lines = [
    `Operation: ${proposal.operation}`,
    `Title: ${proposal.title}`,
    `Capability: ${proposal.capability_id} v${proposal.capability_contract_version}`,
    `Arguments: ${formatReviewValue(proposal.arguments)}`,
    `Schedule: ${formatReviewValue(schedule)}`,
    `Schedule kind: ${scheduleObject.kind}`,
  ];
  if (scheduleObject.occurrence_utc !== undefined) {
    lines.push(`Occurrence UTC: ${scheduleObject.occurrence_utc}`);
  }
  if (scheduleObject.timezone !== undefined) {
    lines.push(`Timezone: ${scheduleObject.timezone}`);
  }
  lines.push(
    `Mode: ${proposal.scheduled_mode}`,
    `Missed-run policy: ${proposal.missed_policy}`,
    `Persistent permission: ${proposal.persistent_permission ? "YES" : "NO"}`,
    `Lifetime: ${proposal.application_lifetime}`,
  );
  if (proposal.dst_policy) {
    lines.push(`DST policy: ${proposal.dst_policy}`);
  }
  return lines.join("\n");
}

function showConfirmation(confirmation) {
  pendingHistoryDelete = null;
  pendingConfirmationToken = confirmation.token;
  confirmationHeading.textContent = "Confirm local change";
  confirmButton.textContent = "Confirm";
  confirmationMessage.textContent = confirmation.message;
  if (confirmation.action === "scheduled_work.authorize") {
    confirmationTarget.textContent = formatScheduledAuthorizationReview(
      confirmation.proposal
    );
    ui.openDialog(confirmationDialog, {
      returnFocus: document.activeElement,
      initialFocus: cancelButton,
    });
    return;
  }
  const target = confirmation.target || confirmation.proposal || {};
  const lines = [];
  for (const [label, value] of Object.entries(target)) {
    if (label === "source_unchanged") {
      lines.push("Source document: will remain unchanged");
    } else if (value !== null && value !== undefined) {
      lines.push(`${label}: ${String(value)}`);
    }
  }
  confirmationTarget.textContent = lines.join("\n");
  ui.openDialog(confirmationDialog, {
    returnFocus: document.activeElement,
    initialFocus: cancelButton,
  });
}

function requestHistoryDeletion(kind, item) {
  const isTask = kind === "task";
  pendingConfirmationToken = null;
  pendingHistoryDelete = {
    kind,
    identifier: item.identifier,
    expectedRevision: item.revision,
  };
  confirmationHeading.textContent = "Delete from History permanently?";
  confirmationMessage.textContent = isTask
    ? `Delete this ${item.status} task from History permanently?`
    : `Delete this ${item.status} reminder from History permanently?`;
  const visible = isTask ? item.description : item.reminder_text;
  confirmationTarget.textContent = `${isTask ? "Task" : "Reminder"}: ${visible.slice(0, 240)}`;
  confirmButton.textContent = "Delete permanently";
  ui.openDialog(confirmationDialog, {
    returnFocus: document.activeElement,
    initialFocus: cancelButton,
  });
}

async function requestCheckpointRemoval(identifier) {
  beginMutation("Preparing checkpoint confirmation…");
  try {
    const result = await postJson("/api/checkpoints/remove", {identifier});
    showConfirmation(result.confirmation);
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
}

async function updateMemory(memory, text) {
  beginMutation("Updating the selected memory…");
  try {
    await postJson("/api/memories/update", {
      identifier: memory.identifier,
      text,
      expected_updated_at: memory.updated_at,
    });
    await loadMemories();
    setStatus("Memory updated and refreshed.");
  } catch (error) {
    showError(error.code === "stale_target" ? "That memory changed. Refresh and review the current text before trying again." : error.message);
  } finally {
    endMutation();
  }
}

async function requestMemoryForget(memory) {
  beginMutation("Preparing memory confirmation…");
  try {
    const result = await postJson("/api/memories/forget", {
      identifier: memory.identifier,
      expected_updated_at: memory.updated_at,
    });
    showConfirmation(result.confirmation);
  } catch (error) {
    showError(error.code === "stale_target" ? "That memory changed. Refresh before confirming removal." : error.message);
  } finally {
    endMutation();
  }
}

async function requestKnowledgeRemoval(identifier) {
  beginMutation("Preparing registration confirmation…");
  try {
    const result = await postJson("/api/knowledge/remove", {identifier});
    showConfirmation(result.confirmation);
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
}

if (checkpointForm !== null) {
  checkpointForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    beginMutation("Saving the current completed conversation…");
    try {
      const value = checkpointName.value;
      await postJson("/api/checkpoints/save", {display_name: value || null});
      checkpointName.value = "";
      await loadCheckpoints();
      setStatus("Checkpoint saved and refreshed.");
    } catch (error) {
      showError(error.message);
    } finally {
      endMutation();
    }
  });
}

projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  beginMutation("Creating the explicit Project…");
  try {
    await postJson("/api/projects/create", {
      title: projectTitle.value.trim(),
      objective: projectObjective.value.trim(),
    });
    projectForm.reset();
    await loadProjects();
    setStatus("Project created and verified.", "success");
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
});

memoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  beginMutation("Creating the explicit memory…");
  try {
    await postJson("/api/memories/create", {text: memoryText.value});
    memoryText.value = "";
    await loadMemories();
    setStatus("Memory created and refreshed.");
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
});

knowledgeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  beginMutation("Registering the exact source path…");
  try {
    await postJson("/api/knowledge/register", {path: knowledgePath.value});
    knowledgePath.value = "";
    await loadKnowledge();
    setStatus("Knowledge registration created and refreshed.");
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
});

scheduledWorkForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  beginMutation("Preparing exact persistent authorization for review…");
  try {
    const body = {
      title: scheduledWorkTitle.value,
      local_date: scheduledWorkDate.value,
      local_time: scheduledWorkTime.value,
      missed_policy: scheduledWorkMissed.value,
    };
    if (scheduledEditId) {
      body.identifier = scheduledEditId;
      body.expected_revision = scheduledEditRevision;
    }
    const result = await postJson("/api/scheduled-work/propose-backup", body);
    showConfirmation(result.confirmation);
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
});
scheduledWorkEditCancel.addEventListener("click", resetScheduledEdit);

operationalHistoryToggle.addEventListener("click", () => {
  const opening = operationalHistory.hidden;
  operationalHistory.hidden = !opening;
  operationalHistoryToggle.setAttribute("aria-expanded", String(opening));
  operationalHistoryToggle.textContent = opening ? "Hide history" : "Show history";
});

async function completeConfirmation(decision) {
  const historyDelete = pendingHistoryDelete;
  pendingHistoryDelete = null;
  if (historyDelete) {
    ui.closeDialog(confirmationDialog);
    if (decision !== "confirm") {
      setStatus("History deletion cancelled.");
      return;
    }
    await mutateOperational(
      historyDelete.kind === "task"
        ? "/api/tasks/delete-history"
        : "/api/reminders/delete-history",
      {
        identifier: historyDelete.identifier,
        expected_revision: historyDelete.expectedRevision,
      }
    );
    return;
  }
  const token = pendingConfirmationToken;
  pendingConfirmationToken = null;
  ui.closeDialog(confirmationDialog);
  if (!token) {
    return;
  }
  beginMutation(decision === "confirm" ? "Applying the confirmed local change…" : "Cancelling the local change…");
  try {
    const result = await postJson("/api/confirm", {token, decision});
    if (decision === "confirm") {
      if (result.action === "memory_forget") {
        await loadMemories();
      } else if (result.action === "knowledge_remove") {
        await loadKnowledge();
      }
      if (result.scheduled_work_revision !== undefined) {
        resetScheduledEdit();
        await loadScheduled();
      }
      setStatus("Confirmed change completed and refreshed.");
    } else {
      setStatus("Local change cancelled.");
    }
  } catch (error) {
    showError(error.message);
  } finally {
    endMutation();
  }
}

confirmButton.addEventListener("click", () => completeConfirmation("confirm"));
cancelButton.addEventListener("click", () => completeConfirmation("cancel"));
confirmationDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  completeConfirmation("cancel");
});
for (const button of refreshAllButtons) {
  button.addEventListener("click", refreshAll);
}
for (const link of document.querySelectorAll('[data-view-link="projects"]')) {
  link.addEventListener("click", () => {
    selectedProjectId = null;
    if (projectDocument !== null) renderProjects(projectDocument);
  });
}

document.addEventListener("tori:viewchange", (event) => {
  if (event.detail.view !== "conversation" && !managementLoaded) {
    refreshAll();
  }
});

document.addEventListener("tori:operationalrevision", () => {
  if (ui.currentView() === "tasks" && managementLoaded && !localMutationBusy) {
    loadOperational().catch((error) => showError(error.message));
  }
});

document.addEventListener("tori:serverbusystatechange", (event) => {
  if (!event.detail || typeof event.detail.busy !== "boolean" ||
      serverBusy === event.detail.busy) {
    return;
  }
  serverBusy = event.detail.busy;
  applyBusyState();
  if (!localMutationBusy) {
    setStatus(
      serverBusy ? "Tori is working; management changes are temporarily unavailable." : "Local data is current.",
      serverBusy ? "warning" : "success"
    );
  }
});

function refreshScheduledCanonicalState() {
  if (ui.currentView() === "scheduled-work" && managementLoaded && !localMutationBusy) {
    loadScheduled().catch((error) => showError(error.message));
  }
}

function refreshProjectCanonicalState() {
  // Replacing the Home while a link form owns focus would discard user input.
  if (ui.currentView() === "projects" && managementLoaded && !localMutationBusy && !projectLinkFormIsEditing()) {
    loadProjects().catch((error) => showError(error.message));
  }
}

window.setInterval(refreshScheduledCanonicalState, 1500);
window.setInterval(refreshProjectCanonicalState, 1500);
window.addEventListener("focus", () => {
  refreshScheduledCanonicalState();
  refreshProjectCanonicalState();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshScheduledCanonicalState();
    refreshProjectCanonicalState();
  }
});

if (ui.currentView() !== "conversation") {
  refreshAll();
}
}());
