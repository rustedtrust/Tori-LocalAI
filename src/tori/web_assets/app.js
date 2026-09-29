"use strict";

(function initializeConversation() {
const ui = window.ToriUI;
const audioActivation = window.ToriAudio;
const conversation = document.getElementById("conversation");
const composer = document.getElementById("composer");
const messageInput = document.getElementById("message");
const sendButton = document.getElementById("send");
const newSessionButton = document.getElementById("new-session");
const chatList = document.getElementById("chat-list");
const chatHistoryError = document.getElementById("chat-history-error");
const refreshChatsButton = document.getElementById("refresh-chats");
const statusArea = document.getElementById("status");
const errorArea = document.getElementById("error");
const confirmationDialog = document.getElementById("confirmation");
const confirmationMessage = document.getElementById("confirmation-message");
const commandProposal = document.getElementById("command-proposal");
const acceptConfirmation = document.getElementById("accept-confirmation");
const cancelConfirmation = document.getElementById("cancel-confirmation");
const activeModel = document.getElementById("active-model");
const activeContext = document.getElementById("active-context");
const activeProject = document.getElementById("active-project");
const activeProjectLabel = document.getElementById("active-project-label");
const openModelControlsButton = document.getElementById("open-model-controls");
const modelContextDialog = document.getElementById("model-context-dialog");
const modelContextForm = document.getElementById("model-context-form");
const providerSelector = document.getElementById("provider-selector");
const modelSelector = document.getElementById("model-selector");
const contextSelector = document.getElementById("context-selector");
const contextCapacityNote = document.getElementById("context-capacity-note");
const contextDetailsList = document.getElementById("context-details-list");
const contextOmissionNote = document.getElementById("context-omission-note");
const modelDialogError = document.getElementById("model-dialog-error");
const refreshModelsButton = document.getElementById("refresh-models");
const cancelModelControlsButton = document.getElementById("cancel-model-controls");
const saveModelControlsButton = document.getElementById("save-model-controls");
const modelError = document.getElementById("model-error");
const autoSpeechButton = document.getElementById("auto-speech");
const stopSpeechButton = document.getElementById("stop-speech");
const voicePartial = document.getElementById("voice-partial");
const speechStatus = document.getElementById("speech-status");
const commandActivity = document.getElementById("command-activity");
const commandLabel = document.getElementById("command-label");
const commandStatus = document.getElementById("command-status");
const commandDetailsButton = document.getElementById("command-details");
const commandDetailsDialog = document.getElementById("command-details-dialog");
const closeCommandDetailsButton = document.getElementById("close-command-details");
const commandMetadata = document.getElementById("command-metadata");
const commandExact = document.getElementById("command-exact");
const commandStdout = document.getElementById("command-stdout");
const commandStderr = document.getElementById("command-stderr");
const stopCommandButton = document.getElementById("stop-command");
const dismissCommandButton = document.getElementById("dismiss-command");
const attentionCard = document.getElementById("attention-card");
const attentionText = document.getElementById("attention-text");
const attentionSchedule = document.getElementById("attention-schedule");
const attentionLinked = document.getElementById("attention-linked");
const attentionQueue = document.getElementById("attention-queue");
const attentionDetailsButton = document.getElementById("attention-details");
const attentionDoneButton = document.getElementById("attention-done");
const attentionDismissButton = document.getElementById("attention-dismiss");
const attentionDiscussButton = document.getElementById("attention-discuss");
const attentionDelayButtons = document.querySelectorAll(".attention-delay");
const attentionDelayCustomButton = document.getElementById("attention-delay-custom");
const reminderDetailsDialog = document.getElementById("reminder-details-dialog");
const reminderDetails = document.getElementById("reminder-details");
const closeReminderDetails = document.getElementById("close-reminder-details");
const reminderDelayDialog = document.getElementById("reminder-delay-dialog");
const reminderDelayForm = document.getElementById("reminder-delay-form");
const reminderDelayDate = document.getElementById("reminder-delay-date");
const reminderDelayTime = document.getElementById("reminder-delay-time");
const cancelReminderDelay = document.getElementById("cancel-reminder-delay");
const companionAttentionCard = document.getElementById("utility-attention-card");
const companionAttentionCount = document.getElementById("utility-attention-count");
const companionAttentionGroups = document.getElementById("utility-attention-groups");
const companionAttentionEmpty = document.getElementById("utility-attention-empty");

let busy = false;
let localConversationPending = false;
let pendingConfirmationToken = null;
let pendingConfirmationSource = null;
let pendingCommandProposal = null;
let pendingScheduledProposal = null;
let pendingSystemServiceProposal = null;
let pendingPlanningProposal = false;
let currentCommandInvocationId = null;
let commandPollTimer = null;
let commandPollGeneration = 0;
let renderedCommandStatus = null;
let dismissedCommandInvocationId = null;
let visibleTranscript = [];
let modelPending = false;
let modelCatalogDocument = null;
let speechAvailable = false;
let autoSpeech = false;
let activeSpeechSession = null;
let speechAbortController = null;
let nextPlaybackTime = 0;
let speechGeneration = 0;
let playbackCompletionTimer = null;
let conversationRequestGeneration = 0;
let activeForegroundKind = null;
let activeStreamingDraft = null;
let interruptedPresentations = [];
let composerRevision = 0;
let activeReminder = null;
let attentionRevision = 0;
let renderedChatId = null;
let renderedTranscriptRevision = 0;
let renderedChatListRevision = null;
let chatListRequestGeneration = 0;
let pendingTranscriptChatId = null;
let pendingTranscriptRevision = 0;
let attentionGeneration = 0;
let attentionPollTimer = null;
let attentionMutationPending = false;
let currentCompanionEventId = null;
let companionSettingsRevision = 0;
let upcomingPending = false;
let upcomingLoadedAt = 0;
let hostStatusPending = false;
let hostStatusLoadedAt = 0;
let codingWorkPending = false;
let codingWorkLoadedAt = 0;
let researchPending = false;
let researchLoadedAt = 0;
let companionAttentionPending = false;
const activeAudioSources = new Set();

const ROLE_LABELS = Object.freeze({
  user: "You",
  assistant: "Tori",
  system: "Local result",
  warning: "Notice",
  error: "Error",
});
const LOCAL_COMMANDS = new Set(Array.from(
  document.querySelectorAll("[data-browser-command]"),
  (element) => element.dataset.browserCommand
));
const COMMAND_SHAPED_PREFIX = /^\/[A-Za-z]+(?:-[A-Za-z]+)*(?:\s|$)/;

function roleLabel(role) {
  return ROLE_LABELS[role] || "Local result";
}

function entryLabel(entry) {
  if (entry.interrupted === true && entry.role === "assistant") {
    return "Tori · Interrupted — incomplete";
  }
  if (entry.role === "assistant" && typeof entry.provider === "string" &&
      typeof entry.model === "string") {
    return `${roleLabel(entry.role)} · ${entry.provider}/${entry.model}`;
  }
  if (entry.application_event?.type === "companion_initiative") {
    return "Tori · Check-in";
  }
  return roleLabel(entry.role);
}

function messageTimestamp(entry) {
  if (typeof entry.created_at !== "string") {
    return null;
  }
  const value = new Date(entry.created_at);
  if (Number.isNaN(value.valueOf())) {
    return null;
  }
  return {
    dateTime: entry.created_at,
    label: new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(value),
    title: new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(value),
  };
}

function isLocalCommand(message) {
  const command = message.trim().split(/\s+/, 1)[0].toLowerCase();
  if (command === "/search") {
    return false;
  }
  return LOCAL_COMMANDS.has(command) ||
    COMMAND_SHAPED_PREFIX.test(message.trim());
}

function sourceLocation(source) {
  return source.line_start === source.line_end
    ? `source line ${source.line_start}`
    : `source span ${source.line_start}–${source.line_end}`;
}

function formatVisibleTranscript(entries) {
  const blocks = [];
  for (const entry of entries) {
    const lines = [`${entryLabel(entry)}:`, entry.text];
    if (Array.isArray(entry.sources) && entry.sources.length > 0) {
      lines.push("Knowledge supplied:");
      for (const source of entry.sources) {
        lines.push(`- ${source.filename} — ${sourceLocation(source)}`);
      }
    }
    blocks.push(lines.join("\n"));
  }
  return blocks.join("\n\n");
}

function setBusy(value, statusText) {
  busy = value;
  sendButton.disabled = value;
  newSessionButton.disabled = value;
  openModelControlsButton.disabled = value || modelPending;
  providerSelector.disabled = value || modelPending;
  modelSelector.disabled = value || modelPending;
  contextSelector.disabled = value || modelPending;
  refreshModelsButton.disabled = value || modelPending;
  saveModelControlsButton.disabled = value || modelPending;
  autoSpeechButton.disabled = value || !speechAvailable;
  for (const button of conversation.querySelectorAll(".speak-message")) {
    button.disabled = value || !speechAvailable;
  }
  ui.setBusy(conversation, value);
  ui.setStatus(statusArea, statusText, value ? "busy" : "neutral");
  document.dispatchEvent(new CustomEvent("tori:conversationbusy", {detail: {busy: value}}));
}

function showError(message) {
  ui.showError(errorArea, message);
}

function commandIsActive(command) {
  return command && typeof command === "object" &&
    ["authorized", "starting", "running"].includes(command.status);
}

function commandIsTerminal(command) {
  return command && typeof command === "object" &&
    ["succeeded", "failed", "timed_out", "stopped", "rejected"].includes(
      command.status
    );
}

function commandStatusText(command) {
  const labels = {
    proposed: "Proposed",
    authorized: "Starting",
    starting: "Starting",
    running: "Running",
    succeeded: "Completed",
    failed: "Failed",
    timed_out: "Timed out",
    stopped: "Stopped",
    rejected: "Rejected",
  };
  const parts = [labels[command.status] || "Status unavailable"];
  if (Number.isInteger(command.exit_code)) {
    parts.push(`exit ${command.exit_code}`);
  }
  if (command.status === "succeeded" && command.stdout === "" &&
      command.stderr === "") {
    parts.push("no output");
  }
  return parts.join(" · ");
}

function renderCommandOutput(element, value, streamName, terminal) {
  const available = typeof value === "string";
  const empty = available && value.length === 0;
  element.dataset.empty = String(empty);
  if (!available) {
    element.textContent = terminal ? `${streamName} was not available.` :
      `Waiting for ${streamName}…`;
  } else if (empty) {
    element.textContent = `No ${streamName} output.`;
  } else {
    element.textContent = value;
  }
}

function renderCommand(command) {
  commandMetadata.replaceChildren();
  if (!command || typeof command !== "object" || Array.isArray(command)) {
    commandActivity.hidden = true;
    stopCommandButton.hidden = true;
    dismissCommandButton.hidden = true;
    currentCommandInvocationId = null;
    renderedCommandStatus = null;
    return;
  }
  const priorInvocation = currentCommandInvocationId;
  currentCommandInvocationId = typeof command.invocation_id === "string" ?
    command.invocation_id : null;
  renderedCommandStatus = command.status;
  if (currentCommandInvocationId !== dismissedCommandInvocationId) {
    dismissedCommandInvocationId = null;
  }
  if (commandIsTerminal(command) &&
      currentCommandInvocationId === dismissedCommandInvocationId) {
    commandActivity.hidden = true;
    stopCommandButton.hidden = true;
    dismissCommandButton.hidden = true;
    return;
  }
  commandActivity.hidden = false;
  commandLabel.textContent = typeof command.command === "string" ?
    command.command : "Supervised local command";
  commandStatus.textContent = commandStatusText(command);
  const details = [
    ["Status", command.status],
    ["Workspace", command.workspace],
    ["Isolation", command.isolation],
    ["Environment", command.environment],
    ["Timeout", Number.isFinite(command.timeout_seconds) ?
      `${command.timeout_seconds} seconds` : null],
    ["stdout bound", Number.isInteger(command.stdout_limit_bytes) ?
      `${command.stdout_limit_bytes} bytes` : null],
    ["stderr bound", Number.isInteger(command.stderr_limit_bytes) ?
      `${command.stderr_limit_bytes} bytes` : null],
    ["Exit code", Number.isInteger(command.exit_code) ? String(command.exit_code) : null],
    ["Termination", command.termination_reason],
    ["stdout truncated", command.stdout_truncated === true ? "yes" : null],
    ["stderr truncated", command.stderr_truncated === true ? "yes" : null],
  ];
  for (const [labelText, value] of details) {
    if (typeof value !== "string" || !value) {
      continue;
    }
    const term = document.createElement("dt");
    term.textContent = labelText;
    const description = document.createElement("dd");
    description.textContent = value;
    commandMetadata.append(term, description);
  }
  commandExact.textContent = typeof command.command === "string" ? command.command : "";
  const active = commandIsActive(command);
  renderCommandOutput(commandStdout, command.stdout, "stdout", !active);
  renderCommandOutput(commandStderr, command.stderr, "stderr", !active);
  stopCommandButton.hidden = !active;
  stopCommandButton.disabled = false;
  dismissCommandButton.hidden = !commandIsTerminal(command);
  if (priorInvocation !== currentCommandInvocationId && commandDetailsDialog.open) {
    ui.closeDialog(commandDetailsDialog);
  }
}

function stopCommandPolling() {
  commandPollGeneration += 1;
  if (commandPollTimer !== null) {
    window.clearTimeout(commandPollTimer);
    commandPollTimer = null;
  }
}

function startCommandPolling(invocationId) {
  if (typeof invocationId !== "string" || !invocationId) {
    return;
  }
  stopCommandPolling();
  const generation = commandPollGeneration;
  const poll = async () => {
    if (generation !== commandPollGeneration) {
      return;
    }
    try {
      const result = await ui.requestJson("/api/commands/active");
      const command = result.command;
      if (!command || command.invocation_id !== invocationId) {
        return;
      }
      renderCommand(command);
      if (!commandIsActive(command)) {
        stopCommandPolling();
        await loadSession();
        return;
      }
      setBusy(true, command.status === "running" ?
        "Supervised command running…" : "Starting supervised command…");
    } catch (error) {
      showError(error.message);
    }
    if (generation === commandPollGeneration) {
      commandPollTimer = window.setTimeout(poll, 400);
    }
  };
  commandPollTimer = window.setTimeout(poll, 200);
}

function formatCommandProposal(proposal) {
  const availability = proposal.isolation_available ? "available" : "UNAVAILABLE";
  return [
    `Command: ${proposal.command}`,
    `Workspace: ${proposal.workspace}`,
    `Isolation: ${proposal.isolation} (${availability})`,
    proposal.isolation_reason ? `Isolation notice: ${proposal.isolation_reason}` : null,
    `Environment: ${proposal.environment}`,
    `Timeout: ${proposal.timeout_seconds} seconds`,
    `Output bounds: stdout ${proposal.stdout_limit_bytes} bytes; stderr ${proposal.stderr_limit_bytes} bytes`,
  ].filter(Boolean).join("\n");
}

function formatScheduledProposal(proposal) {
  const schedule = proposal.schedule || {};
  const scheduleText = schedule.kind === "one_shot" ?
    `${schedule.occurrence_utc} (${schedule.timezone})` :
    `${schedule.kind} at ${schedule.local_time} from ${schedule.start_date} (${schedule.timezone})`;
  return [
    `Operation: ${proposal.operation}`,
    `Title: ${proposal.title}`,
    `Capability: ${proposal.capability_id} v${proposal.capability_contract_version}`,
    `Arguments: ${JSON.stringify(proposal.arguments)}`,
    `Schedule: ${scheduleText}`,
    `Mode: ${proposal.scheduled_mode}`,
    `Missed-run policy: ${proposal.missed_policy}`,
    `Persistent permission: ${proposal.persistent_permission ? "YES" : "NO"}`,
    `Lifetime: ${proposal.application_lifetime}`,
    proposal.dst_policy ? `DST policy: ${proposal.dst_policy}` : null,
  ].filter(Boolean).join("\n");
}

function formatSystemServiceProposal(proposal) {
  return [
    `Action: ${proposal.action}`,
    `Service: ${proposal.service}`,
    `System target: ${proposal.system_target}`,
    `Control: ${proposal.control}`,
  ].join("\n");
}

function renderTranscript(entries) {
  visibleTranscript = Array.isArray(entries) ? entries : [];
  interruptedPresentations = interruptedPresentations.filter((turn) => {
    const user = visibleTranscript[turn.afterIndex];
    const assistant = visibleTranscript[turn.afterIndex + 1];
    return !(user?.role === "user" && user.text === turn.user &&
      assistant?.role === "assistant" && assistant.text.startsWith(turn.text));
  });
  renderEntries(presentationEntries(visibleTranscript), true);
}

function presentationEntries(entries) {
  const presented = entries.map((entry, archiveIndex) => ({...entry, archiveIndex}));
  for (const turn of [...interruptedPresentations].sort(
    (left, right) => right.afterIndex - left.afterIndex
  )) {
    presented.splice(turn.afterIndex, 0,
      {role: "user", text: turn.user, interrupted: true},
      {role: "assistant", text: turn.text, interrupted: true});
  }
  return presented;
}

function preserveInterruptedDraft() {
  const draft = activeStreamingDraft;
  if (!draft || draft.generation !== conversationRequestGeneration) return;
  const text = draft.textElement.textContent.trim();
  if (!text) return;
  interruptedPresentations.push({
    afterIndex: draft.afterIndex,
    user: draft.user,
    text,
  });
}

function renderActiveProject(project) {
  const associated = project && typeof project === "object" &&
    typeof project.identifier === "string" && typeof project.title === "string";
  activeProject.hidden = !associated;
  activeProjectLabel.textContent = associated ?
    `${project.title} · ${project.status} · Context active` : "";
  window.ToriUtilityRail?.setProject(associated ? project : null);
}

function projectContextTier(label, items) {
  const section = document.createElement("section");
  const heading = document.createElement("h4");
  heading.textContent = label;
  section.append(heading);
  const list = document.createElement("ul");
  if (!Array.isArray(items) || items.length === 0) {
    const empty = document.createElement("li");
    empty.textContent = "No items supplied.";
    list.append(empty);
  } else {
    for (const item of items) {
      const row = document.createElement("li");
      row.textContent = `${item.label}: ${item.value}`;
      list.append(row);
    }
  }
  section.append(list);
  return section;
}

function projectContextDisclosure(receipt) {
  const details = document.createElement("details");
  details.className = "project-context-disclosure";
  const summary = document.createElement("summary");
  summary.textContent = "Project context used";
  details.append(summary);
  const identity = document.createElement("p");
  identity.className = "project-context-metadata";
  identity.textContent = `Chat ${receipt.chat_id} · assistant turn ${receipt.assistant_sequence} · ` +
    `Project revision ${receipt.project_revision} · input allowance ~${formatTokenCount(receipt.budget_tokens)} tokens`;
  details.append(identity);
  details.append(
    projectContextTier("Stable", receipt.stable),
    projectContextTier("Working", receipt.working),
    projectContextTier("Historical", receipt.historical),
  );
  const omitted = document.createElement("section");
  const omittedHeading = document.createElement("h4");
  omittedHeading.textContent = "Not loaded";
  const omittedList = document.createElement("ul");
  if (receipt.omissions.length === 0) {
    const none = document.createElement("li");
    none.textContent = "Nothing recorded as omitted.";
    omittedList.append(none);
  } else {
    for (const item of receipt.omissions) {
      const row = document.createElement("li");
      const identity = typeof item.source_id === "string" ? ` · ${item.source_id}` : "";
      const count = Number.isInteger(item.count) ? ` · ${item.count} item(s)` : "";
      row.textContent = `${item.provenance} · ${item.reason}${identity}${count}`;
      omittedList.append(row);
    }
  }
  omitted.append(omittedHeading, omittedList);
  const exact = document.createElement("details");
  const exactSummary = document.createElement("summary");
  exactSummary.textContent = "Exact provider-visible Project context";
  const rendered = document.createElement("pre");
  rendered.textContent = receipt.rendered_context;
  const digest = document.createElement("p");
  digest.textContent = `SHA-256 ${receipt.rendered_digest} · ~${formatTokenCount(receipt.estimated_tokens)} tokens · ${receipt.estimator_version}`;
  exact.append(exactSummary, rendered, digest);
  details.append(omitted, exact);
  return details;
}

function isNearConversationBottom() {
  return conversation.scrollHeight - conversation.scrollTop -
    conversation.clientHeight <= 96;
}

function followConversationIfNeeded(shouldFollow) {
  if (shouldFollow) {
    conversation.scrollTop = conversation.scrollHeight;
  }
}

function renderEntries(entries, authoritative = false) {
  const shouldFollow = conversation.childElementCount === 0 ||
    isNearConversationBottom();
  conversation.replaceChildren();
  entries.forEach((entry, entryIndex) => {
    const article = document.createElement("article");
    article.className = `message ${entry.role}`;
    if (entry.interrupted === true) article.classList.add("interrupted");
    if (entry.application_event?.type === "companion_initiative") {
      article.classList.add("companion-check-in");
    }

    const metadata = document.createElement("div");
    metadata.className = "message-header";
    const label = document.createElement("strong");
    label.textContent = entryLabel(entry);
    metadata.append(label);
    const timestamp = messageTimestamp(entry);
    if (timestamp !== null) {
      const time = document.createElement("time");
      time.className = "message-timestamp";
      time.dateTime = timestamp.dateTime;
      time.title = timestamp.title;
      time.setAttribute("aria-label", timestamp.title);
      time.textContent = timestamp.label;
      metadata.append(time);
    }
    article.append(metadata);

    const text = document.createElement("p");
    text.textContent = entry.text;
    article.append(text);

    if (Array.isArray(entry.sources) && entry.sources.length > 0) {
      const sourceTitle = document.createElement("span");
      sourceTitle.className = "source-title";
      sourceTitle.textContent = "Knowledge supplied:";
      article.append(sourceTitle);
      const list = document.createElement("ul");
      list.className = "sources";
      for (const source of entry.sources) {
        const item = document.createElement("li");
        item.textContent = `${source.filename} — ${sourceLocation(source)}`;
        list.append(item);
      }
      article.append(list);
    }
    if (entry.project_context_receipt) {
      article.append(projectContextDisclosure(entry.project_context_receipt));
    }
    if (authoritative && entry.role === "assistant" && entry.interrupted !== true) {
      const speak = document.createElement("button");
      speak.className = "button secondary speak-message";
      speak.type = "button";
      speak.textContent = "Speak";
      speak.dataset.entryIndex = String(entry.archiveIndex ?? entryIndex);
      speak.disabled = busy || !speechAvailable;
      speak.addEventListener("click", () => replayAssistantMessage(
        entry.archiveIndex ?? entryIndex
      ));
      speak.setAttribute("aria-label", "Speak this message");
      metadata.append(speak);
      const initiativeEventId = entry.application_event?.type === "companion_initiative" &&
        typeof entry.application_event.id === "string" ? entry.application_event.id : null;
      if (initiativeEventId !== null && initiativeEventId === currentCompanionEventId) {
        const actions = document.createElement("div");
        actions.className = "message-actions";
        const dismiss = document.createElement("button");
        dismiss.className = "button secondary dismiss-initiative";
        dismiss.type = "button";
        dismiss.textContent = "Dismiss";
        dismiss.addEventListener("click", () => dismissCompanionInitiative(initiativeEventId));
        const pauseDay = document.createElement("button");
        pauseDay.className = "button secondary pause-initiative";
        pauseDay.type = "button";
        pauseDay.textContent = "Pause 1 day";
        pauseDay.addEventListener("click", () => pauseCompanionInitiative(
          "one_day", initiativeEventId
        ));
        const pauseWeek = document.createElement("button");
        pauseWeek.className = "button secondary pause-initiative";
        pauseWeek.type = "button";
        pauseWeek.textContent = "Pause 1 week";
        pauseWeek.addEventListener("click", () => pauseCompanionInitiative(
          "one_week", initiativeEventId
        ));
        actions.append(dismiss, pauseDay, pauseWeek);
        article.append(actions);
      }
    }
    conversation.append(article);
  });
  followConversationIfNeeded(shouldFollow);
}

function renderPendingUserMessage(message) {
  renderEntries(presentationEntries([
    ...visibleTranscript,
    {role: "user", text: message},
  ]), false);
}

function renderStreamingDraft(message) {
  renderEntries(presentationEntries([
    ...visibleTranscript,
    {role: "user", text: message},
    {role: "assistant", text: ""},
  ]), false);
  const draft = conversation.lastElementChild;
  draft.classList.add("streaming");
  draft.setAttribute("aria-label", "Tori response draft");
  return draft.querySelector("p");
}

async function copyChatTranscript(chat) {
  let entries;
  try {
    const result = await request("/api/chats/transcript", {
      identifier: chat.identifier,
      expected_revision: chat.revision,
    });
    entries = result.transcript;
  } catch (error) {
    chatHistoryError.textContent = error.message;
    chatHistoryError.hidden = false;
    return;
  }
  const transcript = formatVisibleTranscript(entries);
  if (!transcript) {
    statusArea.textContent = `“${chat.label}” has no transcript to copy.`;
    return;
  }
  try {
    await navigator.clipboard.writeText(transcript);
    statusArea.textContent = `Transcript copied from “${chat.label}”.`;
  } catch (_error) {
    statusArea.textContent = `Could not copy the transcript from “${chat.label}”.`;
  }
}

async function request(path, body) {
  try {
    return await ui.requestJson(path, {method: "POST", body});
  } catch (error) {
    const documentBody = error.document || {};
    if (Array.isArray(documentBody.transcript)) {
      renderTranscript(documentBody.transcript);
    }
    error.authoritativeTranscript =
      Array.isArray(documentBody.transcript) ? documentBody.transcript : null;
    throw error;
  }
}

function chatMetadataLine(chat, activeChatId) {
  const active = chat.identifier === activeChatId ? "Active · " : "";
  const turns = `${chat.completed_turn_count} ${chat.completed_turn_count === 1 ? "turn" : "turns"}`;
  const timestamp = new Date(chat.updated_at);
  const updated = Number.isNaN(timestamp.valueOf()) ? chat.updated_at :
    new Intl.DateTimeFormat(undefined, {month: "short", day: "numeric"}).format(timestamp);
  const model = typeof chat.latest_provider === "string" &&
    typeof chat.latest_model === "string" ?
    ` · ${chat.latest_provider}/${chat.latest_model}` : "";
  return `${active}${turns} · ${updated}${model}`;
}

async function projectTitlesForChats(chats) {
  if (!chats.some((chat) => typeof chat.project_id === "string")) {
    return new Map();
  }
  try {
    const documentBody = await ui.requestJson("/api/projects/labels");
    return new Map((documentBody.projects || []).map((project) => [
      project.identifier, project.title,
    ]));
  } catch (_error) {
    return new Map();
  }
}

async function openArchivedChat(chat) {
  stopSpeaking({resetAudio: true});
  const result = await request("/api/chats/open", {
    identifier: chat.identifier,
    expected_revision: chat.revision,
  });
  renderTranscript(result.transcript);
  renderSelectedModel(result.selected_model);
  renderContextState(result.context);
  renderActiveProject(result.project);
  ui.navigate("conversation");
  messageInput.focus();
  await loadModels();
  ui.setStatus(statusArea, "Archived conversation opened · Connected locally", "success");
  await loadChats();
  return result;
}

async function loadChats() {
  const generation = ++chatListRequestGeneration;
  chatHistoryError.hidden = true;
  chatHistoryError.textContent = "";
  try {
    const documentBody = await ui.requestJson("/api/chats");
    if (generation !== chatListRequestGeneration) return;
    const chats = Array.isArray(documentBody.chats) ? documentBody.chats : [];
    const projectTitles = await projectTitlesForChats(chats);
    if (generation !== chatListRequestGeneration) return;
    renderedChatListRevision = typeof documentBody.chat_list_revision === "string" ?
      documentBody.chat_list_revision : renderedChatListRevision;
    chatList.replaceChildren();
    if (chats.length === 0) {
      const empty = document.createElement("p");
      empty.textContent = "No archived conversations yet.";
      chatList.append(empty);
      return;
    }
    for (const chat of chats) {
      const card = document.createElement("article");
      card.className = "chat-history-row";
      if (chat.identifier === documentBody.active_chat_id) {
        card.dataset.active = "true";
      }
      const summary = document.createElement("button");
      summary.className = "chat-history-open";
      summary.type = "button";
      const heading = document.createElement("h3");
      heading.textContent = chat.label;
      const metadata = document.createElement("p");
      metadata.textContent = chatMetadataLine(chat, documentBody.active_chat_id);
      if (projectTitles.has(chat.project_id)) {
        const project = document.createElement("span");
        project.className = "chat-project-badge";
        project.textContent = projectTitles.get(chat.project_id);
        summary.append(project);
      }
      summary.prepend(heading, metadata);
      summary.addEventListener("click", async () => {
        try {
          await openArchivedChat(chat);
        } catch (error) {
          chatHistoryError.textContent = error.message;
          chatHistoryError.hidden = false;
        }
      });
      const actions = document.createElement("details");
      actions.className = "chat-row-actions";
      const actionToggle = document.createElement("summary");
      actionToggle.textContent = "•••";
      actionToggle.setAttribute("aria-label", `Actions for ${chat.label}`);
      actionToggle.title = "Conversation actions";
      const actionMenu = document.createElement("div");
      actionMenu.className = "chat-row-action-menu";
      const copyButton = document.createElement("button");
      copyButton.className = "chat-row-action";
      copyButton.type = "button";
      copyButton.textContent = "Copy transcript";
      copyButton.addEventListener("click", async () => {
        actions.open = false;
        await copyChatTranscript(chat);
      });
      const renameButton = document.createElement("button");
      renameButton.className = "chat-row-action";
      renameButton.type = "button";
      renameButton.textContent = "Rename";
      renameButton.addEventListener("click", async () => {
        actions.open = false;
        const requested = window.prompt("Rename conversation", chat.label);
        if (requested === null || requested.trim() === chat.label) return;
        try {
          await request("/api/chats/rename", {
            identifier: chat.identifier,
            expected_revision: chat.revision,
            label: requested.trim(),
          });
          await loadChats();
        } catch (error) {
          chatHistoryError.textContent = error.message;
          chatHistoryError.hidden = false;
          await loadChats();
        }
      });
      const deleteButton = document.createElement("button");
      deleteButton.className = "chat-row-action danger";
      deleteButton.type = "button";
      deleteButton.textContent = "Delete";
      deleteButton.addEventListener("click", async () => {
        actions.open = false;
        if (!window.confirm(`Delete archived conversation “${chat.label}”?`)) {
          return;
        }
        try {
          stopSpeaking({resetAudio: true});
          const result = await request("/api/chats/delete", {
            identifier: chat.identifier,
            expected_revision: chat.revision,
          });
          renderTranscript(result.transcript);
          await loadChats();
        } catch (error) {
          chatHistoryError.textContent = error.message;
          chatHistoryError.hidden = false;
        }
      });
      actionMenu.append(copyButton, renameButton, deleteButton);
      actions.append(actionToggle, actionMenu);
      card.append(summary, actions);
      chatList.append(card);
    }
  } catch (error) {
    if (generation === chatListRequestGeneration) {
      chatHistoryError.textContent = error.message;
      chatHistoryError.hidden = false;
    }
  }
}

async function loadUpcoming() {
  if (upcomingPending) return;
  upcomingPending = true;
  try {
    const documentBody = await ui.requestJson("/api/upcoming");
    window.ToriUtilityRail?.setUpcoming(documentBody);
    const active = documentBody.active_scheduled_work;
    const nightOwl = documentBody.active_night_owl;
    const activityCard = document.getElementById("utility-activity-card");
    if (nightOwl && !busy && !activeSpeechSession && !commandIsActive({
      invocation_id: currentCommandInvocationId,
      status: renderedCommandStatus,
    })) {
      const trigger = nightOwl.trigger === "scheduled" ? "Scheduled" : "On-demand";
      window.ToriUtilityRail?.setActivity(
        "Night Owl research",
        `${trigger} bounded background research is running.`,
        "busy",
        "night-owl"
      );
    } else if (active && !busy && !activeSpeechSession && !commandIsActive({
      invocation_id: currentCommandInvocationId,
      status: renderedCommandStatus,
    })) {
      window.ToriUtilityRail?.setActivity(
        "Scheduled work",
        `${active.label} · ${active.status}`,
        "busy",
        "scheduled-work"
      );
    } else if (["night-owl", "scheduled-work"].includes(activityCard?.dataset.source)) {
      window.ToriUtilityRail?.setActivity();
    }
  } catch (_error) {
    window.ToriUtilityRail?.setUpcoming({items: [], unavailable: true});
  } finally {
    upcomingLoadedAt = Date.now();
    upcomingPending = false;
  }
}

async function loadCodingWork() {
  if (codingWorkPending) return;
  codingWorkPending = true;
  try {
    const documentBody = await ui.requestJson("/api/coding-work");
    window.ToriUtilityRail?.setCodingWork(documentBody);
  } catch (_error) {
    window.ToriUtilityRail?.setCodingWork({work: []});
  } finally {
    codingWorkLoadedAt = Date.now();
    codingWorkPending = false;
  }
}

async function loadResearch() {
  if (researchPending) return;
  researchPending = true;
  try {
    window.ToriUtilityRail?.setResearch(await ui.requestJson("/api/research"));
  } catch (_error) {
    window.ToriUtilityRail?.setResearch({jobs: []});
  } finally {
    researchLoadedAt = Date.now();
    researchPending = false;
  }
}

function attentionSourceTarget(source) {
  return {
    research: "utility-research-card",
    coding_work: "utility-coding-work-card",
    night_owl: null,
    scheduled_work: null,
  }[source] || null;
}

const ATTENTION_SOURCE_LABELS = Object.freeze({
  research: "Research",
  coding_work: "Coding Work",
  night_owl: "Night Owl",
  scheduled_work: "Scheduled Work",
});

async function mutateCompanionAttention(item, action) {
  try {
    const result = await request("/api/companion-attention/action", {
      identifier: item.identifier,
      expected_revision: item.revision,
      action,
    });
    renderCompanionAttention(result);
    await loadCompanionAttention();
    if (action === "review") {
      if (item.source === "scheduled_work") {
        window.ToriUI?.navigate("scheduled-work");
      } else if (item.source === "night_owl") {
        window.ToriUI?.navigate("settings");
      } else {
        document.getElementById(attentionSourceTarget(item.source))?.scrollIntoView({block: "nearest"});
      }
    }
  } catch (error) {
    showError(error.message);
    await loadCompanionAttention();
  }
}

function renderCompanionAttention(documentBody, security) {
  const items = Array.isArray(documentBody?.items) ? documentBody.items : [];
  companionAttentionGroups.replaceChildren();
  const sections = [
    ["needs_attention", "Needs attention", items.filter((item) => ["open", "deferred"].includes(item.state) && item.attention_class === "needs_attention")],
    ["worth_reviewing", "Worth reviewing", items.filter((item) => ["open", "deferred"].includes(item.state) && item.attention_class !== "needs_attention")],
    ["resolved", "Recently resolved", items.filter((item) => ["resolved", "dismissed", "reviewed"].includes(item.state)).slice(0, 3)],
  ];
  const activeCount = items.filter((item) => ["open", "deferred"].includes(item.state)).length;
  const securityCount = Number.isInteger(security?.attention_count) ? Math.min(9, security.attention_count) : 0;
  companionAttentionCount.textContent = String(activeCount + securityCount);
  if (securityCount > 0) {
    const row = document.createElement("section");
    row.className = "attention-workspace-group";
    const title = document.createElement("strong");
    title.textContent = `Security — ${securityCount} new high-interest threat intelligence finding${securityCount === 1 ? "" : "s"}`;
    const action = document.createElement("button");
    action.type = "button";
    action.className = "button secondary";
    action.textContent = "Review";
    action.addEventListener("click", () => ui.navigate("security"));
    row.append(title, action);
    companionAttentionGroups.append(row);
  }
  for (const [key, label, entries] of sections) {
    if (!entries.length) continue;
    const section = document.createElement("section");
    section.className = "attention-workspace-group";
    const heading = document.createElement("h4");
    heading.textContent = label;
    section.append(heading);
    for (const item of entries) {
      const article = document.createElement("article");
      article.className = "attention-workspace-item";
      article.dataset.kind = key;
      const title = document.createElement("strong");
      title.textContent = item.title;
      const meta = document.createElement("p");
      meta.className = "attention-workspace-meta";
      meta.textContent = `${ATTENTION_SOURCE_LABELS[item.source] || item.source} · ${item.state}`;
      article.append(title, meta);
      if (item.state === "deferred" && item.deferred_until_utc) {
        const deferred = document.createElement("small");
        deferred.className = "attention-workspace-state";
        const until = new Date(item.deferred_until_utc);
        const label = Number.isNaN(until.valueOf()) ? item.deferred_until_utc :
          new Intl.DateTimeFormat(undefined, {
            dateStyle: "medium", timeStyle: "short",
          }).format(until);
        deferred.textContent = `Deferred until ${label}`;
        article.append(deferred);
      }
      if (["open", "deferred"].includes(item.state)) {
        const actions = document.createElement("div");
        actions.className = "attention-workspace-actions";
        for (const [action, text] of [["review", "Review"], ["later", "Later"], ["dismiss", "Dismiss"]]) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "button secondary";
          button.textContent = text;
          button.addEventListener("click", () => mutateCompanionAttention(item, action));
          actions.append(button);
        }
        article.append(actions);
      }
      section.append(article);
    }
    companionAttentionGroups.append(section);
  }
  companionAttentionEmpty.hidden = activeCount + securityCount !== 0;
  companionAttentionCard.hidden = items.length === 0 && securityCount === 0;
}

async function loadCompanionAttention() {
  if (companionAttentionPending) return;
  companionAttentionPending = true;
  try {
    let attention = {items: []};
    try { attention = await ui.requestJson("/api/companion-attention"); } catch (_error) { /* optional companion attention */ }
    let security = null;
    try { security = await ui.requestJson("/api/security"); } catch (_error) { /* keep existing attention */ }
    renderCompanionAttention(attention, security);
  } catch (_error) {
    companionAttentionCard.hidden = true;
  } finally {
    companionAttentionPending = false;
  }
}
document.addEventListener("tori:securitychanged", loadCompanionAttention);
document.addEventListener("tori:viewchange", (event) => {
  if (event.detail?.view === "home") loadCompanionAttention();
});

async function loadHostStatus() {
  if (hostStatusPending) return;
  hostStatusPending = true;
  try {
    window.ToriUtilityRail?.setHostStatus(await ui.requestJson("/api/host-status"));
  } catch (_error) {
    window.ToriUtilityRail?.setHostStatus(null);
  } finally {
    hostStatusLoadedAt = Date.now();
    hostStatusPending = false;
  }
}

document.addEventListener("tori:operationalrevision", loadUpcoming);
document.addEventListener("tori:scheduledworkrevision", loadUpcoming);
document.addEventListener("tori:nightowlrevision", loadUpcoming);

function exactFields(record, expected) {
  const actual = Object.keys(record).sort();
  return actual.length === expected.length &&
    actual.every((field, index) => field === expected[index]);
}

function validTranscript(entries) {
  if (!Array.isArray(entries)) {
    return false;
  }
  return entries.every((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      return false;
    }
    const expected = ["role", "text"];
    if (Object.hasOwn(entry, "sources")) {
      expected.push("sources");
    }
    if (Object.hasOwn(entry, "web_search")) {
      expected.push("web_search");
    }
    if (Object.hasOwn(entry, "created_at")) {
      expected.push("created_at");
    }
    if (Object.hasOwn(entry, "provider") || Object.hasOwn(entry, "model")) {
      expected.push("provider", "model");
    }
    if (Object.hasOwn(entry, "application_event")) {
      expected.push("application_event");
    }
    if (Object.hasOwn(entry, "project_context_receipt")) {
      expected.push("project_context_receipt");
    }
    expected.sort();
    if (!exactFields(entry, expected) ||
        !Object.hasOwn(ROLE_LABELS, entry.role) ||
        typeof entry.text !== "string") {
      return false;
    }
    if (Object.hasOwn(entry, "provider") &&
        (entry.role !== "assistant" || typeof entry.provider !== "string" ||
         !entry.provider || typeof entry.model !== "string" || !entry.model)) {
      return false;
    }
    if (Object.hasOwn(entry, "created_at") &&
        (typeof entry.created_at !== "string" ||
         !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(entry.created_at))) {
      return false;
    }
    if (Object.hasOwn(entry, "application_event")) {
      const applicationEvent = entry.application_event;
      if (entry.role !== "assistant" || !applicationEvent ||
          typeof applicationEvent !== "object" || Array.isArray(applicationEvent) ||
          !exactFields(applicationEvent, ["id", "type"]) ||
          applicationEvent.type !== "companion_initiative" ||
          typeof applicationEvent.id !== "string" ||
          !/^event-[0-9a-f]{32}$/.test(applicationEvent.id)) {
        return false;
      }
    }
    if (Object.hasOwn(entry, "project_context_receipt") &&
        !validProjectContextReceipt(entry.project_context_receipt, entry.role)) {
      return false;
    }
    if (Object.hasOwn(entry, "web_search")) {
      const search = entry.web_search;
      if (entry.role !== "assistant" || !search || typeof search !== "object" ||
          Array.isArray(search) ||
          !exactFields(search, ["query", "sources", "status"]) ||
          typeof search.query !== "string" || search.status !== "completed" ||
          !Array.isArray(search.sources) || !search.sources.every((source) =>
            source && typeof source === "object" && !Array.isArray(source) &&
            exactFields(source, ["title", "url"]) &&
            typeof source.title === "string" && typeof source.url === "string")) {
        return false;
      }
    }
    return !Object.hasOwn(entry, "sources") || (Array.isArray(entry.sources) && entry.sources.every((source) =>
      source && typeof source === "object" && !Array.isArray(source) &&
      exactFields(source, ["filename", "line_end", "line_start"]) &&
      typeof source.filename === "string" &&
      Number.isInteger(source.line_start) && source.line_start > 0 &&
      Number.isInteger(source.line_end) &&
      source.line_end >= source.line_start
    ));
  });
}

function validProjectContextReceipt(receipt, role) {
  if (role !== "assistant" || !receipt || typeof receipt !== "object" ||
      Array.isArray(receipt) || !exactFields(receipt, [
        "assistant_sequence", "budget_tokens", "chat_id", "created_at", "estimated_tokens",
        "estimator_version", "format_version", "historical", "omissions",
        "project_id", "project_revision", "rendered_context", "rendered_digest",
        "stable", "working",
      ])) {
    return false;
  }
  const tiers = [receipt.stable, receipt.working, receipt.historical];
  return receipt.format_version === 1 &&
    /^chat-[0-9a-f]{32}$/.test(receipt.chat_id) &&
    /^project-[0-9a-f]{32}$/.test(receipt.project_id) &&
    Number.isInteger(receipt.project_revision) && receipt.project_revision > 0 &&
    Number.isInteger(receipt.assistant_sequence) && receipt.assistant_sequence >= 0 &&
    Number.isInteger(receipt.budget_tokens) && receipt.budget_tokens > 0 &&
    Number.isInteger(receipt.estimated_tokens) && receipt.estimated_tokens > 0 &&
    typeof receipt.estimator_version === "string" && receipt.estimator_version.length > 0 &&
    typeof receipt.rendered_context === "string" && receipt.rendered_context.length > 0 &&
    /^[0-9a-f]{64}$/.test(receipt.rendered_digest) &&
    typeof receipt.created_at === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(receipt.created_at) &&
    tiers.every((tier) => Array.isArray(tier) && tier.every((item) =>
      item && typeof item === "object" && !Array.isArray(item) &&
      exactFields(item, ["key", "label", "provenance", "source_id", "value"]) &&
      Object.values(item).every((value) => typeof value === "string"))) &&
    Array.isArray(receipt.omissions) && receipt.omissions.every((item) =>
      item && typeof item === "object" && !Array.isArray(item) &&
      ["category", "provenance", "reason"].every((field) => Object.hasOwn(item, field)) &&
      Object.keys(item).every((field) =>
        ["category", "provenance", "reason", "source_id", "count"].includes(field)) &&
      typeof item.category === "string" && typeof item.provenance === "string" &&
      ["stable", "working", "historical", "multiple"].includes(item.category) &&
      ["budget", "not_relevant", "source_not_loaded", "unavailable"].includes(item.reason) &&
      (!Object.hasOwn(item, "source_id") || typeof item.source_id === "string") &&
      (!Object.hasOwn(item, "count") ||
        (Number.isInteger(item.count) && item.count > 0)));
}

function validTerminalRequest(request) {
  if (!request || typeof request !== "object" || Array.isArray(request) ||
      !["BLACKLIST", "ALWAYS_ASK", "WHITELIST", "DEFAULT_ASK"].includes(request.policy)) {
    return false;
  }
  const expected = ["command", "cwd", "policy", "reason", "rule_id", "scope", "source"];
  if (request.policy === "WHITELIST") expected.push("session_id");
  if (["ALWAYS_ASK", "DEFAULT_ASK"].includes(request.policy)) {
    expected.push("expires_in_seconds", "proposal_token");
  }
  if (!exactFields(request, expected.sort()) ||
      typeof request.command !== "string" || !request.command ||
      typeof request.cwd !== "string" || !request.cwd.startsWith("/") ||
      !["HOST_USER", "PROJECT_SANDBOX"].includes(request.scope) ||
      typeof request.reason !== "string" || !request.reason ||
      !(request.rule_id === null || typeof request.rule_id === "string") ||
      typeof request.source !== "string" || !request.source) {
    return false;
  }
  if (request.policy === "WHITELIST") {
    return typeof request.session_id === "string" &&
      /^term-[0-9a-f]{32}$/.test(request.session_id);
  }
  if (request.policy === "ALWAYS_ASK" || request.policy === "DEFAULT_ASK") {
    return typeof request.proposal_token === "string" &&
      /^[A-Za-z0-9_-]{43}$/.test(request.proposal_token) &&
      Number.isInteger(request.expires_in_seconds) &&
      request.expires_in_seconds > 0 && request.expires_in_seconds <= 60;
  }
  return true;
}

function parseStreamEvent(line) {
  let record;
  try {
    record = JSON.parse(line);
  } catch (_error) {
    throw new Error("Tori returned malformed streaming data.");
  }
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new Error("Tori returned an invalid streaming event.");
  }
  if (record.type === "delta") {
    if (!exactFields(record, ["text", "type"]) ||
        typeof record.text !== "string" || !record.text) {
      throw new Error("Tori returned an invalid streaming delta.");
    }
    return record;
  }
  if (record.type === "status") {
    if (!exactFields(record, ["text", "type"]) ||
        typeof record.text !== "string" || !record.text) {
      throw new Error("Tori returned an invalid streaming status.");
    }
    return record;
  }
  if (record.type === "speech") {
    if (!exactFields(record, ["session", "type"]) ||
        typeof record.session !== "string" || !record.session) {
      throw new Error("Tori returned an invalid speech session event.");
    }
    return record;
  }
  if (record.type === "complete") {
    const expected = ["transcript", "type"];
    if (Object.hasOwn(record, "action")) expected.push("action");
    if (Object.hasOwn(record, "memory_status")) expected.push("memory_status");
    if (Object.hasOwn(record, "confirmation")) expected.push("confirmation");
    if (Object.hasOwn(record, "terminal_request")) expected.push("terminal_request");
    expected.sort();
    if (!exactFields(record, expected) ||
        !validTranscript(record.transcript)) {
      throw new Error("Tori returned an invalid completion event.");
    }
    if (Object.hasOwn(record, "action") && !validActionOutcome(record.action)) {
      throw new Error("Tori returned an invalid action outcome.");
    }
    if (Object.hasOwn(record, "terminal_request") &&
        !validTerminalRequest(record.terminal_request)) {
      throw new Error("Tori returned an invalid terminal request.");
    }
    if (Object.hasOwn(record, "memory_status") &&
        (!Array.isArray(record.memory_status) ||
         !record.memory_status.every((item) => typeof item === "string" && item))) {
      throw new Error("Tori returned an invalid memory status.");
    }
    if (Object.hasOwn(record, "confirmation") &&
        (!record.confirmation || typeof record.confirmation !== "object" ||
         typeof record.confirmation.token !== "string" ||
         typeof record.confirmation.message !== "string" ||
         (record.confirmation.action === "system.service_action" &&
          (!record.confirmation.proposal ||
           typeof record.confirmation.proposal !== "object" ||
           !exactFields(record.confirmation.proposal, [
             "action", "control", "service", "system_target",
           ]) ||
           Object.values(record.confirmation.proposal).some(
             (value) => typeof value !== "string" || !value
           ))))) {
      throw new Error("Tori returned an invalid confirmation.");
    }
    return record;
  }
  if (record.type === "interrupted") {
    if (!exactFields(record, ["transcript", "type"]) ||
        !validTranscript(record.transcript)) {
      throw new Error("Tori returned an invalid interruption event.");
    }
    return record;
  }
  if (record.type === "error") {
    if (!exactFields(record, ["error", "transcript", "type"]) ||
        typeof record.error !== "string" || !record.error ||
        !validTranscript(record.transcript)) {
      throw new Error("Tori returned an invalid streaming error event.");
    }
    return record;
  }
  throw new Error("Tori returned an unknown streaming event.");
}

function validActionOutcome(action) {
  if (!action || typeof action !== "object" || Array.isArray(action) ||
      !exactFields(action, [
        "action_id", "authorized", "code", "invocation_id", "message",
        "permission", "result", "source", "status",
      ]) || typeof action.invocation_id !== "string" ||
      !action.invocation_id || action.action_id !== "tori.backup" ||
      action.source !== "conversation" || action.permission !== "interactive" ||
      action.authorized !== true ||
      !["succeeded", "failed"].includes(action.status) ||
      typeof action.code !== "string" || !action.code ||
      typeof action.message !== "string" || !action.message) {
    return false;
  }
  if (action.status === "failed") {
    return action.result === null;
  }
  const result = action.result;
  return result && typeof result === "object" && !Array.isArray(result) &&
    exactFields(result, [
      "completed_at", "directory", "directory_count", "identifier",
      "regular_file_count", "symlink_count", "total_regular_bytes",
      "verification",
    ]) && result.verification === "verified";
}

async function requestStream(path, body, onDelta, onStatus, onSpeech) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Tori-CSRF": ui.csrfToken,
    },
    body: JSON.stringify(body),
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    let documentBody = {};
    try {
      documentBody = await response.json();
    } catch (_error) {
      // The safe fallback below covers malformed pre-stream failures.
    }
    const error = new Error(
      documentBody.error || "The local streaming request failed."
    );
    error.code = documentBody.code || "request_failed";
    throw error;
  }
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.split(";", 1)[0].trim().toLowerCase() !==
      "application/x-ndjson") {
    throw new Error("Tori returned an unexpected streaming response.");
  }
  if (!response.body) {
    throw new Error("Tori did not provide a readable response stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", {fatal: true});
  let buffer = "";
  let terminal = null;

  function consumeLine(line) {
    if (!line.trim()) {
      return;
    }
    if (terminal !== null) {
      throw new Error("Tori returned data after the terminal stream event.");
    }
    const event = parseStreamEvent(line);
    if (event.type === "delta") {
      onDelta(event.text);
    } else if (event.type === "status") {
      onStatus(event.text);
    } else if (event.type === "speech") {
      onSpeech(event.session);
    } else {
      terminal = event;
    }
  }

  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, {stream: true});
      let newline;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        consumeLine(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      consumeLine(buffer);
    }
    if (terminal === null) {
      throw new Error("Tori's response stream ended before completion.");
    }
    return terminal;
  } catch (error) {
    try {
      await reader.cancel();
    } catch (_cancelError) {
      // Cleanup failure does not replace the safe parser or transport error.
    }
    throw error;
  } finally {
    reader.releaseLock();
  }
}

function setSpeechStatus(message, state = "neutral") {
  speechStatus.textContent = message;
  speechStatus.dataset.state = state;
  if (state === "busy") {
    window.ToriUtilityRail?.setActivity("Voice output", message, "busy", "speech");
  } else {
    window.ToriUtilityRail?.setActivity();
  }
}

function stopLocalAudio() {
  for (const source of activeAudioSources) {
    try {
      source.stop();
    } catch (_error) {
      // A source that already ended is already harmless.
    }
  }
  activeAudioSources.clear();
  nextPlaybackTime = 0;
}

function stopSpeaking({notifyServer = true, message = "Speech stopped.", resetAudio = false} = {}) {
  const session = activeSpeechSession;
  const hadPlayback = activeAudioSources.size > 0;
  speechGeneration += 1;
  activeSpeechSession = null;
  if (playbackCompletionTimer !== null) {
    window.clearTimeout(playbackCompletionTimer);
    playbackCompletionTimer = null;
  }
  if (speechAbortController) {
    speechAbortController.abort();
    speechAbortController = null;
  }
  stopLocalAudio();
  if (resetAudio && hadPlayback) audioActivation.reset?.();
  stopSpeechButton.disabled = true;
  if (notifyServer && session) {
    ui.requestJson("/api/speech/stop", {
      method: "POST",
      body: {session},
    }).catch(() => {});
  }
  setSpeechStatus(message);
}

function decodePCM(encoded) {
  let binary;
  try {
    binary = atob(encoded);
  } catch (_error) {
    throw new Error("Tori returned malformed speech audio.");
  }
  if (!binary.length || binary.length % 2 !== 0) {
    throw new Error("Tori returned malformed speech audio.");
  }
  const samples = new Float32Array(binary.length / 2);
  for (let index = 0; index < samples.length; index += 1) {
    const low = binary.charCodeAt(index * 2);
    const high = binary.charCodeAt(index * 2 + 1);
    let value = low | (high << 8);
    if (value >= 0x8000) {
      value -= 0x10000;
    }
    samples[index] = value / 32768;
  }
  return samples;
}

async function schedulePCM(encoded, format, generation) {
  if (generation !== speechGeneration) {
    return;
  }
  const context = audioActivation.requireActive();
  if (generation !== speechGeneration) {
    return;
  }
  const samples = decodePCM(encoded);
  const buffer = context.createBuffer(1, samples.length, format.sampleRate);
  buffer.copyToChannel(samples, 0);
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(context.destination);
  const startAt = Math.max(context.currentTime + 0.04, nextPlaybackTime);
  nextPlaybackTime = startAt + buffer.duration;
  activeAudioSources.add(source);
  source.addEventListener("ended", () => {
    activeAudioSources.delete(source);
    if (generation === speechGeneration && activeAudioSources.size === 0 &&
        activeSpeechSession === null) {
      if (playbackCompletionTimer !== null) {
        window.clearTimeout(playbackCompletionTimer);
        playbackCompletionTimer = null;
      }
      stopSpeechButton.disabled = true;
      if (audioActivation.isActive()) {
        setSpeechStatus("Speech complete.", "success");
      } else {
        setSpeechStatus(
          "Browser audio is not active. Tap Auto speech or Speak and try again.",
          "warning"
        );
      }
    }
  }, {once: true});
  source.start(startAt);
  setSpeechStatus("Speaking…", "busy");
}

function parseSpeechEvent(line) {
  let record;
  try {
    record = JSON.parse(line);
  } catch (_error) {
    throw new Error("Tori returned malformed speech data.");
  }
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new Error("Tori returned an invalid speech event.");
  }
  if (record.type === "start") {
    if (!exactFields(record, ["channels", "sample_rate", "sample_width", "type"]) ||
        record.sample_rate !== 24000 || record.channels !== 1 ||
        record.sample_width !== 2) {
      throw new Error("Tori returned an unsupported speech format.");
    }
  } else if (record.type === "audio") {
    if (!exactFields(record, ["data", "type"]) ||
        typeof record.data !== "string" || !record.data) {
      throw new Error("Tori returned invalid speech audio.");
    }
  } else if (record.type === "error") {
    if (!exactFields(record, ["error", "type"]) ||
        typeof record.error !== "string" || !record.error) {
      throw new Error("Tori returned an invalid speech error.");
    }
  } else if (!(["complete", "stopped"].includes(record.type) &&
               exactFields(record, ["type"]))) {
    throw new Error("Tori returned an unknown speech event.");
  }
  return record;
}

async function consumeSpeechStream(session, generation) {
  speechAbortController = new AbortController();
  const response = await fetch("/api/speech/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Tori-CSRF": ui.csrfToken,
    },
    body: JSON.stringify({session}),
    cache: "no-store",
    credentials: "same-origin",
    signal: speechAbortController.signal,
  });
  if (!response.ok || !response.body) {
    throw new Error("Speech is unavailable right now.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", {fatal: true});
  let textBuffer = "";
  let format = null;
  let terminal = false;

  async function consumeLine(line) {
    if (!line.trim()) {
      return;
    }
    if (terminal) {
      throw new Error("Tori returned speech data after completion.");
    }
    const event = parseSpeechEvent(line);
    if (event.type === "start") {
      format = {sampleRate: event.sample_rate};
      setSpeechStatus("Preparing speech…", "busy");
    } else if (event.type === "audio") {
      if (!format) {
        throw new Error("Tori returned speech audio before its format.");
      }
      await schedulePCM(event.data, format, generation);
    } else if (event.type === "error") {
      terminal = true;
      throw new Error(event.error);
    } else {
      terminal = true;
      activeSpeechSession = null;
      if (event.type === "stopped") {
        stopSpeaking({notifyServer: false, resetAudio: true});
      } else if (activeAudioSources.size === 0) {
        stopSpeechButton.disabled = true;
        if (audioActivation.isActive()) {
          setSpeechStatus("Speech complete.", "success");
        } else {
          setSpeechStatus(
            "Browser audio is not active. Tap Auto speech or Speak and try again.",
            "warning"
          );
        }
      } else {
        // Short application-authored replies can finish their server stream
        // before browser playback ends. Usually `ended` clears Speaking, but
        // a suspended/lost audio source may never deliver that callback.
        const context = audioActivation.isActive() ? audioActivation.requireActive() : null;
        const remaining = context ? Math.max(0, nextPlaybackTime - context.currentTime) : 0;
        playbackCompletionTimer = window.setTimeout(() => {
          playbackCompletionTimer = null;
          if (generation !== speechGeneration || activeSpeechSession !== null ||
              activeAudioSources.size === 0) return;
          const wasActive = audioActivation.isActive();
          speechGeneration += 1; // Fence late `ended` from claiming success.
          if (speechAbortController) {
            speechAbortController.abort();
            speechAbortController = null;
          }
          stopLocalAudio();
          audioActivation.reset?.(); // Retire the stalled context, not just its source.
          stopSpeechButton.disabled = true;
          setSpeechStatus(
            wasActive ?
              "Speech playback did not finish. Tap Speak to try again." :
              "Browser audio is not active. Tap Auto speech or Speak and try again.",
            "warning"
          );
        }, Math.ceil(remaining * 1000) + 2000);
      }
    }
  }

  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) {
        break;
      }
      textBuffer += decoder.decode(value, {stream: true});
      let newline;
      while ((newline = textBuffer.indexOf("\n")) !== -1) {
        await consumeLine(textBuffer.slice(0, newline));
        textBuffer = textBuffer.slice(newline + 1);
      }
    }
    textBuffer += decoder.decode();
    if (textBuffer.trim()) {
      await consumeLine(textBuffer);
    }
    if (!terminal && generation === speechGeneration) {
      throw new Error("Tori's speech stream ended before completion.");
    }
  } finally {
    reader.releaseLock();
  }
}

async function beginSpeech(session) {
  stopSpeaking({notifyServer: true, message: "Preparing speech…"});
  const generation = speechGeneration;
  activeSpeechSession = session;
  stopSpeechButton.disabled = false;
  setSpeechStatus("Preparing speech…", "busy");
  try {
    audioActivation.requireActive();
    await consumeSpeechStream(session, generation);
  } catch (error) {
    if (generation !== speechGeneration || error.name === "AbortError") {
      return;
    }
    stopSpeaking({notifyServer: true, resetAudio: true});
    audioActivation.reset?.(); // Includes source-creation failure before tracking.
    setSpeechStatus(error.message || "Speech is unavailable right now.", "warning");
  } finally {
    if (generation === speechGeneration) {
      speechAbortController = null;
    }
  }
}

async function replayAssistantMessage(entryIndex) {
  if (!speechAvailable) {
    setSpeechStatus("Speech is unavailable right now.", "warning");
    return;
  }
  try {
    stopSpeaking({resetAudio: true, message: "Preparing speech…"});
    await audioActivation.activate();
    const result = await request("/api/speech/replay", {entry_index: entryIndex});
    beginSpeech(result.speech_session);
  } catch (error) {
    setSpeechStatus(error.message, "warning");
  }
}

async function loadSpeechState() {
  try {
    const state = await ui.requestJson("/api/speech");
    speechAvailable = state.enabled === true && state.available === true;
    autoSpeechButton.disabled = busy || !speechAvailable;
    setSpeechStatus(
      speechAvailable
        ? `Automatic speech is ${autoSpeech ? "on" : "off"}.`
        : (state.error || "Speech is unavailable right now."),
      speechAvailable ? "neutral" : "warning"
    );
    renderTranscript(visibleTranscript);
  } catch (_error) {
    speechAvailable = false;
    autoSpeechButton.disabled = true;
    setSpeechStatus("Speech is unavailable right now.", "warning");
  }
}

document.addEventListener("tori:speechsettingchange", (event) => {
  if (event.detail && event.detail.enabled === false) {
    stopSpeaking({notifyServer: true, message: "Speech Output is disabled in Settings.", resetAudio: true});
  }
  loadSpeechState();
});

async function loadSession({expectedChatId, expectedTranscriptRevision} = {}) {
  try {
    const documentBody = await ui.requestJson("/api/session");
    const sessionChatId = typeof documentBody.active_chat_id === "string" ?
      documentBody.active_chat_id : null;
    const sessionTranscriptRevision = Number.isInteger(documentBody.transcript_revision) ?
      documentBody.transcript_revision : 0;
    if ((expectedChatId !== undefined && sessionChatId !== expectedChatId) ||
        (expectedTranscriptRevision !== undefined &&
         sessionTranscriptRevision < expectedTranscriptRevision)) {
      return false;
    }
    applyCompanionState(documentBody.companion_initiative);
    renderTranscript(documentBody.transcript);
    // These values mean successfully rendered, not merely observed by polling.
    const priorRenderedChatId = renderedChatId;
    renderedChatId = sessionChatId;
    if (priorRenderedChatId !== renderedChatId) {
      document.dispatchEvent(new CustomEvent("tori:conversationchanged", {
        detail: {chatId: renderedChatId},
      }));
    }
    renderedTranscriptRevision = sessionTranscriptRevision;
    if (pendingTranscriptChatId !== renderedChatId ||
        pendingTranscriptRevision <= renderedTranscriptRevision) {
      pendingTranscriptChatId = null;
      pendingTranscriptRevision = 0;
    }
    renderSelectedModel(documentBody.selected_model);
    renderContextState(documentBody.context);
    renderActiveProject(documentBody.project);
    renderCommand(documentBody.command);
    if (commandIsActive(documentBody.command)) {
      startCommandPolling(documentBody.command.invocation_id);
    }
    document.dispatchEvent(new CustomEvent("tori:serverbusystatechange", {
      detail: {busy: documentBody.busy === true},
    }));
    const reconciledBusy = localConversationPending || documentBody.busy === true;
    setBusy(reconciledBusy, reconciledBusy ? "Tori is working…" : "Connected locally");
    return true;
  } catch (error) {
    setBusy(false, "Connection unavailable");
    showError(error.message);
    return false;
  }
}

function formatReminderSchedule(reminder) {
  const start = new Date(reminder.scheduled_start_utc);
  const end = reminder.scheduled_end_utc ? new Date(reminder.scheduled_end_utc) : null;
  const startText = Number.isNaN(start.valueOf()) ? reminder.scheduled_start_utc :
    start.toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
  if (!end || Number.isNaN(end.valueOf())) {
    return `${reminder.overdue ? "Overdue · scheduled" : "Scheduled"} ${startText} · ${reminder.scheduled_timezone}`;
  }
  return `${reminder.overdue ? "Overdue · window" : "Window"} ${startText} – ${end.toLocaleString([], {dateStyle: "medium", timeStyle: "short"})} · ${reminder.scheduled_timezone}`;
}

function renderAttention(documentBody) {
  if (!documentBody || !Number.isInteger(documentBody.operational_revision)) {
    return;
  }
  if (documentBody.operational_revision < attentionRevision) {
    return;
  }
  const priorOperationalRevision = attentionRevision;
  attentionRevision = documentBody.operational_revision;
  if (attentionRevision > priorOperationalRevision) {
    document.dispatchEvent(new CustomEvent("tori:operationalrevision", {
      detail: {revision: attentionRevision},
    }));
  }
  activeReminder = documentBody.active_reminder || null;
  if (!activeReminder) {
    attentionCard.hidden = true;
    if (reminderDetailsDialog.open) {
      ui.closeDialog(reminderDetailsDialog);
    }
    if (reminderDelayDialog.open) {
      ui.closeDialog(reminderDelayDialog);
    }
    return;
  }
  attentionText.textContent = activeReminder.reminder_text;
  attentionSchedule.textContent = formatReminderSchedule(activeReminder);
  const linked = activeReminder.linked_task;
  attentionLinked.hidden = !linked;
  attentionLinked.textContent = linked ? `Linked task: ${linked.description} · ${linked.status}` : "";
  attentionQueue.hidden = !documentBody.queued_count;
  attentionQueue.textContent = documentBody.queued_count ? `${documentBody.queued_count} more due` : "";
  attentionCard.hidden = false;
}

function renderMemoryConfirmation(documentBody) {
  const proposal = documentBody?.memory_confirmation || null;
  if (!proposal) {
    if (pendingConfirmationSource === "durable-memory") {
      pendingConfirmationToken = null;
      pendingConfirmationSource = null;
      if (confirmationDialog.open) {
        ui.closeDialog(confirmationDialog);
      }
    }
    return;
  }
  if (pendingConfirmationToken === proposal.token) {
    return;
  }
  if (confirmationDialog.open && pendingConfirmationSource !== "durable-memory") {
    return;
  }
  pendingConfirmationToken = proposal.token;
  pendingConfirmationSource = "durable-memory";
  pendingCommandProposal = null;
  pendingScheduledProposal = null;
  pendingSystemServiceProposal = null;
  pendingPlanningProposal = false;
  commandProposal.hidden = true;
  confirmationMessage.textContent = proposal.message;
  acceptConfirmation.textContent = "Confirm";
  acceptConfirmation.disabled = false;
  ui.openDialog(confirmationDialog, {
    returnFocus: messageInput,
    initialFocus: cancelConfirmation,
  });
}

function scheduleAttentionPoll(delay) {
  if (attentionPollTimer !== null) {
    window.clearTimeout(attentionPollTimer);
  }
  attentionPollTimer = window.setTimeout(refreshAttention, delay);
}

function applyCompanionState(state) {
  const nextEvent = state && typeof state.current_event_id === "string" ?
    state.current_event_id : null;
  const nextRevision = state && Number.isInteger(state.settings_revision) ?
    state.settings_revision : 0;
  const changed = nextEvent !== currentCompanionEventId;
  currentCompanionEventId = nextEvent;
  companionSettingsRevision = nextRevision;
  return changed;
}

async function dismissCompanionInitiative(applicationEventId) {
  try {
    const result = await request("/api/companion-initiative/dismiss", {
      application_event_id: applicationEventId,
    });
    applyCompanionState(result.companion_initiative);
    renderTranscript(result.transcript);
  } catch (error) {
    showError(error.message);
    await loadSession();
  }
}

async function pauseCompanionInitiative(duration, applicationEventId) {
  try {
    await request("/api/companion-initiative/pause", {
      duration,
      expected_revision: companionSettingsRevision,
      application_event_id: applicationEventId,
    });
    await loadSession();
  } catch (error) {
    showError(error.message);
    await loadSession();
  }
}

async function refreshAttention({immediate = false} = {}) {
  const generation = ++attentionGeneration;
  try {
    const result = await ui.requestJson("/api/attention");
    if (generation !== attentionGeneration) {
      return;
    }
    renderAttention(result);
    renderMemoryConfirmation(result);
    const companionChanged = applyCompanionState(result.companion_initiative);
    if (companionChanged && !localConversationPending) {
      renderTranscript(visibleTranscript);
    }
    if (Date.now() - upcomingLoadedAt >= 10000) {
      loadUpcoming();
    }
    if (Date.now() - hostStatusLoadedAt >= 5000) {
      loadHostStatus();
    }
    if (Date.now() - codingWorkLoadedAt >= 3000) {
      loadCodingWork();
    }
    if (Date.now() - researchLoadedAt >= 3000) {
      loadResearch();
    }
    if (typeof result.chat_list_revision === "string" &&
        result.chat_list_revision !== renderedChatListRevision) {
      await loadChats();
    }
    const attentionChatId = typeof result.active_chat_id === "string" ?
      result.active_chat_id : null;
    // Project-only edits do not revise the transcript. Reconcile the compact
    // indicator directly, but only for the chat this browser actually rendered.
    if (attentionChatId === renderedChatId &&
        Object.prototype.hasOwnProperty.call(result, "project")) {
      renderActiveProject(result.project);
    }
    const observedSameChatRevision = attentionChatId === renderedChatId &&
      Number.isInteger(result.transcript_revision) ? result.transcript_revision : 0;
    if (!localConversationPending) {
      if (result.busy === true) {
        if (observedSameChatRevision > renderedTranscriptRevision &&
            (pendingTranscriptChatId !== attentionChatId ||
             observedSameChatRevision > pendingTranscriptRevision)) {
          pendingTranscriptChatId = attentionChatId;
          pendingTranscriptRevision = observedSameChatRevision;
        }
        document.dispatchEvent(new CustomEvent("tori:serverbusystatechange", {
          detail: {busy: true},
        }));
        if (!busy) {
          setBusy(true, "Tori is working…");
        }
      } else if (attentionChatId === renderedChatId && Math.max(
        observedSameChatRevision,
        pendingTranscriptChatId === renderedChatId ? pendingTranscriptRevision : 0
      ) > renderedTranscriptRevision) {
        const expectedRevision = Math.max(
          observedSameChatRevision,
          pendingTranscriptChatId === renderedChatId ? pendingTranscriptRevision : 0
        );
        await loadSession({
          expectedChatId: attentionChatId,
          expectedTranscriptRevision: expectedRevision,
        });
      } else if (busy) {
        document.dispatchEvent(new CustomEvent("tori:serverbusystatechange", {
          detail: {busy: false},
        }));
        setBusy(false, "Connected locally");
      }
    }
  } catch (_error) {
    // Ordinary connection status owns user-visible transport failures.
  } finally {
    if (generation === attentionGeneration) {
      scheduleAttentionPoll(activeReminder || attentionMutationPending ? 400 : 1500);
    }
  }
}

async function mutateAttention(path, body) {
  if (!activeReminder || attentionMutationPending) {
    return;
  }
  attentionMutationPending = true;
  const revision = activeReminder.revision;
  try {
    const result = await request(path, {
      identifier: activeReminder.identifier,
      expected_revision: revision,
      ...body,
    });
    renderAttention(result);
    await loadSession();
  } catch (error) {
    showError(error.message);
    await refreshAttention({immediate: true});
  } finally {
    attentionMutationPending = false;
    scheduleAttentionPoll(activeReminder ? 400 : 1500);
  }
}

function addReminderDetail(label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value === null || value === undefined ? "—" : String(value);
  reminderDetails.append(term, detail);
}

attentionDetailsButton.addEventListener("click", () => {
  if (!activeReminder) {
    return;
  }
  reminderDetails.replaceChildren();
  addReminderDetail("Reminder", activeReminder.reminder_text);
  addReminderDetail("Status", activeReminder.status);
  addReminderDetail("Schedule", formatReminderSchedule(activeReminder));
  addReminderDetail("Timezone", activeReminder.scheduled_timezone);
  addReminderDetail("Created", activeReminder.created_at_utc);
  addReminderDetail("Updated", activeReminder.updated_at_utc);
  addReminderDetail("Became due", activeReminder.became_due_at_utc);
  addReminderDetail("Linked task", activeReminder.linked_task ? activeReminder.linked_task.description : null);
  if (activeReminder.linked_task) {
    addReminderDetail("Linked task status", activeReminder.linked_task.status);
    addReminderDetail("Linked task created", activeReminder.linked_task.created_at_utc);
    addReminderDetail("Linked task updated", activeReminder.linked_task.updated_at_utc);
    addReminderDetail("Linked task completed", activeReminder.linked_task.completed_at_utc);
    addReminderDetail("Linked task cancelled", activeReminder.linked_task.cancelled_at_utc);
  }
  ui.openDialog(reminderDetailsDialog, {returnFocus: attentionDetailsButton, initialFocus: closeReminderDetails});
});
closeReminderDetails.addEventListener("click", () => ui.closeDialog(reminderDetailsDialog));
attentionDoneButton.addEventListener("click", () => mutateAttention("/api/reminders/done", {}));
attentionDismissButton.addEventListener("click", () => mutateAttention("/api/reminders/dismiss", {}));
for (const button of attentionDelayButtons) {
  button.addEventListener("click", () => mutateAttention("/api/reminders/delay", {preset: button.dataset.delay}));
}
attentionDelayCustomButton.addEventListener("click", () => {
  if (!activeReminder) {
    return;
  }
  reminderDelayDate.value = "";
  reminderDelayTime.value = "";
  ui.openDialog(reminderDelayDialog, {returnFocus: attentionDelayCustomButton, initialFocus: reminderDelayDate});
});
cancelReminderDelay.addEventListener("click", () => ui.closeDialog(reminderDelayDialog));
reminderDelayForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!reminderDelayDate.value || !reminderDelayTime.value) {
    return;
  }
  ui.closeDialog(reminderDelayDialog);
  mutateAttention("/api/reminders/delay", {local_date: reminderDelayDate.value, local_time: reminderDelayTime.value});
});
attentionDiscussButton.addEventListener("click", async () => {
  if (!activeReminder || attentionMutationPending) {
    return;
  }
  try {
    await request("/api/operational/discuss", {kind: "reminder", identifier: activeReminder.identifier, expected_revision: activeReminder.revision});
    composer.querySelector("#message").focus();
  } catch (error) {
    showError(error.message);
  }
});

window.addEventListener?.("focus", () => {
  refreshAttention({immediate: true});
  loadCompanionAttention();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshAttention({immediate: true});
    loadCompanionAttention();
  }
});

function renderSelectedModel(selection) {
  window.ToriUtilityRail?.setModel(selection);
  if (!selection || typeof selection.qualified_name !== "string") {
    activeModel.textContent = "Model selection unavailable";
    return;
  }
  const profile = typeof selection.profile_display_name === "string" ?
    selection.profile_display_name : selection.provider;
  const model = typeof selection.model_display_name === "string" ?
    selection.model_display_name : selection.model;
  const availability = selection.status === "available" ? "" :
    ` · ${selection.status}`;
  activeModel.textContent = `${profile} · ${model}${availability}`;
}

function formatTokenCount(value) {
  if (!Number.isInteger(value) || value < 0) {
    return "unknown";
  }
  if (value >= 1024) {
    const units = value / 1024;
    return `${Number.isInteger(units) ? units : units.toFixed(1)}K`;
  }
  return String(value);
}

function contextPolicyLabel(policy) {
  if (policy === "auto") {
    return "Auto";
  }
  if (typeof policy === "string" && policy.startsWith("fixed:")) {
    const value = Number(policy.slice(6));
    return Number.isInteger(value) ? `${formatTokenCount(value)} planning budget` : policy;
  }
  return "Unavailable";
}

function addContextDetail(labelText, value) {
  if (value === null || value === undefined || value === "") {
    return;
  }
  const term = document.createElement("dt");
  term.textContent = labelText;
  const description = document.createElement("dd");
  description.textContent = String(value);
  contextDetailsList.append(term, description);
}

function renderContextState(context) {
  contextDetailsList.replaceChildren();
  contextOmissionNote.textContent = "";
  if (!context || typeof context.policy !== "string") {
    activeContext.textContent = "Context status unavailable";
    window.ToriUtilityRail?.setContext(activeContext.textContent);
    contextCapacityNote.textContent = "Backend context capacity is unknown.";
    return;
  }
  const last = context.last_request;
  if (last && Number.isInteger(last.estimated_input_tokens) &&
      Number.isInteger(last.effective_planning_budget)) {
    const percent = Math.min(999, Math.round(
      last.estimated_input_tokens / last.effective_planning_budget * 100
    ));
    activeContext.textContent = `Context ~${formatTokenCount(last.estimated_input_tokens)} / ${formatTokenCount(last.effective_planning_budget)} · ${percent}%`;
    addContextDetail("Requested policy", contextPolicyLabel(last.requested_policy));
    addContextDetail("Effective planning budget", formatTokenCount(last.effective_planning_budget));
    addContextDetail("Estimated input", `~${formatTokenCount(last.estimated_input_tokens)} (${last.estimator_version})`);
    addContextDetail("Reply planning headroom", formatTokenCount(last.reply_planning_headroom));
    addContextDetail("Estimator uncertainty reserve", formatTokenCount(last.estimation_uncertainty_reserve));
    addContextDetail("Provider-reported prompt", Number.isInteger(last.actual_prompt_tokens) ? formatTokenCount(last.actual_prompt_tokens) : "Unknown");
    addContextDetail("Provider-reported completion", Number.isInteger(last.actual_completion_tokens) ? formatTokenCount(last.actual_completion_tokens) : "Unknown");
    addContextDetail("Provider-reported total", Number.isInteger(last.actual_total_tokens) ? formatTokenCount(last.actual_total_tokens) : "Unknown");
    addContextDetail("Generated by", `${last.provider}/${last.model}`);
    const omitted = last.omitted_history_exchanges;
    contextOmissionNote.textContent = Number.isInteger(omitted) && omitted > 0 ?
      `${omitted} older ${omitted === 1 ? "exchange was" : "exchanges were"} not supplied for this request.` :
      "No eligible older exchange was omitted for this request.";
  } else {
    activeContext.textContent = `Context ${contextPolicyLabel(context.policy)} · no completed request yet`;
    addContextDetail("Selected policy", contextPolicyLabel(context.policy));
  }
  contextCapacityNote.textContent = context.backend_capacity_verified === true &&
    Number.isInteger(context.backend_capacity_tokens) ?
    `Verified backend maximum: ${formatTokenCount(context.backend_capacity_tokens)} tokens.` :
    "Backend context capacity is unknown; fixed choices are Tori planning limits, not verified backend capacity.";
  window.ToriUtilityRail?.setContext(activeContext.textContent);
}

function selectedCatalogModel() {
  if (!modelCatalogDocument) {
    return null;
  }
  return (modelCatalogDocument.models || []).find((model) =>
    model.provider === providerSelector.value && model.model === modelSelector.value
  ) || null;
}

function populateContextChoices() {
  const selectedModel = selectedCatalogModel();
  const capacity = selectedModel && Number.isInteger(selectedModel.context_window_tokens) ?
    selectedModel.context_window_tokens : null;
  const currentPolicy = modelCatalogDocument?.context?.policy || "auto";
  const values = new Set(modelCatalogDocument?.context_presets || []);
  if (capacity !== null) {
    values.add(capacity);
  }
  contextSelector.replaceChildren();
  const automatic = document.createElement("option");
  automatic.value = "auto";
  automatic.textContent = capacity === null ? "Auto · backend maximum unknown" :
    `Auto · verified maximum ${formatTokenCount(capacity)}`;
  contextSelector.append(automatic);
  for (const value of Array.from(values).sort((left, right) => left - right)) {
    if (!Number.isInteger(value) || value < 4096 || (capacity !== null && value > capacity)) {
      continue;
    }
    const option = document.createElement("option");
    option.value = `fixed:${value}`;
    option.textContent = `${formatTokenCount(value)} planning budget${capacity === null ? " · capacity unverified" : ""}`;
    contextSelector.append(option);
  }
  if (!Array.from(contextSelector.options).some((option) => option.value === currentPolicy)) {
    const historical = document.createElement("option");
    historical.value = currentPolicy;
    historical.textContent = `${contextPolicyLabel(currentPolicy)} · unavailable for this model`;
    historical.disabled = true;
    contextSelector.append(historical);
  }
  contextSelector.value = currentPolicy;
}

function populateModels() {
  const current = modelCatalogDocument?.selected_model;
  const models = (modelCatalogDocument?.models || []).filter(
    (model) => model.provider === providerSelector.value
  );
  modelSelector.replaceChildren();
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model.model;
    option.textContent = `${model.display_name} · ${model.status}`;
    const isCurrent = current && model.provider === current.provider &&
      model.model === current.model;
    option.disabled = !["available", "configured"].includes(model.status) && !isCurrent;
    option.selected = isCurrent;
    modelSelector.append(option);
  }
  if (!modelSelector.value && modelSelector.options.length > 0) {
    modelSelector.selectedIndex = 0;
  }
  populateContextChoices();
}

function populateModelControls(documentBody) {
  modelCatalogDocument = documentBody;
  renderSelectedModel(documentBody.selected_model);
  renderContextState(documentBody.context);
  providerSelector.replaceChildren();
  for (const profile of documentBody.profiles || []) {
    const option = document.createElement("option");
    option.value = profile.identifier;
    option.textContent = `${profile.display_name} · ${profile.status}`;
    option.selected = profile.identifier === documentBody.selected_model.provider;
    option.disabled = profile.status === "unavailable" && !option.selected;
    providerSelector.append(option);
  }
  populateModels();
  providerSelector.disabled = busy || modelPending;
  modelSelector.disabled = busy || modelPending;
  contextSelector.disabled = busy || modelPending;
  saveModelControlsButton.disabled = busy || modelPending;
}

async function loadModels(refresh = false) {
  modelError.hidden = true;
  modelError.textContent = "";
  modelDialogError.hidden = true;
  modelDialogError.textContent = "";
  try {
    const documentBody = refresh
      ? await request("/api/models/refresh", {})
      : await ui.requestJson("/api/models");
    populateModelControls(documentBody);
    if (documentBody.error) {
      modelError.textContent = documentBody.error;
      modelError.hidden = false;
    }
  } catch (error) {
    modelError.textContent = error.message;
    modelError.hidden = false;
  }
}

providerSelector.addEventListener("change", populateModels);
modelSelector.addEventListener("change", populateContextChoices);

openModelControlsButton.addEventListener("click", async () => {
  if (busy || modelPending) {
    return;
  }
  await loadModels();
  modelContextDialog.scrollTop = 0;
  ui.openDialog(modelContextDialog, {
    returnFocus: openModelControlsButton,
    initialFocus: providerSelector,
  });
});

cancelModelControlsButton.addEventListener("click", () => {
  ui.closeDialog(modelContextDialog);
});

modelContextDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  ui.closeDialog(modelContextDialog);
});

modelContextForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (modelPending || busy || !providerSelector.value || !modelSelector.value) {
    return;
  }
  modelPending = true;
  setBusy(true, "Saving model and context selection…");
  modelDialogError.hidden = true;
  try {
    const documentBody = await request("/api/model-context/select", {
      provider: providerSelector.value,
      model: modelSelector.value,
      policy: contextSelector.value,
    });
    populateModelControls(documentBody);
    ui.closeDialog(modelContextDialog);
    ui.setStatus(statusArea, "Model and context selection saved · Connected locally", "success");
  } catch (error) {
    modelDialogError.textContent = error.message;
    modelDialogError.hidden = false;
  } finally {
    modelPending = false;
    setBusy(false, "Connected locally");
  }
});

refreshModelsButton.addEventListener("click", async () => {
  if (modelPending || busy) {
    return;
  }
  modelPending = true;
  setBusy(true, "Refreshing configured local models…");
  try {
    await loadModels(true);
  } finally {
    modelPending = false;
    setBusy(false, "Connected locally");
  }
});

document.addEventListener("tori:modelcatalogchange", () => {
  if (!modelPending && !busy) {
    loadModels(false);
  }
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value;
  if (busy || !message.trim()) {
    if (!message.trim()) {
      showError("Enter a message before sending.");
    }
    return;
  }
  const authoritativeTranscript = visibleTranscript;
  const localCommand = isLocalCommand(message);
  stopSpeaking({
    notifyServer: true,
    message: autoSpeech ? "Preparing speech…" : "Automatic speech is off.",
    resetAudio: true,
  });
  let autoSpeechForTurn = false;
  if (autoSpeech && !localCommand && speechAvailable) {
    try {
      await audioActivation.activate();
      autoSpeechForTurn = true;
    } catch (error) {
      setSpeechStatus(error.message, "warning");
    }
  }
  let terminalStatus = "Connected locally";
  let terminalState = "neutral";
  showError("");
  messageInput.value = "";
  const composerRevisionAtClear = composerRevision;
  const requestGeneration = ++conversationRequestGeneration;
  activeForegroundKind = localCommand ? "command" : "model";
  localConversationPending = true;
  setBusy(true, "Tori is generating a response…");
  const draftText = localCommand ? null : renderStreamingDraft(message);
  if (draftText !== null) {
    activeStreamingDraft = {
      afterIndex: visibleTranscript.length,
      generation: requestGeneration,
      textElement: draftText,
      user: message,
    };
  }
  if (localCommand) {
    renderPendingUserMessage(message);
  }
  try {
    const result = localCommand
      ? await request("/api/message", {message})
      : await requestStream("/api/message/stream", {
          message,
          auto_speech: autoSpeechForTurn,
        }, (delta) => {
          const shouldFollow = isNearConversationBottom();
          draftText.append(document.createTextNode(delta));
          followConversationIfNeeded(shouldFollow);
        }, (statusText) => ui.setStatus(statusArea, statusText, "busy"),
        (session) => {
          if (requestGeneration === conversationRequestGeneration) beginSpeech(session);
        });
    if (requestGeneration !== conversationRequestGeneration) return;
    renderTranscript(result.transcript);
    renderCommand(result.command);
    if (Array.isArray(result.memory_status) && result.memory_status.length) {
      ui.setStatus(statusArea, result.memory_status.join(" · "), "success");
    }
    if (result.type === "error") {
      const error = new Error(result.error);
      error.authoritativeTranscript = result.transcript;
      throw error;
    }
    if (result.type === "interrupted") {
      terminalStatus = "Response interrupted · Connected locally";
      terminalState = "neutral";
      return;
    }
    await loadSession();
    terminalStatus = localCommand ? "Local command complete · Connected locally" :
      "Response complete · Connected locally";
    if (Array.isArray(result.memory_status) && result.memory_status.length) {
      terminalStatus = result.memory_status.join(" · ");
    }
    terminalState = "success";
    if (result.terminal_request) {
      document.dispatchEvent(new CustomEvent("tori:terminalrequest", {
        detail: result.terminal_request,
      }));
      terminalStatus = result.terminal_request.policy === "BLACKLIST" ?
        "Command blocked by terminal policy" :
        result.terminal_request.session_id ? "Terminal command started" :
        "Terminal approval required";
    }
    if (result.confirmation) {
      pendingConfirmationToken = result.confirmation.token;
      pendingConfirmationSource = "foreground";
      confirmationMessage.textContent = result.confirmation.message;
      pendingCommandProposal = result.confirmation.action === "tori.command.execute" ?
        result.confirmation.proposal : null;
      pendingScheduledProposal = result.confirmation.action === "scheduled_work.authorize" ?
        result.confirmation.proposal : null;
      pendingSystemServiceProposal = result.confirmation.action === "system.service_action" ?
        result.confirmation.proposal : null;
      pendingPlanningProposal = result.confirmation.action === "planning.authorize";
      commandProposal.hidden = pendingCommandProposal === null &&
        pendingScheduledProposal === null && pendingSystemServiceProposal === null;
      commandProposal.textContent = pendingCommandProposal ?
        formatCommandProposal(pendingCommandProposal) : pendingScheduledProposal ?
        formatScheduledProposal(pendingScheduledProposal) : pendingSystemServiceProposal ?
        formatSystemServiceProposal(pendingSystemServiceProposal) : "";
      acceptConfirmation.textContent = pendingCommandProposal ? "Execute" :
        pendingScheduledProposal ? "Authorize" : "Confirm";
      acceptConfirmation.disabled = Boolean(
        pendingCommandProposal && !pendingCommandProposal.isolation_available
      );
      if (pendingCommandProposal) {
        renderCommand(pendingCommandProposal);
      }
      ui.openDialog(confirmationDialog, {
        returnFocus: messageInput,
        initialFocus: cancelConfirmation,
      });
    }
  } catch (error) {
    if (requestGeneration !== conversationRequestGeneration) return;
    if (Array.isArray(error.authoritativeTranscript)) {
      renderTranscript(error.authoritativeTranscript);
    } else {
      renderTranscript(authoritativeTranscript);
      if (composerRevision === composerRevisionAtClear) {
        messageInput.value = message;
      }
      try {
        await loadSession();
      } catch (_loadError) {
        // The original transport error remains the useful visible failure.
      }
    }
    showError(error.message);
    terminalStatus = localCommand ? "Local command failed · Connected locally" :
      "Generation failed · Connected locally";
    terminalState = "warning";
  } finally {
    if (requestGeneration === conversationRequestGeneration) {
      activeStreamingDraft = null;
      activeForegroundKind = null;
      localConversationPending = false;
      setBusy(false, terminalStatus);
      ui.setStatus(statusArea, terminalStatus, terminalState);
      refreshAttention({immediate: true});
      loadChats();
      messageInput.focus();
    }
  }
});

async function submitVoiceFinal(admission) {
  if (!admission || typeof admission.text !== "string" || !admission.text.trim()) {
    throw new Error("Tori cannot accept that voice turn right now.");
  }
  const authoritativeTranscript = visibleTranscript;
  const message = admission.text;
  let autoSpeechForTurn = false;
  if (autoSpeech && speechAvailable) {
    try {
      await audioActivation.activate();
      autoSpeechForTurn = true;
    } catch (error) {
      setSpeechStatus(error.message, "warning");
    }
  }
  preserveInterruptedDraft();
  const requestGeneration = ++conversationRequestGeneration;
  activeForegroundKind = "model";
  showError("");
  localConversationPending = true;
  setBusy(true, "Tori is generating a response…");
  const draftText = renderStreamingDraft(message);
  activeStreamingDraft = {
    afterIndex: visibleTranscript.length,
    generation: requestGeneration,
    textElement: draftText,
    user: message,
  };
  try {
    const result = await requestStream("/api/voice-input/admit", {
      epoch: admission.epoch, lease: admission.lease,
      lease_generation: admission.lease_generation, revision: admission.revision,
      segment: admission.segment, event_sequence: admission.event_sequence,
      auto_speech: autoSpeechForTurn,
    }, (delta) => {
      if (requestGeneration !== conversationRequestGeneration) return;
      const shouldFollow = isNearConversationBottom();
      draftText.append(document.createTextNode(delta));
      followConversationIfNeeded(shouldFollow);
    }, (statusText) => {
      if (requestGeneration === conversationRequestGeneration) {
        ui.setStatus(statusArea, statusText, "busy");
      }
    }, (session) => {
      if (requestGeneration === conversationRequestGeneration) beginSpeech(session);
    });
    if (requestGeneration !== conversationRequestGeneration) return result;
    renderTranscript(result.transcript);
    renderCommand(result.command);
    if (result.type === "error") throw new Error(result.error);
    await loadSession();
    return result;
  } catch (error) {
    if (requestGeneration !== conversationRequestGeneration) throw error;
    renderTranscript(authoritativeTranscript);
    if (!messageInput.value.trim()) {
      messageInput.value = message;
      composerRevision += 1;
    }
    try { await loadSession(); } catch (_loadError) {}
    showError(error.message);
    throw error;
  } finally {
    if (requestGeneration === conversationRequestGeneration) {
      activeStreamingDraft = null;
      activeForegroundKind = null;
      localConversationPending = false;
      setBusy(false, "Connected locally");
      refreshAttention({immediate: true});
      loadChats();
    }
  }
}

function canStartVoiceTurn() {
  return !busy || activeForegroundKind === "model" || activeSpeechSession !== null ||
    activeAudioSources.size > 0;
}

async function beginVoiceTurn() {
  if (!canStartVoiceTurn()) return false;
  const interruptedPlayback = activeSpeechSession !== null ||
    activeAudioSources.size > 0;
  stopSpeaking({
    notifyServer: true,
    message: "Speech interrupted. Listening for your next turn…",
    resetAudio: true,
  });
  if (autoSpeech && speechAvailable) {
    try {
      await audioActivation.activate();
    } catch (error) {
      setSpeechStatus(error.message, "warning");
    }
  }
  return {allowed: true, discardPreRoll: interruptedPlayback};
}

document.addEventListener("tori:voicepartial", (event) => {
  const text = event.detail?.text;
  voicePartial.textContent = typeof text === "string" ? text : "";
  voicePartial.hidden = !voicePartial.textContent;
});
document.addEventListener("tori:voiceerror", (event) => {
  if (typeof event.detail === "string") showError(event.detail);
});
window.ToriConversation = Object.freeze({
  beginVoiceTurn,
  canStartVoiceTurn,
  isBusy: () => busy,
  openArchivedChat,
  startProjectChat,
  submitVoiceFinal,
});

messageInput.addEventListener("input", () => {
  composerRevision += 1;
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

newSessionButton.addEventListener("click", async () => {
  if (busy) {
    return;
  }
  stopSpeaking({resetAudio: true});
  showError("");
  setBusy(true, "Starting a new conversation…");
  try {
    let result;
    try {
      result = await request("/api/new-session", {confirmed: false});
    } catch (error) {
      if (error.code !== "new_session_confirmation_required") {
        throw error;
      }
      setBusy(false, "Connected locally");
      const accepted = window.confirm(
        "Start a new conversation? This conversation could not be archived and " +
        "its visible transcript will be lost."
      );
      if (!accepted) {
        return;
      }
      setBusy(true, "Starting a new conversation…");
      result = await request("/api/new-session", {confirmed: true});
    }
    renderTranscript(result.transcript);
    renderSelectedModel(result.selected_model);
    renderContextState(result.context);
    renderActiveProject(result.project);
    ui.navigate("conversation", {focus: false});
    messageInput.focus();
    await loadChats();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false, "Connected locally");
  }
});

async function startProjectChat(project) {
  if (busy) return false;
  stopSpeaking({resetAudio: true});
  showError("");
  setBusy(true, "Starting a new Project chat…");
  try {
    let result;
    try {
      result = await request("/api/projects/new-chat", {
        identifier: project.identifier,
        expected_revision: project.revision,
        confirmed: false,
      });
    } catch (error) {
      if (error.code !== "new_session_confirmation_required") throw error;
      setBusy(false, "Connected locally");
      const accepted = window.confirm(
        "Start a new Project chat? This conversation could not be archived and " +
        "its visible transcript will be lost."
      );
      if (!accepted) return false;
      setBusy(true, "Starting a new Project chat…");
      result = await request("/api/projects/new-chat", {
        identifier: project.identifier,
        expected_revision: project.revision,
        confirmed: true,
      });
    }
    renderTranscript(result.transcript);
    renderSelectedModel(result.selected_model);
    renderContextState(result.context);
    renderActiveProject(result.project);
    ui.navigate("conversation");
    messageInput.focus();
    await loadChats();
    return true;
  } finally {
    setBusy(false, "Connected locally");
  }
}

autoSpeechButton.addEventListener("click", async () => {
  if (!speechAvailable || busy) {
    return;
  }
  autoSpeech = !autoSpeech;
  autoSpeechButton.setAttribute("aria-pressed", String(autoSpeech));
  autoSpeechButton.setAttribute(
    "aria-label", `Turn automatic speech ${autoSpeech ? "off" : "on"}`
  );
  autoSpeechButton.textContent = `Auto voice: ${autoSpeech ? "On" : "Off"}`;
  if (autoSpeech) {
    try {
      await audioActivation.activate();
      setSpeechStatus("Automatic speech is on.", "success");
    } catch (error) {
      autoSpeech = false;
      autoSpeechButton.setAttribute("aria-pressed", "false");
      autoSpeechButton.setAttribute("aria-label", "Turn automatic speech on");
      autoSpeechButton.textContent = "Auto voice: Off";
      setSpeechStatus(error.message, "warning");
    }
  } else {
    stopSpeaking({notifyServer: true, message: "Automatic speech is off.", resetAudio: true});
  }
});

stopSpeechButton.addEventListener("click", () => stopSpeaking({resetAudio: true}));

refreshChatsButton.addEventListener("click", loadChats);

document.addEventListener("tori:utilityaction", async (event) => {
  const action = event.detail?.action;
  if (action === "model") {
    ui.navigate("conversation");
    openModelControlsButton.click();
  } else if (action === "new") {
    ui.navigate("conversation");
    newSessionButton.click();
  } else if (action === "tasks") {
    ui.navigate("tasks");
  } else if (action === "settings") {
    ui.navigate("settings");
  }
});

const planningActionDialog = document.getElementById("planning-action-dialog");
const planningActionForm = document.getElementById("planning-action-form");
const planningActionHeading = document.getElementById("planning-action-heading");
const planningActionCommand = document.getElementById("planning-action-command");
const planningActionKind = document.getElementById("planning-action-kind");
const planningActionTitle = document.getElementById("planning-action-title");
const planningActionWhen = document.getElementById("planning-action-when");

document.addEventListener("tori:planningaction", (event) => {
  const {action, item} = event.detail || {};
  if (action === "complete" || action === "delete") {
    const message = action === "complete" ? `Mark ${item.title} done.` :
      `${item.kind === "event" ? "Cancel" : "Delete"} ${item.title}.`;
    messageInput.value = message; composer.requestSubmit(); return;
  }
  planningActionCommand.value = action === "edit" ? `edit-${item.kind}` : "new";
  planningActionHeading.textContent = action === "edit" ? `Edit ${item.title}` : "Add to Planning";
  planningActionKind.value = item?.kind || "task";
  planningActionKind.disabled = action === "edit";
  planningActionTitle.value = item?.title || "";
  planningActionTitle.readOnly = action === "edit";
  planningActionWhen.value = "";
  ui.openDialog(planningActionDialog, {returnFocus: document.activeElement, initialFocus: action === "edit" ? planningActionWhen : planningActionTitle});
});

document.getElementById("planning-action-cancel")?.addEventListener("click", () => ui.closeDialog(planningActionDialog));
planningActionForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const title = planningActionTitle.value.trim();
  const when = planningActionWhen.value.trim();
  const command = planningActionCommand.value;
  let message;
  if (command === "edit-event") message = `Move the ${title} appointment to ${when}.`;
  else if (command === "edit-task") message = `Make ${title} due ${when}.`;
  else if (planningActionKind.value === "event") message = `Add ${title} ${when}.`;
  else if (planningActionKind.value === "reminder") message = `Remind me ${when} to ${title}.`;
  else message = `Add a task to ${title} ${when}.`;
  ui.closeDialog(planningActionDialog);
  messageInput.value = message;
  composer.requestSubmit();
});

window.ToriUtilityRail?.setCodingWorkCancelHandler(async ({
  identifier, expectedRevision,
}) => {
  try {
    return await request("/api/coding-work/cancel", {
      identifier,
      expected_revision: expectedRevision,
    });
  } catch (error) {
    await loadCodingWork();
    throw error;
  }
});

window.ToriUtilityRail?.setResearchCancelHandler(async ({identifier, expectedRevision}) => {
  try {
    const result = await request("/api/research/cancel", {
      identifier, expected_revision: expectedRevision,
    });
    await loadResearch();
    return result;
  } catch (error) {
    await loadResearch();
    throw error;
  }
});

async function completeConfirmation(decision) {
  const token = pendingConfirmationToken;
  const confirmationSourceAtDecision = pendingConfirmationSource;
  const commandProposalAtDecision = pendingCommandProposal;
  const planningProposalAtDecision = pendingPlanningProposal;
  pendingConfirmationToken = null;
  pendingConfirmationSource = null;
  ui.closeDialog(confirmationDialog);
  if (!token) {
    return;
  }
  if (confirmationSourceAtDecision === "durable-memory") {
    try {
      await request("/api/confirm", {token, decision});
    } catch (error) {
      showError(error.message);
    }
    return;
  }
  if (commandProposalAtDecision && decision === "confirm") {
    renderCommand({...commandProposalAtDecision, status: "starting"});
  }
  let commandContinues = false;
  setBusy(true, "Applying the confirmed local change…");
  try {
    const result = await request("/api/confirm", {token, decision});
    renderTranscript(result.transcript);
    renderCommand(result.command);
    commandContinues = commandIsActive(result.command);
    if (commandContinues) {
      startCommandPolling(result.command.invocation_id);
      setBusy(true, result.command.status === "running" ?
        "Supervised command running…" : "Starting supervised command…");
    }
  } catch (error) {
    showError(error.message);
    if (commandProposalAtDecision && decision === "confirm") {
      await loadSession();
      commandContinues = commandIsActive({
        invocation_id: currentCommandInvocationId,
        status: renderedCommandStatus,
      });
    }
  } finally {
    pendingCommandProposal = null;
    pendingScheduledProposal = null;
    pendingSystemServiceProposal = null;
    pendingPlanningProposal = false;
    commandProposal.hidden = true;
    commandProposal.textContent = "";
    acceptConfirmation.textContent = "Confirm";
    acceptConfirmation.disabled = false;
    if (!commandContinues) {
      setBusy(false, "Connected locally");
    }
    loadCodingWork();
    loadResearch();
    messageInput.focus();
  }
}

acceptConfirmation.addEventListener("click", (event) => {
  event.preventDefault();
  completeConfirmation("confirm");
});

cancelConfirmation.addEventListener("click", (event) => {
  event.preventDefault();
  completeConfirmation("cancel");
});
confirmationDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  completeConfirmation("cancel");
});

stopCommandButton.addEventListener("click", async () => {
  const invocationId = currentCommandInvocationId;
  if (!invocationId) {
    return;
  }
  stopCommandButton.disabled = true;
  try {
    const result = await request("/api/commands/stop", {
      invocation_id: invocationId,
    });
    renderCommand(result.command);
    startCommandPolling(invocationId);
    ui.setStatus(statusArea, "Stopping supervised command…", "busy");
  } catch (error) {
    showError(error.message);
    stopCommandButton.disabled = false;
  }
});

commandDetailsButton.addEventListener("click", () => {
  if (commandActivity.hidden || !currentCommandInvocationId) {
    return;
  }
  commandDetailsDialog.scrollTop = 0;
  ui.openDialog(commandDetailsDialog, {
    returnFocus: commandDetailsButton,
    initialFocus: closeCommandDetailsButton,
  });
});

dismissCommandButton.addEventListener("click", () => {
  if (!currentCommandInvocationId ||
      ["authorized", "starting", "running"].includes(renderedCommandStatus)) {
    return;
  }
  dismissedCommandInvocationId = currentCommandInvocationId;
  commandActivity.hidden = true;
  dismissCommandButton.hidden = true;
});

loadSession();
loadChats();
loadUpcoming();
loadHostStatus();
loadCodingWork();
loadResearch();
loadCompanionAttention();
loadModels();
loadSpeechState();
refreshAttention({immediate: true});
}());
