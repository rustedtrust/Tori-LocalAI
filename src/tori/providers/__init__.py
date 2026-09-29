"""Replaceable model-provider implementations."""

from .base import (
    ChatMessage,
    ChatResponse,
    ModelDescriptor,
    ModelIdentity,
    ModelProvider,
    ProviderStream,
    ProviderUsage,
    ModelUnavailableError,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnsupportedResponseError,
    StreamResult,
    validate_model_identifier,
    validate_model_identity,
    validate_provider_identifier,
)
from .ollama import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider

__all__ = [
    "ChatMessage",
    "ChatResponse",
    "ModelProvider",
    "ProviderStream",
    "ProviderUsage",
    "ModelUnavailableError",
    "ModelDescriptor",
    "ModelIdentity",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderAuthenticationError",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderMalformedResponseError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderUnsupportedResponseError",
    "StreamResult",
    "validate_model_identifier",
    "validate_model_identity",
    "validate_provider_identifier",
]
