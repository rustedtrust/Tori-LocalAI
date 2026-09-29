"""Allowlisted construction for Tori text-to-speech provider adapters."""

from .current_qwen import (
    DEFAULT_TTS_ENDPOINT,
    DEFAULT_TTS_PROVIDER,
    CurrentQwenTTSAdapter,
    is_valid_qwen_endpoint,
    validate_qwen_profile_selection,
)
from .kokoro import (
    KOKORO_PROVIDER,
    KokoroTTSAdapter,
    is_valid_kokoro_endpoint,
    validate_kokoro_profile_selection,
)
from .openai_compatible import (
    OPENAI_COMPATIBLE_TTS,
    OpenAICompatibleTTSAdapter,
    is_valid_openai_compatible_endpoint,
)
from ..tts_provider import (
    TextToSpeechProvider,
    TTSConfigurationError,
    TTSSynthesisRequest,
)


# qwen and kokoro remain read-only compatibility adapter identities for
# already-persisted profiles. New normal profiles use the protocol identity.
SUPPORTED_TTS_PROVIDERS = frozenset({OPENAI_COMPATIBLE_TTS, DEFAULT_TTS_PROVIDER, KOKORO_PROVIDER})


def create_tts_provider(
    provider_type: str,
    *,
    endpoint: str,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
) -> TextToSpeechProvider:
    """Construct one explicitly configured adapter without discovery or fallback."""

    if provider_type == OPENAI_COMPATIBLE_TTS:
        return OpenAICompatibleTTSAdapter(
            endpoint=endpoint,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
        )
    if provider_type == DEFAULT_TTS_PROVIDER:
        return CurrentQwenTTSAdapter(
            endpoint=endpoint,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
        )
    if provider_type == KOKORO_PROVIDER:
        return KokoroTTSAdapter(
            endpoint=endpoint,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
        )
    raise ValueError(f"Unsupported TTS provider: {provider_type!r}.")


def is_valid_tts_endpoint(provider_type: str, endpoint: str) -> bool:
    """Validate one endpoint through its explicit allowlisted adapter policy."""
    if provider_type == OPENAI_COMPATIBLE_TTS:
        return is_valid_openai_compatible_endpoint(endpoint)
    if provider_type == DEFAULT_TTS_PROVIDER:
        return is_valid_qwen_endpoint(endpoint)
    if provider_type == KOKORO_PROVIDER:
        return (
            endpoint.rstrip("/") != DEFAULT_TTS_ENDPOINT
            and is_valid_kokoro_endpoint(endpoint)
        )
    return False


def validate_tts_profile_configuration(
    provider_type: str,
    *,
    endpoint: str,
    model: str | None,
    voice: str,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
) -> None:
    """Offline-validate one canonical profile through the bounded adapters."""
    provider = create_tts_provider(
        provider_type,
        endpoint=endpoint,
        connect_timeout_seconds=connect_timeout_seconds,
        read_timeout_seconds=read_timeout_seconds,
    )
    validation = provider.validate_configuration()
    if not validation.valid:
        raise TTSConfigurationError("The TTS profile configuration is invalid.")
    # The request contract owns portable identifier bounds. Each adapter owns
    # only the meaning of its opaque model identifier.
    TTSSynthesisRequest(
        request_id="profile-validation",
        text="validation",
        voice=voice,
        model=model,
    )
    if provider_type == OPENAI_COMPATIBLE_TTS:
        return
    if provider_type == DEFAULT_TTS_PROVIDER:
        validate_qwen_profile_selection(model)
    elif provider_type == KOKORO_PROVIDER:
        validate_kokoro_profile_selection(model)
    else:  # create_tts_provider currently rejects this first; fail closed.
        raise TTSConfigurationError("The TTS provider is unsupported.")


__all__ = [
    "DEFAULT_TTS_ENDPOINT",
    "DEFAULT_TTS_PROVIDER",
    "KOKORO_PROVIDER",
    "OPENAI_COMPATIBLE_TTS",
    "KokoroTTSAdapter",
    "SUPPORTED_TTS_PROVIDERS",
    "CurrentQwenTTSAdapter",
    "OpenAICompatibleTTSAdapter",
    "create_tts_provider",
    "is_valid_tts_endpoint",
    "is_valid_qwen_endpoint",
    "is_valid_openai_compatible_endpoint",
    "validate_tts_profile_configuration",
]
