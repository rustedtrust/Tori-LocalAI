"""Provider-neutral model interfaces used by Tori."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Literal, Sequence
import unicodedata


Role = Literal["system", "user", "assistant"]
MAX_PROVIDER_IDENTIFIER_LENGTH = 64
MAX_MODEL_IDENTIFIER_LENGTH = 255


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One provider-neutral conversation message."""

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Validated optional token usage reported by a model provider."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        values = (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0) for value in values):
            raise ValueError("Provider token usage must contain non-negative integers.")
        if all(value is None for value in values):
            raise ValueError("Empty provider token usage must be represented as unknown.")
        if (
            self.total_tokens is not None
            and self.prompt_tokens is not None
            and self.completion_tokens is not None
            and self.total_tokens != self.prompt_tokens + self.completion_tokens
        ):
            raise ValueError("Provider total token usage is inconsistent.")


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """The provider-neutral result of one chat request."""

    content: str
    model: str
    usage: ProviderUsage | None = None


@dataclass(frozen=True, slots=True)
class StreamResult:
    """Terminal metadata available only after a stream completes."""

    model: str
    usage: ProviderUsage | None = None


class ProviderStream(Iterator[str]):
    """Ordered fragments with terminal metadata after successful exhaustion."""

    def __init__(self, iterator: Iterator[str]) -> None:
        self._iterator = iterator
        self._result: StreamResult | None = None

    @property
    def result(self) -> StreamResult | None:
        return self._result

    def set_result(self, result: StreamResult) -> None:
        if self._result is not None:
            raise ProviderResponseError("Provider stream terminal metadata was repeated.")
        self._result = result

    def __iter__(self) -> ProviderStream:
        return self

    def __next__(self) -> str:
        return next(self._iterator)

    def close(self) -> None:
        close = getattr(self._iterator, "close", None)
        if close is not None:
            close()


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """One validated provider/model selection."""

    provider: str
    model: str

    @property
    def qualified_name(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Objective provider-neutral description of one local model."""

    provider: str
    model: str
    display_name: str
    status: str = "available"
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    storage_size: int | None = None
    modified_at: str | None = None
    context_window_tokens: int | None = None
    provider_metadata: tuple[tuple[str, str | int | float | bool | None], ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.provider}/{self.model}"


def validate_provider_identifier(value: object) -> str:
    return _validate_identifier(
        value,
        label="Provider identifier",
        maximum=MAX_PROVIDER_IDENTIFIER_LENGTH,
        lowercase=True,
    )


def validate_model_identifier(value: object) -> str:
    return _validate_identifier(
        value,
        label="Model identifier",
        maximum=MAX_MODEL_IDENTIFIER_LENGTH,
        lowercase=False,
    )


def validate_model_identity(provider: object, model: object) -> ModelIdentity:
    return ModelIdentity(
        validate_provider_identifier(provider),
        validate_model_identifier(model),
    )


def _validate_identifier(
    value: object, *, label: str, maximum: int, lowercase: bool
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{label} is invalid.")
    if value != value.strip() or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in value
    ):
        raise ValueError(f"{label} is invalid.")
    normalized = value.lower() if lowercase else value
    if lowercase and normalized != value:
        raise ValueError(f"{label} is invalid.")
    return normalized


class ProviderError(RuntimeError):
    """Base exception for model-provider failures."""


class ProviderConnectionError(ProviderError):
    """Raised when a model provider cannot be reached."""


class ProviderAuthenticationError(ProviderError):
    """Raised when a provider requires different local credentials."""


class ProviderTimeoutError(ProviderError):
    """Raised when a reachable provider does not respond within its deadline."""


class ProviderResponseError(ProviderError):
    """Raised when a provider returns an unusable response."""


class ProviderMalformedResponseError(ProviderResponseError):
    """Raised when provider response data violates its advertised protocol."""


class ProviderUnsupportedResponseError(ProviderResponseError):
    """Raised when valid provider data requests an unsupported interaction."""


class ModelUnavailableError(ProviderError):
    """Raised when an exact selected model is known to be unavailable."""


class ModelProvider(ABC):
    """Contract that all model backends must implement."""

    @abstractmethod
    def chat(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        """Return one completed response for the supplied messages."""

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Yield ordered text fragments for one streaming chat response."""

        raise ProviderResponseError(
            "The configured model provider does not support streaming."
        )

    def chat_for_model(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        """Return a response from one exact provider-native model.

        Legacy/test providers retain their configured behavior. Providers that
        support manual selection override this method.
        """

        return self.chat(messages)

    def stream_chat_for_model(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> Iterator[str]:
        """Stream a response from one exact provider-native model."""

        return self.stream_chat(messages)

    def chat_with_options(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        context_budget: int | None,
    ) -> ChatResponse:
        """Complete one request with provider-neutral optional context hints."""

        return self.chat_for_model(messages, model=model)

    def stream_chat_with_options(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        context_budget: int | None,
    ) -> Iterator[str]:
        """Stream one request with provider-neutral optional context hints."""

        return self.stream_chat_for_model(messages, model=model)

    def extract_memory_candidates(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        """Return one hidden bounded extraction response when supported."""

        raise ProviderResponseError(
            "The configured model provider does not support memory extraction."
        )

    def assess_memory_relationship(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        """Return one hidden bounded relationship assessment when supported."""

        raise ProviderResponseError(
            "The configured model provider does not support memory relationship assessment."
        )

    def interpret_task_intent(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        """Return one hidden bounded task/reminder interpretation when supported."""

        raise ProviderResponseError(
            "The configured model provider does not support task interpretation."
        )

    def interpret_capability_intent(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        """Return advisory speech-act classification, never tool authority."""
        raise ProviderResponseError(
            "The configured model provider does not support capability interpretation."
        )

    def list_models(self) -> Sequence[object]:
        """Return provider-native inventory records when supported."""

        raise ProviderResponseError(
            "The configured model provider does not support model discovery."
        )
