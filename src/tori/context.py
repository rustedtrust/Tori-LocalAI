"""Provider-neutral active-conversation context budgeting."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from collections.abc import Sequence

from .providers.base import ChatMessage, ProviderUsage


ESTIMATOR_VERSION = "lexical-v1"
AUTO_CONTEXT_BUDGET = 32_768
MIN_CONTEXT_BUDGET = 4_096
MAX_CONTEXT_BUDGET = 1_048_576
CONTEXT_BUDGET_PRESETS = (4_096, 8_192, 16_384, 32_768, 65_536, 131_072)
_SEGMENT = re.compile(r"[A-Za-z]+|[0-9]+|[^\x00-\x7f]|[^\w\s]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    """One canonical per-conversation active-context preference."""

    token_budget: int | None = None

    @property
    def canonical(self) -> str:
        return "auto" if self.token_budget is None else f"fixed:{self.token_budget}"

    @classmethod
    def parse(cls, value: object) -> ContextPolicy:
        if value == "auto":
            return cls()
        if isinstance(value, str) and value.startswith("fixed:"):
            raw = value.removeprefix("fixed:")
            if raw.isdigit():
                return cls(_validate_budget(int(raw)))
        raise ValueError("Context policy must be 'auto' or 'fixed:<tokens>'.")

    @classmethod
    def fixed(cls, token_budget: int) -> ContextPolicy:
        return cls(_validate_budget(token_budget))


@dataclass(frozen=True, slots=True)
class ContextTelemetry:
    requested_policy: str
    effective_budget: int
    estimator_version: str
    estimated_input_tokens: int
    included_history_messages: int
    omitted_history_messages: int
    actual_usage: ProviderUsage | None = None


@dataclass(frozen=True, slots=True)
class ContextPlan:
    messages: tuple[ChatMessage, ...]
    telemetry: ContextTelemetry
    reply_reserve: int
    uncertainty_reserve: int


class ContextPlanningError(ValueError):
    """Raised before provider contact when mandatory context cannot fit."""


def estimate_text_tokens(text: str) -> int:
    """Conservatively estimate tokens using versioned lexical structure.

    Alphabetic runs use four-character pieces, numeric/identifier-like runs use
    three-character pieces, punctuation is counted individually, and each
    non-ASCII code point counts at least once. This is deterministic and more
    responsive to code, hashes, punctuation, and non-Latin text than a single
    bytes-per-token ratio; a separate planner reserve covers tokenizer and
    provider-template uncertainty.
    """

    if not isinstance(text, str):
        raise TypeError("Context estimation requires text.")
    total = 0
    for match in _SEGMENT.finditer(text):
        segment = match.group(0)
        if segment.isascii() and segment.isalpha():
            total += max(1, math.ceil(len(segment) / 4))
        elif segment.isascii() and segment.isdigit():
            total += max(1, math.ceil(len(segment) / 3))
        else:
            total += 1
    return total


def estimate_messages_tokens(messages: Sequence[ChatMessage]) -> int:
    """Estimate provider-visible messages including a stable envelope cost."""

    return 3 + sum(6 + estimate_text_tokens(item.role) + estimate_text_tokens(item.content) for item in messages)


def reply_reserve(token_budget: int) -> int:
    budget = _validate_budget(token_budget)
    return min(8_192, max(2_048, math.ceil(budget * 0.125)))


def uncertainty_reserve(token_budget: int) -> int:
    budget = _validate_budget(token_budget)
    return max(512, math.ceil(budget * 0.10))


def context_budget_presets(model_capacity: int | None) -> tuple[int, ...]:
    """Return bounded fixed planning choices for one selected model.

    A verified capacity removes choices above it and is included as a useful
    exact upper choice when it does not match a standard planning preset.
    Unknown capacity leaves the backend limit explicitly unverified.
    """

    if model_capacity is None:
        return CONTEXT_BUDGET_PRESETS
    capacity = _validate_budget(model_capacity)
    choices = {value for value in CONTEXT_BUDGET_PRESETS if value <= capacity}
    choices.add(capacity)
    return tuple(sorted(choices))


def effective_context_budget(
    policy: ContextPolicy, model_capacity: int | None
) -> int:
    """Resolve the planner budget through the canonical policy/capacity rules."""

    if model_capacity is not None:
        model_capacity = _validate_budget(model_capacity)
    effective = policy.token_budget or model_capacity or AUTO_CONTEXT_BUDGET
    if model_capacity is not None and effective > model_capacity:
        raise ContextPlanningError(
            "The selected context budget exceeds the known model capacity."
        )
    return effective


def context_input_limit(policy: ContextPolicy, model_capacity: int | None) -> int:
    """Return the exact provider-input allowance used by ``plan_context``."""

    effective = effective_context_budget(policy, model_capacity)
    return effective - reply_reserve(effective) - uncertainty_reserve(effective)


def plan_context(
    *,
    policy: ContextPolicy,
    model_capacity: int | None,
    mandatory_prefix: Sequence[ChatMessage],
    mandatory_suffix: Sequence[ChatMessage] = (),
    optional_context: Sequence[ChatMessage],
    history: Sequence[ChatMessage],
    current_user: ChatMessage,
) -> ContextPlan:
    """Select whole recent exchanges after protecting current-turn context."""

    if len(history) % 2 or any(
        message.role != ("user" if index % 2 == 0 else "assistant")
        for index, message in enumerate(history)
    ):
        raise ContextPlanningError("Eligible history must contain complete exchanges.")
    if current_user.role != "user":
        raise ContextPlanningError("Current context requires one user message.")
    effective = effective_context_budget(policy, model_capacity)
    reply = reply_reserve(effective)
    uncertainty = uncertainty_reserve(effective)
    input_limit = context_input_limit(policy, model_capacity)
    required = (*mandatory_prefix, *mandatory_suffix, current_user)
    if estimate_messages_tokens(required) > input_limit:
        raise ContextPlanningError(
            "Required current-turn context does not fit the selected context budget."
        )

    selected_optional = list(optional_context)
    while selected_optional and estimate_messages_tokens(
        (*mandatory_prefix, *selected_optional, *mandatory_suffix, current_user)
    ) > input_limit:
        selected_optional.pop()

    selected_reversed: list[tuple[ChatMessage, ChatMessage]] = []
    exchanges = tuple(zip(history[::2], history[1::2], strict=True))
    for exchange in reversed(exchanges):
        candidate_history = tuple(
            message
            for pair in reversed((*selected_reversed, exchange))
            for message in pair
        )
        candidate = (
            *mandatory_prefix,
            *selected_optional,
            *mandatory_suffix,
            *candidate_history,
            current_user,
        )
        if estimate_messages_tokens(candidate) > input_limit:
            break
        selected_reversed.append(exchange)
    selected_history = tuple(
        message for pair in reversed(selected_reversed) for message in pair
    )
    messages = (
        *mandatory_prefix,
        *selected_optional,
        *mandatory_suffix,
        *selected_history,
        current_user,
    )
    estimate = estimate_messages_tokens(messages)
    return ContextPlan(
        messages=messages,
        telemetry=ContextTelemetry(
            requested_policy=policy.canonical,
            effective_budget=effective,
            estimator_version=ESTIMATOR_VERSION,
            estimated_input_tokens=estimate,
            included_history_messages=len(selected_history),
            omitted_history_messages=len(history) - len(selected_history),
        ),
        reply_reserve=reply,
        uncertainty_reserve=uncertainty,
    )


def _validate_budget(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_CONTEXT_BUDGET <= value <= MAX_CONTEXT_BUDGET:
        raise ValueError(
            f"Context budget must be between {MIN_CONTEXT_BUDGET} and {MAX_CONTEXT_BUDGET} tokens."
        )
    return value
