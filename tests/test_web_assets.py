from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest

from tori.commands import BROWSER_COMMAND_NAMES


ASSET_ROOT = Path(__file__).parents[1] / "src" / "tori" / "web_assets"


def css_declarations(styles: str, selector: str) -> dict[str, list[str]]:
    selector_pattern = r"\s*".join(
        re.escape(part) for part in selector.split()
    )
    match = re.search(
        rf"(?:^|\}})\s*{selector_pattern}\s*\{{([^{{}}]+)\}}",
        styles,
    )
    if match is None:
        raise AssertionError(f"CSS rule not found: {selector}")
    declarations: dict[str, list[str]] = {}
    for declaration in match.group(1).split(";"):
        if ":" not in declaration:
            continue
        property_name, value = declaration.split(":", 1)
        declarations.setdefault(property_name.strip(), []).append(value.strip())
    return declarations


class AssetDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.parents_by_id: dict[str, tuple[str, dict[str, str | None]]] = {}
        self._stack: list[tuple[str, dict[str, str | None]]] = []
        self.inline_script_text: list[str] = []
        self._inside_script_without_source = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        identifier = attributes.get("id")
        if identifier and self._stack:
            self.parents_by_id[identifier] = self._stack[-1]
        if tag == "script" and "src" not in attributes:
            self._inside_script_without_source = True
        if tag not in {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }:
            self._stack.append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside_script_without_source = False
        while self._stack:
            name, _attributes = self._stack.pop()
            if name == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._inside_script_without_source and data.strip():
            self.inline_script_text.append(data)

    def attributes_for(self, tag: str) -> list[dict[str, str | None]]:
        return [attributes for name, attributes in self.elements if name == tag]


class PackagedWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ASSET_ROOT / "index.html").read_text(encoding="utf-8")
        cls.styles = (ASSET_ROOT / "styles.css").read_text(encoding="utf-8")
        cls.settings_styles = (ASSET_ROOT / "settings.css").read_text(
            encoding="utf-8"
        )
        cls.scripts = {
            name: (ASSET_ROOT / name).read_text(encoding="utf-8")
            for name in (
                "view_modules.js", "settings.js", "utility.js", "ui.js", "audio.js",
                "app.js", "voice_input.js", "manage.js", "skills_management.js",
            )
        }
        cls.parser = AssetDocumentParser()
        cls.parser.feed(cls.html)

    def test_shared_shell_has_semantic_landmarks_and_exact_destinations(
        self,
    ) -> None:
        self.assertTrue(self.parser.attributes_for("header"))
        navigation = self.parser.attributes_for("nav")
        self.assertEqual(len(navigation), 1)
        self.assertEqual(navigation[0].get("aria-label"), "Primary navigation")
        self.assertEqual(len(self.parser.attributes_for("main")), 1)
        self.assertGreaterEqual(len(self.parser.attributes_for("section")), 4)

        links = [
            attributes
            for attributes in self.parser.attributes_for("a")
            if "data-view-link" in attributes
        ]
        self.assertEqual(
            [attributes["data-view-link"] for attributes in links],
            [
                "home",
                "conversation",
                "projects",
                "security",
                "tasks",
                "memories",
                "knowledge",
                "scheduled-work",
                "commands",
                "skills-mcp",
                "settings",
            ],
        )
        self.assertEqual(
            [attributes["href"] for attributes in links],
            [
                "/#home",
                "/",
                "/manage#projects",
                "/security",
                "/manage#tasks",
                "/manage#memories",
                "/manage#knowledge",
                "/manage#scheduled-work",
                "/commands",
                "/skills",
                "/settings",
            ],
        )

        panels = [
            attributes["data-view-panel"]
            for attributes in self.parser.attributes_for("section")
            if "data-view-panel" in attributes
        ]
        self.assertEqual(
            panels,
            [
                "home", "conversation", "security", "projects", "tasks", "scheduled-work", "memories", "knowledge",
                "commands", "skills-mcp", "settings",
            ],
        )
        self.assertIn('data-view-panel="security" data-view-module-root="security"', self.html)

    def test_skills_mcp_management_surface_is_safe_and_bounded(self) -> None:
        view = self.html.split('id="view-skills-mcp"', 1)[1].split(
            'id="view-settings"', 1
        )[0]
        self.assertIn('data-view-module-root="skills-mcp"', view)
        self.assertIn('id="skills-confirmation"', self.html)
        script = self.scripts["skills_management.js"]
        for route in (
            "/api/skills", "/api/mcp", "/api/skills/search",
            "/api/skills/github/inspect", "/api/skills/github/propose-install",
            "/api/skills/lifecycle", "/api/mcp/lifecycle", "/api/confirm",
            "/api/capability-growth", "/api/capability-growth/review",
            "/api/capability-growth/lifecycle",
        ):
            self.assertIn(route, script)
        self.assertIn("Discovered — not approved", script)
        self.assertIn("untrusted-description", script)
        self.assertIn("server.credential_status", script)
        self.assertIn('proposeSkill("uninstall", skill)', script)
        self.assertIn("unrelated user data remains", script)
        self.assertIn("Capability Growth", script)
        self.assertIn("separate from curated Memory", script)
        self.assertIn("FIX / IMPROVE / EXPAND", script)
        self.assertIn("Run Skills Review", script)
        self.assertIn("Known-good baselines", script)
        self.assertIn("inspection attempts", script)
        self.assertIn("successful, ${result.failed_inspections} failed", script)
        self.assertIn("nothing was installed, enabled, granted, or executed", script)
        self.assertNotIn("innerHTML", script)

    def test_projects_surface_is_bounded_safe_and_authoritatively_refreshed(self) -> None:
        for identifier in (
            "view-projects", "project-form", "project-title", "project-objective",
            "project-list", "active-project", "active-project-label",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn('id="project-title" maxlength="120"', self.html)
        self.assertIn('id="project-objective" maxlength="1000"', self.html)
        self.assertNotIn('id="project-brief"', self.html)
        conversation_markup = self.html.split(
            'id="active-project"', 1
        )[1].split("</section>", 1)[0]
        self.assertIn("Project", conversation_markup)
        self.assertNotIn("objective", conversation_markup.casefold())
        self.assertNotIn("continuity brief", conversation_markup.casefold())
        management = self.scripts["manage.js"]
        conversation = self.scripts["app.js"]
        self.assertIn('getJson("/api/projects")', management)
        self.assertIn("project.title", management)
        self.assertIn("documentBody.project_homes", management)
        self.assertIn("Where We Are", management)
        self.assertIn("Current Plan", management)
        self.assertIn("Open Questions", management)
        self.assertIn("Legacy Continuity", management)
        self.assertIn('projectHomeSection("Related Work")', management)
        self.assertIn('projectHomeSection("Project links")', management)
        self.assertIn('"night_owl_finding", "Night Owl finding"', management)
        self.assertIn('"scheduled_work_definition", "Scheduled Work definition"', management)
        self.assertIn('"knowledge_source", "Knowledge source"', management)
        self.assertIn('mutateProject("/api/projects/link"', management)
        self.assertIn('mutateProject("/api/projects/unlink"', management)
        self.assertIn('expected_link_revision: link.revision', management)
        self.assertIn('confirmed: true', management)
        self.assertIn('Source unavailable; link retained', management)
        self.assertIn('Source-owned by ${label}', management)
        self.assertIn('document.activeElement?.closest(".project-link-form")', management)
        self.assertIn('!projectLinkFormIsEditing()', management)
        self.assertIn('forceRender: true', management)
        self.assertIn('"Cancel link"', management)
        self.assertIn('Finding ID: ${finding.id}', self.scripts["settings.js"])
        self.assertIn("unavailable_sources.includes(key)", management)
        self.assertIn("Partial view: unavailable sources", management)
        self.assertIn("Current source-record updates, not a complete event history", management)
        self.assertIn("Read-only compatibility data", management)
        self.assertIn("Open Project", management)
        self.assertIn("Back to Projects", management)
        self.assertIn("New Project Chat", management)
        self.assertIn("openArchivedChat(conversation)", management)
        self.assertIn("startProjectChat(project)", management)
        self.assertIn("heading.textContent = project.title", management)
        self.assertIn("window.setInterval(refreshProjectCanonicalState, 1500)", management)
        self.assertIn("if (projectLoadPromise !== null)", management)
        self.assertIn("projectForm.hidden = selectedProjectId !== null", management)
        self.assertIn("generation !== projectLoadGeneration", management)
        self.assertIn("expected_revision: project.revision", management)
        self.assertIn("renderActiveProject(documentBody.project)", conversation)
        self.assertIn("Context active", conversation)
        self.assertIn("projectContextDisclosure", conversation)
        self.assertIn("Exact provider-visible Project context", conversation)
        self.assertIn("validProjectContextReceipt", conversation)
        self.assertIn("Chat ${receipt.chat_id}", conversation)
        self.assertIn("input allowance ~${formatTokenCount(receipt.budget_tokens)}", conversation)
        self.assertIn('request("/api/projects/new-chat"', conversation)
        self.assertIn("openArchivedChat", conversation)
        attention_poll = conversation[
            conversation.index("async function refreshAttention"):
            conversation.index("async function mutateAttention")
        ]
        self.assertIn('attentionChatId === renderedChatId', attention_poll)
        self.assertIn('renderActiveProject(result.project)', attention_poll)
        self.assertNotIn("innerHTML", management)
        indicator = css_declarations(self.styles, ".project-indicator")
        project_card = css_declarations(self.styles, ".project-home-card")
        project_conversation = css_declarations(self.styles, ".project-conversation")
        self.assertEqual(project_card.get("display"), ["grid"])
        self.assertEqual(css_declarations(self.styles, ".project-link-form").get("flex-wrap"), ["wrap"])
        link_field = css_declarations(self.styles, ".project-link-form label")
        self.assertEqual(link_field.get("flex"), ["1 1 13rem"], "link selectors wrap on narrow screens")
        self.assertEqual(css_declarations(self.styles, ".project-link-details").get("overflow-wrap"), ["anywhere"])
        self.assertEqual(project_conversation.get("width"), ["100%"])
        self.assertEqual(
            project_conversation.get("min-height"), ["var(--touch-target)"]
        )
        self.assertEqual(indicator["display"], ["flex"])
        self.assertEqual(indicator["white-space"], ["nowrap"])
        self.assertEqual(indicator["max-width"], ["100%"])
        label = css_declarations(self.styles, "#active-project-label")
        self.assertEqual(label["overflow"], ["hidden"])
        self.assertEqual(label["text-overflow"], ["ellipsis"])
        disclosure = css_declarations(
            self.styles, ".project-context-disclosure"
        )
        self.assertEqual(disclosure["overflow-wrap"], ["anywhere"])

    def test_project_link_polling_preserves_active_form_and_resumes(self) -> None:
        subprocess.run(
            ["node", str(Path(__file__).with_name("test_project_link_management.js"))],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_commands_reference_matches_registry_and_has_no_execution_controls(
        self,
    ) -> None:
        command_records = [
            attributes["data-browser-command"]
            for _tag, attributes in self.parser.elements
            if "data-browser-command" in attributes
        ]
        self.assertEqual(
            command_records,
            [name for name in BROWSER_COMMAND_NAMES if name not in {"/save", "/run", "/exit", "/quit"}],
        )
        self.assertEqual(len(command_records), len(set(command_records)))

        commands_view = self.html.split('id="view-commands"', 1)[1].split(
            'id="view-settings"', 1
        )[0]
        for forbidden_control in (
            "<button",
            "<form",
            "<select",
            "<input",
            "<textarea",
        ):
            self.assertNotIn(forbidden_control, commands_view)
        for value in (
            "Browser conversation commands",
            "What each kind of persistence means",
            "Curated memories",
            "Knowledge registrations",
            "automatically preserve usable transcripts",
            "informational reference",
            "ask Tori naturally",
            "Slash commands are optional",
            "supervised Terminal in Chat",
            "Finance commands",
            "/finance initialize",
            "/finance import FILENAME | FRIENDLY ACCOUNT",
            "/finance review",
            "/finance review NUMBER | MERCHANT | CATEGORY",
            "/finance review NUMBER | include",
            "/finance review NUMBER | exclude",
            "/finance review rule NUMBER | exact|starts_with|contains | MATCH | MERCHANT | CATEGORY",
            "/finance review propose",
            "/finance review cancel",
            "/finance import statement.csv | Citi Card",
            "/finance review 3 | Amazon | Amazon",
            "/finance review rule 2 | contains | MCDONALDS | McDonald's | Dining / Fast Food",
            "How much did I spend on fast food this month?",
            "What bills are due next week?",
            "Can I afford an $800 guitar?",
        ):
            self.assertIn(value, commands_view)
        for unsupported in ("/memory",):
            self.assertIn(f"<code>{unsupported}</code>", commands_view)
            self.assertNotIn(
                f'data-browser-command="{unsupported}"',
                commands_view,
            )
        for retired_from_reference in ("/run", "/exit", "/quit"):
            self.assertNotIn(f'data-browser-command="{retired_from_reference}"', commands_view)
        links = [attrs for attrs in self.parser.attributes_for("a") if attrs.get("data-view-link") == "commands"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["href"], "/commands")
        self.assertIn('>Commands</a>', self.html)

    def test_supervised_command_activity_is_compact_text_only_and_stoppable(self) -> None:
        script = self.scripts["app.js"]
        for identifier in (
            'id="command-activity"',
            'id="command-label"',
            'id="command-status"',
            'id="command-details"',
            'id="command-details-dialog"',
            'id="close-command-details"',
            'id="command-exact"',
            'id="command-stdout"',
            'id="command-stderr"',
            'id="stop-command"',
            'id="dismiss-command"',
            'id="command-proposal"',
        ):
            self.assertIn(identifier, self.html)
        self.assertIn('/api/commands/stop', script)
        self.assertIn('/api/commands/active', script)
        self.assertIn('invocation_id: invocationId', script)
        self.assertIn('proposal.isolation_available', script)
        self.assertIn('acceptConfirmation.textContent = pendingCommandProposal ? "Execute"', script)
        render_command = script.split("function renderCommand(command)", 1)[1].split(
            "function stopCommandPolling", 1
        )[0]
        self.assertNotIn("openDialog", render_command)
        self.assertIn("dismissCommandButton.hidden = !commandIsTerminal(command)", render_command)
        self.assertNotIn("innerHTML", script)
        activity_markup = self.html.split('id="command-activity"', 1)[1].split(
            "</section>", 1
        )[0]
        self.assertLess(
            activity_markup.index('id="stop-command"'),
            activity_markup.index('id="dismiss-command"'),
        )
        self.assertNotIn("<details", activity_markup)
        self.assertNotIn('id="command-metadata"', activity_markup)
        self.assertIn('id="conversation"', self.html)
        activity = css_declarations(self.styles, ".command-activity")
        self.assertEqual(activity["display"], ["flex"])
        self.assertEqual(activity["flex-direction"], ["column"])
        self.assertEqual(activity["min-height"], ["0"])
        self.assertEqual(activity["overflow"], ["hidden"])
        self.assertIn("20dvh", activity["max-height"][0])
        self.assertIn("10rem", activity["max-height"][0])
        header = css_declarations(self.styles, ".command-activity-header")
        self.assertEqual(header["display"], ["flex"])
        self.assertEqual(header["flex"], ["0 0 auto"])
        label = css_declarations(self.styles, ".command-label")
        self.assertEqual(label["max-height"], ["3em"])
        self.assertEqual(label["overflow-x"], ["hidden"])
        self.assertEqual(label["overflow-y"], ["auto"])
        self.assertNotIn(".command-details[open]", self.styles)
        self.assertNotIn(".command-detail-body", self.styles)
        command_dialog = css_declarations(self.styles, ".command-details-dialog")
        self.assertIn("100vw", command_dialog["width"][0])
        self.assertIn("100vw", command_dialog["max-width"][0])
        self.assertEqual(command_dialog["overflow-y"], ["auto"])
        self.assertEqual(command_dialog["overflow-x"], ["hidden"])
        base_dialog = css_declarations(self.styles, "dialog")
        self.assertIn("100dvh", base_dialog["max-height"][0])
        detail_markup = self.html.split(
            'id="command-details-dialog"', 1
        )[1].split("</dialog>", 1)[0]
        for evidence in (
            'id="command-metadata"',
            'id="command-exact"',
            'id="command-stdout"',
            'id="command-stderr"',
        ):
            self.assertIn(evidence, detail_markup)
        self.assertIn('id="close-command-details"', detail_markup)
        self.assertNotIn('id="stop-command"', detail_markup)
        self.assertNotIn('id="dismiss-command"', detail_markup)
        details_listener = script.split(
            'commandDetailsButton.addEventListener("click"', 1
        )[1].split("dismissCommandButton.addEventListener", 1)[0]
        self.assertIn("ui.openDialog(commandDetailsDialog", details_listener)
        self.assertNotIn("request(", details_listener)
        self.assertNotIn("renderTranscript", details_listener)
        transcript = css_declarations(self.styles, ".conversation")
        self.assertEqual(transcript["overflow-y"], ["auto"])
        self.assertIn("20dvh", transcript["min-height"][0])
        narrow = self.styles.split("@media (max-width: 479px)", 1)[1].split(
            "@media (min-width: 480px)", 1
        )[0]
        self.assertIn("max-height: min(9rem, 18dvh)", narrow)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", narrow)
        layout = css_declarations(self.styles, ".conversation-view")
        self.assertIn(
            "auto auto auto auto auto auto minmax(0, 1fr) auto",
            layout["grid-template-rows"],
        )
        self.assertEqual(
            layout["grid-template-areas"],
            ['"header"\n    "model"\n    "project"\n    "feedback"\n    "activity"\n    "attention"\n    "transcript"\n    "composer"'],
        )
        self.assertEqual(
            css_declarations(
                self.styles, ".conversation-view > .conversation"
            )["grid-area"],
            ["transcript"],
        )
        composer = css_declarations(self.styles, ".composer")
        self.assertEqual(composer["align-self"], ["end"])
        self.assertEqual(composer["height"], ["auto"])
        self.assertEqual(
            css_declarations(
                self.styles, ".conversation-view > .composer"
            )["grid-area"],
            ["composer"],
        )

        subprocess.run(
            [
                "node",
                str(Path(__file__).with_name(
                    "test_browser_command_activity.js"
                )),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_shell_uses_external_assets_skip_link_and_accessible_dialogs(
        self,
    ) -> None:
        self.assertFalse((ASSET_ROOT / "manage.html").exists())
        scripts = self.parser.attributes_for("script")
        self.assertEqual(
            [attributes.get("src") for attributes in scripts],
            [
                "/assets/view_modules.js",
                "/assets/settings.js",
                "/assets/utility.js",
                "/assets/ui.js",
                "/assets/audio.js",
                "/assets/app.js",
                "/assets/security.js",
                "/assets/voice_input.js",
                "/assets/manage.js",
                "/assets/skills_management.js",
                "/assets/vendor/xterm/xterm.js",
                "/assets/vendor/xterm/addon-fit.js",
                "/assets/terminal_ui.js",
                "/assets/terminal_policy_ui.js",
            ],
        )
        self.assertFalse(self.parser.inline_script_text)
        self.assertIn('class="skip-link" href="#main-content"', self.html)
        self.assertIn('role="log"', self.html)
        self.assertIn('aria-live="off"', self.html)
        self.assertIn('aria-busy="false"', self.html)

        dialogs = self.parser.attributes_for("dialog")
        self.assertEqual(len(dialogs), 9)
        for dialog in dialogs:
            self.assertIn("aria-labelledby", dialog)
            self.assertIn("aria-describedby", dialog)

    def test_every_form_control_has_a_visible_label(self) -> None:
        labelled_ids = {
            attributes["for"]
            for attributes in self.parser.attributes_for("label")
            if attributes.get("for")
        }
        control_ids = {
            attributes["id"]
            for tag in ("input", "textarea", "select")
            for attributes in self.parser.attributes_for(tag)
            if attributes.get("id")
        }
        self.assertTrue(control_ids.issubset(labelled_ids))

    def test_model_context_controls_are_accessible_manual_and_non_recommending(self) -> None:
        script = self.scripts["app.js"]
        self.assertIn('id="active-model"', self.html)
        self.assertIn('id="active-context"', self.html)
        self.assertIn('<label for="provider-selector">Provider profile</label>', self.html)
        self.assertIn('<label for="model-selector">Model</label>', self.html)
        self.assertIn('<label for="context-selector">Conversation context</label>', self.html)
        self.assertIn('id="model-context-dialog"', self.html)
        self.assertIn('id="refresh-models"', self.html)
        self.assertIn('/api/model-context/select', script)
        self.assertIn('/api/models/refresh', script)
        self.assertIn("reply and estimator headroom", self.html)
        self.assertIn("Backend context capacity is unknown", script)
        self.assertIn("older ${omitted === 1", script)
        self.assertNotIn("setInterval", script)
        self.assertNotIn("recommend", (self.html + script).casefold())
        self.assertNotIn("innerHTML", script)

    def test_navigation_uses_history_without_browser_persistence(self) -> None:
        routing = self.scripts["ui.js"]
        self.assertIn("pushState", routing)
        self.assertIn("replaceState", routing)
        self.assertIn('addEventListener("popstate"', routing)
        self.assertIn('addEventListener("hashchange"', routing)
        self.assertIn("event.preventDefault()", routing)
        self.assertIn('window.location.pathname === "/commands"', routing)
        self.assertIn('window.location.pathname === "/settings"', routing)
        self.assertIn('view === "commands" || view === "settings"', routing)
        self.assertIn("panel.hidden = !visible", routing)
        self.assertNotIn("replaceChildren", routing)
        self.assertNotIn("messageInput", routing)
        self.assertNotIn("/api/", routing)

        subprocess.run(
            ["node", str(Path(__file__).with_name("test_browser_navigation.js"))],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_mobile_drawers_reuse_navigation_history_and_utility_module(
        self,
    ) -> None:
        routing = self.scripts["ui.js"]
        reference = css_declarations(self.styles, ".reference-view")
        self.assertEqual(reference["overflow-x"], ["hidden"])
        self.assertEqual(reference["overflow-y"], ["auto"])
        self.assertIn('id="mobile-menu-panel"', self.html)
        self.assertIn('aria-label="Open navigation"', self.html)
        self.assertIn('id="mobile-utility-panel"', self.html)
        self.assertIn('aria-label="Open status and utilities"', self.html)
        self.assertEqual(self.html.count('class="primary-nav"'), 1)
        self.assertIn("mobileNavigationSlot.append(primaryNavigation)", routing)
        self.assertIn("sidebar.insertBefore(primaryNavigation, localBoundary)", routing)
        self.assertIn("mobileHistorySlot.append(sidebarConversations)", routing)
        self.assertIn("mobileUtilitySlot.append(utilityModule)", routing)
        self.assertNotIn("mobileActionsSlot.append(button)", routing)
        self.assertIn('id="auto-speech"', self.html)
        self.assertIn('class="composer-voice-controls"', self.html)
        self.assertNotIn("mobileConversationTools", routing)
        self.assertIn('window.matchMedia("(max-width: 1023px)")', routing)
        self.assertNotIn("overflow-x: scroll", self.styles)

    def test_settings_view_is_typed_protected_and_separate_from_conversation(self) -> None:
        script = self.scripts["settings.js"]
        registry = self.scripts["view_modules.js"]
        self.assertIn('id="view-settings"', self.html)
        self.assertIn('data-view-module-root="settings"', self.html)
        self.assertNotIn('id="toggle-web-search"', self.html)
        self.assertNotIn('id="model-provider-dialog"', self.html)
        self.assertIn('"toggle-web-search"', script)
        self.assertIn('"toggle-speech-output"', script)
        self.assertIn('id: "settings"', script)
        self.assertIn("buildSettingsView(root)", script)
        self.assertIn("root.replaceChildren", script)
        self.assertIn("Administrator", script)
        self.assertIn("Your preference", script)
        self.assertIn("Effective state", script)
        self.assertIn('"/api/settings/web-search"', script)
        self.assertIn('"/api/settings/speech-output"', script)
        self.assertIn('id: "maintenance-heading"', script)
        self.assertIn('"backup-now"', script)
        self.assertIn("Back Up Now", script)
        self.assertIn("<installation-name>_backups", script)
        self.assertIn('"/api/backups"', script)
        self.assertIn("body: {}", script)
        self.assertIn('addBackupDetail("Current backup", "In progress")', script)
        self.assertIn("Restore Backup", script)
        self.assertIn('"/api/restores"', script)
        self.assertIn('"/api/restores/propose"', script)
        self.assertIn('"/api/restores/confirm"', script)
        self.assertIn('"restore-metadata-row"', script)
        self.assertIn('"restore-backup-identifier"', script)
        self.assertIn('"restore-metadata-value restore-source-identity"', script)
        self.assertIn('className: "restore-management"', script)
        self.assertIn('id: "restore-confirm-backup"', script)
        self.assertEqual(
            css_declarations(
                self.settings_styles,
                ".settings-module .restore-metadata-value",
            )["overflow-wrap"],
            ["anywhere"],
        )
        self.assertEqual(
            css_declarations(
                self.settings_styles,
                ".settings-module .restore-metadata-row",
            )["grid-template-columns"],
            ["minmax(8.5rem, 0.85fr) minmax(0, 1.15fr)"],
        )
        self.assertIn(
            ".settings-module .restore-management {\n  display: grid;\n  grid-column: 1 / -1;",
            self.settings_styles,
        )
        self.assertIn(
            ".settings-module #restore-confirm-backup",
            self.settings_styles,
        )
        self.assertRegex(
            self.settings_styles,
            r"\.settings-module #restore-confirm-backup \{[^}]*overflow-wrap: anywhere;",
        )
        self.assertIn(
            "@media (max-width: 760px)",
            self.settings_styles,
        )
        self.assertIn(
            ".settings-module .restore-record {\n    grid-template-columns: minmax(0, 1fr);",
            self.settings_styles,
        )
        self.assertNotIn("Delete Backup", script)
        self.assertNotIn("retention", script.casefold())
        self.assertIn("body: {enabled: desired}", script)
        self.assertIn("tori:speechsettingchange", script)
        self.assertNotIn("messageInput", script)
        self.assertNotIn("autoSpeech", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("setInterval", script)
        self.assertIn("window.ToriViewModules.activate(selected)", self.scripts["ui.js"])
        self.assertIn("definition.mount(root)", registry)
        self.assertIn("lifecycle.unmount", registry)
        self.assertIn("lifecycle.refresh", registry)
        self.assertNotIn("settings", registry.casefold())
        self.assertNotIn("/api/", registry)
        self.assertNotIn("/api/settings", self.scripts["app.js"])
        self.assertIn(".settings-module", self.settings_styles)
        for section in (
            "Models", "Model Settings", "Voice", "Web Search",
            "MCP server connections", "Capabilities", "Memory",
            "Schedule & Tasks", "Maintenance", "Appearance", "Advanced",
            "Night Owl",
        ):
            self.assertIn(section, script)
        self.assertIn('data-settings-target', script)
        self.assertIn('data-settings-panel', script)
        self.assertIn('text: "Unavailable"', script)
        self.assertIn("Desktop microphone input stays off", script)
        self.assertIn('id: "voice-microphone"', script)
        self.assertIn('id: "voice-input-ptt-mode"', script)
        self.assertIn("MCP execution architecture is not implemented", script)
        self.assertIn("Run Night Owl Now", script)
        category_heading = 'h("h3", {text: "Research categories"})'
        schedule_heading = 'h("h3", {text: "Schedule"})'
        run_heading = 'h("h3", {text: "Run and status"})'
        findings_heading = 'h("h3", {text: "Findings"})'
        self.assertLess(script.index(category_heading), script.index(schedule_heading))
        self.assertLess(script.index(schedule_heading), script.index(run_heading))
        self.assertLess(script.index(run_heading), script.index(findings_heading))
        self.assertIn("Bounded background research", script)
        self.assertIn("model interpretation are shown separately", script)
        self.assertIn("finding.analysis.label", script)
        self.assertIn("Night Owl findings · Off", script)
        self.assertIn("active_night_owl", self.scripts["app.js"])
        self.assertIn("Night Owl research", self.scripts["app.js"])
        self.assertIn("tori:nightowlrevision", self.scripts["app.js"])
        self.assertIn('applicationEvent.type !== "companion_initiative"', self.scripts["app.js"])
        self.assertIn('ui.navigate("skills-mcp")', script)
        self.assertIn("noopener noreferrer", script)
        self.assertNotIn("innerHTML", script)
        for forbidden in ("Install", "Clone", "Enable Skill", "Add MCP"):
            self.assertNotIn(f">{forbidden}<", script)
        module_layout = css_declarations(
            self.settings_styles, ".settings-module"
        )
        self.assertEqual(module_layout["min-width"], ["0"])
        self.assertEqual(module_layout["overflow-x"], ["hidden"])
        workspace = css_declarations(
            self.settings_styles, ".settings-module .settings-workspace"
        )
        self.assertIn("11.5rem", workspace["grid-template-columns"][-1])
        self.assertIn("overflow", workspace)
        category = css_declarations(
            self.settings_styles, ".settings-module .night-owl-category"
        )
        self.assertEqual(category["display"], ["grid"])
        self.assertIn("minmax(0, 1fr)", category["grid-template-columns"][-1])
        category_input = css_declarations(
            self.settings_styles, ".settings-module .night-owl-category input"
        )
        self.assertEqual(category_input["margin"], ["0"])
        self.assertIn("place-self", category_input)
        self.assertIn("night-owl-metric-grid", self.settings_styles)
        self.assertIn("night-owl-coverage-card", self.settings_styles)
        self.assertIn("white-space: nowrap", self.settings_styles)
        self.assertIn("@media (max-width: 440px)", self.settings_styles)

        subprocess.run(
            ["node", str(Path(__file__).with_name("test_settings_module.js"))],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_utility_rail_is_modular_truthful_and_conversation_independent(self) -> None:
        utility = self.scripts["utility.js"]
        conversation = self.scripts["app.js"]
        self.assertIn('data-utility-module-root="overview"', self.html)
        self.assertIn('aria-label="Status and utilities"', self.html)
        for identifier in (
            "utility-status-card", "utility-host-card", "utility-host-cpu",
            "utility-host-memory", "utility-host-gpu", "utility-host-vram",
            "utility-coding-work-card",
            "utility-coding-work-details", "utility-coding-work-cancel",
            "utility-research-card", "utility-research-limits",
            "utility-research-cancel",
            "utility-upcoming-card", "utility-activity-card",
        ):
            self.assertIn(identifier, self.html)
        self.assertIn("setApplicationStatus", utility)
        self.assertIn("setActivity", utility)
        self.assertIn("setUpcoming", utility)
        self.assertIn("setCodingWork", utility)
        self.assertIn("setCodingWorkCancelHandler", utility)
        self.assertIn("limits.maximum_search_queries", utility)
        self.assertIn("source.search_provider", utility)
        self.assertIn("Provenance: source-linked excerpts retained", utility)
        self.assertIn("researchReport.textContent", utility)
        self.assertNotIn("innerHTML", utility)
        self.assertIn("documentBody.current_work_id", utility)
        self.assertNotIn("const activeStates", utility)
        self.assertNotIn("No Project attached", self.html)
        self.assertNotIn("Quick actions", self.html)
        self.assertNotIn("utility-planning-card", self.html)
        self.assertNotIn("utility-project-card", self.html)
        self.assertNotIn("utility-model-label", self.html)
        self.assertIn('activityCard.hidden = state === "neutral"', utility)
        self.assertIn("setHostStatus", utility)
        host_rows = css_declarations(self.styles, ".utility-host-facts > div")
        self.assertIn("max-content minmax(0, 1fr)", host_rows["grid-template-columns"])
        self.assertEqual(
            css_declarations(self.styles, ".utility-host-facts dd")["text-align"],
            ["right"],
        )
        self.assertNotIn("terminal output", utility.casefold())
        self.assertIn('id="terminal-viewport"', self.html)
        self.assertIn("No background activity is being claimed", self.html)
        self.assertNotIn("fetch(", utility)
        self.assertIn('ui.requestJson("/api/upcoming")', conversation)
        self.assertIn('ui.requestJson("/api/host-status")', conversation)
        self.assertIn("hostStatusLoadedAt >= 5000", conversation)
        self.assertIn('ui.requestJson("/api/coding-work")', conversation)
        self.assertNotIn('ui.requestJson("/api/planning")', conversation)
        self.assertIn('document.addEventListener("tori:planningaction"', conversation)
        self.assertIn("composer.requestSubmit()", conversation)
        self.assertIn('request("/api/coding-work/cancel"', conversation)
        self.assertIn("setCodingWorkCancelHandler(async", conversation)
        self.assertIn("expected_revision: expectedRevision", conversation)
        self.assertIn("await loadCodingWork()", conversation)
        self.assertIn("throw error", conversation)
        self.assertNotIn('action === "cancel-coding-work"', conversation)
        self.assertNotIn("localStorage", utility)
        self.assertIn('action === "tasks"', conversation)
        self.assertRegex(self.html, r'data-view-link="tasks">.*</svg>Reminders</a>')
        self.assertRegex(self.html, r'data-view-link="projects">.*</svg>Projects</a>')
        self.assertNotIn('data-view-link="tasks">Legacy tasks</a>', self.html)
        self.assertIn("Reminders &amp; legacy tasks", self.html)
        self.assertNotIn('id="task-form"', self.html)
        subprocess.run(
            ["node", str(Path(__file__).with_name("test_utility_module.js"))],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_recent_chat_titles_and_rename_remain_canonical(self) -> None:
        script = self.scripts["app.js"]
        self.assertIn('renameButton.textContent = "Rename"', script)
        self.assertIn('request("/api/chats/rename"', script)
        self.assertIn("expected_revision: chat.revision", script)
        self.assertIn("renderedChatListRevision", script)
        self.assertIn("result.chat_list_revision", script)
        self.assertNotIn("generateChatTitle", script)
        self.assertNotIn("localStorage", script)

    def test_workspace_column_and_responsive_transition_never_form_a_sliver(
        self,
    ) -> None:
        desktop = self.styles.split("@media (min-width: 1024px)", 2)[2].split(
            "@media (max-width: 1023px)", 1
        )[0]
        responsive = self.styles.split("@media (max-width: 1023px)", 1)[1].split(
            "@media (min-width: 1024px)", 1
        )[0]

        self.assertIn(
            "grid-template-columns: 14rem minmax(0, 1fr)",
            desktop,
        )
        self.assertIn(".workspace-shell", desktop)
        self.assertIn(
            "grid-template-columns: minmax(0, 1fr) minmax(16rem, 19rem)",
            desktop,
        )
        self.assertIn('grid-template-areas: "sidebar workspace"', desktop)
        self.assertIn('grid-template-areas: "conversation utility"', desktop)
        self.assertIn("grid-template-rows: minmax(0, 1fr)", desktop)
        self.assertIsNone(re.search(r"(?:^|[;{}])\s*order\s*:", self.styles))
        self.assertNotIn(".app-main {\n    grid-row:", self.styles)
        self.assertNotIn("minmax(31rem, 1fr)", desktop)
        self.assertEqual(self.styles.count(".app-shell {"), 3)
        self.assertIn(".sidebar,\n  .utility-rail", responsive)
        self.assertIn("display: none", responsive)
        self.assertIn(".mobile-toolbar", responsive)
        self.assertIn("display: grid", responsive)
        self.assertIn('"toolbar"\n      "workspace"', responsive)
        self.assertIn('window.matchMedia("(max-width: 1023px)")', self.scripts["ui.js"])

        utility = css_declarations(desktop, ".utility-rail")
        self.assertEqual(utility["min-height"], ["0"])
        self.assertEqual(utility["height"], ["100%"])
        self.assertEqual(utility["overflow-y"], ["auto"])

        workspace_parent = self.parser.parents_by_id["workspace-shell"]
        conversation_parent = self.parser.parents_by_id["main-content"]
        utility_parent = self.parser.parents_by_id["utility-rail"]
        self.assertIn("app-shell", workspace_parent[1].get("class", ""))
        self.assertEqual(conversation_parent[1].get("id"), "workspace-shell")
        self.assertEqual(utility_parent[1].get("id"), "workspace-shell")

        conversation = css_declarations(self.styles, ".conversation-view")
        self.assertIn("minmax(0, 1fr)", conversation["grid-template-rows"][0])
        self.assertEqual(conversation["grid-template-areas"], [
            '"header"\n    "model"\n    "project"\n    "feedback"\n    '
            '"activity"\n    "attention"\n    "transcript"\n    "composer"'
        ])

    def test_new_chat_label_is_centered_text_without_a_decorative_prefix(self) -> None:
        self.assertIn(
            '<button id="new-session" class="button primary new-chat-button" '
            'type="button">New chat</button>',
            self.html,
        )
        self.assertNotIn("＋</span> New chat", self.html)

    def test_mobile_header_has_one_tori_label_without_a_standalone_mark(self) -> None:
        self.assertIn('<span class="mobile-brand">Tori</span>', self.html)
        self.assertNotIn(
            '<span class="mobile-brand"><span class="brand-mark"',
            self.html,
        )
        self.assertNotIn(".mobile-brand .brand-mark", self.styles)

    def test_mobile_conversation_prioritizes_transcript_without_small_targets(
        self,
    ) -> None:
        mobile = "}" + self.styles.split(
            "@media (max-width: 479px)", 1
        )[1].split("{", 1)[1].split("@media (min-width: 480px)", 1)[0]
        responsive = "}" + self.styles.split(
            "@media (max-width: 1023px)", 1
        )[1].split("{", 1)[1].split("@media (min-width: 1024px)", 1)[0]
        conversation_view = css_declarations(mobile, ".conversation-view")
        header = css_declarations(mobile, ".conversation-view .view-header")
        actions = css_declarations(mobile, ".view-actions")
        action_buttons = css_declarations(
            mobile, ".view-actions .button, .view-header > .button"
        )
        model = css_declarations(mobile, ".model-controls")
        model_actions = css_declarations(mobile, ".model-control-actions")
        context_dialog = css_declarations(mobile, ".model-context-dialog")
        context_fields = css_declarations(mobile, ".model-context-fields")
        composer = css_declarations(mobile, ".composer")
        textarea = css_declarations(mobile, ".composer textarea")
        navigation = css_declarations(responsive, ".sidebar, .utility-rail")
        shell = css_declarations(responsive, ".app-shell")
        toolbar = css_declarations(responsive, ".mobile-toolbar")
        mobile_navigation = css_declarations(
            mobile, ".primary-nav, .mobile-menu-actions"
        )
        inactive_status = css_declarations(
            mobile,
            '.feedback-stack .status:not([data-state="busy"]):not([data-state="warning"]), '
            '.feedback-stack .speech-status:not([data-state="busy"]):not([data-state="warning"])',
        )
        hidden_stop = css_declarations(mobile, "#stop-speech:disabled")

        self.assertEqual(conversation_view["gap"], ["var(--space-1)"])
        self.assertEqual(header["min-height"], ["var(--touch-target)"])
        self.assertEqual(actions["flex-wrap"], ["nowrap"])
        self.assertEqual(
            action_buttons["min-height"], ["var(--touch-target)"]
        )
        self.assertEqual(
            model["padding"], ["var(--space-1) var(--space-2)"]
        )
        self.assertEqual(
            model["grid-template-columns"],
            ["minmax(0, 1fr) auto"],
        )
        self.assertEqual(model_actions["display"], ["flex"])
        self.assertEqual(context_dialog["width"], ["calc(100vw - 1rem)"])
        self.assertEqual(context_dialog["max-width"], ["calc(100vw - 1rem)"])
        self.assertEqual(context_fields["grid-template-columns"], ["minmax(0, 1fr)"])
        self.assertEqual(composer["padding"], ["var(--space-2)"])
        self.assertEqual(composer["width"], ["100%"])
        self.assertEqual(textarea["height"], ["3.25rem"])
        self.assertEqual(textarea["min-height"], ["3.25rem"])
        self.assertEqual(navigation["display"], ["none"])
        self.assertEqual(
            shell["grid-template-rows"], ["auto minmax(0, 1fr)"]
        )
        self.assertEqual(toolbar["display"], ["grid"])
        self.assertEqual(
            mobile_navigation["grid-template-columns"], ["minmax(0, 1fr)"]
        )
        self.assertEqual(inactive_status["display"], ["none"])
        self.assertEqual(hidden_stop["display"], ["none"])

        shrinking_children = css_declarations(
            self.styles,
            ".conversation-view > *, .model-controls > *, "
            ".model-control-actions > *, .composer > *",
        )
        self.assertEqual(shrinking_children["min-width"], ["0"])
        self.assertEqual(shrinking_children["max-width"], ["100%"])

    def test_mobile_chat_history_uses_bounded_internal_scrolling(self) -> None:
        routing = self.scripts["ui.js"]
        mobile = "}" + self.styles.rsplit(
            "@media (max-width: 1023px)", 1
        )[1].split("{", 1)[1]
        history = css_declarations(mobile, ".chat-history-list")
        panel = css_declarations(
            mobile, ".mobile-menu-panel, .mobile-utility-panel"
        )
        self.assertEqual(history["overflow-y"], ["auto"])
        self.assertEqual(history["max-height"], ["48dvh"])
        self.assertEqual(panel["overflow-y"], ["auto"])
        self.assertIn("safe-area-inset", self.styles)
        self.assertIn("mobileHistorySlot.append(sidebarConversations)", routing)

    def test_all_scripts_preserve_text_only_and_storage_free_boundary(self) -> None:
        forbidden = (
            "innerHTML",
            "insertAdjacentHTML",
            "document.write",
            "sessionStorage",
            "indexedDB",
            "document.cookie",
            "eval(",
            "new Function",
            'addEventListener("resize"',
        )
        for name, source in self.scripts.items():
            with self.subTest(script=name):
                for value in forbidden:
                    self.assertNotIn(value, source)
                if name != "voice_input.js":
                    self.assertNotIn("localStorage", source)
        voice_input = self.scripts["voice_input.js"]
        self.assertIn('"tori.voice-input.microphone"', voice_input)
        self.assertIn('"tori.voice-input.ptt-mode"', voice_input)
        self.assertEqual(voice_input.count("localStorage."), 3)
        self.assertIn("textContent", self.scripts["ui.js"])
        self.assertIn("document.createTextNode(delta)", self.scripts["app.js"])

    def test_task_management_uses_read_only_view_and_explicit_edit_mode(self) -> None:
        script = self.scripts["manage.js"]
        render_tasks = script.split("function renderTasks", 1)[1].split(
            "function renderReminders", 1
        )[0]
        edit_mode = script.split("function showTaskEditMode", 1)[1].split(
            "function showReminderEditMode", 1
        )[0]

        self.assertIn('actionButton("Edit"', render_tasks)
        self.assertNotIn("Save edit", render_tasks)
        self.assertNotIn("document.createElement(\"input\")", render_tasks)
        self.assertIn('actionButton("Save"', edit_mode)
        self.assertIn('actionButton("Cancel", finishEditing, true)', edit_mode)
        self.assertIn("editor.value = task.description", edit_mode)
        self.assertIn("normalActions.hidden = true", edit_mode)
        self.assertIn("normalActions.hidden = false", edit_mode)
        self.assertIn('mutateOperational("/api/tasks/update"', edit_mode)
        self.assertIn("expected_revision: task.revision", edit_mode)
        self.assertNotIn("mutateOperational", edit_mode.split(
            'actionButton("Cancel"', 1
        )[1])
        self.assertIn("await loadOperational()", script)
        self.assertIn('error.code === "stale_revision"', script)

    def test_reminder_management_uses_read_only_view_and_explicit_edit_mode(self) -> None:
        script = self.scripts["manage.js"]
        render_reminders = script.split("function renderReminders", 1)[1].split(
            "function newestFirst", 1
        )[0]
        edit_mode = script.split("function showReminderEditMode", 1)[1].split(
            "function renderTasks", 1
        )[0]

        self.assertIn('actionButton("Edit"', render_reminders)
        self.assertNotIn("Save edit", script)
        self.assertNotIn('document.createElement("input")', render_reminders)
        self.assertIn('actionButton("Save"', edit_mode)
        self.assertIn('actionButton("Cancel", finishEditing, true)', edit_mode)
        self.assertIn("editor.value = reminder.reminder_text", edit_mode)
        self.assertIn("normalActions.hidden = true", edit_mode)
        self.assertIn("normalActions.hidden = false", edit_mode)
        self.assertIn('mutateOperational("/api/reminders/update"', edit_mode)
        self.assertIn("expected_revision: reminder.revision", edit_mode)
        self.assertNotIn("mutateOperational", edit_mode.split(
            'actionButton("Cancel"', 1
        )[1])
        for label in (
            'actionButton("Done"',
            'actionButton("Dismiss"',
            'actionButton("Delay 15 min"',
            'actionButton("Cancel reminder"',
            'actionButton("Discuss"',
        ):
            self.assertIn(label, render_reminders)
        self.assertIn("if (!history)", render_reminders)
        self.assertIn('error.code === "stale_revision"', script)

    def test_operational_history_is_separate_bounded_and_collapsed_by_default(self) -> None:
        script = self.scripts["manage.js"]
        history_markup = self.html.split(
            'id="operational-history"', 1
        )[1].split("</section>", 1)[0]
        toggle = next(
            attributes
            for attributes in self.parser.attributes_for("button")
            if attributes.get("id") == "operational-history-toggle"
        )
        history_section = next(
            attributes
            for attributes in self.parser.attributes_for("section")
            if attributes.get("id") == "operational-history"
        )

        self.assertEqual(toggle.get("aria-expanded"), "false")
        self.assertEqual(toggle.get("aria-controls"), "operational-history")
        self.assertIn("hidden", history_section)
        self.assertIn("Task history", history_markup)
        self.assertIn("Reminder history", history_markup)
        self.assertIn('task.status === "open"', script)
        self.assertIn('["completed", "cancelled"].includes(task.status)', script)
        self.assertIn('["scheduled", "due"].includes(reminder.status)', script)
        self.assertIn(
            '["dismissed", "completed", "cancelled"].includes(reminder.status)',
            script,
        )
        self.assertIn("const HISTORY_LIMIT = 50", script)
        self.assertIn("historicalTasks.slice(0, HISTORY_LIMIT)", script)
        self.assertIn("historicalReminders.slice(0, HISTORY_LIMIT)", script)
        self.assertIn("operationalHistory.hidden = !opening", script)
        self.assertIn('renderTasks(historicalTasks.slice(0, HISTORY_LIMIT), taskHistoryList, {history: true})', script)
        self.assertIn('renderReminders(historicalReminders.slice(0, HISTORY_LIMIT), reminderHistoryList, {history: true})', script)
        self.assertNotIn("Reopen", history_markup)
        history_task_actions = script.split("function renderTasks", 1)[1].split(
            "function renderReminders", 1
        )[0]
        self.assertIn('actions.append(actionButton("Discuss"', history_task_actions)

        history = css_declarations(self.styles, ".operational-history")
        hidden = css_declarations(self.styles, ".operational-history[hidden]")
        actions = css_declarations(self.styles, ".record-actions")
        self.assertEqual(history["min-width"], ["0"])
        self.assertEqual(hidden["display"], ["none"])
        self.assertEqual(actions["flex-wrap"], ["wrap"])

    def test_scheduled_work_is_separate_confirmed_and_has_no_ad_hoc_run_control(self) -> None:
        script = self.scripts["manage.js"]
        conversation_script = self.scripts["app.js"]
        self.assertIn('data-view-panel="scheduled-work"', self.html)
        for identifier in (
            "scheduled-work-active", "scheduled-work-paused",
            "scheduled-work-history", "scheduled-run-history",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("/api/scheduled-work/propose-backup", script)
        self.assertIn("/api/scheduled-work/delete-history", script)
        self.assertIn("scheduled_work.authorize", conversation_script)
        self.assertIn("formatScheduledProposal", conversation_script)
        self.assertNotIn("Run Now", self.html)
        self.assertNotIn("Run Again", self.html)

    def test_scheduled_work_polling_preserves_interaction_without_stale_authority(self) -> None:
        script = self.scripts["manage.js"]
        render = script.split("function renderScheduled", 1)[1].split(
            "async function loadScheduled", 1
        )[0]
        card = script.split("function scheduledDefinitionCard", 1)[1].split(
            "function scheduledRunCard", 1
        )[0]
        polling = script.split("function refreshScheduledCanonicalState", 1)[1].split(
            "window.setInterval", 1
        )[0]

        self.assertIn("scheduledRevision === nextRevision", render)
        same_revision = render.split("scheduledRevision === nextRevision", 1)[1].split(
            "const survivingDetails", 1
        )[0]
        self.assertIn("return false", same_revision)
        self.assertNotIn("replaceChildren", same_revision)
        self.assertIn("scheduledOpenDetails", card)
        self.assertIn("definition:${item.identifier}", card)
        self.assertIn("scheduledOpenDetails.delete(detailsKey)", card)
        self.assertIn("scheduledOpenDetails.add(detailsKey)", card)
        self.assertIn("survivingDetails", render)
        self.assertIn("scheduledOpenDetails.delete(detailsKey)", render)
        self.assertIn("target.replaceChildren()", render)
        self.assertIn("scheduledRunHistory.replaceChildren()", render)
        self.assertIn("scheduledRevision = nextRevision", render)
        self.assertIn("generation !== scheduledLoadGeneration", script)
        self.assertIn("expected_revision: item.revision", script)
        self.assertIn("window.setInterval(refreshScheduledCanonicalState, 1500)", script)
        self.assertIn('window.addEventListener("focus", () => {', script)
        self.assertIn("refreshScheduledCanonicalState();", script)
        self.assertIn('document.addEventListener("visibilitychange"', script)
        self.assertIn("loadScheduled()", polling)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)

    def test_scheduled_run_details_label_definition_id(self) -> None:
        script = self.scripts["manage.js"]
        card = script.split("function scheduledRunCard", 1)[1].split(
            "function renderScheduled", 1
        )[0]
        self.assertIn('addDefinition(details, "Definition ID", run.job_id)', card)
        self.assertNotIn('addDefinition(details, "Definition", ', card)

    def test_companion_attention_rail_is_compact(self) -> None:
        script = self.scripts["app.js"]
        render = script.split("function renderCompanionAttention", 1)[1].split(
            "async function loadCompanionAttention", 1
        )[0]
        labels = script.split("const ATTENTION_SOURCE_LABELS", 1)[1].split(
            "});", 1
        )[0]
        self.assertIn('research: "Research"', labels)
        self.assertIn('coding_work: "Coding Work"', labels)
        self.assertIn('night_owl: "Night Owl"', labels)
        self.assertIn('scheduled_work: "Scheduled Work"', labels)
        self.assertNotIn("item.summary", render)
        self.assertIn("ATTENTION_SOURCE_LABELS[item.source]", render)
        self.assertIn('"attention-workspace-meta"', render)
        self.assertIn("title.textContent = item.title", render)
        self.assertIn("Deferred until", render)
        for action in ('["review", "Review"]', '["later", "Later"]', '["dismiss", "Dismiss"]'):
            self.assertIn(action, render)
        self.assertIn(
            "companionAttentionCount.textContent = String(activeCount + securityCount)", render
        )

        item_text = css_declarations(self.styles, ".attention-workspace-item p")
        self.assertEqual(item_text.get("overflow-wrap"), ["anywhere"])
        strong_text = css_declarations(self.styles, ".attention-workspace-item strong")
        self.assertEqual(strong_text.get("overflow-wrap"), ["anywhere"])

        subprocess.run(
            ["node", str(Path(__file__).with_name("test_companion_attention_rail.js"))],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_scheduled_authorization_review_renders_exact_safe_structures(self) -> None:
        script = self.scripts["manage.js"]
        formatter = script.split("function formatReviewValue", 1)[1].split(
            "function formatScheduledAuthorizationReview", 1
        )[0]
        scheduled_review = script.split(
            "function formatScheduledAuthorizationReview", 1
        )[1].split("function showConfirmation", 1)[0]
        confirmation = script.split("function showConfirmation", 1)[1].split(
            "function requestHistoryDeletion", 1
        )[0]

        self.assertIn('value === null', formatter)
        self.assertIn('typeof value === "string"', formatter)
        self.assertIn("JSON.stringify(value)", formatter)
        self.assertIn("Array.isArray(value)", formatter)
        self.assertIn("Object.keys(value).sort()", formatter)
        self.assertIn("formatReviewValue(value[key])", formatter)
        for evidence in (
            "Operation:", "Title:", "Capability:", "Arguments:", "Schedule:",
            "Schedule kind:", "Occurrence UTC:", "Timezone:", "Mode:",
            "Missed-run policy:", "Persistent permission:", "Lifetime:",
        ):
            self.assertIn(evidence, scheduled_review)
        self.assertIn('confirmation.action === "scheduled_work.authorize"', confirmation)
        self.assertIn("confirmation.proposal", confirmation)
        self.assertIn("confirmationTarget.textContent", confirmation)
        self.assertNotIn("innerHTML", confirmation)
        self.assertNotIn("confirmation.token", scheduled_review)

        subprocess.run(
            ["node", str(Path(__file__).with_name("test_scheduled_work_management.js"))],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_history_delete_is_confirmed_bounded_and_history_only(self) -> None:
        script = self.scripts["manage.js"]
        task_render = script.split("function renderTasks", 1)[1].split(
            "function renderReminders", 1
        )[0]
        reminder_render = script.split("function renderReminders", 1)[1].split(
            "function newestFirst", 1
        )[0]
        confirmation = script.split("function requestHistoryDeletion", 1)[1].split(
            "async function requestCheckpointRemoval", 1
        )[0]
        completion = script.split("async function completeConfirmation", 1)[1].split(
            "confirmButton.addEventListener", 1
        )[0]

        self.assertIn('actionButton("Delete"', script)
        self.assertIn('button.className = "button danger mutation"', script)
        self.assertIn('actions.append(historyDeleteButton("task", task))', task_render)
        self.assertIn('actions.append(historyDeleteButton("reminder", reminder))', reminder_render)
        self.assertIn("} else {", task_render)
        self.assertIn("} else {", reminder_render)
        self.assertIn("Delete from History permanently?", confirmation)
        self.assertIn("visible.slice(0, 240)", confirmation)
        self.assertIn('confirmButton.textContent = "Delete permanently"', confirmation)
        self.assertIn("initialFocus: cancelButton", confirmation)
        self.assertIn('decision !== "confirm"', completion)
        cancel_branch = completion.split('if (decision !== "confirm")', 1)[1].split(
            "await mutateOperational", 1
        )[0]
        self.assertNotIn("postJson", cancel_branch)
        self.assertIn('"/api/tasks/delete-history"', completion)
        self.assertIn('"/api/reminders/delete-history"', completion)
        self.assertIn("identifier: historyDelete.identifier", completion)
        self.assertIn("expected_revision: historyDelete.expectedRevision", completion)
        self.assertIn('document.addEventListener("tori:operationalrevision"', script)
        self.assertIn("const generation = ++operationalLoadGeneration", script)
        self.assertIn("generation !== operationalLoadGeneration", script)
        self.assertIn('new CustomEvent("tori:operationalrevision"', self.scripts["app.js"])
        self.assertNotIn("Reopen", script)
        self.assertNotIn("Clear History", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)

        dialog = css_declarations(self.styles, "dialog")
        actions = css_declarations(self.styles, ".record-actions")
        self.assertTrue(any("100dvh" in value for value in dialog["max-height"]))
        self.assertEqual(actions["flex-wrap"], ["wrap"])

    def test_web_audio_activation_is_gesture_first_and_failure_visible(self) -> None:
        audio = self.scripts["audio.js"]
        app = self.scripts["app.js"]
        replay = app.split("async function replayAssistantMessage", 1)[1].split(
            "async function loadSpeechState", 1
        )[0]
        submit = app.split('composer.addEventListener("submit"', 1)[1].split(
            'messageInput.addEventListener("input"', 1
        )[0]
        automatic = app.split(
            'autoSpeechButton.addEventListener("click"', 1
        )[1].split('stopSpeechButton.addEventListener("click"', 1)[0]

        subprocess.run(
            ["node", str(Path(__file__).with_name("test_browser_audio.js"))],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertLess(
            audio.index("configurePlaybackSession();"),
            audio.index("const current = audioContext();"),
        )
        self.assertIn('audioSession.type = "playback"', audio)
        self.assertIn('audioSession.type !== "playback"', audio)
        self.assertLess(audio.index("silentSource.start(0)"), audio.index("await current.resume()"))
        self.assertIn('current.state !== "running"', audio)
        self.assertIn("activatedContext === current", audio)
        self.assertIn("audioActivation.requireActive()", app)
        self.assertIn("audioActivation.isActive()", app)
        self.assertLess(replay.index("await audioActivation.activate()"), replay.index("await request("))
        self.assertIn("await audioActivation.activate()", automatic)
        self.assertIn("await audioActivation.activate()", submit)
        self.assertIn("auto_speech: autoSpeechForTurn", submit)
        self.assertIn('setSpeechStatus(error.message, "warning")', submit)
        self.assertLess(
            submit.index('setSpeechStatus(error.message, "warning")'),
            submit.index("messageInput.value = \"\""),
        )

    def test_responsive_tokens_safe_areas_and_accessibility_media_exist(
        self,
    ) -> None:
        required = (
            "--color-canvas:",
            "--color-surface-1:",
            "--color-accent-primary:",
            "--touch-target: 2.75rem",
            "min-height: 100vh",
            "min-height: 100dvh",
            "env(safe-area-inset-top",
            "overflow-x: hidden",
            "@media (max-width: 479px)",
            "@media (min-width: 480px)",
            "@media (min-width: 720px)",
            "@media (min-width: 1024px)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (forced-colors: active)",
            'a:focus-visible',
        )
        for value in required:
            self.assertIn(value, self.styles)

    def test_visual_tokens_define_neutral_surfaces_and_distinct_accents(
        self,
    ) -> None:
        root = css_declarations(self.styles, ":root")
        for token in (
            "--color-canvas",
            "--color-graphite",
            "--color-gunmetal",
            "--color-steel",
            "--color-surface-raised",
            "--color-text-primary",
            "--color-text-secondary",
        ):
            self.assertIn(token, root)

        accent_values = {
            root["--color-accent-primary"][0],
            root["--color-accent-cyan"][0],
            root["--color-accent-secondary"][0],
        }
        self.assertEqual(len(accent_values), 3)
        self.assertIn("--gradient-primary", root)
        primary = root["--gradient-primary"][0]
        self.assertGreaterEqual(primary.count("linear-gradient("), 2)
        self.assertGreaterEqual(len(re.findall(r"#[0-9a-fA-F]{6}", primary)), 2)

    def test_ambient_illumination_uses_multiple_noninteractive_sources(
        self,
    ) -> None:
        root = css_declarations(self.styles, ":root")
        ambient = root["--gradient-canvas"][0]
        ambient += css_declarations(self.styles, "body::before")["background"][0]
        self.assertGreaterEqual(ambient.count("radial-gradient("), 4)

        illumination = css_declarations(self.styles, "body::before")
        self.assertEqual(illumination["position"], ["fixed"])
        self.assertEqual(illumination["pointer-events"], ["none"])

    def test_elevated_surfaces_have_metallic_highlights_and_depth(
        self,
    ) -> None:
        root = css_declarations(self.styles, ":root")
        self.assertGreaterEqual(
            root["--gradient-metal"][0].count("linear-gradient("), 2
        )
        self.assertGreaterEqual(
            root["--gradient-panel"][0].count("linear-gradient("), 2
        )
        self.assertIn("inset 0 1px", root["--shadow-panel"][0])
        self.assertIn("inset 0 -1px", root["--shadow-panel"][0])

        secondary = css_declarations(self.styles, ".button.secondary")
        self.assertIn("var(--gradient-metal)", secondary["background"])
        transcript = css_declarations(self.styles, ".conversation")
        self.assertIn("inset", transcript["box-shadow"][0])

    def test_selected_surfaces_use_dark_glass_with_usable_fallbacks(
        self,
    ) -> None:
        cards = css_declarations(
            self.styles, ".composer, .surface-card, .record-card"
        )
        self.assertIn("var(--color-gunmetal)", cards["background"])
        self.assertTrue(any("rgba(" in value for value in cards["background"]))
        self.assertTrue(cards["backdrop-filter"][0].startswith("blur("))
        self.assertTrue(cards["-webkit-backdrop-filter"][0].startswith("blur("))

        self.assertIn("@supports not ((backdrop-filter:", self.styles)
        self.assertIn("background-color: var(--color-surface-raised)", self.styles)
        opaque = self.styles.index(
            "background: var(--color-gunmetal)",
            self.styles.index(".composer,"),
        )
        translucent = self.styles.index("rgba(", opaque)
        backdrop = self.styles.index("backdrop-filter:", translucent)
        self.assertLess(opaque, translucent)
        self.assertLess(translucent, backdrop)

    def test_visual_system_adds_no_external_asset_dependency(self) -> None:
        self.assertNotIn("@import", self.styles)
        self.assertNotIn("url(", self.styles)
        for attributes in self.parser.attributes_for("link"):
            self.assertTrue(str(attributes.get("href", "")).startswith("/assets/"))

    def test_application_shell_owns_the_visual_viewport(self) -> None:
        body = css_declarations(self.styles, "body")
        shell = css_declarations(self.styles, ".app-shell")
        main = css_declarations(self.styles, ".app-main")
        view = css_declarations(self.styles, ".view")

        self.assertEqual(body["overflow"], ["hidden"])
        self.assertEqual(shell["height"], ["100vh", "100dvh"])
        self.assertEqual(shell["min-height"], ["0"])
        self.assertEqual(shell["overflow"], ["hidden"])
        self.assertNotIn("grid-template-rows", shell)
        self.assertEqual(main["min-width"], ["0"])
        self.assertEqual(main["min-height"], ["0"])
        self.assertEqual(main["overflow"], ["hidden"])
        self.assertEqual(view["min-width"], ["0"])
        self.assertEqual(view["min-height"], ["0"])

    def test_views_own_their_intended_scrolling_boundaries(self) -> None:
        conversation_view = css_declarations(self.styles, ".conversation-view")
        transcript = css_declarations(self.styles, ".conversation")
        management_view = css_declarations(self.styles, ".management-view")
        sidebar = css_declarations(self.styles, ".sidebar")

        self.assertEqual(
            conversation_view["grid-template-rows"],
            ["auto auto auto auto auto auto minmax(0, 1fr) auto"],
        )
        self.assertEqual(conversation_view["overflow"], ["hidden"])
        self.assertEqual(transcript["min-height"], ["min(8rem, 20dvh)"])
        self.assertEqual(transcript["overflow-y"], ["auto"])
        self.assertEqual(management_view["overflow-y"], ["auto"])
        self.assertNotIn("order", sidebar)
        self.assertNotIn("position", sidebar)

        fallback = self.styles.index("height: 100vh", self.styles.index(".app-shell"))
        dynamic = self.styles.index("height: 100dvh", fallback)
        self.assertLess(fallback, dynamic)

    def test_stream_following_is_proximity_bound_and_status_is_separate(
        self,
    ) -> None:
        conversation = self.scripts["app.js"]
        self.assertIn("function isNearConversationBottom()", conversation)
        self.assertIn("followConversationIfNeeded(shouldFollow)", conversation)
        self.assertIn("Response complete · Connected locally", conversation)
        self.assertIn("Generation failed · Connected locally", conversation)
        self.assertIn('aria-label", "Tori response draft"', conversation)

    def test_busy_generation_preserves_editable_composer_draft(self) -> None:
        script = self.scripts["app.js"]
        busy_handler = script.split("function setBusy(value, statusText) {", 1)[
            1
        ].split("function showError", 1)[0]
        submit_handler = script.split(
            'composer.addEventListener("submit"',
            1,
        )[1].split(
            'messageInput.addEventListener("keydown"',
            1,
        )[0]
        speech_status_handler = script.split(
            "function setSpeechStatus(message, state = \"neutral\") {",
            1,
        )[1].split("function stopLocalAudio", 1)[0]
        speech_lifecycle = script.split(
            "function setSpeechStatus(message, state = \"neutral\") {",
            1,
        )[1].split("function renderMemoryConfirmation", 1)[0]
        stop_speaking_handler = script.split(
            "function stopSpeaking(",
            1,
        )[1].split("function decodePCM", 1)[0]

        self.assertIn("sendButton.disabled = value", busy_handler)
        self.assertNotIn("messageInput.disabled", busy_handler)
        self.assertIn("if (busy || !message.trim())", submit_handler)
        self.assertIn("messageInput.value = \"\"", submit_handler)
        self.assertIn(
            "const composerRevisionAtClear = composerRevision",
            submit_handler,
        )
        self.assertIn(
            "composerRevision === composerRevisionAtClear",
            submit_handler,
        )
        self.assertLess(
            submit_handler.index("messageInput.value = message"),
            submit_handler.index("setBusy(false, terminalStatus)"),
        )
        self.assertIn("setBusy(false, terminalStatus)", submit_handler)
        self.assertEqual(submit_handler.count("messageInput.value ="), 3)
        self.assertNotIn("messageInput", speech_status_handler)
        self.assertNotIn("messageInput", speech_lifecycle)
        self.assertNotIn("messageInput", stop_speaking_handler)
        self.assertIn(
            'stopSpeechButton.addEventListener("click", () => stopSpeaking({resetAudio: true}))',
            script,
        )
        self.assertIn(
            'messageInput.addEventListener("input", () => {\n'
            "  composerRevision += 1;",
            script,
        )

    def test_multi_browser_busy_state_reconciles_from_authoritative_polling(self) -> None:
        script = self.scripts["app.js"]
        management = self.scripts["manage.js"]
        polling = script.split("async function refreshAttention", 1)[1].split(
            "async function mutateAttention", 1
        )[0]
        self.assertIn("result.busy === true", polling)
        self.assertIn("pendingTranscriptRevision", polling)
        self.assertIn("else if (busy)", polling)
        self.assertIn("await loadSession({", polling)
        self.assertIn("localConversationPending", polling)
        self.assertIn("attentionChatId === renderedChatId", polling)
        self.assertIn(
            "observedSameChatRevision > renderedTranscriptRevision", polling
        )
        self.assertNotIn("attentionTranscriptRevision", script)
        self.assertIn("expectedTranscriptRevision", script)
        self.assertIn('new CustomEvent("tori:serverbusystatechange"', script)
        self.assertIn(
            'document.addEventListener("tori:serverbusystatechange"', management
        )
        subprocess.run(
            ["node", str(Path(__file__).with_name("test_browser_command_activity.js"))],
            check=True,
            cwd=Path(__file__).resolve().parents[1],
        )

    def test_archive_history_is_persistent_truthful_and_mobile_reused(self) -> None:
        script = self.scripts["app.js"]
        self.assertNotIn('id="chat-archive"', self.html)
        self.assertIn('id="chat-list" class="chat-history-list"', self.html)
        self.assertIn('id="new-session"', self.html)
        self.assertIn('id="mobile-history-slot"', self.html)
        self.assertIn('ui.requestJson("/api/chats")', script)
        self.assertIn('ui.requestJson("/api/projects/labels")', script)
        self.assertIn("chat.completed_turn_count", script)
        self.assertIn("chat.updated_at", script)
        self.assertIn("projectTitles.get(chat.project_id)", script)
        self.assertNotIn("ai-generated", script.casefold())
        history = css_declarations(self.styles, ".chat-history-list")
        row = css_declarations(self.styles, ".chat-history-row")
        opener = css_declarations(self.styles, ".chat-history-open")
        self.assertEqual(history["display"], ["grid"])
        self.assertEqual(row["min-width"], ["0"])
        self.assertEqual(opener["min-width"], ["0"])

    def test_model_provider_management_is_human_only_bounded_and_mobile_safe(self) -> None:
        settings = self.scripts["settings.js"]
        self.assertIn('"/api/model-providers/create"', settings)
        self.assertIn('"/api/model-providers/update"', settings)
        self.assertIn('"/api/model-providers/enabled"', settings)
        self.assertIn('"/api/model-providers/token"', settings)
        self.assertIn('"/api/model-providers/delete"', settings)
        self.assertIn("confirmed: true", settings)
        self.assertIn("Built-in · Editable", settings)
        self.assertIn("will become unavailable", settings)
        self.assertIn('value: "openai_compatible"', settings)
        self.assertIn('type: "password"', settings)
        self.assertIn('autocomplete: "new-password"', settings)
        self.assertIn("Token configured", settings)
        self.assertIn("never reads it back", settings)
        self.assertNotIn("profile.token,", settings)
        self.assertNotIn("tori-local-compatibility", self.html + settings)
        self.assertNotIn("localStorage", settings)
        self.assertNotIn("sessionStorage", settings)
        dialog = css_declarations(
            self.settings_styles, ".settings-module #model-provider-dialog"
        )
        card = css_declarations(
            self.settings_styles, ".settings-module .provider-form-card"
        )
        copy = css_declarations(
            self.settings_styles,
            ".settings-module .provider-form-card > h2, .settings-module .provider-form-card > p",
        )
        form_grid = css_declarations(
            self.settings_styles, ".settings-module .provider-form-grid"
        )
        controls = css_declarations(
            self.settings_styles,
            ".settings-module .provider-form-grid input, .settings-module .provider-form-grid select",
        )
        actions = css_declarations(
            self.settings_styles,
            ".settings-module .provider-form-card .dialog-actions",
        )
        action_buttons = css_declarations(
            self.settings_styles,
            ".settings-module .provider-form-card .dialog-actions .button",
        )
        endpoint = css_declarations(
            self.settings_styles, ".settings-module .provider-endpoint"
        )
        self.assertIn("100vw", dialog["width"][0])
        self.assertIn("100vw", dialog["max-width"][0])
        self.assertEqual(dialog["overflow-x"], ["hidden"])
        self.assertEqual(dialog["overflow-y"], ["auto"])
        self.assertEqual(card["width"], ["100%"])
        self.assertEqual(card["min-width"], ["0"])
        self.assertEqual(card["max-width"], ["100%"])
        self.assertEqual(copy["white-space"], ["normal"])
        self.assertEqual(copy["overflow-wrap"], ["anywhere"])
        self.assertEqual(form_grid["grid-template-columns"], ["minmax(0, 1fr)"])
        self.assertEqual(form_grid["min-width"], ["0"])
        self.assertEqual(form_grid["max-width"], ["100%"])
        self.assertEqual(controls["width"], ["100%"])
        self.assertEqual(controls["min-width"], ["0"])
        self.assertEqual(controls["max-width"], ["100%"])
        self.assertIn("minmax(0, 1fr)", actions["grid-template-columns"][0])
        self.assertEqual(actions["min-width"], ["0"])
        self.assertEqual(actions["max-width"], ["100%"])
        self.assertEqual(action_buttons["min-width"], ["0"])
        self.assertEqual(action_buttons["width"], ["100%"])
        self.assertEqual(endpoint["overflow-wrap"], ["anywhere"])
        mobile = "}" + self.settings_styles.split("@media (max-width: 640px)", 1)[1]
        mobile_dialog = css_declarations(
            mobile, ".settings-module #model-provider-dialog"
        )
        mobile_card = css_declarations(
            mobile, ".settings-module .provider-form-card"
        )
        mobile_actions = css_declarations(
            mobile, ".settings-module .provider-record-actions"
        )
        self.assertIn("100vw", mobile_dialog["width"][0])
        self.assertIn("100vw", mobile_dialog["max-width"][0])
        self.assertIn("100dvh", mobile_dialog["max-height"][0])
        self.assertEqual(mobile_card["width"], ["100%"])
        self.assertIn("minmax(0, 1fr)", mobile_actions["grid-template-columns"][0])

    def test_tts_profile_settings_use_canonical_revision_safe_apis_and_mobile_layout(self) -> None:
        settings = self.scripts["settings.js"]
        for path in (
            "/api/tts-profiles", "/api/tts-profiles/active",
            "/api/tts-profiles/create", "/api/tts-profiles/update",
            "/api/tts-profiles/delete", "/api/tts-profiles/select",
        ):
            self.assertIn(f'"{path}"', settings)
        for field in (
            "tts-profile-name", "tts-profile-endpoint",
            "tts-profile-model", "tts-profile-voice",
            "tts-profile-connect-timeout", "tts-profile-read-timeout",
            "tts-profile-enabled",
        ):
            self.assertIn(f'"{field}"', settings)
        self.assertIn("OpenAI-compatible local TTS contract", settings)
        self.assertIn('authentication_mode: "none"', settings)
        self.assertIn("provider_options: {}", settings)
        self.assertIn('requestError.code === "stale_revision"', settings)
        self.assertIn("changed in another client", settings)
        self.assertIn("No local substitute or browser copy", settings)
        self.assertIn("selected enabled profile supplies future speech", settings)
        self.assertIn("Availability not checked", settings)
        self.assertIn("availability === \"unavailable\"", settings)
        self.assertIn("saving does not connect or select the profile", settings)
        self.assertNotIn("tts-profile-credential", settings)
        self.assertNotIn("tts-profile-provider", settings)
        self.assertNotIn("localStorage", settings)
        self.assertNotIn("sessionStorage", settings)
        self.assertNotIn("/api/speech", settings)

        dialog = css_declarations(
            self.settings_styles, ".settings-module #tts-profile-dialog"
        )
        record = css_declarations(
            self.settings_styles, ".settings-module .tts-profile-record"
        )
        endpoint = css_declarations(
            self.settings_styles, ".settings-module .tts-profile-endpoint"
        )
        self.assertIn("100vw", dialog["width"][0])
        self.assertEqual(dialog["overflow-x"], ["hidden"])
        self.assertIn("minmax(0, 1fr)", record["grid-template-columns"][0])
        self.assertEqual(record["min-width"], ["0"])
        self.assertEqual(endpoint["overflow-wrap"], ["anywhere"])
        mobile = "}" + self.settings_styles.split("@media (max-width: 640px)", 1)[1]
        mobile_dialog = css_declarations(
            mobile, ".settings-module #tts-profile-dialog"
        )
        self.assertIn("100vw", mobile_dialog["width"][0])
        self.assertIn("100dvh", mobile_dialog["max-height"][0])


if __name__ == "__main__":
    unittest.main()
