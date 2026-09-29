"use strict";

(function registerSettingsModule() {
function loadSettingsStylesheet() {
  if (document.getElementById("settings-module-styles")) {
    return;
  }
  const stylesheet = document.createElement("link");
  stylesheet.id = "settings-module-styles";
  stylesheet.rel = "stylesheet";
  stylesheet.href = "/assets/settings.css";
  document.head.append(stylesheet);
}

function settingElement(tagName, options = {}, ...children) {
  const element = document.createElement(tagName);
  if (options.id) element.id = options.id;
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = options.text;
  for (const [name, value] of Object.entries(options.attributes || {})) {
    element.setAttribute(name, value);
  }
  for (const child of children.flat()) {
    element.append(
      typeof child === "string" ? document.createTextNode(child) : child
    );
  }
  return element;
}

function settingsButton(identifier, label, className = "button secondary", attributes = {}) {
  return settingElement("button", {
    id: identifier,
    className,
    text: label,
    attributes: {type: "button", ...attributes},
  });
}

function labelledField(label, identifier, field) {
  return [
    settingElement("label", {text: label, attributes: {for: identifier}}),
    field,
  ];
}

function buildSettingsView(root) {
  const h = settingElement;
  const capabilityCard = (identifier, toggleIdentifier, title, description) => h(
    "article", {className: "settings-card surface-card", attributes: {"aria-labelledby": `${identifier}-heading`}},
    h("div", {},
      h("h3", {id: `${identifier}-heading`, text: title}),
      h("p", {text: description})
    ),
    h("dl", {id: `${identifier}-state`, className: "settings-state"}),
    settingsButton(toggleIdentifier, "Loading…", "button secondary", {"aria-pressed": "false", disabled: ""})
  );
  const header = h(
    "header", {className: "view-header"},
    h("div", {},
      h("p", {className: "eyebrow", text: "Local preferences"}),
      h("h1", {id: "settings-heading", text: "Settings"})
    ),
    settingsButton("refresh-settings", "Refresh")
  );
  const webSearchCard = capabilityCard(
      "web-search-setting",
      "toggle-web-search",
      "Web Search",
      "Controls authorized searches through Tori's configured local search service. Existing consent and source attribution still apply."
    );
  const speechCard = capabilityCard(
      "speech-output-setting",
      "toggle-speech-output",
      "Speech Output",
      "Controls manual and automatic speech on every browser. Automatic Speech itself remains a temporary preference for this browser only."
    );
  const operatorActivityCard = capabilityCard(
      "operator-activity-log-setting",
      "toggle-operator-activity-log",
      "Operator Activity Log",
      "Shows concise privacy-safe lifecycle and activity events in Tori's terminal. Errors remain visible when this is off."
    );
  const remoteChatCard = h(
    "article", {className: "settings-card surface-card", attributes: {"aria-labelledby": "remote-chat-setting-heading"}},
    h("div", {},
      h("h3", {id: "remote-chat-setting-heading", text: "Discord Remote Chat"}),
      h("p", {text: "Controls only durable owner enablement for the existing private Discord connector. Credentials and identities remain CLI-only."})
    ),
    h("dl", {id: "remote-chat-setting-state", className: "settings-state"}),
    h("p", {id: "remote-chat-setting-explanation", className: "context-semantics"}),
    settingsButton("toggle-remote-chat", "Loading…", "button secondary", {"aria-pressed": "false", disabled: ""})
  );
  const companionCard = h(
    "div", {className: "settings-card-stack companion-settings"},
    h("article", {className: "settings-card surface-card"},
      h("div", {},
        h("h3", {text: "Proactive Companion"}),
        h("p", {text: "Allows occasional local Conversation check-ins. It never authorizes Search, actions, remote messages, or automatic speech."})
      ),
      h("dl", {id: "companion-setting-state", className: "settings-state"}),
      settingsButton("toggle-companion-master", "Loading…", "button secondary", {"aria-pressed": "false", disabled: ""})
    ),
    h("article", {className: "surface-card companion-type-settings"},
      h("h3", {text: "Check-in types"}),
      h("div", {className: "companion-toggle-grid"},
        settingsButton("toggle-companion-morning", "Morning · Off", "button secondary", {"aria-pressed": "false", disabled: ""}),
        settingsButton("toggle-companion-resume", "Resume work · Off", "button secondary", {"aria-pressed": "false", disabled: ""}),
        settingsButton("toggle-companion-silence", "Long silence · Off", "button secondary", {"aria-pressed": "false", disabled: ""}),
        settingsButton("toggle-companion-night-owl", "Night Owl findings · Off", "button secondary", {"aria-pressed": "false", disabled: ""})
      )
    ),
    h("form", {id: "companion-time-form", className: "surface-card companion-time-form"},
      h("h3", {text: "Local time windows"}),
      h("p", {id: "companion-timezone", className: "context-semantics"}),
      h("div", {className: "companion-time-grid"},
        ...labelledField("Morning starts", "companion-morning-start", h("input", {id: "companion-morning-start", attributes: {type: "time", required: ""}})),
        ...labelledField("Morning ends", "companion-morning-end", h("input", {id: "companion-morning-end", attributes: {type: "time", required: ""}})),
        ...labelledField("Quiet hours start", "companion-quiet-start", h("input", {id: "companion-quiet-start", attributes: {type: "time", required: ""}})),
        ...labelledField("Quiet hours end", "companion-quiet-end", h("input", {id: "companion-quiet-end", attributes: {type: "time", required: ""}}))
      ),
      settingsButton("save-companion-times", "Save time windows", "button primary", {type: "submit", disabled: ""})
    ),
    h("article", {className: "surface-card companion-pause-settings"},
      h("h3", {text: "Pause check-ins"}),
      h("p", {text: "A pause affects only proactive check-ins. Conversation and every other Tori capability continue normally."}),
      h("div", {className: "companion-pause-actions"},
        settingsButton("pause-companion-day", "Pause 1 day", "button secondary", {disabled: ""}),
        settingsButton("pause-companion-week", "Pause 1 week", "button secondary", {disabled: ""}),
        settingsButton("resume-companion-now", "Resume now", "button secondary", {disabled: ""})
      )
    ),
    h("p", {className: "context-semantics", text: "Fixed protections: 15-minute recent-activity suppression, a 24-hour global cooldown, and no more than 3 check-ins per 7 days or 8 per 30 days."})
  );
  const nightOwlCategories = [
    ["local_models", "Local models"],
    ["voice", "Voice / TTS / STT"],
    ["image_generation", "Image generation"],
    ["coding_agents", "Coding and agent tooling"],
    ["mcp_infrastructure", "MCP infrastructure"],
    ["skills_tori_tools", "Skills and Tori-relevant tools"],
    ["security", "Security intelligence"],
  ];
  const nightOwlCard = h(
    "div", {className: "settings-card-stack night-owl-settings"},
    h("article", {className: "surface-card night-owl-master"},
      h("div", {},
        h("h3", {text: "Bounded background research"}),
        h("p", {text: "Turning this on authorizes public research only for the categories you select. It is separate from interactive Search and never authorizes installation, execution, configuration changes, or broader browsing."})
      ),
      h("dl", {id: "night-owl-state", className: "settings-state"}),
      settingsButton("toggle-night-owl", "Turn On", "button secondary", {"aria-pressed": "false", disabled: ""})
    ),
    h("article", {className: "surface-card"},
      h("h3", {text: "Research categories"}),
      h("p", {text: "At least one category is required while Night Owl is on. Changing this selection replaces the durable grant and fences older schedules."}),
      h("div", {id: "night-owl-categories", className: "night-owl-category-grid"},
        ...nightOwlCategories.map(([identifier, label]) => h(
          "label", {className: "night-owl-category", attributes: {for: `night-owl-category-${identifier}`}},
          h("input", {id: `night-owl-category-${identifier}`, attributes: {type: "checkbox", value: identifier, "data-night-owl-category": identifier}}),
          h("span", {text: label})
        ))
      ),
      settingsButton("save-night-owl-categories", "Save categories", "button primary", {disabled: ""})
    ),
    h("form", {id: "night-owl-schedule-form", className: "surface-card night-owl-schedule"},
      h("h3", {text: "Schedule"}),
      h("p", {text: "A missed run is skipped; Tori does not catch it up at startup. Research may run during Quiet Hours, but Companion check-ins remain suppressed."}),
      h("div", {className: "night-owl-schedule-grid"},
        ...labelledField("Mode", "night-owl-schedule-mode", h("select", {id: "night-owl-schedule-mode"},
          h("option", {text: "On demand only", attributes: {value: "on_demand"}}),
          h("option", {text: "Nightly", attributes: {value: "nightly"}}),
          h("option", {text: "Weekly", attributes: {value: "weekly"}})
        )),
        ...labelledField("Local time", "night-owl-schedule-time", h("input", {id: "night-owl-schedule-time", attributes: {type: "time", value: "02:00", required: ""}})),
        ...labelledField("Weekly day", "night-owl-schedule-weekday", h("select", {id: "night-owl-schedule-weekday"},
          ...["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, index) => h("option", {text: day, attributes: {value: String(index)}}))
        ))
      ),
      h("div", {className: "night-owl-actions"},
        settingsButton("save-night-owl-schedule", "Save schedule", "button primary", {type: "submit", disabled: ""}),
        settingsButton("pause-night-owl-schedule", "Pause", "button secondary", {disabled: ""}),
        settingsButton("resume-night-owl-schedule", "Resume", "button secondary", {disabled: ""}),
        settingsButton("cancel-night-owl-schedule", "Cancel schedule", "button secondary", {disabled: ""})
      )
    ),
    h("article", {className: "surface-card night-owl-run-controls"},
      h("div", {},
        h("h3", {text: "Run and status"}),
        h("p", {text: "Run one bounded review using the enabled categories. Progress also appears in Workspace while research is active."})
      ),
      h("div", {className: "night-owl-run-action"},
        settingsButton("run-night-owl-now", "Run Night Owl Now", "button primary", {disabled: ""})
      )
    ),
    h("article", {className: "surface-card night-owl-last-run-card"},
      h("h3", {id: "night-owl-last-run-details-heading", text: "Last Run Details"}),
      h("div", {id: "night-owl-last-run-details", className: "night-owl-last-run-details", attributes: {"aria-labelledby": "night-owl-last-run-details-heading"}})
    ),
    h("article", {className: "surface-card"},
      h("div", {className: "night-owl-review-heading"},
        h("div", {}, h("h3", {text: "Findings"}), h("p", {text: "Source facts and model interpretation are shown separately. Findings are advisory until you choose a next step."}))
      ),
      h("div", {id: "night-owl-findings", className: "record-list night-owl-findings"})
    )
  );
  const voiceInputCard = h(
    "article", {className: "settings-card surface-card", attributes: {"aria-labelledby": "voice-input-setting-heading"}},
    h("div", {},
      h("h3", {id: "voice-input-setting-heading", text: "Voice Input"}),
      h("p", {text: "Desktop microphone input stays off until you explicitly turn it on. Ready keeps the selected browser microphone local; audio is sent only while push-to-talk is active."})
    ),
    h("dl", {id: "voice-input-setting-state", className: "settings-state"}),
    h("label", {text: "Microphone", attributes: {for: "voice-microphone"}}),
    h("select", {id: "voice-microphone", className: "voice-microphone", attributes: {disabled: "", "aria-label": "Voice input microphone"}},
      h("option", {text: "Default microphone", attributes: {value: ""}})
    ),
    h("label", {text: "Push-to-talk mode", attributes: {for: "voice-input-ptt-mode"}}),
    h("select", {id: "voice-input-ptt-mode"},
      h("option", {text: "Hold to talk", attributes: {value: "hold"}}),
      h("option", {text: "Toggle to talk", attributes: {value: "toggle"}})
    ),
    settingsButton("toggle-voice-input", "Turn On", "button secondary", {"aria-pressed": "false"})
  );
  const ttsProfiles = h(
    "section", {className: "tts-profile-management settings-section", attributes: {"aria-labelledby": "tts-profiles-heading"}},
    h("div", {className: "provider-management-heading"},
      h("div", {},
        h("h3", {id: "tts-profiles-heading", text: "TTS profiles"}),
        h("p", {text: "Save and select provider-neutral speech configurations. The selected enabled profile supplies future speech sessions."})
      ),
      settingsButton("add-tts-profile", "Add Profile", "button primary")
    ),
    h("p", {id: "tts-profiles-status", className: "status", text: "TTS profiles have not been loaded yet.", attributes: {role: "status", "aria-live": "polite"}}),
    h("p", {id: "tts-profiles-error", className: "error", attributes: {role: "alert", hidden: ""}}),
    h("article", {className: "tts-active-profile surface-card", attributes: {"aria-labelledby": "tts-active-profile-heading"}},
      h("div", {},
        h("span", {className: "availability-badge", text: "Active selection"}),
        h("h4", {id: "tts-active-profile-heading", text: "No active TTS profile"}),
        h("p", {id: "tts-active-profile-detail", text: "Select an enabled saved profile when one is available."})
      )
    ),
    h("div", {id: "tts-profiles-list", className: "record-list tts-profile-list"})
  );
  const maintenance = h(
    "section", {className: "settings-section maintenance-section", attributes: {"aria-labelledby": "maintenance-heading"}},
    h("h2", {id: "maintenance-heading", text: "Maintenance"}),
    h("article", {className: "settings-card surface-card", attributes: {"aria-labelledby": "backup-setting-heading"}},
      h("div", {},
        h("h3", {id: "backup-setting-heading", text: "Verified Tori backup"}),
        h("p", {text: "Creates a complete disaster-recovery snapshot of this Tori project, including local runtime data, and publishes it only after verification succeeds."}),
        h("p", {}, "Backup destination: sibling of the Tori installation (", h("code", {id: "backup-destination", text: "<installation-name>_backups"}), ")")
      ),
      h("dl", {id: "backup-state", className: "settings-state"}),
      settingsButton("backup-now", "Back Up Now", "button primary"),
      h("section", {className: "restore-management", attributes: {"aria-labelledby": "restore-backups-heading"}},
        h("h3", {id: "restore-backups-heading", text: "Restore Backup"}),
        h("p", {text: "Catalog status is based on publication metadata. A selected backup must fully reverify and have a trusted source commit before restore."}),
        h("div", {id: "restore-list", className: "record-list restore-list"})
      )
    )
  );
  const restoreDialog = h(
    "dialog", {id: "restore-confirm-dialog", className: "dialog", attributes: {"aria-labelledby": "restore-confirm-heading", "aria-describedby": "restore-confirm-description"}},
    h("form", {id: "restore-confirm-form", className: "dialog-card", attributes: {method: "dialog"}},
      h("h2", {id: "restore-confirm-heading", text: "Confirm Restore Backup"}),
      h("p", {id: "restore-confirm-description", text: "Tori will stop temporarily and replace current runtime/state. This machine's tori.toml is preserved. Finance, Radicale, and Knowledge source data are excluded. A fresh verified safety backup is required first."}),
      h("p", {id: "restore-confirm-backup", className: "record-meta"}),
      h("div", {className: "dialog-actions"},
        settingsButton("cancel-restore", "Cancel"),
        settingsButton("confirm-restore", "Restore and Restart", "button primary", {type: "submit"})
      )
    )
  );
  const providers = h(
    "section", {className: "provider-management settings-section", attributes: {"aria-labelledby": "model-providers-heading"}},
    h("div", {className: "provider-management-heading"},
      h("div", {},
        h("h2", {id: "model-providers-heading", text: "Providers"}),
        h("p", {text: "Built-in local profiles keep their stable identity and deletion protection while operational settings remain editable. User-owned OpenAI-compatible profiles retain enable and delete controls."})
      ),
      settingsButton("add-model-provider", "Add Provider", "button primary")
    ),
    h("p", {id: "model-providers-status", className: "status", text: "Provider profiles have not been loaded yet.", attributes: {role: "status", "aria-live": "polite"}}),
    h("p", {id: "model-providers-error", className: "error", attributes: {role: "alert", hidden: ""}}),
    h("div", {id: "model-providers-list", className: "record-list provider-record-list"})
  );

  const providerFormGrid = h(
    "div", {className: "provider-form-grid"},
    ...labelledField("Name", "model-provider-name", h("input", {id: "model-provider-name", attributes: {maxlength: "80", required: "", autocomplete: "off"}})),
    ...labelledField("Type", "model-provider-type", h("select", {id: "model-provider-type", attributes: {disabled: ""}},
      h("option", {text: "OpenAI Compatible", attributes: {value: "openai_compatible"}}),
      h("option", {text: "Ollama", attributes: {value: "ollama"}})
    )),
    ...labelledField("API URL", "model-provider-url", h("input", {id: "model-provider-url", attributes: {type: "url", maxlength: "512", required: "", inputmode: "url", autocapitalize: "none", spellcheck: "false", placeholder: "http://192.168.1.50:1234/v1"}})),
    ...labelledField("Authentication", "model-provider-authentication", h("select", {id: "model-provider-authentication"},
      h("option", {text: "None", attributes: {value: "none"}}),
      h("option", {text: "Dummy bearer compatibility", attributes: {value: "dummy_bearer"}}),
      h("option", {text: "Environment bearer reference", attributes: {value: "environment_bearer"}})
    )),
    ...labelledField("Structured output", "model-provider-structured", h("select", {id: "model-provider-structured"},
      h("option", {text: "JSON object mode", attributes: {value: "json_object"}}),
      h("option", {text: "Prompt-only compatibility", attributes: {value: "prompt_only"}})
    )),
    ...labelledField("Timeout (seconds)", "model-provider-timeout", h("input", {id: "model-provider-timeout", attributes: {type: "number", min: "0.1", max: "3600", step: "0.1", value: "30", required: ""}})),
    ...labelledField("Known model (optional)", "model-provider-known-model", h("input", {id: "model-provider-known-model", attributes: {maxlength: "240", autocapitalize: "none", spellcheck: "false"}})),
    ...labelledField("Verified context capacity (optional)", "model-provider-known-capacity", h("input", {id: "model-provider-known-capacity", attributes: {type: "number", min: "1024", max: "10000000", step: "1"}}))
  );
  const providerDialog = h(
    "dialog", {id: "model-provider-dialog", className: "dialog", attributes: {"aria-labelledby": "model-provider-dialog-heading", "aria-describedby": "model-provider-dialog-description"}},
    h("form", {id: "model-provider-form", className: "dialog-card provider-form-card", attributes: {method: "dialog"}},
      h("h2", {id: "model-provider-dialog-heading", text: "Add model provider"}),
      h("p", {id: "model-provider-dialog-description", text: "Only numeric IPv4 loopback or private-LAN API roots with an explicit port are accepted. OpenAI-compatible roots normalize to /v1."}),
      providerFormGrid,
      h("section", {id: "model-provider-token-controls", className: "provider-token-controls", attributes: {"aria-labelledby": "model-provider-token-heading"}},
        h("h3", {id: "model-provider-token-heading", text: "Local API token"}),
        h("p", {id: "model-provider-token-status", className: "context-semantics", text: "No token configured."}),
        ...labelledField("New token", "model-provider-token", h("input", {id: "model-provider-token", attributes: {type: "password", maxlength: "4096", autocomplete: "new-password", spellcheck: "false"}})),
        h("div", {className: "record-actions"},
          settingsButton("save-model-provider-token", "Add Token"),
          settingsButton("clear-model-provider-token", "Clear Token", "button secondary")
        )
      ),
      h("p", {className: "context-semantics", text: "Stored tokens remain server-side and owner-private. Tori reports only whether a token is configured and never reads it back into this form."}),
      h("p", {id: "model-provider-dialog-error", className: "error", attributes: {role: "alert", hidden: ""}}),
      h("div", {className: "dialog-actions"},
        settingsButton("cancel-model-provider", "Cancel"),
        settingsButton("save-model-provider", "Save Provider", "button primary", {type: "submit"})
      )
    )
  );
  const deleteDialog = h(
    "dialog", {id: "delete-model-provider-dialog", className: "dialog", attributes: {"aria-labelledby": "delete-model-provider-heading", "aria-describedby": "delete-model-provider-description"}},
    h("form", {id: "delete-model-provider-form", className: "dialog-card", attributes: {method: "dialog"}},
      h("h2", {id: "delete-model-provider-heading", text: "Delete model provider?"}),
      h("p", {id: "delete-model-provider-description", text: "Existing conversations and transcript attribution keep this provider's stable identity. Their selection will become unavailable; Tori will not substitute another provider."}),
      h("p", {id: "delete-model-provider-name"}),
      h("div", {className: "dialog-actions"},
        settingsButton("cancel-delete-model-provider", "Cancel"),
        settingsButton("confirm-delete-model-provider", "Delete Provider", "button danger", {type: "submit"})
      )
    )
  );
  const ttsProfileFormGrid = h(
    "div", {className: "provider-form-grid tts-profile-form-grid"},
    ...labelledField("Profile name", "tts-profile-name", h("input", {id: "tts-profile-name", attributes: {maxlength: "80", required: "", autocomplete: "off"}})),
    ...labelledField("Endpoint", "tts-profile-endpoint", h("input", {id: "tts-profile-endpoint", attributes: {type: "url", maxlength: "512", required: "", inputmode: "url", autocapitalize: "none", spellcheck: "false", placeholder: "http://192.168.1.50:8000/v1"}})),
    ...labelledField("Model (optional)", "tts-profile-model", h("input", {id: "tts-profile-model", attributes: {maxlength: "256", autocapitalize: "none", spellcheck: "false"}})),
    ...labelledField("Voice", "tts-profile-voice", h("input", {id: "tts-profile-voice", attributes: {maxlength: "64", required: "", autocomplete: "off", autocapitalize: "none", spellcheck: "false"}})),
    ...labelledField("Connection timeout (seconds)", "tts-profile-connect-timeout", h("input", {id: "tts-profile-connect-timeout", attributes: {type: "number", min: "0.1", max: "10", step: "0.1", value: "3", required: ""}})),
    ...labelledField("Read timeout (seconds)", "tts-profile-read-timeout", h("input", {id: "tts-profile-read-timeout", attributes: {type: "number", min: "0.1", max: "120", step: "0.1", value: "30", required: ""}})),
    h("label", {className: "tts-profile-enabled", attributes: {for: "tts-profile-enabled"}},
      h("input", {id: "tts-profile-enabled", attributes: {type: "checkbox"}}),
      h("span", {text: "Enabled and eligible for selection"})
    )
  );
  const ttsProfileDialog = h(
    "dialog", {id: "tts-profile-dialog", className: "dialog", attributes: {"aria-labelledby": "tts-profile-dialog-heading", "aria-describedby": "tts-profile-dialog-description"}},
    h("form", {id: "tts-profile-form", className: "dialog-card provider-form-card", attributes: {method: "dialog"}},
      h("h2", {id: "tts-profile-dialog-heading", text: "Add TTS profile"}),
      h("p", {id: "tts-profile-dialog-description", text: "Profiles use Tori's OpenAI-compatible local TTS contract. Configuration is validated offline; saving does not connect or select the profile."}),
      ttsProfileFormGrid,
      h("p", {className: "context-semantics", text: "Credentials, provider discovery, and provider-specific options are not available here."}),
      h("p", {id: "tts-profile-dialog-error", className: "error", attributes: {role: "alert", hidden: ""}}),
      h("div", {className: "dialog-actions"},
        settingsButton("cancel-tts-profile", "Cancel"),
        settingsButton("save-tts-profile", "Save Profile", "button primary", {type: "submit"})
      )
    )
  );
  const deleteTTSProfileDialog = h(
    "dialog", {id: "delete-tts-profile-dialog", className: "dialog", attributes: {"aria-labelledby": "delete-tts-profile-heading", "aria-describedby": "delete-tts-profile-description"}},
    h("form", {id: "delete-tts-profile-form", className: "dialog-card", attributes: {method: "dialog"}},
      h("h2", {id: "delete-tts-profile-heading", text: "Delete TTS profile?"}),
      h("p", {id: "delete-tts-profile-description", text: "This removes the saved configuration. An active profile must be replaced before it can be deleted."}),
      h("p", {id: "delete-tts-profile-name"}),
      h("div", {className: "dialog-actions"},
        settingsButton("cancel-delete-tts-profile", "Cancel"),
        settingsButton("confirm-delete-tts-profile", "Delete Profile", "button danger", {type: "submit"})
      )
    )
  );

  const unavailable = (title, description) => h(
    "article", {className: "settings-unavailable surface-card"},
    h("span", {className: "availability-badge", text: "Unavailable"}),
    h("h3", {text: title}),
    h("p", {text: description})
  );
  const settingsPanel = (identifier, title, description, ...contents) => h(
    "section", {
      id: `settings-panel-${identifier}`,
      className: "settings-workspace-panel",
      attributes: {
        "data-settings-panel": identifier,
        "aria-labelledby": `settings-${identifier}-heading`,
        ...(identifier === "models" ? {} : {hidden: ""}),
      },
    },
    h("div", {className: "settings-panel-heading"},
      h("p", {className: "eyebrow", text: "Settings workspace"}),
      h("h2", {id: `settings-${identifier}-heading`, text: title}),
      h("p", {text: description})
    ),
    ...contents
  );
  const navigationItems = [
    ["models", "Models", "Configuration"],
    ["model-settings", "Model Settings"],
    ["night-owl", "Night Owl", "Research"],
    ["companion", "Proactive Companion", "Conversation"],
    ["remote-chat", "Remote Chat", "Connections"],
    ["voice", "Voice"],
    ["search", "Search", "Capabilities"],
    ["capabilities", "Capabilities"],
    ["memory", "Memory"],
    ["schedule", "Schedule & Tasks"],
    ["maintenance", "Maintenance"],
    ["appearance", "Appearance", "Interface"],
    ["advanced", "Advanced"],
  ];
  const navigation = h(
    "nav", {className: "settings-navigation", attributes: {"aria-label": "Settings sections"}},
    ...navigationItems.flatMap(([identifier, label, group], index) => [
      ...(group ? [h("p", {className: "settings-nav-group-label", text: group})] : []),
      h("button", {
        className: "settings-nav-item",
        text: label,
        attributes: {
          type: "button",
          "data-settings-target": identifier,
          ...(index === 0 ? {"aria-current": "page"} : {}),
        },
      }),
    ])
  );
  const modelSettingsAction = settingsButton("open-conversation-model-settings", "Open model & context controls", "button primary");
  const memoryAction = settingsButton("open-memory-workspace", "Open Memory workspace", "button secondary");
  const tasksAction = settingsButton("open-tasks-workspace", "Open Tasks & Reminders", "button secondary");
  const scheduleAction = settingsButton("open-schedule-workspace", "Open Scheduled Work", "button secondary");

  root.className = "settings-module";
  root.replaceChildren(
    header,
    h("p", {className: "view-intro", text: "Manage durable local preferences and trusted numeric LOCAL/LAN provider profiles. Local provider tokens stay owner-private on Tori's server and are never returned to the browser."}),
    h("div", {className: "management-feedback"},
      h("p", {id: "settings-status", className: "status", text: "Settings have not been loaded yet.", attributes: {role: "status", "aria-live": "polite", "aria-atomic": "true"}}),
      h("p", {id: "settings-error", className: "error", attributes: {role: "alert", hidden: ""}})
    ),
    h("div", {className: "settings-workspace"},
      navigation,
      h("div", {className: "settings-workspace-content"},
        settingsPanel("models", "Models", "Discover and manage the provider profiles Tori can use without moving provider authority into the browser.",
          h("div", {className: "settings-summary-strip"},
            h("div", {}, h("span", {text: "Scope"}), h("strong", {text: "Local / trusted LAN"})),
            h("div", {}, h("span", {text: "Selection"}), h("strong", {text: "Conversation-owned"})),
            h("div", {}, h("span", {text: "Fallback"}), h("strong", {text: "Never silent"}))
          ),
          providers
        ),
        settingsPanel("model-settings", "Model Settings", "Selection and context are conversation-scoped and use the existing authoritative model controls.",
          h("article", {className: "settings-info-card surface-card"}, h("h3", {text: "Active model and context"}), h("p", {text: "Choose an administrator-configured provider, model, and conversation context without changing archived history."}), modelSettingsAction)
        ),
        settingsPanel("night-owl", "Night Owl", "Choose bounded public research, run it explicitly, schedule it, and review attributed findings without granting action authority.", nightOwlCard),
        settingsPanel("companion", "Proactive Companion", "Opt in to restrained, local-only check-ins and choose when they may appear.", companionCard),
        settingsPanel("remote-chat", "Remote Chat", "View sanitized Discord connector status from any accepted browser; change it only from this computer.",
          remoteChatCard
        ),
        settingsPanel("voice", "Voice", "Manage local speech output and the explicit desktop Voice Input control.",
          h("div", {className: "settings-card-stack"}, voiceInputCard, ttsProfiles, speechCard,
            h("article", {className: "settings-info-card surface-card"}, h("h3", {text: "Voice Input scope"}), h("p", {text: "Push-to-talk can interrupt current speech. Wake phrase and passive listening are not enabled. Voice Input returns Off after a browser or Tori restart."}))
          )
        ),
        settingsPanel("search", "Search", "The existing Web Search preference controls Tori's configured local SearXNG path; provider switching is not implied.",
          h("div", {className: "settings-card-stack"}, webSearchCard,
            h("article", {className: "settings-info-card surface-card"},
              h("h3", {text: "Search implementation"}),
              h("p", {text: "Tori uses the administrator-configured local search service with existing consent, source attribution, and failure boundaries. Endpoint and provider selection are not browser-editable."})
            )
          )
        ),
        settingsPanel("capabilities", "Capabilities", "Capability availability is reported honestly without claiming a generic execution framework.",
          h("div", {className: "settings-card-stack"},
            unavailable("MCP server connections", "Not configured. MCP execution architecture is not implemented in this phase."),
            unavailable("Capability registry", "Not implemented. Tori does not claim a generic capability registry or plugin execution framework.")
          ),
        ),
        settingsPanel("memory", "Memory", "Memory remains application-owned and separate from ordinary conversation archives.",
          h("article", {className: "settings-info-card surface-card"}, h("h3", {text: "Curated memory"}), h("p", {text: "Review and manage existing durable memories in the dedicated Memory workspace."}), memoryAction)
        ),
        settingsPanel("schedule", "Schedule & Tasks", "Open the existing canonical operational workspaces without duplicating their management controls here.",
          h("div", {className: "settings-link-grid"},
            h("article", {className: "settings-info-card surface-card"}, h("h3", {text: "Tasks & Reminders"}), h("p", {text: "Manage durable tasks, scheduled attention, and History."}), tasksAction),
            h("article", {className: "settings-info-card surface-card"}, h("h3", {text: "Scheduled Work"}), h("p", {text: "Review active, paused, and completed authorized work."}), scheduleAction)
          )
        ),
        settingsPanel("maintenance", "Maintenance", "Inspect and run the existing verified backup workflow.", maintenance),
        settingsPanel("appearance", "Appearance", "The Balanced Tori interface is active.", unavailable("Appearance preferences", "The current dark blue/chrome theme is fixed for now. No unimplemented theme control is shown.")),
        settingsPanel("advanced", "Advanced", "Advanced provider details and operator controls remain explicit and bounded.",
          h("div", {className: "settings-card-stack"}, operatorActivityCard,
            h("article", {className: "settings-info-card surface-card"}, h("h3", {text: "Provider boundaries"}), h("p", {text: "Only trusted numeric loopback or private-LAN OpenAI-compatible roots are accepted. Stored local tokens remain server-side; public provider setup remains outside this interface."}))
          )
        )
      )
    ),
    providerDialog,
    deleteDialog,
    ttsProfileDialog,
    deleteTTSProfileDialog,
    restoreDialog
  );
}

function initializeSettings(root) {
  const ui = window.ToriUI;
  const element = (identifier) => root.querySelector(`#${identifier}`);
  const panel = root;
  const refreshButton = element("refresh-settings");
  const backupButton = element("backup-now");
  const backupState = element("backup-state");
  const backupDestination = element("backup-destination");
  const restoreList = element("restore-list");
  const restoreDialog = element("restore-confirm-dialog");
  const restoreForm = element("restore-confirm-form");
  const restoreDescription = element("restore-confirm-description");
  const restoreBackup = element("restore-confirm-backup");
  const restoreCancel = element("cancel-restore");
  const status = element("settings-status");
  const error = element("settings-error");
  const voiceInputButton = element("toggle-voice-input");
  const voiceInputState = element("voice-input-setting-state");
  const voiceInputMode = element("voice-input-ptt-mode");
  const voiceInputMicrophone = element("voice-microphone");
  const companionState = element("companion-setting-state");
  const companionMaster = element("toggle-companion-master");
  const companionMorning = element("toggle-companion-morning");
  const companionResume = element("toggle-companion-resume");
  const companionSilence = element("toggle-companion-silence");
  const companionNightOwl = element("toggle-companion-night-owl");
  const companionTimeForm = element("companion-time-form");
  const companionMorningStart = element("companion-morning-start");
  const companionMorningEnd = element("companion-morning-end");
  const companionQuietStart = element("companion-quiet-start");
  const companionQuietEnd = element("companion-quiet-end");
  const companionTimezone = element("companion-timezone");
  const companionSaveTimes = element("save-companion-times");
  const companionPauseDay = element("pause-companion-day");
  const companionPauseWeek = element("pause-companion-week");
  const companionResumeNow = element("resume-companion-now");
  const companionButtons = [
    companionMaster, companionMorning, companionResume, companionSilence, companionNightOwl,
    companionSaveTimes, companionPauseDay, companionPauseWeek, companionResumeNow,
  ];
  const nightOwlState = element("night-owl-state");
  const nightOwlMaster = element("toggle-night-owl");
  const nightOwlCategorySave = element("save-night-owl-categories");
  const nightOwlCategoryInputs = Array.from(root.querySelectorAll("[data-night-owl-category]"));
  const nightOwlScheduleForm = element("night-owl-schedule-form");
  const nightOwlScheduleMode = element("night-owl-schedule-mode");
  const nightOwlScheduleTime = element("night-owl-schedule-time");
  const nightOwlScheduleWeekday = element("night-owl-schedule-weekday");
  const nightOwlScheduleSave = element("save-night-owl-schedule");
  const nightOwlSchedulePause = element("pause-night-owl-schedule");
  const nightOwlScheduleResume = element("resume-night-owl-schedule");
  const nightOwlScheduleCancel = element("cancel-night-owl-schedule");
  const nightOwlRun = element("run-night-owl-now");
  const nightOwlLastRunDetails = element("night-owl-last-run-details");
  const nightOwlFindings = element("night-owl-findings");
  const nightOwlButtons = [
    nightOwlMaster, nightOwlCategorySave, nightOwlScheduleSave,
    nightOwlSchedulePause, nightOwlScheduleResume, nightOwlScheduleCancel,
    nightOwlRun,
  ];
  window.ToriVoiceInput?.bindMicrophoneControl?.(voiceInputMicrophone);
  const controls = Object.freeze({
    web_search: {
      button: element("toggle-web-search"),
      state: element("web-search-setting-state"),
      path: "/api/settings/web-search",
    },
    speech_output: {
      button: element("toggle-speech-output"),
      state: element("speech-output-setting-state"),
      path: "/api/settings/speech-output",
    },
    operator_activity_log: {
      button: element("toggle-operator-activity-log"),
      state: element("operator-activity-log-setting-state"),
      path: "/api/settings/operator-activity-log",
    },
    remote_chat: {
      button: element("toggle-remote-chat"),
      state: element("remote-chat-setting-state"),
      explanation: element("remote-chat-setting-explanation"),
      path: "/api/settings/remote-chat",
    },
  });
  let current = null;
  let pending = false;
  let restoreConfirmation = null;

  function selectSection(identifier, {focus = false} = {}) {
    for (const item of root.querySelectorAll("[data-settings-target]")) {
      if (item.dataset.settingsTarget === identifier) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    }
    for (const section of root.querySelectorAll("[data-settings-panel]")) {
      const selected = section.dataset.settingsPanel === identifier;
      section.hidden = !selected;
      if (selected && focus) {
        const heading = section.querySelector("h2");
        heading?.setAttribute("tabindex", "-1");
        heading?.focus({preventScroll: true});
      }
    }
  }

  for (const item of root.querySelectorAll("[data-settings-target]")) {
    item.addEventListener("click", () => selectSection(item.dataset.settingsTarget, {focus: true}));
  }
  element("open-conversation-model-settings").addEventListener("click", () => {
    const modelControl = document.getElementById("open-model-controls");
    ui.navigate("conversation");
    modelControl?.click();
  });
  element("open-memory-workspace").addEventListener("click", () => ui.navigate("memories"));
  element("open-tasks-workspace").addEventListener("click", () => ui.navigate("tasks"));
  element("open-schedule-workspace").addEventListener("click", () => ui.navigate("scheduled-work"));

  function addState(definitions, label, value) {
    const term = ui.createElement("dt", "", label);
    const detail = ui.createElement("dd", "", value);
    definitions.append(term, detail);
  }

  function renderVoiceInput(detail = {state: "off", message: "Voice Input is off.", enabled: false, mode: "hold"}) {
    voiceInputState.replaceChildren();
    addState(voiceInputState, "Status", detail.message || "Voice Input is off.");
    addState(voiceInputState, "Microphone", detail.enabled ? "Browser-local selection" : "Released");
    voiceInputButton.textContent = detail.enabled ? "Turn Off" : "Turn On";
    voiceInputButton.setAttribute("aria-pressed", String(Boolean(detail.enabled)));
    voiceInputMode.value = detail.mode === "toggle" ? "toggle" : "hold";
    voiceInputMode.disabled = detail.state === "listening_ptt" || detail.state === "finalizing";
    voiceInputButton.disabled = ["preparing", "listening_ptt", "finalizing"].includes(detail.state);
  }

  function renderCapability(name, capability) {
    const control = controls[name];
    control.state.replaceChildren();
    addState(
      control.state,
      "Administrator",
      capability.administrator_permitted ? "Permitted and configured" : "Not permitted"
    );
    addState(
      control.state,
      "Your preference",
      capability.user_enabled ? "Enabled" : "Disabled"
    );
    addState(
      control.state,
      "Effective state",
      capability.effective_enabled ? "Enabled" : "Disabled"
    );
    control.button.dataset.enabled = String(capability.user_enabled);
    control.button.setAttribute("aria-pressed", String(capability.user_enabled));
    control.button.textContent = capability.user_enabled ? "Disable" : "Enable";
    control.button.disabled = pending || !capability.administrator_permitted;
    if (!capability.administrator_permitted) {
      control.button.textContent = "Administrator disabled";
    }
  }

  function safeNightOwlSource(source) {
    try {
      const value = new URL(source.url);
      return value.protocol === "https:" && ["github.com", "api.github.com", "skills.sh"].includes(value.hostname)
        ? value.href : null;
    } catch (_error) {
      return null;
    }
  }

  function nightOwlList(title, values) {
    const section = ui.createElement("div", "night-owl-finding-list");
    if (title) section.append(ui.createElement("h5", "", title));
    const list = ui.createElement("ul");
    for (const value of values || []) list.append(ui.createElement("li", "", value));
    if (!(values || []).length) list.append(ui.createElement("li", "", "None identified."));
    section.append(list);
    return section;
  }

  function nightOwlRelevance(values) {
    const labels = {
      category_match: "Matches an enabled Night Owl research category.",
      local_self_hosted: "Indicates local or self-hosted operation.",
      protocol_fit: "Mentions a protocol or API Tori can evaluate.",
      tori_subsystem_fit: "Fits an existing Tori capability area.",
      capability_gap: "May address a bounded Capability Growth area.",
      operational_friction: "Links to recorded operational friction.",
      meaningful_improvement: "May materially improve an existing tool.",
    };
    return (values || []).map((value) => labels[value] || "Matched a bounded relevance rule.");
  }

  function nightOwlAction(label, handler, className = "button secondary") {
    const button = ui.createElement("button", className, label);
    button.type = "button";
    button.disabled = pending;
    button.addEventListener("click", handler);
    return button;
  }

  function renderNightOwl(nightOwl) {
    const available = nightOwl?.available === true;
    nightOwlState.replaceChildren();
    addState(nightOwlState, "Status", !available ? "Unavailable" : nightOwl?.enabled ? "On" : "Off");
    addState(nightOwlState, "Authorization", nightOwl?.authorization || "Off");
    addState(nightOwlState, "Run", nightOwl?.status?.running ? "Running" : (nightOwl?.status?.last_run_outcome || "Not run yet"));
    addState(nightOwlState, "Last run", nightOwl?.status?.last_run_time ? new Date(nightOwl.status.last_run_time).toLocaleString() : "None");
    addState(nightOwlState, "Next scheduled run", nightOwl?.schedule?.next_run ? new Date(nightOwl.schedule.next_run).toLocaleString() : "None");
    addState(nightOwlState, "Findings", `${nightOwl?.status?.reviewable_count || 0} reviewable · ${nightOwl?.status?.unseen_count || 0} unseen · ${nightOwl?.status?.findings_count || 0} retained`);
    if (nightOwl?.warning) addState(nightOwlState, "Notice", nightOwl.warning);
    if ((nightOwl?.status?.last_run_errors || []).length) addState(nightOwlState, "Last run detail", nightOwl.status.last_run_errors.join(", "));
    renderNightOwlLastRunDetails((nightOwl?.runs || [])[0]);

    nightOwlMaster.dataset.enabled = String(nightOwl?.enabled === true);
    nightOwlMaster.setAttribute("aria-pressed", String(nightOwl?.enabled === true));
    nightOwlMaster.textContent = nightOwl?.enabled ? "Turn Off" : "Turn On";
    for (const input of nightOwlCategoryInputs) {
      input.checked = (nightOwl?.categories || []).includes(input.value);
      input.disabled = pending || !available;
    }
    nightOwlScheduleMode.value = nightOwl?.schedule?.mode || "on_demand";
    nightOwlScheduleTime.value = nightOwl?.schedule?.local_time || "02:00";
    nightOwlScheduleWeekday.value = String(nightOwl?.schedule?.weekday ?? 6);
    const scheduled = ["nightly", "weekly"].includes(nightOwlScheduleMode.value);
    nightOwlScheduleTime.disabled = pending || !available || !scheduled;
    nightOwlScheduleWeekday.disabled = pending || !available || nightOwlScheduleMode.value !== "weekly";
    for (const button of nightOwlButtons) button.disabled = pending || !available;
    nightOwlRun.disabled = pending || !available || !nightOwl?.enabled || nightOwl?.status?.running;
    nightOwlSchedulePause.disabled = pending || nightOwl?.schedule?.status !== "active";
    nightOwlScheduleResume.disabled = pending || nightOwl?.schedule?.status !== "paused";
    nightOwlScheduleCancel.disabled = pending || !["active", "paused"].includes(nightOwl?.schedule?.status);

    nightOwlFindings.replaceChildren();
    const findings = (nightOwl?.findings || []).filter((finding) => finding.category !== "security");
    if (!findings.length) {
      nightOwlFindings.append(ui.createElement("p", "empty-state", "No other reviewable Night Owl findings are available. Security intelligence is in Security."));
      return;
    }
    for (const finding of findings) {
      const card = ui.createElement("article", "record-card night-owl-finding");
      const heading = ui.createElement("div", "night-owl-finding-heading");
      heading.append(
        ui.createElement("h4", "", finding.title),
        ui.createElement("span", "availability-badge", `${finding.category_name} · ${finding.state}`)
      );
      card.append(
        heading,
        ui.createElement("h5", "eyebrow", "What it is"),
        ui.createElement("p", "night-owl-source-description", finding.source_description),
        ui.createElement("h5", "eyebrow", "Why it may matter"),
        nightOwlList("", nightOwlRelevance(finding.relevance_reasons))
      );
      const details = ui.createElement("section", "night-owl-finding-details");
      details.hidden = true;
      details.append(
        ui.createElement("p", "record-meta", `Finding ID: ${finding.id}`),
        ui.createElement("p", "record-meta", `Observed ${finding.first_observed} · latest ${finding.last_observed} · ${finding.version}`),
        nightOwlList("Source-derived risks", finding.risks),
        nightOwlList("Source-derived unknowns", finding.unknowns),
        ui.createElement("p", "record-meta", `Suggested human-review step: ${finding.suggested_next_step}`)
      );
      if (finding.analysis) {
        const analysis = ui.createElement("section", "night-owl-analysis");
        analysis.append(
          ui.createElement("p", "eyebrow", finding.analysis.label),
          ui.createElement("p", "", finding.analysis.summary),
          ui.createElement("p", "", finding.analysis.why_it_matters),
          nightOwlList("Interpreted risks", finding.analysis.risks),
          nightOwlList("Interpreted unknowns", finding.analysis.unknowns),
          ui.createElement("p", "record-meta", `Human-review next step: ${finding.analysis.next_step}`)
        );
        details.append(analysis);
      }
      const sources = ui.createElement("div", "night-owl-sources");
      sources.append(ui.createElement("h5", "", "Attributed sources"));
      for (const source of finding.sources || []) {
        const safeUrl = safeNightOwlSource(source);
        const item = safeUrl ? document.createElement("a") : ui.createElement("span", "", source.title);
        if (safeUrl) {
          item.textContent = source.title;
          item.href = safeUrl;
          item.target = "_blank";
          item.rel = "noopener noreferrer";
        }
        sources.append(item);
      }
      card.append(sources, details);
      const actions = ui.createElement("div", "night-owl-actions");
      if (finding.state !== "dismissed") {
        actions.append(nightOwlAction("Details", () => {
          details.hidden = !details.hidden;
        }, "button secondary"));
        if (finding.state !== "reviewed") actions.append(nightOwlAction("Mark reviewed", () => updateNightOwlFinding(finding, "reviewed")));
        actions.append(nightOwlAction("Dismiss", () => updateNightOwlFinding(finding, "dismissed")));
        if (finding.promotion) {
          actions.append(ui.createElement("span", "record-meta", `Promoted: ${finding.promotion.recommendation_id}`));
          actions.append(nightOwlAction("Open Capability Growth", () => ui.navigate("skills-mcp")));
        } else {
          actions.append(nightOwlAction("Promote as EXPAND", () => promoteNightOwlFinding(finding, "expand", null), "button primary"));
          for (const option of finding.improve_options || []) {
            actions.append(nightOwlAction(`Promote IMPROVE · ${option.label}`, () => promoteNightOwlFinding(finding, "improve", option.id)));
          }
        }
      }
      card.append(actions);
      nightOwlFindings.append(card);
    }
  }

  function renderNightOwlLastRunDetails(run) {
    nightOwlLastRunDetails.replaceChildren();
    if (!run) {
      nightOwlLastRunDetails.append(ui.createElement("p", "record-meta", "No Night Owl run has completed yet."));
      return;
    }
    const details = run.details;
    if (!details) {
      nightOwlLastRunDetails.append(ui.createElement("p", "record-meta", "Detailed counters are available for runs completed after the current research-depth update."));
      return;
    }
    const used = run.budget_used || {};
    const allowed = current?.night_owl?.budget_profile || {};
    const duration = `${(details.duration_millis / 1000).toFixed(1)} s`;
    const rows = [
      ["Duration", duration],
      ["Searches", `${used.searches || 0} / ${allowed.searches || 0}`],
      ["Results considered", `${used.search_results || 0} / ${allowed.search_results || 0}`],
      ["GitHub-hosted results", String(details.aggregate.github_hosted_results || 0)],
      ["Canonical repository leads", String(details.aggregate.github_eligible_leads || 0)],
      ["Repositories queued", String(details.aggregate.canonical_repositories_queued || 0)],
      ["GitHub fetches", `${used.github_fetches || 0} / ${allowed.github_fetches || 0}`],
      ["Repositories inspected", String(details.aggregate.repositories_inspected || Math.floor((used.github_fetches || 0) / 2))],
      ["Skills catalog candidates", `${details.aggregate.skills_catalog_candidates || used.skills_inspections || 0} / ${allowed.skills_inspections || 0}`],
      ["Skills catalog requests", `${details.aggregate.skills_catalog_successes || 0} successful · ${details.aggregate.skills_catalog_failures || 0} failed`],
      ["Model enrichment calls", `${used.model_calls || 0} / ${allowed.model_calls || 0}`],
      ["Findings created or updated", String(details.aggregate.findings_changed || 0)],
    ];
    const grid = ui.createElement("div", "night-owl-metric-grid");
    for (const [label, value] of rows) {
      const metric = ui.createElement("div", "night-owl-metric");
      metric.append(ui.createElement("span", "", label), ui.createElement("strong", "", value));
      grid.append(metric);
    }
    nightOwlLastRunDetails.append(grid);
    const diagnostics = [
      ["Source-policy rejections", details.aggregate.source_policy_rejected || 0],
      ["Relevance rejections", details.aggregate.relevance_rejected || 0],
      ["Corroboration failures", details.aggregate.corroboration_failures || 0],
      ["Budget-skipped corroboration", details.aggregate.corroboration_budget_skipped || 0],
    ].filter(([, value]) => value > 0);
    if (diagnostics.length || (run.error_codes || []).length) {
      const note = ui.createElement("p", "record-meta night-owl-run-notes");
      note.textContent = [
        ...diagnostics.map(([label, value]) => `${label}: ${value}`),
        ...(run.error_codes || []),
      ].join(" · ");
      nightOwlLastRunDetails.append(note);
    }
    const categoryRows = Object.entries(details.categories || {});
    if (!categoryRows.length) return;
    const coverage = ui.createElement("div", "night-owl-category-coverage");
    coverage.append(ui.createElement("h5", "", "Per-category coverage"));
    for (const [category, counters] of categoryRows) {
      const label = (current?.night_owl?.category_options || []).find(
        (option) => option.id === category
      )?.name || category;
      const card = ui.createElement("div", "night-owl-coverage-card");
      const values = [
        `Searches ${counters.searches_executed || 0}`,
        `Results ${counters.results_considered || 0}`,
        `Repo leads ${counters.github_eligible_leads || 0}`,
        `Queued ${counters.canonical_repositories_queued || 0}`,
        `Inspected ${counters.repositories_inspected || 0}`,
        `Retained ${counters.findings_retained || 0}`,
      ];
      card.append(ui.createElement("h6", "", label), ui.createElement("p", "record-meta", values.join(" · ")));
      coverage.append(card);
    }
    nightOwlLastRunDetails.append(coverage);
  }

  function render(documentBody) {
    current = documentBody;
    renderCapability("web_search", documentBody.web_search);
    renderCapability("speech_output", documentBody.speech_output);
    renderCapability("operator_activity_log", documentBody.operator_activity_log);
    renderRemoteChat(documentBody.remote_chat);
    renderCompanion(documentBody.companion_initiative);
    renderNightOwl(documentBody.night_owl);
  }

  function renderCompanion(companion) {
    companionState.replaceChildren();
    const available = companion?.available === true;
    addState(companionState, "Status", !available ? "Unavailable" : companion.master_enabled ? "On" : "Off");
    addState(companionState, "Pause", companion?.paused ? `Until ${new Date(companion.snoozed_until_utc).toLocaleString()}` : "Not paused");
    addState(companionState, "Last check-in", companion?.last_delivery ?
      `${companion.last_delivery.type} · ${new Date(companion.last_delivery.delivered_at_utc).toLocaleString()}` : "None");
    if (companion?.warning) addState(companionState, "Notice", companion.warning);
    const toggles = [
      [companionMaster, "master_enabled", "Turn On", "Turn Off"],
      [companionMorning, "morning_enabled", "Morning · Off", "Morning · On"],
      [companionResume, "resume_enabled", "Resume work · Off", "Resume work · On"],
      [companionSilence, "long_silence_enabled", "Long silence · Off", "Long silence · On"],
      [companionNightOwl, "night_owl_findings_enabled", "Night Owl findings · Off", "Night Owl findings · On"],
    ];
    for (const [button, field, offLabel, onLabel] of toggles) {
      const enabled = available && companion[field] === true;
      button.dataset.enabled = String(enabled);
      button.setAttribute("aria-pressed", String(enabled));
      button.textContent = enabled ? onLabel : offLabel;
    }
    companionMorningStart.value = companion?.morning_start || "08:00";
    companionMorningEnd.value = companion?.morning_end || "10:00";
    companionQuietStart.value = companion?.quiet_start || "22:00";
    companionQuietEnd.value = companion?.quiet_end || "08:00";
    companionTimezone.textContent = `Times use ${companion?.timezone || "the configured application timezone"}.`;
    for (const button of companionButtons) button.disabled = pending || !available;
    companionResumeNow.disabled = pending || !available || !companion.paused;
    for (const input of companionTimeForm.querySelectorAll("input")) {
      input.disabled = pending || !available;
    }
  }

  function companionBody(overrides = {}) {
    const companion = current.companion_initiative;
    return {
      expected_revision: companion.revision,
      master_enabled: companion.master_enabled,
      morning_enabled: companion.morning_enabled,
      resume_enabled: companion.resume_enabled,
      long_silence_enabled: companion.long_silence_enabled,
      night_owl_findings_enabled: companion.night_owl_findings_enabled,
      morning_start: companionMorningStart.value,
      morning_end: companionMorningEnd.value,
      quiet_start: companionQuietStart.value,
      quiet_end: companionQuietEnd.value,
      ...overrides,
    };
  }

  function selectedNightOwlCategories() {
    return nightOwlCategoryInputs.filter((input) => input.checked).map((input) => input.value);
  }

  async function saveNightOwlSettings(enabled) {
    if (pending || !current?.night_owl) return;
    pending = true;
    ui.showError(error, "");
    ui.setBusy(panel, true);
    try {
      const response = await ui.requestJson("/api/settings/night-owl", {
        method: "POST",
        body: {
          expected_revision: current.night_owl.revision,
          enabled,
          categories: selectedNightOwlCategories(),
        },
      });
      current.night_owl = response.night_owl;
      ui.setStatus(status, enabled ? "Night Owl authorization saved." : "Night Owl turned off and its grant revoked.", "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Night Owl authorization was not changed.", "warning");
      try { current.night_owl = await ui.requestJson("/api/night-owl"); } catch (_error) { /* retain last safe state */ }
    } finally {
      pending = false;
      ui.setBusy(panel, false);
      render(current);
    }
  }

  async function saveNightOwlSchedule() {
    if (pending || !current?.night_owl) return;
    pending = true;
    ui.showError(error, "");
    ui.setBusy(panel, true);
    try {
      const response = await ui.requestJson("/api/night-owl/schedule", {
        method: "POST",
        body: {
          mode: nightOwlScheduleMode.value,
          local_time: nightOwlScheduleTime.value || "02:00",
          weekday: Number(nightOwlScheduleWeekday.value),
        },
      });
      current.night_owl = response.night_owl;
      ui.setStatus(status, nightOwlScheduleMode.value === "on_demand" ? "Night Owl is on demand only." : "Night Owl schedule saved with fresh authorization.", "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Night Owl schedule was not changed.", "warning");
    } finally {
      pending = false;
      ui.setBusy(panel, false);
      render(current);
    }
  }

  async function changeNightOwlSchedule(action) {
    if (pending || !current?.night_owl) return;
    pending = true;
    ui.showError(error, "");
    ui.setBusy(panel, true);
    try {
      const response = await ui.requestJson("/api/night-owl/schedule/action", {
        method: "POST", body: {action},
      });
      current.night_owl = response.night_owl;
      const labels = {pause: "paused", resume: "resumed", cancel: "cancelled"};
      ui.setStatus(status, `Night Owl schedule ${labels[action]}.`, "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Night Owl schedule action was not confirmed.", "warning");
    } finally {
      pending = false;
      ui.setBusy(panel, false);
      render(current);
    }
  }

  async function refreshNightOwl() {
    if (!current) return;
    try {
      current.night_owl = await ui.requestJson("/api/night-owl");
      renderNightOwl(current.night_owl);
      document.dispatchEvent(new CustomEvent("tori:nightowlrevision"));
      if (current.night_owl.status.running) window.setTimeout(refreshNightOwl, 1000);
      else ui.setStatus(status, `Night Owl run ${current.night_owl.status.last_run_outcome || "finished"}.`, current.night_owl.status.last_run_outcome === "failed" ? "warning" : "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Night Owl run status could not be refreshed.", "warning");
    }
  }

  async function runNightOwlNow() {
    if (pending || !current?.night_owl) return;
    pending = true;
    ui.showError(error, "");
    ui.setStatus(status, "Starting one bounded Night Owl run…", "busy");
    try {
      const response = await ui.requestJson("/api/night-owl/run", {method: "POST", body: {}});
      current.night_owl = response.night_owl;
      renderNightOwl(current.night_owl);
      document.dispatchEvent(new CustomEvent("tori:nightowlrevision"));
      window.setTimeout(refreshNightOwl, 350);
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Night Owl did not start.", "warning");
    } finally {
      pending = false;
      render(current);
    }
  }

  async function updateNightOwlFinding(finding, action) {
    if (pending) return;
    pending = true;
    try {
      const response = await ui.requestJson("/api/night-owl/findings/review", {
        method: "POST",
        body: {identifier: finding.id, expected_revision: finding.revision, action},
      });
      current.night_owl = response.night_owl;
      ui.setStatus(status, action === "reviewed" ? "Finding marked reviewed." : "Finding dismissed until meaningful change.", "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Finding state was not changed.", "warning");
    } finally {
      pending = false;
      render(current);
    }
  }

  async function promoteNightOwlFinding(finding, lane, frictionFindingId) {
    if (pending) return;
    pending = true;
    try {
      const response = await ui.requestJson("/api/night-owl/findings/promote", {
        method: "POST",
        body: {identifier: finding.id, lane, friction_finding_id: frictionFindingId},
      });
      current.night_owl = response.night_owl;
      const recommendationId = response.night_owl.promotion?.recommendation_id;
      const reference = recommendationId ? ` (${recommendationId})` : "";
      ui.setStatus(status, `${lane.toUpperCase()} recommendation${reference} created for Capability Growth review. Nothing was installed or executed.`, "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Capability Growth promotion was not completed.", "warning");
    } finally {
      pending = false;
      render(current);
    }
  }

  async function saveCompanion(overrides = {}) {
    if (pending || !current?.companion_initiative?.available) return;
    pending = true;
    ui.showError(error, "");
    ui.setBusy(panel, true);
    try {
      const response = await ui.requestJson("/api/settings/companion-initiative", {
        method: "POST", body: companionBody(overrides),
      });
      current.companion_initiative = response.companion_initiative;
      ui.setStatus(status, "Proactive Companion settings saved.", "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Proactive Companion settings were not changed.", "warning");
      try { current = await ui.requestJson("/api/settings"); } catch (_error) { current = null; }
    } finally {
      pending = false;
      ui.setBusy(panel, false);
      if (current) render(current);
    }
  }

  async function pauseCompanion(duration) {
    if (pending || !current?.companion_initiative?.available) return;
    pending = true;
    ui.showError(error, "");
    ui.setBusy(panel, true);
    try {
      const response = await ui.requestJson("/api/companion-initiative/pause", {
        method: "POST",
        body: {duration, expected_revision: current.companion_initiative.revision},
      });
      current.companion_initiative = response.companion_initiative;
      ui.setStatus(status, duration === "resume_now" ? "Check-ins resumed." : "Check-ins paused.", "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "The pause change was not confirmed.", "warning");
      try { current = await ui.requestJson("/api/settings"); } catch (_error) { current = null; }
    } finally {
      pending = false;
      ui.setBusy(panel, false);
      if (current) render(current);
    }
  }

  function renderRemoteChat(remote) {
    const control = controls.remote_chat;
    const labels = {
      not_configured: "Not configured",
      disabled: "Disabled",
      disconnected: "Configured but disconnected",
      connecting: "Connecting",
      connected: "Connected",
      stopping: "Stopping",
      error: "Error",
    };
    control.state.replaceChildren();
    addState(control.state, "Status", labels[remote.state] || "Unavailable");
    addState(control.state, "Owner enablement", remote.enabled ? "On" : "Off");
    addState(
      control.state,
      "Administrator",
      remote.administrator_permitted ? "Permitted" : "Not permitted"
    );
    control.button.dataset.enabled = String(remote.enabled);
    control.button.setAttribute("aria-pressed", String(remote.enabled));
    control.button.textContent = remote.enabled ? "Turn Off" : "Turn On";
    control.button.disabled = pending || !remote.mutable || (!remote.configured && !remote.enabled);
    if (!remote.mutable) {
      control.explanation.textContent = "Remote Chat can only be changed from this computer.";
    } else if (remote.restart_required) {
      control.explanation.textContent = "The saved state changed. Restart Tori to start this connector.";
    } else if (!remote.configured) {
      control.explanation.textContent = "Configure Discord identities and the bot token with the local CLI first.";
    } else {
      control.explanation.textContent = "The local CLI remains available for the same owner enablement control.";
    }
  }

  function addBackupDetail(term, detail) {
    const label = ui.createElement("dt", "", term);
    const value = ui.createElement("dd", "", detail);
    backupState.append(label, value);
  }

  function formatBytes(value) {
    if (!Number.isSafeInteger(value) || value < 0) {
      return "Unavailable";
    }
    const units = ["bytes", "KiB", "MiB", "GiB", "TiB"];
    let amount = value;
    let index = 0;
    while (amount >= 1024 && index < units.length - 1) {
      amount /= 1024;
      index += 1;
    }
    return index === 0 ? `${amount} ${units[index]}` : `${amount.toFixed(1)} ${units[index]}`;
  }

  function renderBackup(documentBody) {
    backupState.replaceChildren();
    backupDestination.textContent = documentBody.destination;
    if (documentBody.in_progress) {
      addBackupDetail("Current backup", "In progress");
    }
    if (!documentBody.latest) {
      addBackupDetail("Latest published backup", "None found");
      return;
    }
    addBackupDetail("Verification", documentBody.latest.verification === "verified" ? "Verified now" : "Not rechecked since publication");
    addBackupDetail("Completed", documentBody.latest.completed_at);
    addBackupDetail("Directory", documentBody.latest.directory);
    addBackupDetail("Approximate size", formatBytes(documentBody.latest.total_regular_bytes));
  }

  async function loadBackupState() {
    try {
      renderBackup(await ui.requestJson("/api/backups"));
    } catch (requestError) {
      backupState.replaceChildren();
      addBackupDetail("Latest published backup", "Could not be inspected");
    }
    try {
      renderRestores(await ui.requestJson("/api/restores"));
    } catch (requestError) {
      restoreList.replaceChildren(ui.createElement("p", "empty-state", "Restore backups could not be inspected."));
    }
  }

  function renderRestores(documentBody) {
    restoreList.replaceChildren();
    const backups = documentBody.backups || [];
    if (!backups.length) {
      restoreList.append(ui.createElement("p", "empty-state", "No backup publications were found."));
      return;
    }
    for (const backup of backups) {
      const card = ui.createElement("article", "record-card restore-record");
      const summary = ui.createElement("div", "restore-record-summary");
      const sourceCommit = backup.source_commit || "Unknown";
      const sourceIdentity = /^[0-9a-f]{40}$/i.test(sourceCommit)
        ? sourceCommit.slice(0, 7)
        : sourceCommit;
      const sourceValue = ui.createElement(
        "span", "restore-metadata-value restore-source-identity", sourceIdentity
      );
      if (sourceIdentity !== sourceCommit) {
        sourceValue.setAttribute("title", sourceCommit);
      }
      const metadataRow = (label, value, valueClass = "") => {
        const row = ui.createElement("div", "restore-metadata-row");
        row.append(
          ui.createElement("span", "restore-metadata-label", label),
          typeof value === "string"
            ? ui.createElement("span", `restore-metadata-value ${valueClass}`.trim(), value)
            : value
        );
        return row;
      };
      summary.append(
        ui.createElement("h4", "restore-backup-identifier", backup.identifier),
        metadataRow("Created", backup.completed_at || "Unavailable"),
        metadataRow("Verification", backup.verification === "not_rechecked"
          ? "Not rechecked · verifies before restore" : backup.verification),
        metadataRow("Restore compatibility", backup.compatibility),
        metadataRow("Source", sourceValue),
        metadataRow("Approximate size", formatBytes(backup.total_regular_bytes))
      );
      const button = ui.createElement("button", "button secondary", "Restore Backup");
      button.type = "button";
      button.disabled = pending || !backup.selectable || documentBody.restore_pending;
      button.addEventListener("click", () => proposeRestore(backup));
      card.append(summary, button);
      restoreList.append(card);
    }
  }

  async function proposeRestore(backup) {
    if (pending || !backup.selectable) return;
    pending = true;
    ui.showError(error, "");
    ui.setStatus(status, "Preparing the one-use restore confirmation…", "busy");
    try {
      const response = await ui.requestJson("/api/restores/propose", {
        method: "POST", body: {identifier: backup.identifier},
      });
      restoreConfirmation = response.confirmation;
      restoreBackup.textContent = `Backup: ${backup.identifier}`;
      restoreDescription.textContent = response.confirmation.message;
      restoreDialog.showModal();
      ui.setStatus(status, "Review every restore boundary before confirming.", "warning");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Restore was not proposed.", "warning");
    } finally {
      pending = false;
    }
  }

  async function decideRestore(decision) {
    if (pending || !restoreConfirmation) return;
    const confirmation = restoreConfirmation;
    restoreConfirmation = null;
    pending = true;
    restoreDialog.close();
    ui.showError(error, "");
    ui.setBusy(panel, true);
    ui.setStatus(status, decision === "restore" ? "Creating a safety backup and fully verifying the selected backup…" : "Cancelling restore…", "busy");
    try {
      const response = await ui.requestJson("/api/restores/confirm", {
        method: "POST", body: {token: confirmation.token, decision},
      });
      ui.setStatus(status, response.handoff ? "Restore handoff prepared. Tori is stopping temporarily." : "Restore cancelled.", response.handoff ? "warning" : "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Restore stopped safely before activation.", "warning");
      await loadBackupState();
    } finally {
      pending = false;
      ui.setBusy(panel, false);
    }
  }

  async function backUpNow() {
    if (pending) {
      return;
    }
    pending = true;
    backupButton.disabled = true;
    ui.showError(error, "");
    ui.setStatus(status, "Creating and verifying the backup…", "busy");
    ui.setBusy(panel, true);
    try {
      const documentBody = await ui.requestJson("/api/backups", {method: "POST", body: {}});
      renderBackup(documentBody);
      ui.setStatus(status, "Backup completed and verified.", "success");
    } catch (requestError) {
      ui.showError(error, requestError.message);
      ui.setStatus(status, "The backup was not published as verified.", "warning");
      await loadBackupState();
    } finally {
      pending = false;
      backupButton.disabled = false;
      ui.setBusy(panel, false);
    }
  }

  async function loadSettings() {
    if (pending) {
      return;
    }
    ui.showError(error, "");
    ui.setStatus(status, "Loading authoritative settings…", "busy");
    ui.setBusy(panel, true);
    try {
      const documentBody = await ui.requestJson("/api/settings");
      render(documentBody);
      ui.setStatus(status, "Settings are current.", "success");
    } catch (requestError) {
      current = null;
      for (const control of Object.values(controls)) {
        control.button.disabled = true;
      }
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Settings could not be loaded.", "warning");
    } finally {
      await loadBackupState();
      ui.setBusy(panel, false);
    }
  }

  async function change(name) {
    if (pending || !current) {
      return;
    }
    const control = controls[name];
    const desired = control.button.dataset.enabled !== "true";
    pending = true;
    ui.showError(error, "");
    ui.setStatus(status, "Saving setting…", "busy");
    ui.setBusy(panel, true);
    for (const item of Object.values(controls)) {
      item.button.disabled = true;
    }
    try {
      const documentBody = await ui.requestJson(control.path, {
        method: "POST",
        body: {enabled: desired},
      });
      render(documentBody);
      ui.setStatus(status, "Setting saved and applied.", "success");
      if (name === "speech_output") {
        document.dispatchEvent(new CustomEvent("tori:speechsettingchange", {
          detail: {enabled: documentBody.speech_output.effective_enabled},
        }));
      }
    } catch (requestError) {
      pending = false;
      await loadSettings();
      ui.showError(
        error,
        current
          ? requestError.message
          : `${requestError.message} Current settings could not be reloaded.`
      );
      ui.setStatus(status, "The setting was not confirmed as changed.", "warning");
    } finally {
      pending = false;
      ui.setBusy(panel, false);
      if (current) {
        render(current);
      }
    }
  }

  refreshButton.addEventListener("click", loadSettings);
  controls.web_search.button.addEventListener("click", () => change("web_search"));
  controls.speech_output.button.addEventListener("click", () => change("speech_output"));
  controls.operator_activity_log.button.addEventListener("click", () => change("operator_activity_log"));
  controls.remote_chat.button.addEventListener("click", () => change("remote_chat"));
  companionMaster.addEventListener("click", () => saveCompanion({
    master_enabled: companionMaster.dataset.enabled !== "true",
  }));
  companionMorning.addEventListener("click", () => saveCompanion({
    morning_enabled: companionMorning.dataset.enabled !== "true",
  }));
  companionResume.addEventListener("click", () => saveCompanion({
    resume_enabled: companionResume.dataset.enabled !== "true",
  }));
  companionSilence.addEventListener("click", () => saveCompanion({
    long_silence_enabled: companionSilence.dataset.enabled !== "true",
  }));
  companionNightOwl.addEventListener("click", () => saveCompanion({
    night_owl_findings_enabled: companionNightOwl.dataset.enabled !== "true",
  }));
  companionTimeForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveCompanion();
  });
  companionPauseDay.addEventListener("click", () => pauseCompanion("one_day"));
  companionPauseWeek.addEventListener("click", () => pauseCompanion("one_week"));
  companionResumeNow.addEventListener("click", () => pauseCompanion("resume_now"));
  nightOwlMaster.addEventListener("click", () => saveNightOwlSettings(nightOwlMaster.dataset.enabled !== "true"));
  nightOwlCategorySave.addEventListener("click", () => saveNightOwlSettings(current?.night_owl?.enabled === true));
  nightOwlScheduleForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveNightOwlSchedule();
  });
  nightOwlScheduleMode.addEventListener("change", () => {
    const scheduled = ["nightly", "weekly"].includes(nightOwlScheduleMode.value);
    nightOwlScheduleTime.disabled = !scheduled;
    nightOwlScheduleWeekday.disabled = nightOwlScheduleMode.value !== "weekly";
  });
  nightOwlSchedulePause.addEventListener("click", () => changeNightOwlSchedule("pause"));
  nightOwlScheduleResume.addEventListener("click", () => changeNightOwlSchedule("resume"));
  nightOwlScheduleCancel.addEventListener("click", () => changeNightOwlSchedule("cancel"));
  nightOwlRun.addEventListener("click", runNightOwlNow);
  voiceInputButton.addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("tori:voiceinputtoggle"));
  });
  voiceInputMode.addEventListener("change", () => {
    document.dispatchEvent(new CustomEvent("tori:voiceinputmode", {
      detail: {mode: voiceInputMode.value},
    }));
  });
  document.addEventListener("tori:voiceinputstate", (event) => renderVoiceInput(event.detail));
  renderVoiceInput(window.ToriVoiceInput?.statusDetail?.() || {
    state: "off", message: "Voice Input is off.", enabled: false,
    mode: "hold",
  });
  backupButton.addEventListener("click", backUpNow);
  restoreForm.addEventListener("submit", (event) => {
    event.preventDefault();
    decideRestore("restore");
  });
  restoreCancel.addEventListener("click", () => decideRestore("cancel"));
  loadSettings();
  return loadSettings;
}

function initializeModelProviders(root) {
  const ui = window.ToriUI;
  const element = (identifier) => root.querySelector(`#${identifier}`);
  const list = element("model-providers-list");
  const status = element("model-providers-status");
  const error = element("model-providers-error");
  const addButton = element("add-model-provider");
  const dialog = element("model-provider-dialog");
  const form = element("model-provider-form");
  const dialogHeading = element("model-provider-dialog-heading");
  const dialogError = element("model-provider-dialog-error");
  const tokenControls = element("model-provider-token-controls");
  const tokenStatus = element("model-provider-token-status");
  const saveTokenButton = element("save-model-provider-token");
  const clearTokenButton = element("clear-model-provider-token");
  const deleteDialog = element("delete-model-provider-dialog");
  const deleteForm = element("delete-model-provider-form");
  const deleteName = element("delete-model-provider-name");
  const fields = Object.freeze({
    display_name: element("model-provider-name"),
    base_url: element("model-provider-url"),
    authentication: element("model-provider-authentication"),
    structured_output: element("model-provider-structured"),
    timeout_seconds: element("model-provider-timeout"),
    known_model: element("model-provider-known-model"),
    known_capacity: element("model-provider-known-capacity"),
    token: element("model-provider-token"),
  });
  const environmentAuthOption = fields.authentication.querySelector(
    'option[value="environment_bearer"]'
  );
  let current = null;
  let editing = null;
  let deleting = null;
  let pending = false;

  function safeText(value, fallback = "Unavailable") {
    return typeof value === "string" && value ? value : fallback;
  }

  function actionButton(label, action, profile, className = "button secondary") {
    const button = ui.createElement("button", className, label);
    button.type = "button";
    button.disabled = pending;
    button.addEventListener("click", () => action(profile));
    return button;
  }

  function render(documentBody) {
    current = documentBody;
    list.replaceChildren();
    addButton.disabled = pending || !documentBody.initialized;
    if (!documentBody.initialized) {
      const note = ui.createElement(
        "p", "empty-state",
        "The user-managed provider store is not initialized. Built-in profiles remain available and editable, but new user-owned profiles cannot be added yet."
      );
      list.append(note);
    }
    for (const profile of documentBody.profiles || []) {
      const card = ui.createElement("article", "record-card provider-record");
      const summary = ui.createElement("div", "provider-record-summary");
      const heading = ui.createElement("h3", "", safeText(profile.display_name));
      const identity = ui.createElement(
        "p", "record-meta",
        `${safeText(profile.identifier)} · ${profile.implementation === "openai_compatible" ? "OpenAI Compatible" : "Ollama"}`
      );
      const source = ui.createElement(
        "p", "record-meta",
        profile.source === "user"
          ? `User-managed · ${profile.enabled ? "Enabled" : "Disabled"}`
          : "Built-in · Editable"
      );
      summary.append(heading, identity, source);
      const endpoint = ui.createElement("p", "provider-endpoint", safeText(profile.base_url));
      const catalogReason = profile.catalog_status?.reason_code;
      const catalogText = catalogReason === "authentication_required"
        ? "Model catalog unavailable — authentication required"
        : profile.catalog_status?.availability === "available"
        ? "Model catalog available"
        : profile.catalog_status?.availability === "unavailable"
        ? "Model catalog unavailable"
        : "Model catalog not checked";
      const catalogState = ui.createElement("p", "record-meta", catalogText);
      summary.append(endpoint, catalogState);
      if (profile.implementation === "openai_compatible") {
        const tokenText = profile.token_configured
          ? profile.token_source === "environment"
            ? "Token configured by environment"
            : "Token configured"
          : "No token configured";
        summary.append(ui.createElement("p", "record-meta", tokenText));
      }
      const actions = ui.createElement("div", "record-actions provider-record-actions");
      actions.append(actionButton("Refresh Models", refreshProfile, profile));
      if (profile.editable) {
        actions.append(actionButton("Edit", openEdit, profile));
        if (profile.source === "user") {
          actions.append(
            actionButton(profile.enabled ? "Disable" : "Enable", toggleProfile, profile),
            actionButton("Delete", requestDelete, profile, "button danger")
          );
        }
      }
      card.append(summary, actions);
      list.append(card);
    }
    ui.setStatus(
      status,
      documentBody.initialized
        ? "Model provider profiles are current."
        : "Configuration profiles loaded; user-managed storage awaits initialization.",
      documentBody.initialized ? "success" : "warning"
    );
  }

  async function loadProfiles() {
    if (pending) return;
    ui.showError(error, "");
    try {
      render(await ui.requestJson("/api/model-providers"));
    } catch (requestError) {
      current = null;
      list.replaceChildren();
      addButton.disabled = true;
      ui.showError(error, requestError.message);
      ui.setStatus(status, "Model provider profiles could not be loaded.", "warning");
    }
  }

  function clearForm() {
    form.reset();
    fields.timeout_seconds.value = "30";
    fields.authentication.value = "none";
    fields.structured_output.value = "json_object";
    fields.authentication.disabled = false;
    fields.structured_output.disabled = false;
    if (environmentAuthOption) environmentAuthOption.disabled = true;
    fields.token.value = "";
    ui.showError(dialogError, "");
  }

  function openAdd() {
    editing = null;
    clearForm();
    dialogHeading.textContent = "Add model provider";
    tokenControls.hidden = true;
    dialog.showModal();
    fields.display_name.focus();
  }

  function openEdit(profile) {
    editing = profile;
    clearForm();
    dialogHeading.textContent = "Edit model provider";
    fields.display_name.value = profile.display_name;
    element("model-provider-type").value = profile.implementation;
    fields.base_url.value = profile.base_url;
    fields.authentication.value = profile.authentication;
    fields.structured_output.value = profile.structured_output;
    fields.timeout_seconds.value = String(profile.timeout_seconds);
    const known = (profile.known_models || [])[0];
    fields.known_model.value = known?.model || "";
    fields.known_capacity.value = known?.context_window_tokens || "";
    fields.authentication.disabled = profile.implementation === "ollama";
    fields.structured_output.disabled = profile.implementation === "ollama";
    if (environmentAuthOption) {
      environmentAuthOption.disabled = !(
        profile.authentication === "environment_bearer"
        || profile.token_source === "environment"
      );
    }
    tokenControls.hidden = profile.implementation !== "openai_compatible";
    if (profile.implementation === "openai_compatible") {
      tokenStatus.textContent = profile.token_configured
        ? profile.token_source === "environment"
          ? "Token configured by the process environment. A stored token will take precedence."
          : "Token configured. Enter a new value only to replace it."
        : "No token configured.";
      saveTokenButton.textContent = profile.token_configured ? "Replace Token" : "Add Token";
      clearTokenButton.disabled = !profile.token_configured || profile.token_source === "environment";
    }
    dialog.showModal();
    fields.display_name.focus();
  }

  function knownModels() {
    const identifier = fields.known_model.value.trim();
    if (!identifier) return editing?.known_models?.slice(1) || [];
    const capacityText = fields.known_capacity.value.trim();
    return [{
      model: identifier,
      display_name: identifier,
      context_window_tokens: capacityText ? Number(capacityText) : null,
    }, ...(editing?.known_models?.slice(1) || [])];
  }

  async function save(event) {
    event.preventDefault();
    if (pending) return;
    const body = {
      display_name: fields.display_name.value,
      base_url: fields.base_url.value,
      timeout_seconds: Number(fields.timeout_seconds.value),
      authentication: fields.authentication.value,
      structured_output: fields.structured_output.value,
      known_models: knownModels(),
    };
    const path = editing ? "/api/model-providers/update" : "/api/model-providers/create";
    if (editing) {
      body.identifier = editing.identifier;
      body.expected_revision = editing.revision;
    }
    pending = true;
    ui.showError(dialogError, "");
    try {
      const documentBody = await ui.requestJson(path, {method: "POST", body});
      dialog.close();
      editing = null;
      render(documentBody);
      document.dispatchEvent(new CustomEvent("tori:modelcatalogchange"));
    } catch (requestError) {
      ui.showError(dialogError, requestError.message);
    } finally {
      pending = false;
      if (current) render(current);
    }
  }

  async function saveToken() {
    if (!editing || pending) return;
    const token = fields.token.value;
    if (!token) {
      ui.showError(dialogError, "Enter a new token before saving it.");
      return;
    }
    pending = true;
    ui.showError(dialogError, "");
    try {
      const identifier = editing.identifier;
      const documentBody = await ui.requestJson("/api/model-providers/token", {
        method: "POST",
        body: {identifier, action: "replace", token},
      });
      fields.token.value = "";
      render(documentBody);
      editing = (documentBody.profiles || []).find((item) => item.identifier === identifier) || null;
      dialog.close();
      if (editing) openEdit(editing);
      document.dispatchEvent(new CustomEvent("tori:modelcatalogchange"));
    } catch (requestError) {
      ui.showError(dialogError, requestError.message);
    } finally {
      pending = false;
      if (current) render(current);
    }
  }

  async function clearToken() {
    if (!editing || pending || !editing.token_configured) return;
    pending = true;
    ui.showError(dialogError, "");
    try {
      const identifier = editing.identifier;
      const documentBody = await ui.requestJson("/api/model-providers/token", {
        method: "POST",
        body: {identifier, action: "clear"},
      });
      render(documentBody);
      editing = (documentBody.profiles || []).find((item) => item.identifier === identifier) || null;
      dialog.close();
      if (editing) openEdit(editing);
      document.dispatchEvent(new CustomEvent("tori:modelcatalogchange"));
    } catch (requestError) {
      ui.showError(dialogError, requestError.message);
    } finally {
      pending = false;
      if (current) render(current);
    }
  }

  async function mutate(path, body) {
    if (pending) return;
    pending = true;
    ui.showError(error, "");
    try {
      const documentBody = await ui.requestJson(path, {method: "POST", body});
      if (documentBody.profiles) render(documentBody);
      document.dispatchEvent(new CustomEvent("tori:modelcatalogchange"));
    } catch (requestError) {
      ui.showError(error, requestError.message);
      await loadProfiles();
    } finally {
      pending = false;
      if (current) render(current);
    }
  }

  function toggleProfile(profile) {
    mutate("/api/model-providers/enabled", {
      identifier: profile.identifier,
      expected_revision: profile.revision,
      enabled: !profile.enabled,
    });
  }

  async function refreshProfile(profile) {
    await mutate("/api/model-providers/refresh", {identifier: profile.identifier});
    await loadProfiles();
  }

  function requestDelete(profile) {
    deleting = profile;
    deleteName.textContent = profile.display_name;
    deleteDialog.showModal();
  }

  async function confirmDelete(event) {
    event.preventDefault();
    if (!deleting) return;
    const profile = deleting;
    deleteDialog.close();
    deleting = null;
    await mutate("/api/model-providers/delete", {
      identifier: profile.identifier,
      expected_revision: profile.revision,
      confirmed: true,
    });
  }

  addButton.addEventListener("click", openAdd);
  element("cancel-model-provider").addEventListener("click", () => dialog.close());
  element("cancel-delete-model-provider").addEventListener("click", () => deleteDialog.close());
  form.addEventListener("submit", save);
  saveTokenButton.addEventListener("click", saveToken);
  clearTokenButton.addEventListener("click", clearToken);
  deleteForm.addEventListener("submit", confirmDelete);
  loadProfiles();
  return loadProfiles;
}

function initializeTTSProfiles(root) {
  const ui = window.ToriUI;
  const element = (identifier) => root.querySelector(`#${identifier}`);
  const list = element("tts-profiles-list");
  const status = element("tts-profiles-status");
  const error = element("tts-profiles-error");
  const addButton = element("add-tts-profile");
  const activeHeading = element("tts-active-profile-heading");
  const activeDetail = element("tts-active-profile-detail");
  const dialog = element("tts-profile-dialog");
  const form = element("tts-profile-form");
  const dialogHeading = element("tts-profile-dialog-heading");
  const dialogError = element("tts-profile-dialog-error");
  const deleteDialog = element("delete-tts-profile-dialog");
  const deleteForm = element("delete-tts-profile-form");
  const deleteName = element("delete-tts-profile-name");
  const fields = Object.freeze({
    display_name: element("tts-profile-name"),
    endpoint: element("tts-profile-endpoint"),
    model: element("tts-profile-model"),
    voice: element("tts-profile-voice"),
    connect_timeout_seconds: element("tts-profile-connect-timeout"),
    read_timeout_seconds: element("tts-profile-read-timeout"),
    enabled: element("tts-profile-enabled"),
  });
  let profiles = [];
  let selection = null;
  let activeProfile = null;
  let editing = null;
  let deleting = null;
  let pending = false;
  let available = false;

  function profileProtocolLabel(profile) {
    return profile.provider_type === "openai_compatible"
      ? "OpenAI-compatible TTS"
      : "Legacy local TTS profile";
  }

  function availabilityLabel(profile) {
    const availability = profile.status?.availability;
    if (availability === "available") return "Available";
    if (availability === "unavailable") return "Unavailable";
    if (availability === "degraded") return "Degraded";
    return "Not checked";
  }

  function availabilityDetail(profile) {
    const label = availabilityLabel(profile);
    const observed = profile.status?.observed_at;
    const reason = profile.status?.reason_code;
    if (label === "Not checked") {
      return "Availability not checked; saving and selection do not contact providers.";
    }
    const detail = reason && reason !== "not_checked"
      ? ` · ${reason.replaceAll("_", " ")}`
      : "";
    return `${label}${detail}${observed ? ` · observed ${observed}` : ""}`;
  }

  function actionButton(label, action, profile, {danger = false, disabled = false, title = ""} = {}) {
    const button = ui.createElement("button", danger ? "button danger" : "button secondary", label);
    button.type = "button";
    button.disabled = pending || disabled;
    if (title) button.title = title;
    button.addEventListener("click", () => action(profile));
    return button;
  }

  function render() {
    const activeIdentifier = selection?.profile_identifier || null;
    addButton.disabled = pending || !available;
    activeHeading.textContent = activeProfile?.display_name || "No active TTS profile";
    activeDetail.textContent = activeProfile
      ? `${profileProtocolLabel(activeProfile)} · ${activeProfile.voice} · ${availabilityDetail(activeProfile)}`
      : "Select an enabled saved profile to make future speech available.";
    list.replaceChildren();
    if (!available) {
      list.append(ui.createElement("p", "empty-state", "TTS profile storage is unavailable. No local substitute or browser copy has been created."));
      return;
    }
    if (!profiles.length) {
      list.append(ui.createElement("p", "empty-state", "No TTS profiles have been saved yet."));
      return;
    }
    for (const profile of profiles) {
      const selected = profile.identifier === activeIdentifier;
      const card = ui.createElement("article", "record-card tts-profile-record");
      const summary = ui.createElement("div", "tts-profile-summary");
      const headingRow = ui.createElement("div", "tts-profile-heading-row");
      const heading = ui.createElement("h4", "", profile.display_name);
      const badge = ui.createElement(
        "span",
        selected ? "record-badge active" : "record-badge",
        selected ? "Active" : profile.enabled ? "Enabled" : "Disabled"
      );
      const availabilityBadge = ui.createElement(
        "span",
        profile.status?.availability === "unavailable"
          ? "record-badge unavailable"
          : profile.status?.availability === "available"
          ? "record-badge available"
          : "record-badge",
        availabilityLabel(profile)
      );
      headingRow.append(heading, badge, availabilityBadge);
      const identity = ui.createElement(
        "p", "record-meta",
        `${profileProtocolLabel(profile)} · Voice ${profile.voice}${profile.model ? ` · Model ${profile.model}` : ""}`
      );
      const endpoint = ui.createElement("p", "tts-profile-endpoint", profile.endpoint);
      const timeouts = ui.createElement(
        "p", "record-meta",
        `Connect ${profile.connect_timeout_seconds}s · Read ${profile.read_timeout_seconds}s · Revision ${profile.revision}`
      );
      const availability = ui.createElement("p", "record-meta tts-profile-availability", availabilityDetail(profile));
      summary.append(headingRow, identity, endpoint, timeouts, availability);
      const actions = ui.createElement("div", "record-actions tts-profile-actions");
      actions.append(
        actionButton(selected ? "Selected" : "Select", selectProfile, profile, {
          disabled: selected || !profile.enabled,
          title: !profile.enabled ? "Enable this profile before selecting it." : "",
        }),
        actionButton("Edit", openEdit, profile),
        actionButton("Delete", requestDelete, profile, {
          danger: true,
          disabled: selected,
          title: selected ? "Select another profile before deleting this one." : "",
        })
      );
      card.append(summary, actions);
      list.append(card);
    }
  }

  function conflictMessage(requestError) {
    if (requestError.code === "stale_revision") {
      return "This TTS profile changed in another client. Canonical profiles were refreshed; review the current values before trying again.";
    }
    if (requestError.code === "tts_profile_not_found") {
      return "That TTS profile was deleted or changed elsewhere. Canonical profiles were refreshed.";
    }
    if (requestError.code === "tts_profile_conflict") {
      return requestError.message || "That change conflicts with the current canonical TTS profile state.";
    }
    if (requestError.code === "tts_profiles_unavailable" || requestError.code === "tts_profile_store_unavailable") {
      return "TTS profile management is unavailable. No profile was changed.";
    }
    return requestError.message;
  }

  async function loadProfiles({preserveError = false} = {}) {
    if (pending) return;
    if (!preserveError) ui.showError(error, "");
    ui.setStatus(status, "Loading canonical TTS profiles…", "busy");
    try {
      const [profileDocument, activeDocument] = await Promise.all([
        ui.requestJson("/api/tts-profiles"),
        ui.requestJson("/api/tts-profiles/active"),
      ]);
      profiles = profileDocument.profiles || [];
      selection = activeDocument.selection;
      activeProfile = activeDocument.profile;
      available = true;
      ui.setStatus(status, "TTS profiles are current.", "success");
    } catch (requestError) {
      profiles = [];
      selection = null;
      activeProfile = null;
      available = false;
      ui.showError(error, conflictMessage(requestError));
      ui.setStatus(status, "TTS profile management is unavailable.", "warning");
    }
    render();
  }

  function clearForm() {
    fields.display_name.value = "";
    fields.endpoint.value = "";
    fields.model.value = "";
    fields.voice.value = "";
    fields.connect_timeout_seconds.value = "3";
    fields.read_timeout_seconds.value = "30";
    fields.enabled.checked = true;
    ui.showError(dialogError, "");
  }

  function openAdd() {
    editing = null;
    clearForm();
    dialogHeading.textContent = "Add TTS profile";
    dialog.showModal();
    fields.display_name.focus();
  }

  function openEdit(profile) {
    editing = profile;
    clearForm();
    dialogHeading.textContent = "Edit TTS profile";
    fields.display_name.value = profile.display_name;
    fields.endpoint.value = profile.endpoint;
    fields.model.value = profile.model || "";
    fields.voice.value = profile.voice;
    fields.connect_timeout_seconds.value = String(profile.connect_timeout_seconds);
    fields.read_timeout_seconds.value = String(profile.read_timeout_seconds);
    fields.enabled.checked = profile.enabled;
    dialog.showModal();
    fields.display_name.focus();
  }

  async function refreshAfterConflict(requestError, targetError) {
    const message = conflictMessage(requestError);
    if (["stale_revision", "tts_profile_not_found", "tts_profile_conflict"].includes(requestError.code)) {
      pending = false;
      await loadProfiles({preserveError: true});
    }
    ui.showError(targetError, message);
  }

  async function save(event) {
    event.preventDefault();
    if (pending) return;
    const body = {
      display_name: fields.display_name.value,
      endpoint: fields.endpoint.value,
      model: fields.model.value.trim() || null,
      voice: fields.voice.value,
      enabled: fields.enabled.checked,
      connect_timeout_seconds: Number(fields.connect_timeout_seconds.value),
      read_timeout_seconds: Number(fields.read_timeout_seconds.value),
      authentication_mode: "none",
      provider_options: {},
    };
    const path = editing ? "/api/tts-profiles/update" : "/api/tts-profiles/create";
    if (editing) {
      body.identifier = editing.identifier;
      body.expected_revision = editing.revision;
    }
    pending = true;
    ui.showError(dialogError, "");
    try {
      await ui.requestJson(path, {method: "POST", body});
      dialog.close();
      editing = null;
      pending = false;
      await loadProfiles();
    } catch (requestError) {
      await refreshAfterConflict(requestError, dialogError);
    } finally {
      pending = false;
      render();
    }
  }

  async function selectProfile(profile) {
    if (pending || !selection) return;
    pending = true;
    ui.showError(error, "");
    try {
      await ui.requestJson("/api/tts-profiles/select", {
        method: "POST",
        body: {identifier: profile.identifier, expected_revision: selection.revision},
      });
      pending = false;
      await loadProfiles();
    } catch (requestError) {
      await refreshAfterConflict(requestError, error);
    } finally {
      pending = false;
      render();
    }
  }

  function requestDelete(profile) {
    deleting = profile;
    deleteName.textContent = profile.display_name;
    deleteDialog.showModal();
  }

  async function confirmDelete(event) {
    event.preventDefault();
    if (pending || !deleting) return;
    const profile = deleting;
    deleteDialog.close();
    deleting = null;
    pending = true;
    ui.showError(error, "");
    try {
      await ui.requestJson("/api/tts-profiles/delete", {
        method: "POST",
        body: {identifier: profile.identifier, expected_revision: profile.revision, confirmed: true},
      });
      pending = false;
      await loadProfiles();
    } catch (requestError) {
      await refreshAfterConflict(requestError, error);
    } finally {
      pending = false;
      render();
    }
  }

  addButton.addEventListener("click", openAdd);
  element("cancel-tts-profile").addEventListener("click", () => dialog.close());
  element("cancel-delete-tts-profile").addEventListener("click", () => deleteDialog.close());
  form.addEventListener("submit", save);
  deleteForm.addEventListener("submit", confirmDelete);
  element("refresh-settings").addEventListener("click", loadProfiles);
  loadProfiles();
  return loadProfiles;
}

loadSettingsStylesheet();
window.ToriViewModules.register({
  id: "settings",
  mount(root) {
    buildSettingsView(root);
    const refreshSettings = initializeSettings(root);
    const refreshProviders = initializeModelProviders(root);
    const refreshTTSProfiles = initializeTTSProfiles(root);
    return {
      refresh() {
        refreshSettings();
        refreshProviders();
        refreshTTSProfiles();
      },
      unmount() {
        root.replaceChildren();
      },
    };
  },
});
}());
