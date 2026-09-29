"""Strict, engine-independent translation for the local Voice Input transport."""

from __future__ import annotations

import json
from collections.abc import Mapping

from .speech_recognition import AudioFormat, RecognitionError
from .voice_input import VoiceInputService


BINDING = {"epoch", "lease", "lease_generation", "revision"}
SHAPES = {
    "acquire": set(), "release": BINDING, "heartbeat": BINDING,
    "clear": BINDING, "events": BINDING,
    "begin": BINDING | {"sample_rate", "channels", "encoding"},
    "finalize": BINDING | {"utterance_id", "last_sequence"},
    "cancel": BINDING | {"utterance_id"},
    "audio": BINDING | {"utterance_id", "sequence"},
    "admit": BINDING | {"segment", "event_sequence", "auto_speech"},
}


def decode_document(raw: bytes | str, *, limit: int = 4096) -> dict[str, object]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result
    try:
        if len(raw) > limit:
            raise ValueError("Oversized message")
        result = json.loads(raw, object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(result, dict):
            raise ValueError("Invalid message")
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise RecognitionError("invalid_request") from None


def dispatch(service: VoiceInputService, operation: str,
             document: Mapping[str, object], pcm: bytes | None = None):
    if operation not in SHAPES or set(document) != SHAPES[operation]:
        raise RecognitionError("invalid_request")
    if operation != "acquire":
        if any(not isinstance(document[k], str) or len(document[k]) > 128
               for k in ("epoch", "lease")):
            raise RecognitionError("invalid_request")
        if any(type(document[k]) is not int or not 0 <= document[k] <= 2**63 - 1
               for k in ("lease_generation", "revision")):
            raise RecognitionError("invalid_request")
    if "utterance_id" in document and (
        not isinstance(document["utterance_id"], str) or len(document["utterance_id"]) > 128
    ):
        raise RecognitionError("invalid_request")
    if "auto_speech" in document and not isinstance(document["auto_speech"], bool):
        raise RecognitionError("invalid_request")
    if any(
        type(document[key]) is not int or not 0 <= document[key] <= 2**63 - 1
        for key in ("segment", "event_sequence") if key in document
    ):
        raise RecognitionError("invalid_request")
    if operation == "acquire":
        return service.acquire()
    if operation == "begin":
        return service.begin(document, AudioFormat(document["sample_rate"],
                             document["channels"], document["encoding"]))
    if operation == "audio":
        return service.audio(document, document["sequence"], pcm)
    if operation == "finalize":
        return service.finalize(document, document["last_sequence"])
    if operation == "admit":
        return service.claim_final(document, document["segment"], document["event_sequence"])
    return getattr(service, operation)(document)


def error_status(code: str) -> int:
    if code in {"invalid_request", "malformed_audio"}:
        return 400
    if code in {"controller_busy", "stale_controller", "stale_revision", "stale_segment",
                "invalid_transition", "backpressure", "utterance_limit"}:
        return 409
    return 503


def encode_event(event: dict[str, object]) -> bytes:
    return json.dumps(event, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
