"""Ollama implementation of Tori's model-provider contract."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)

from .. import __version__
from .base import (
    ChatMessage,
    ChatResponse,
    ModelDescriptor,
    ModelProvider,
    ProviderStream,
    ProviderUsage,
    ProviderConnectionError,
    ProviderResponseError,
    StreamResult,
    validate_model_identifier,
    validate_provider_identifier,
)


MAX_CATALOG_BODY_BYTES = 4 * 1024 * 1024


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_LOCAL_OPENER = build_opener(ProxyHandler({}), _RejectRedirects())


def urlopen(request: Request, *, timeout: float):  # type: ignore[no-untyped-def]
    """Open without environment proxies or redirect following."""

    return _LOCAL_OPENER.open(request, timeout=timeout)


MAX_CATALOG_MODELS = 10_000
_HIDDEN_REASONING_FIELDS = ("thinking", "reasoning", "reasoning_content")
_MEMORY_EXTRACTION_FORMAT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "general", "preference", "project", "goal",
                            "routine", "constraint",
                        ],
                    },
                    "evidence": {"type": "string"},
                    "origin": {"type": "string", "enum": ["direct", "inferred"]},
                },
                "required": ["text", "category", "evidence", "origin"],
            },
        },
    },
    "required": ["candidates"],
}
_MEMORY_RELATIONSHIP_FORMAT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "relationship": {
            "type": "string",
            "enum": [
                "independent", "duplicate", "update", "contradiction", "uncertain",
            ],
        },
        "target": {"type": ["string", "null"]},
    },
    "required": ["relationship", "target"],
}
_TASK_INTENT_FORMAT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "create_task", "create_reminder", "create_task_with_reminder",
                "list_tasks", "list_reminders", "complete_task",
                "complete_reminder", "dismiss_reminder", "delay_reminder", "modify_task",
                "modify_reminder", "cancel_task", "cancel_reminder",
                "discuss", "clarify", "none",
            ],
        },
        "task_text": {"type": ["string", "null"]},
        "reminder_text": {"type": ["string", "null"]},
        "target": {"type": ["string", "null"]},
        "schedule": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "kind": {"type": "string", "enum": ["civil", "elapsed"]},
                "date": {"type": ["string", "null"]},
                "time": {"type": ["string", "null"]},
                "end_date": {"type": ["string", "null"]},
                "end_time": {"type": ["string", "null"]},
                "minutes": {"type": ["integer", "null"], "minimum": 1, "maximum": 525600},
            },
            "required": ["kind", "date", "time", "end_date", "end_time", "minutes"],
        },
        "clarification": {"type": ["string", "null"]},
    },
    "required": [
        "intent", "task_text", "reminder_text", "target", "schedule",
        "clarification",
    ],
}


class OllamaProvider(ModelProvider):
    """Send provider-neutral chat requests to a local Ollama server."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        keep_alive: str,
        profile_id: str = "ollama",
    ) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/api/chat"
        self._catalog_endpoint = f"{base_url.rstrip('/')}/api/tags"
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._keep_alive = keep_alive
        self._profile_id = validate_provider_identifier(profile_id)

    def chat(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        return self.chat_for_model(messages, model=self._model_name)

    def chat_for_model(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete_chat_for_model(messages, model=model)

    def _complete_chat_for_model(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        response_format: object | None = None,
        context_budget: int | None = None,
    ) -> ChatResponse:
        selected_model = validate_model_identifier(model)
        request = self._request(
            messages,
            stream=False,
            model=selected_model,
            response_format=response_format,
            context_budget=context_budget,
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            exc.close()
            raise ProviderResponseError(
                f"Ollama returned HTTP {exc.code}."
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise ProviderConnectionError(
                "Could not connect to the configured Ollama provider."
            ) from exc

        try:
            document = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "Ollama returned a response that was not valid JSON."
            ) from exc

        if not isinstance(document, dict):
            raise ProviderResponseError("Ollama returned an unexpected response shape.")

        if document.get("error"):
            raise ProviderResponseError("Ollama reported a request failure.")

        message = document.get("message")
        if not isinstance(message, dict):
            raise ProviderResponseError("Ollama's response did not contain a message.")

        _validate_unexposed_message_fields(message)
        if message.get("role") not in {None, "assistant"}:
            raise ProviderResponseError(
                "Ollama's response contained an invalid message role."
            )

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError("Ollama returned an empty assistant response.")

        response_model = document.get("model")
        if not isinstance(response_model, str) or not response_model.strip():
            response_model = selected_model
        if response_model != selected_model:
            raise ProviderResponseError(
                "Ollama returned a response from an unexpected model."
            )

        return ChatResponse(
            content=content.strip(),
            model=response_model,
            usage=_usage_from_document(document),
        )

    def chat_with_options(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        context_budget: int | None,
    ) -> ChatResponse:
        return self._complete_chat_for_model(
            messages, model=model, context_budget=context_budget
        )

    def extract_memory_candidates(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        """Run one hidden extraction request with the selected local model."""

        return self._complete_chat_for_model(
            messages,
            model=model,
            response_format=_MEMORY_EXTRACTION_FORMAT,
        )

    def assess_memory_relationship(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        """Run one hidden bounded relationship request with the selected model."""

        return self._complete_chat_for_model(
            messages,
            model=model,
            response_format=_MEMORY_RELATIONSHIP_FORMAT,
        )

    def interpret_task_intent(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete_chat_for_model(
            messages,
            model=model,
            response_format=_TASK_INTENT_FORMAT,
        )

    def interpret_capability_intent(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete_chat_for_model(
            messages, model=model, response_format={
                "type": "object", "additionalProperties": False,
                "required": ["kind", "capability"],
                "properties": {
                    "kind": {"type": "string", "enum": ["conversation", "discussion", "information", "action", "clarification"]},
                    "capability": {"type": ["string", "null"]},
                },
            },
        )

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Yield validated fragments from Ollama's streaming chat response."""

        return self.stream_chat_for_model(messages, model=self._model_name)

    def stream_chat_for_model(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> Iterator[str]:
        """Yield validated fragments from one exact Ollama model."""

        return self.stream_chat_with_options(
            messages, model=model, context_budget=None
        )

    def stream_chat_with_options(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        context_budget: int | None,
    ) -> ProviderStream:
        selected_model = validate_model_identifier(model)
        request = self._request(
            messages,
            stream=True,
            model=selected_model,
            context_budget=context_budget,
        )
        stream: ProviderStream

        def records() -> Iterator[str]:
            nonlocal response
            completed = False
            terminal_usage: ProviderUsage | None = None
            try:
                while True:
                    try:
                        raw_line = response.readline()
                    except (TimeoutError, socket.timeout, OSError) as exc:
                        raise ProviderConnectionError(
                            "The connection to Ollama failed while streaming."
                        ) from exc
                    if not raw_line:
                        break
                    try:
                        decoded_line = raw_line.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise ProviderResponseError(
                            "Ollama returned streaming data that was not valid UTF-8."
                        ) from exc
                    if not decoded_line.strip():
                        continue
                    try:
                        document = json.loads(decoded_line)
                    except json.JSONDecodeError as exc:
                        raise ProviderResponseError(
                            "Ollama returned malformed streaming JSON."
                        ) from exc
                    fragment, done, hidden_progress = _stream_fragment(
                        document, expected_model=selected_model
                    )
                    if done:
                        terminal_usage = _usage_from_document(document)
                    if fragment or hidden_progress:
                        yield fragment
                    if done:
                        completed = True
                        break
                if not completed:
                    raise ProviderResponseError(
                        "Ollama's streaming response ended before completion."
                    )
                stream.set_result(StreamResult(selected_model, terminal_usage))
            finally:
                response.close()

        try:
            response = urlopen(request, timeout=self._timeout_seconds)
        except HTTPError as exc:
            exc.close()
            raise ProviderResponseError(
                f"Ollama returned HTTP {exc.code}."
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise ProviderConnectionError(
                "Could not connect to the configured Ollama provider."
            ) from exc

        stream = ProviderStream(records())
        return stream

    def list_models(self) -> Sequence[ModelDescriptor]:
        """Return normalized objective metadata from Ollama's installed models."""

        request = Request(
            self._catalog_endpoint,
            headers={"User-Agent": f"Tori/{__version__}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read(MAX_CATALOG_BODY_BYTES + 1)
                if len(raw_body) > MAX_CATALOG_BODY_BYTES:
                    raise ProviderResponseError(
                        "Ollama returned an oversized local model catalog."
                    )
                response_body = raw_body.decode("utf-8")
        except HTTPError as exc:
            raise ProviderResponseError(
                "Ollama could not provide the local model catalog."
            ) from exc
        except UnicodeDecodeError as exc:
            raise ProviderResponseError(
                "Ollama returned an invalid local model catalog."
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise ProviderConnectionError(
                "The local Ollama model catalog is unavailable."
            ) from exc
        try:
            document = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderResponseError(
                "Ollama returned an invalid local model catalog."
            ) from exc
        return _normalize_catalog(document, provider=self._profile_id)

    def _request(
        self,
        messages: Sequence[ChatMessage],
        *,
        stream: bool,
        model: str,
        response_format: object | None = None,
        context_budget: int | None = None,
    ) -> Request:
        payload = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": stream,
            "keep_alive": self._keep_alive,
        }
        if response_format is not None:
            payload["format"] = response_format
        if context_budget is not None:
            payload["options"] = {"num_ctx": context_budget}
        return Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"Tori/{__version__}",
            },
            method="POST",
        )


def _normalize_catalog(
    document: object, *, provider: str = "ollama"
) -> tuple[ModelDescriptor, ...]:
    if not isinstance(document, dict) or "models" not in document:
        raise ProviderResponseError("Ollama returned an invalid local model catalog.")
    models = document["models"]
    if not isinstance(models, list) or len(models) > MAX_CATALOG_MODELS:
        raise ProviderResponseError("Ollama returned an invalid local model catalog.")
    result: list[ModelDescriptor] = []
    seen: set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            raise ProviderResponseError("Ollama returned an invalid local model catalog.")
        native = item.get("name", item.get("model"))
        alternate = item.get("model")
        if (
            "name" in item
            and alternate is not None
            and alternate != native
        ):
            raise ProviderResponseError("Ollama returned an invalid local model catalog.")
        if not isinstance(native, str):
            raise ProviderResponseError("Ollama returned an invalid local model catalog.")
        try:
            native = validate_model_identifier(native)
        except Exception as exc:
            raise ProviderResponseError(
                "Ollama returned an invalid local model catalog."
            ) from exc
        if native in seen:
            raise ProviderResponseError(
                "Ollama returned duplicate local model identifiers."
            )
        seen.add(native)
        details = item.get("details")
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise ProviderResponseError("Ollama returned an invalid local model catalog.")
        family = _optional_catalog_text(details.get("family"))
        parameter_size = _optional_catalog_text(details.get("parameter_size"))
        quantization = _optional_catalog_text(details.get("quantization_level"))
        modified_at = _optional_catalog_text(item.get("modified_at"))
        size = item.get("size")
        if size is not None and (
            isinstance(size, bool) or not isinstance(size, int) or size < 0
        ):
            raise ProviderResponseError("Ollama returned an invalid local model catalog.")
        objective: list[tuple[str, str | int | float | bool | None]] = []
        for key, value in (
            ("digest", item.get("digest")),
            ("format", details.get("format")),
        ):
            normalized = _optional_catalog_text(value)
            if normalized is not None:
                objective.append((key, normalized))
        result.append(
            ModelDescriptor(
                provider=provider,
                model=native,
                display_name=native,
                family=family,
                parameter_size=parameter_size,
                quantization=quantization,
                storage_size=size,
                modified_at=modified_at,
                provider_metadata=tuple(objective),
            )
        )
    return tuple(result)


def _optional_catalog_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 255 or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ProviderResponseError("Ollama returned an invalid local model catalog.")
    return value


def _stream_fragment(
    document: object, *, expected_model: str | None = None
) -> tuple[str, bool, bool]:
    if not isinstance(document, dict):
        raise ProviderResponseError(
            "Ollama returned an unexpected streaming response shape."
        )
    if "error" in document:
        error = document["error"]
        if not isinstance(error, str) or not error.strip():
            raise ProviderResponseError(
                "Ollama returned an invalid streaming error response."
            )
        raise ProviderResponseError("Ollama reported a request failure.")
    response_model = document.get("model")
    if response_model is not None and response_model != expected_model:
        raise ProviderResponseError(
            "Ollama returned streaming data from an unexpected model."
        )
    done = document.get("done")
    if not isinstance(done, bool):
        raise ProviderResponseError(
            "Ollama's streaming response did not contain a valid done state."
        )
    message = document.get("message")
    if not isinstance(message, dict):
        raise ProviderResponseError(
            "Ollama's streaming response did not contain a message."
        )
    if message.get("role") != "assistant":
        raise ProviderResponseError(
            "Ollama's streaming response contained an invalid message role."
        )
    hidden_progress = _validate_unexposed_message_fields(message)
    content = message.get("content")
    if not isinstance(content, str):
        raise ProviderResponseError(
            "Ollama's streaming response contained invalid message content."
        )
    return content, done, hidden_progress


def _validate_unexposed_message_fields(message: dict[str, object]) -> bool:
    """Validate and withhold provider-only reasoning and tool channels."""

    hidden_progress = False
    for field in _HIDDEN_REASONING_FIELDS:
        value = message.get(field)
        if value is not None and not isinstance(value, str):
            raise ProviderResponseError(
                "Ollama returned an invalid hidden reasoning field."
            )
        if isinstance(value, str) and value:
            hidden_progress = True
    if "tool_calls" in message:
        tool_calls = message["tool_calls"]
        if not isinstance(tool_calls, list):
            raise ProviderResponseError(
                "Ollama returned an invalid tool-call channel."
            )
        if tool_calls:
            raise ProviderResponseError(
                "Ollama returned an unsupported tool-call response."
            )
    return hidden_progress


def _usage_from_document(document: dict[str, object]) -> ProviderUsage | None:
    prompt = document.get("prompt_eval_count")
    completion = document.get("eval_count")
    if prompt is None and completion is None:
        return None
    if any(
        value is not None
        and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
        for value in (prompt, completion)
    ):
        raise ProviderResponseError("Ollama returned invalid token usage metadata.")
    total = (
        prompt + completion
        if isinstance(prompt, int) and isinstance(completion, int)
        else None
    )
    return ProviderUsage(prompt, completion, total)
