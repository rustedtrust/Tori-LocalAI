"""Application-owned capability knowledge and advisory message understanding.

This registry describes existing services; it is not an executor or a permission
registry. Model classifications select a discussion/clarification path only.
Execution still requires the original text to pass a domain's authority boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import re

from .context import estimate_text_tokens
from .providers import ChatMessage, ModelProvider, ProviderError


@dataclass(frozen=True, slots=True)
class Capability:
    identifier: str
    name: str
    terms: tuple[str, ...]
    scope: str
    boundary: str


CAPABILITIES = (
    Capability("memory", "Memory", ("memory", "memories", "remember"),
               "curated local facts/preferences; review, correct, forget", "Memory policy applies; never claim a save without its receipt"),
    Capability("knowledge", "Knowledge", ("knowledge", "document"),
               "register exact local txt/md files and retrieve passages", "no folder ingestion or arbitrary file access"),
    Capability("search", "Search/SearXNG", ("search", "searxng", "web"),
               "search public web sources and summarize attributed results with bounded source reading", "enabled/configured Search and application authorization required; explicit request or one-use consent; no silent model-only fallback"),
    Capability("finance", "Finance", ("finance", "budget", "spending", "bills", "debt", "afford"),
               "external budgeting workbook, spending/bills/debts/goals and deterministic affordability calculations", "not arbitrary spreadsheets; reviewed imports and confirmed writes; no banking or payments"),
    Capability("planning", "Planning/CalDAV", ("planning", "calendar", "caldav", "radicale", "appointment"),
               "calendar events, planning tasks and reminders", "ask for title/date/time; show exact proposal before confirmed changes"),
    Capability("tasks", "Tasks/reminders", ("task", "tasks", "reminder", "reminders", "remind", "to-do"),
               "local tasks and timed reminders", "explicit intent, description and resolved time; runs only while Tori runs"),
    Capability("scheduled_work", "Scheduled Work", ("scheduled work",),
               "confirmed one-shot backups, derived Planning reminders and authorized Night Owl schedules", "no arbitrary scheduled prompts/commands; cannot wake host"),
    Capability("projects", "Projects", ("project", "projects"),
               "Project Home, structured continuity, related work and associated chats", "context organization grants no action; changes require explicit authority"),
    Capability("host", "Host information", ("ram", "cpu", "gpu", "disk", "storage", "uptime", "lan"),
               "deterministic RAM/disk/CPU/GPU/LAN/status reads", "read-only; no invented measurements"),
    Capability("coding_work", "Coding Work/OpenCode", ("opencode", "coding work", "code", "repository"),
               "supervise coding/review in one explicit existing workspace", "bounded sandbox; exact scope and confirmation; no unrestricted access"),
    Capability("research", "Research Worker", ("deep research", "research job", "research worker"),
               "authorized multi-step public-web research with durable evidence and reports", "public objective only; isolated egress; explicit confirmation; no private Tori context"),
    Capability("mcp_time", "MCP Time", ("mcp time", "mcp server", "mcp capability"),
               "current time in one exact IANA timezone through the reviewed local MCP Time server", "safe bounded read; Tori allowlists one tool, validates input/output, and grants no filesystem or network authority"),
    Capability("run", "Supervised Terminal", ("supervised terminal", "terminal", "shell command", "run a command"),
               "local browser Terminal drawer and exact conversational command proposals", "loopback only; policy and one-use approval govern execution; browser /run is retired"),
    Capability("services", "Service controls", ("ollama", "service"),
               "fixed Ollama/Radicale start, stop, restart", "one-use confirmation and installed allowlisted helper/privileges"),
    Capability("backup", "Verified backup", ("backup", "backups"),
               "fixed-policy verified Tori project/runtime snapshot", "success only after verification; no automatic backup pruning"),
    Capability("restore", "Verified restore", ("restore", "restore backup"),
               "separately confirmed whole-runtime restore from a verified compatible backup, with a safety backup", "never automatic; source compatibility and local authority checks apply"),
    Capability("tts", "Speech output", ("tts", "speech output", "text to speech", "speak", "qwen", "kokoro"),
               "speak responses using a selected local speech profile, including OpenAI-compatible TTS", "speech preference/profile/backend must be usable; never silently switch providers"),
    Capability("voice_input", "Voice input", ("voice input", "voice", "speech recognition", "microphone", "listen to me", "stt"),
               "desktop loopback-browser push-to-talk speech recognition", "separately prepared runtime; no wake word, passive listening or LAN microphone"),
    Capability("night_owl", "Night Owl", ("night owl",),
               "bounded category-based advisory discovery and reviewable findings", "default off; authorized categories only; no automatic installation or action"),
    Capability("security", "Security Center", ("security center", "security intelligence"),
               "review, discuss or dismiss Night Owl Security intelligence and relevance metadata", "not a scanner, SIEM, IDS, EDR, AV, local alert-ingestion or remediation system"),
    Capability("capability_growth", "Capability Growth", ("capability growth", "skills review"),
               "review operational findings and request bounded Skills Reviews for recommendations", "advisory only; no autonomous Skill creation, installation or updates"),
    Capability("skills", "Skills", ("skills", "skill"),
               "inspect, manage and invoke explicitly approved local Skills", "discovering a Skill never installs or enables it; grants and origin rules apply"),
    Capability("remote_chat", "Discord Remote Chat", ("remote chat", "discord"),
               "one-owner private Discord text DM with bounded Search and reminder reads", "default off each process; local enablement; remote origin cannot use local tools"),
    Capability("companion", "Companion Initiative", ("companion initiative", "proactive companion"),
               "optional local check-ins and suggestion-only attention/briefs", "default off; no remote delivery or authority to start work"),
    Capability("models", "Model/provider controls", ("model settings", "model providers"),
               "choose local model/provider profiles and per-chat context through Settings and Chat", "unavailable selections do not silently fall back; no cloud provisioning"),
    Capability("applications", "Application opening", ("brave", "dolphin", "open application"),
               "open allowlisted desktop apps and existing folders", "fixed executable vectors, not arbitrary desktop control"),
)
_BY_ID = {item.identifier: item for item in CAPABILITIES}
_PROMPT_HINTS = {
    "search": "public web search/attributed; consent",
    "voice_input": "loopback push-to-talk STT; no wake/passive listening",
    "security": "intelligence review; no scanner/alerts/remediation",
    "run": "loopback Terminal; policy/approval; browser /run retired",
    "tts": "local/OpenAI-compatible speech profile",
    "restore": "confirmed whole-runtime; safety backup; never automatic",
    "scheduled_work": "Night Owl schedules; no arbitrary jobs",
    "night_owl": "default-off advisory; no installs",
    "capability_growth": "advisory Skills Review",
}
_CONVERSATIONAL_DESCRIPTIONS = {
    "search": "I can search public web sources and summarize attributed results when Web Search is enabled. Search still needs an explicit request or your consent.",
    "voice_input": "I can take push-to-talk voice input in the local desktop browser when the recognition runtime is ready. I don't listen passively or use a wake word.",
    "tts": "I can speak responses aloud through your selected local TTS profile, including OpenAI-compatible speech, when its backend is available.",
    "run": "I can propose a command through my supervised Terminal in the local browser. The Terminal policy decides whether your approval is needed before it runs; browser /run is retired.",
    "security": "I have a Security Center for reviewing and discussing Night Owl security intelligence. It's not a scanner, SIEM, antivirus, local alert system or remediation tool.",
    "restore": "I can restore Tori's whole runtime from a verified compatible backup after your separate confirmation. I create a safety backup first; restore never happens automatically.",
}
MAX_AWARENESS_ESTIMATED_TOKENS = 270
STATES = frozenset({"available", "configured", "disabled", "not_configured", "unavailable", "unknown"})


@dataclass(frozen=True, slots=True)
class CapabilityState:
    state: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError("Unknown capability state.")


def _safe_dynamic_capability(value: object) -> bool:
    if not isinstance(value, Capability) or value.terms:
        return False
    if not re.fullmatch(r"skill\.[a-z0-9._-]{1,594}", value.identifier):
        return False
    return all(
        isinstance(text, str)
        and 0 < len(text) <= 600
        and not any(ord(character) < 32 for character in text)
        for text in (value.name, value.scope, value.boundary)
    )


class CapabilityRegistry:
    """One source for capability inventory, current state and model awareness.

    Readers must be non-mutating, return no personal records/credentials, and
    must not probe external services merely to compose a conversation prompt.
    Configured does not mean reachable; execution performs the final check.
    """

    def __init__(
        self,
        readers: Mapping[str, Callable[[], CapabilityState]] = (),
        *,
        dynamic_reader: Callable[[], tuple[Capability, ...]] | None = None,
    ) -> None:
        self._readers = dict(readers)
        self._dynamic_reader = dynamic_reader
        if set(self._readers) - _BY_ID.keys():
            raise ValueError("Unknown capability reader.")

    def _dynamic_capabilities(self) -> tuple[Capability, ...]:
        if self._dynamic_reader is None:
            return ()
        try:
            result = self._dynamic_reader()
            if (
                not isinstance(result, tuple)
                or len(result) > 64
                or any(not _safe_dynamic_capability(item) for item in result)
            ):
                return ()
            identifiers = tuple(item.identifier for item in result)
            if len(set(identifiers)) != len(identifiers) or any(identifier in _BY_ID for identifier in identifiers):
                return ()
            return result
        except Exception:
            # Dynamic capability discovery is non-authorizing and fail-closed.
            return ()

    def _snapshot(self, dynamic: tuple[Capability, ...]) -> dict[str, CapabilityState]:
        result = {}
        for item in CAPABILITIES:
            reader = self._readers.get(item.identifier)
            try:
                result[item.identifier] = reader() if reader else CapabilityState("not_configured")
            except Exception:
                # No storage/provider diagnostic or secret enters model context.
                result[item.identifier] = CapabilityState("unavailable", "state could not be read")
        for item in dynamic:
            result[item.identifier] = CapabilityState("available")
        return result

    def snapshot(self) -> dict[str, CapabilityState]:
        return self._snapshot(self._dynamic_capabilities())

    def awareness(self) -> str:
        dynamic = self._dynamic_capabilities()
        states = self._snapshot(dynamic)
        def project(hints: set[str]) -> str:
            lines = [
                "TORI CAPABILITIES: claim only listed abilities; configured isn't proven reachable; actions need app confirmation. Voice input is loopback push-to-talk, not wake/passive listening. Security Center reviews intelligence, not local scans or alerts. Direct image generation is not available; researching image tools is not generating images.",
            ]
            not_configured: list[str] = []
            brief_states: dict[str, list[str]] = {}
            for item in (*CAPABILITIES, *dynamic):
                state = states[item.identifier]
                # Absent MCP consumes no routine context; it remains available
                # for deterministic capability discussion.
                if item.identifier == "mcp_time" and state.state == "not_configured":
                    continue
                if state.state == "not_configured":
                    not_configured.append(item.name)
                    continue
                hint = _PROMPT_HINTS.get(item.identifier) if item.identifier in hints else None
                if hint:
                    lines.append(f"{item.name}: {state.state}; {hint}")
                else:
                    brief_states.setdefault(state.state, []).append(item.name)
            for state, names in brief_states.items():
                lines.append(f"{state.title()}: " + ", ".join(names) + ".")
            if not_configured:
                lines.append("Supported but not configured here: " + ", ".join(not_configured) + ".")
            return "\n".join(lines)

        selected: set[str] = set()
        for identifier in _PROMPT_HINTS:
            candidate = selected | {identifier}
            if estimate_text_tokens(project(candidate)) <= MAX_AWARENESS_ESTIMATED_TOKENS:
                selected = candidate
        return project(selected)

    def describe(self, identifier: str) -> str:
        dynamic = self._dynamic_capabilities()
        items = {item.identifier: item for item in (*CAPABILITIES, *dynamic)}
        item = items[identifier]
        state = self._snapshot(dynamic)[identifier]
        answer = _CONVERSATIONAL_DESCRIPTIONS.get(identifier)
        if answer is None:
            answer = (f"I can help with {item.name.lower()}. "
                      f"{item.scope[0].upper() + item.scope[1:]}. "
                      f"{item.boundary[0].upper() + item.boundary[1:]}.")
        if state.state in {"available", "configured"}:
            if identifier == "voice_input" and state.state == "configured":
                return answer + " Voice input is currently off until you turn it on in Chat."
            if identifier == "security" and state.state == "configured":
                return answer + " Night Owl Security research is enabled; source readiness is checked on use."
            if state.state == "available" and state.detail:
                return answer + " " + state.detail.rstrip(".") + "."
            return answer
        if identifier == "security" and state.state == "disabled":
            return answer + " Night Owl Security research is off, but stored findings remain available for review. You can enable research in Settings."
        limitation = {
            "disabled": "It's currently turned off.",
            "not_configured": "It isn't configured in this interface.",
            "unavailable": "It's currently unavailable.",
            "unknown": "I can't verify its availability right now.",
        }[state.state]
        if state.detail:
            limitation += f" {state.detail}."
        return answer + " " + limitation


@dataclass(frozen=True, slots=True)
class MessageIntent:
    kind: str  # conversation, discussion, information, action, clarification
    capability: str | None = None
    understood: bool = False

    @property
    def discussion_only(self) -> bool:
        return self.understood and self.kind in {"conversation", "discussion"}


def mentioned_capabilities(text: str) -> tuple[str, ...]:
    return tuple(item.identifier for item in CAPABILITIES if any(
        re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I)
        for term in item.terms
    ))


def is_capability_discussion(text: str) -> bool:
    """Speech-act guard, independent of the capability nouns in the sentence."""
    value = text.strip().casefold().replace("’", "'")
    if value.startswith("/"):
        return False
    terms = "|".join(re.escape(term) for item in CAPABILITIES for term in item.terms)
    if re.fullmatch(r"(?:what is|what are|what's)\s+(?:an?\s+)?(?:" + terms + r")[?.!]*", value):
        return True
    if re.fullmatch(r"(?:my |the |your )?(?:" + terms + r")\s+(?:isn't|aren't|is not|are not|not)\s+working[.!?]*", value):
        return True
    return bool(re.search(
        r"^(?:what|which)\s+(?:do you need|is required|are the requirements)|"
        r"^(?:how|why)\s+(?:do|does|can|would|is|are)\b|"
        r"^(?:let's|let us|i want to)\s+(?:discuss|talk|understand)\b",
        value,
    ))


def cli_capabilities(memory: object, knowledge: object, search: object, preferences: object,
                     *, commands: object = None) -> CapabilityRegistry:
    """The CLI exposes fewer application routes than the Web composition."""
    def search_state() -> CapabilityState:
        if preferences is not None:
            state = preferences.state().web_search
            if not state.administrator_permitted or not state.user_enabled:
                return CapabilityState("disabled")
        return CapabilityState("configured" if search is not None and search.available else "not_configured")
    return CapabilityRegistry({
        "memory": lambda: CapabilityState("available" if memory is not None else "not_configured"),
        "knowledge": lambda: CapabilityState("available" if knowledge is not None else "not_configured"),
        "search": search_state,
        # The CLI has no supervised Terminal or /run execution route.
    })


def capability_question(text: str) -> str | None:
    normalized = " ".join(text.casefold().replace("’", "'").split()).rstrip("?!. ")
    # Pure questions without an objective: these never become an execution
    # request, even if an advisory intent model would call them actions.
    for question, identifier in (
        ("can you listen to me or use voice input", "voice_input"),
        ("can you listen to me", "voice_input"),
        ("can you speak responses out loud", "tts"),
        ("can you run a command for me", "run"),
        ("can you restore a tori backup", "restore"),
        ("can you search the web", "search"),
    ):
        if normalized == question:
            return identifier
    mentioned = mentioned_capabilities(text)
    if not mentioned:
        return None
    # A question about ability has no requested objective. "Can you create ..."
    # is deliberately not included: it can be an action request.
    if re.fullmatch(r"(?is)\s*(?:can|could|do)\s+you\s+(?:use|access|support|have|work with)\s+[^?!.]+[?!.]*\s*", text) and not re.search(r"\bto\s+\w+", text, re.I):
        # The narrower noun wins when a phrase also contains "voice" or
        # "backup". This choice is descriptive, never authorizing.
        if "voice_input" in mentioned and "voice input" in normalized:
            return "voice_input"
        if "restore" in mentioned and "restore" in normalized:
            return "restore"
        return mentioned[0]
    return None


class CapabilityUnderstanding:
    """Advisory classification; never turns model text into executable input."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def interpret(self, text: str, provider: ModelProvider | None, model: str) -> MessageIntent:
        if text.lstrip().startswith("/"):
            return MessageIntent("action")  # Exact commands never go to an intent model.
        mentioned = mentioned_capabilities(text)
        if is_capability_discussion(text):
            return MessageIntent("discussion", mentioned[0] if mentioned else None, True)
        if not mentioned:
            return MessageIntent("conversation")
        fallback = MessageIntent("clarification", mentioned[0]) if mentioned[0] in {"planning", "tasks", "finance", "memory", "coding_work"} and re.match(
            r"(?is)^\s*(?:(?:can|could|would) you\s+)?(?:please\s+)?"
            r"(?:create|add|set|schedule|use|open|start|stop|restart|remind)\b", text
        ) else MessageIntent("conversation")
        if provider is None:
            return fallback
        try:
            response = provider.interpret_capability_intent((
                ChatMessage("system", self.registry.awareness() + "\nClassify the user's speech act. Return only JSON with exactly kind and capability. kind is conversation, discussion, information, action, or clarification. capability is one supplied ID or null. Capability questions, advice, complaints and hypothetical discussion are NOT action requests. Do not invent arguments or execute anything. IDs: " + ", ".join(_BY_ID)),
                ChatMessage("user", text),
            ), model=model)
            if len(response.content) > 1000:
                return MessageIntent("conversation")
            value = json.loads(response.content)
            if (not isinstance(value, dict) or set(value) != {"kind", "capability"}
                    or value["kind"] not in {"conversation", "discussion", "information", "action", "clarification"}
                    or value["capability"] not in (*mentioned, None)):
                return MessageIntent("conversation")
            return MessageIntent(value["kind"], value["capability"], True)
        except (ProviderError, ValueError, TypeError):
            return fallback


def explicit_memory_text(text: str) -> str | None:
    """Return a bounded, explicit durable-memory payload, if one was asked for.

    This is deliberately narrower than conversational use of ``remember``.
    Time-bound ``remember to`` requests continue into the task/reminder path;
    only an explicit fact/preference directive receives an immediate, verified
    Memory receipt.
    """

    normalized = text.strip()
    match = re.fullmatch(
        r"(?is)(?:(?:can|could|would) you\s+)?(?:please\s+)?"
        r"(?:create|save|add)\s+(?:a\s+)?memory\s+(?:that\s+|:\s*)(.+?)\s*",
        normalized,
    )
    if match is not None:
        return _memory_payload(match.group(1))

    # Scheduling stays authoritative when an actual future action/time is
    # present.  This avoids treating a reminder as a durable preference merely
    # because its natural phrasing begins with "remember to".
    if _looks_like_timed_reminder(normalized):
        return None

    weather_preference = _weather_fahrenheit_preference(normalized)
    if weather_preference is not None:
        return weather_preference

    match = re.fullmatch(
        r"(?is)(?:please\s+)?remember\s+that\s+(.+?)\s*", normalized,
    )
    if match is None:
        match = re.fullmatch(
            r"(?is)(?:can|could|would)\s+you\s+(?:please\s+)?remember\s+that\s+(.+?)\s*",
            normalized,
        )
    if match is not None:
        return _memory_payload(match.group(1))

    match = re.fullmatch(
        r"(?is)please\s+remember\s+(.+?)\s*", normalized,
    )
    if match is not None and re.search(
        r"\b(?:prefer|preference|like|dislike|favou?rite)\b", match.group(1), re.I
    ):
        return _memory_payload(match.group(1))
    return None


def ambiguous_memory_request(text: str) -> bool:
    """Identify an unsaved request that needs clarification, not model promise."""

    normalized = text.strip()
    if explicit_memory_text(normalized) is not None or _looks_like_timed_reminder(normalized):
        return False
    return bool(re.match(
        r"(?is)^(?:(?:can|could|would)\s+you\s+|please\s+)?remember\b|^from\s+now\s+on\b",
        normalized,
    ))


def _looks_like_timed_reminder(text: str) -> bool:
    return bool(re.search(
        r"(?i)\b(?:tomorrow|today|tonight|next\s+(?:week|month)|"
        r"at\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|"
        r"on\s+\d{1,2}[/-]\d{1,2})\b",
        text,
    ))


def _memory_payload(value: str) -> str:
    """Remove the outer question mark from a polite memory request only."""

    return value.strip().removesuffix("?").rstrip()


def _weather_fahrenheit_preference(text: str) -> str | None:
    """Normalize the one clearly-supported weather-unit preference."""

    value = text.casefold()
    has_weather = "weather" in value
    has_fahrenheit = bool(re.search(r"\b(?:fahrenheit|f)\b", value))
    has_celsius = bool(re.search(r"\b(?:celsius|c)\b", value))
    directive = bool(re.search(
        r"\b(?:remember|from now on|prefer|use)\b", value
    ))
    if has_weather and has_fahrenheit and has_celsius and directive:
        return "I prefer Fahrenheit rather than Celsius for weather."
    if (
        has_weather
        and has_fahrenheit
        and bool(re.match(r"(?is)^from\s+now\s+on\s+use\b", text.strip()))
    ):
        return "I prefer Fahrenheit for weather."
    return None
