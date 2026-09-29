"""Provider-neutral normalization for untrusted model response content."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator

from .providers.base import ProviderResponseError


MAX_BUFFERED_MODEL_RESPONSE_CHARACTERS = 1_000_000
MAX_TOOL_SHAPED_RESPONSE_CHARACTERS = 32_768
MAX_INCREMENTAL_CLASSIFICATION_CHARACTERS = 560
EXTERNAL_KNOWLEDGE_ADVISORY = "[[TORI:EXTERNAL_KNOWLEDGE_NEEDED]]"
CONTROL_DATA_WITHHELD_MESSAGE = (
    "An unsafe internal model control response was withheld."
)

_LEADING_THINK = re.compile(r"\A\s*<think>", re.IGNORECASE)
_ANY_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_ANY_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)
_FENCED_BLOCK = re.compile(
    r"\A\s*```(?:json)?[ \t]*(?:\r?\n)?(.*?)(?:\r?\n)?```\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_ADVISORY_CODE_BLOCK = re.compile(
    r"\A```(?:text|plaintext)?[ \t]*(?:\r?\n)"
    r"(?P<content>.*?)"
    r"(?:\r?\n)```\Z",
    re.IGNORECASE | re.DOTALL,
)
_ADVISORY_INLINE_CODE = re.compile(r"\A`(?P<content>[^`\r\n]+)`\Z")
_TORI_CONTROL_PREFIX = re.compile(
    r"\[\[\s*TORI\s*(?::|_)",
    re.IGNORECASE,
)
_TOOL_KEY = re.compile(r'"tool"\s*:', re.IGNORECASE)
_NAME_KEY = re.compile(r'"name"\s*:', re.IGNORECASE)
_ARGUMENTS_KEY = re.compile(r'"arguments"\s*:', re.IGNORECASE)


class ExternalKnowledgeNeededAdvisory(ProviderResponseError):
    """Internal whole-response advisory; never eligible for presentation."""


class DeferredModelAction(Exception):
    """Trusted application handler accepted an action without assistant prose."""


def normalize_model_response(
    content: object,
    *,
    allow_external_knowledge_advisory: bool = True,
) -> str:
    """Return only safe final assistant content or fail without echoing it."""

    if not isinstance(content, str):
        raise ProviderResponseError(
            "The model provider returned non-text assistant content."
        )
    if len(content) > MAX_BUFFERED_MODEL_RESPONSE_CHARACTERS:
        raise ProviderResponseError(
            "The model response exceeded Tori's presentation safety limit."
        )

    visible = _without_leading_reasoning(content)
    stripped = visible.strip()
    if EXTERNAL_KNOWLEDGE_ADVISORY in stripped:
        advisory = _whole_response_advisory(stripped)
        if advisory and allow_external_knowledge_advisory:
            raise ExternalKnowledgeNeededAdvisory(
                "The model advised that external knowledge is needed."
            )
        raise ProviderResponseError(
            "The model returned a malformed external-knowledge advisory."
        )
    if contains_tori_control_data(stripped):
        raise ProviderResponseError(
            "The model returned malformed internal control data."
        )
    if '"tori_terminal_proposal_v1"' in stripped:
        raise ProviderResponseError(
            "The model returned an unauthorized terminal proposal."
        )
    if _is_tool_call_shaped(visible):
        raise ProviderResponseError(
            "The model returned an unsupported tool-call response."
        )
    visible = visible.strip()
    if not visible:
        raise ProviderResponseError(
            "The model response was empty or contained no safe assistant content."
        )
    return visible


def contains_tori_control_data(content: object) -> bool:
    """Identify exact or malformed application-owned control markers."""

    return isinstance(content, str) and (
        EXTERNAL_KNOWLEDGE_ADVISORY in content
        or _TORI_CONTROL_PREFIX.search(content) is not None
    )


def _whole_response_advisory(content: str) -> bool:
    """Accept only the exact signal, optionally wrapped as Markdown code."""

    if content == EXTERNAL_KNOWLEDGE_ADVISORY:
        return True
    for pattern in (_ADVISORY_CODE_BLOCK, _ADVISORY_INLINE_CODE):
        match = pattern.fullmatch(content)
        if match is not None:
            return match.group("content").strip() == EXTERNAL_KNOWLEDGE_ADVISORY
    return False


def normalized_response_stream(
    fragments: Iterator[str],
    *,
    transform: Callable[[str], str] | None = None,
    model_action_handler: Callable[[str], str | None] | None = None,
    allow_external_knowledge_advisory: bool = True,
) -> Iterator[str]:
    """Yield approved ordinary text at bounded boundaries, then validate fully.

    Reasoning-, code-, advisory-, and transform-bearing responses remain fully
    buffered because their eventual classification can change presentation.
    An ordinary response becomes incrementally presentable only after a
    complete natural text boundary (or a bounded long-text fallback) has made
    its leading prose unambiguous. This is the shared safe-visible boundary for
    both browser text and secondary presentation such as speech.
    """

    length = 0
    mode = "pending"
    raw_fragments: list[str] = []
    emitted = ""

    for fragment in fragments:
        if not isinstance(fragment, str):
            raise ProviderResponseError(
                "The model provider returned a non-text stream fragment."
            )
        length += len(fragment)
        if length > MAX_BUFFERED_MODEL_RESPONSE_CHARACTERS:
            raise ProviderResponseError(
                "The model response exceeded Tori's presentation safety limit."
            )
        raw_fragments.append(fragment)
        if not fragment and mode == "pending":
            yield ""
            continue
        if mode == "pending":
            mode = _stream_prefix_mode("".join(raw_fragments))
        if transform is not None or mode in {"reasoning", "buffered"}:
            # An internal empty fragment gives an iterator consumer a coherent
            # cancellation point while no hidden or unclassified text is
            # eligible for a browser delta.
            yield ""
            continue
        if mode == "ordinary":
            raw = "".join(raw_fragments)
            candidate = raw.lstrip()
            if emitted and not candidate.startswith(emitted):
                raise ProviderResponseError(
                    "The model response changed already approved visible text."
                )
            pending = candidate[len(emitted):]
            boundary = _incremental_visible_boundary(pending)
            if boundary is None:
                yield ""
                continue
            approved = pending[:boundary]
            emitted += approved
            yield approved

    raw = "".join(raw_fragments)
    # The assistant's visible response, not its validated leading reasoning,
    # is the only candidate for a structured action. Keep the parser strict:
    # a fenced, partial, or prose-wrapped envelope is still not executable.
    visible = _without_leading_reasoning(raw)
    action_result = model_action_handler(visible) if model_action_handler is not None else None
    completed = (action_result if action_result is not None else normalize_model_response(
        raw,
        allow_external_knowledge_advisory=allow_external_knowledge_advisory,
    ))
    presented = completed if action_result is not None or transform is None else transform(completed)
    if not isinstance(presented, str) or not presented.strip():
        raise ProviderResponseError(
            "The model response could not be safely presented."
        )
    presented = presented.strip()
    if emitted:
        if not presented.startswith(emitted):
            raise ProviderResponseError(
                "The completed response did not match approved visible text."
            )
        remainder = presented[len(emitted):]
        if remainder:
            yield remainder
        return
    yield presented


def _stream_prefix_mode(content: str) -> str:
    stripped = content.lstrip()
    if not stripped:
        return "pending"
    folded = stripped.casefold()
    compact_prefix = re.sub(r"\s+", "", folded[:16])
    if stripped.startswith("[") and "[[tori".startswith(compact_prefix):
        return "pending"
    for marker in (
        "<think>", "</think>", "```", "{",
        EXTERNAL_KNOWLEDGE_ADVISORY.casefold(),
    ):
        if marker.startswith(folded):
            return "pending"
    if folded.startswith("<think>") or folded.startswith("</think>"):
        return "reasoning"
    if (
        stripped.startswith("{")
        or stripped.startswith("```")
        or EXTERNAL_KNOWLEDGE_ADVISORY.casefold().startswith(folded)
        or _TORI_CONTROL_PREFIX.match(stripped)
    ):
        return "buffered"
    return "ordinary"


def _incremental_visible_boundary(content: str) -> int | None:
    """Return one safe natural prefix boundary for ordinary visible prose."""

    if not content:
        return None
    if _TORI_CONTROL_PREFIX.search(content):
        return None
    folded = content.casefold()
    if "<think>" in folded or "</think>" in folded:
        return None
    for index, character in enumerate(content):
        end = index + 1
        if character in "!?" and (end == len(content) or content[end].isspace()):
            return end
        if character == "." and (end == len(content) or content[end].isspace()):
            before = content[index - 1] if index else ""
            after = content[index + 1] if index + 1 < len(content) else ""
            if not (before.isdigit() and after.isdigit()):
                return end
        if character == "\n" and (
            content[index:index + 2] == "\n\n" or end >= 80
        ):
            return end
    if len(content) < MAX_INCREMENTAL_CLASSIFICATION_CHARACTERS:
        return None
    fallback = max(
        content.rfind(separator, 80, MAX_INCREMENTAL_CLASSIFICATION_CHARACTERS)
        for separator in (";", ":", ",", " ", "\t")
    )
    return fallback + 1 if fallback >= 80 else None


def _without_leading_reasoning(content: str) -> str:
    leading = _LEADING_THINK.match(content)
    first_open = _ANY_THINK_OPEN.search(content)
    first_close = _ANY_THINK_CLOSE.search(content)

    if leading is not None:
        closing = _ANY_THINK_CLOSE.search(content, leading.end())
        if closing is None:
            raise ProviderResponseError(
                "The model returned an incomplete hidden reasoning section."
            )
        hidden = content[leading.end() : closing.start()]
        remainder = content[closing.end() :]
        if _ANY_THINK_OPEN.search(hidden) or _ANY_THINK_CLOSE.search(hidden):
            raise ProviderResponseError(
                "The model returned a malformed hidden reasoning section."
            )
        if _ANY_THINK_OPEN.search(remainder) or _ANY_THINK_CLOSE.search(remainder):
            raise ProviderResponseError(
                "The model returned contradictory reasoning markers."
            )
        if not remainder.strip():
            raise ProviderResponseError(
                "The model response was empty or contained no safe assistant content."
            )
        return remainder

    # A closing marker without an earlier opening marker retroactively marks
    # the leading material as unsafe. Whole-response classification prevents
    # that material from having already reached a presentation surface.
    if first_close is not None and (
        first_open is None or first_close.start() < first_open.start()
    ):
        raise ProviderResponseError(
            "The model returned a malformed hidden reasoning section."
        )

    # Non-leading, balanced examples remain ordinary visible text. Only a
    # validated leading reasoning section is removed.
    return content


def _is_tool_call_shaped(content: str) -> bool:
    stripped = content.strip()
    fenced = _FENCED_BLOCK.fullmatch(stripped)
    payload = fenced.group(1).strip() if fenced is not None else stripped

    candidate = payload.startswith("{")
    if not candidate and stripped.startswith("```"):
        # An incomplete fence is still rejected when its whole response has a
        # narrow tool-call signature.
        candidate = _looks_like_tool_signature(stripped)
        payload = stripped
    if not candidate:
        return False

    signature = _looks_like_tool_signature(payload)
    if len(payload) > MAX_TOOL_SHAPED_RESPONSE_CHARACTERS and signature:
        return True
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, RecursionError):
        return signature
    if not isinstance(document, dict):
        return False

    tool = document.get("tool")
    if isinstance(tool, str):
        return True
    name = document.get("name")
    return isinstance(name, str) and "arguments" in document


def _looks_like_tool_signature(payload: str) -> bool:
    return bool(
        _TOOL_KEY.search(payload)
        or (_NAME_KEY.search(payload) and _ARGUMENTS_KEY.search(payload))
    )
