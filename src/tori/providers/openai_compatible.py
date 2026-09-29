"""Focused LOCAL/LAN OpenAI-compatible Chat Completions adapter."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)
from urllib.parse import urlsplit, urlunsplit

from .. import __version__
from .base import (
    ChatMessage,
    ChatResponse,
    ModelDescriptor,
    ModelProvider,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderResponseError,
    ProviderStream,
    ProviderTimeoutError,
    ProviderUnsupportedResponseError,
    ProviderUsage,
    StreamResult,
    validate_model_identifier,
    validate_provider_identifier,
)


MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_MODELS = 10_000
MAX_STREAM_LINE_BYTES = 1024 * 1024
MAX_STREAM_RECORDS = 100_000
DUMMY_BEARER_TOKEN = "tori-local-compatibility"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def local_opener() -> OpenerDirector:
    """Return a transport that ignores environment proxies and rejects redirects."""

    return build_opener(ProxyHandler({}), _RejectRedirects())


class OpenAICompatibleProvider(ModelProvider):
    """Use only the bounded OpenAI-compatible Chat Completions surface."""

    def __init__(
        self,
        *,
        profile_id: str,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        authentication: str = "none",
        credential_environment: str | None = None,
        bearer_token: str | None = None,
        structured_output: str = "json_object",
        opener: OpenerDirector | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._profile_id = validate_provider_identifier(profile_id)
        root = _canonical_api_root(base_url)
        self._chat_endpoint = root + "/chat/completions"
        self._models_endpoint = root + "/models"
        self._model_name = validate_model_identifier(model_name)
        self._timeout_seconds = timeout_seconds
        if authentication not in {"none", "dummy_bearer", "environment_bearer"}:
            raise ValueError("Unsupported OpenAI-compatible authentication mode.")
        if bearer_token is not None and not _valid_bearer_token(bearer_token):
            raise ValueError("The OpenAI-compatible bearer token is invalid.")
        if authentication == "environment_bearer":
            if credential_environment != "LM_API_TOKEN":
                raise ValueError(
                    "OpenAI-compatible environment bearer authentication requires LM_API_TOKEN."
                )
            source = os.environ if environ is None else environ
            token = source.get(credential_environment)
            environment_token = token if _valid_bearer_token(token) else None
        else:
            if credential_environment is not None:
                raise ValueError(
                    "OpenAI-compatible credential environment is unsupported."
                )
            environment_token = None
        self._bearer_token = bearer_token or environment_token
        if structured_output not in {"json_object", "prompt_only"}:
            raise ValueError("Unsupported structured-output compatibility mode.")
        self._authentication = authentication
        self._structured_output = structured_output
        self._opener = opener or local_opener()

    def chat(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        return self.chat_for_model(messages, model=self._model_name)

    def chat_for_model(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete(messages, model=model)

    def chat_with_options(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        context_budget: int | None,
    ) -> ChatResponse:
        # Standard Chat Completions cannot change the backend context window.
        return self._complete(messages, model=model)

    def extract_memory_candidates(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete(messages, model=model, structured=True)

    def assess_memory_relationship(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete(messages, model=model, structured=True)

    def interpret_task_intent(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete(messages, model=model, structured=True)

    def interpret_capability_intent(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> ChatResponse:
        return self._complete(messages, model=model, structured=True)

    def _complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        structured: bool = False,
    ) -> ChatResponse:
        selected = validate_model_identifier(model)
        payload = self._payload(messages, model=selected, stream=False)
        if structured and self._structured_output == "json_object":
            payload["response_format"] = {"type": "json_object"}
        request = self._request(self._chat_endpoint, payload)
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                document = _read_json(response, MAX_RESPONSE_BYTES)
        except HTTPError as exc:
            raise _http_error(exc) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeoutError(
                "The local OpenAI-compatible provider timed out."
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError(
                    "The local OpenAI-compatible provider timed out."
                ) from exc
            raise ProviderConnectionError(
                "The local OpenAI-compatible provider is unreachable."
            ) from exc
        except OSError as exc:
            raise ProviderConnectionError(
                "The local OpenAI-compatible provider is unreachable."
            ) from exc
        content, response_model = _complete_content(document, selected)
        return ChatResponse(content, response_model, _usage(document))

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        return self.stream_chat_for_model(messages, model=self._model_name)

    def stream_chat_for_model(
        self, messages: Sequence[ChatMessage], *, model: str
    ) -> Iterator[str]:
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
        selected = validate_model_identifier(model)
        payload = self._payload(messages, model=selected, stream=True)
        payload["stream_options"] = {"include_usage": True}
        request = self._request(self._chat_endpoint, payload)
        try:
            response = self._opener.open(request, timeout=self._timeout_seconds)
        except HTTPError as exc:
            raise _http_error(exc) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeoutError(
                "The local OpenAI-compatible provider timed out."
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError(
                    "The local OpenAI-compatible provider timed out."
                ) from exc
            raise ProviderConnectionError(
                "The local OpenAI-compatible provider is unreachable."
            ) from exc
        except OSError as exc:
            raise ProviderConnectionError(
                "The local OpenAI-compatible provider is unreachable."
            ) from exc

        stream: ProviderStream

        def records() -> Iterator[str]:
            completed = False
            terminal_usage: ProviderUsage | None = None
            count = 0
            total_bytes = 0
            saw_stop = False
            saw_visible_content = False
            try:
                while True:
                    try:
                        raw = response.readline(MAX_STREAM_LINE_BYTES + 1)
                    except (TimeoutError, socket.timeout) as exc:
                        raise ProviderTimeoutError(
                            "The local OpenAI-compatible stream timed out."
                        ) from exc
                    except OSError as exc:
                        raise ProviderConnectionError(
                            "The local OpenAI-compatible stream failed."
                        ) from exc
                    if not raw:
                        break
                    if len(raw) > MAX_STREAM_LINE_BYTES:
                        raise ProviderMalformedResponseError(
                            "The local OpenAI-compatible stream was oversized."
                        )
                    total_bytes += len(raw)
                    if total_bytes > MAX_RESPONSE_BYTES:
                        raise ProviderMalformedResponseError(
                            "The local OpenAI-compatible stream was oversized."
                        )
                    if not raw.strip():
                        continue
                    count += 1
                    if count > MAX_STREAM_RECORDS:
                        raise ProviderMalformedResponseError(
                            "The local OpenAI-compatible stream contained too many records."
                        )
                    try:
                        line = raw.decode("utf-8").strip()
                    except UnicodeDecodeError as exc:
                        raise ProviderMalformedResponseError(
                            "The local OpenAI-compatible stream was not valid UTF-8."
                        ) from exc
                    if not line.startswith("data:"):
                        raise ProviderMalformedResponseError(
                            "The local OpenAI-compatible stream was malformed."
                        )
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if not saw_stop:
                            raise ProviderMalformedResponseError(
                                "The local OpenAI-compatible stream ended before normal completion."
                            )
                        completed = True
                        break
                    try:
                        document = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderMalformedResponseError(
                            "The local OpenAI-compatible stream contained malformed JSON."
                        ) from exc
                    fragment, usage, stopped = _stream_content(document, selected)
                    saw_stop = saw_stop or stopped
                    if usage is not None:
                        terminal_usage = usage
                    if fragment:
                        saw_visible_content = saw_visible_content or bool(fragment.strip())
                        yield fragment
                if not completed:
                    raise ProviderMalformedResponseError(
                        "The local OpenAI-compatible stream ended before completion."
                    )
                if not saw_visible_content:
                    raise ProviderMalformedResponseError(
                        "The local OpenAI-compatible provider returned an empty response."
                    )
                stream.set_result(StreamResult(selected, terminal_usage))
            finally:
                response.close()

        stream = ProviderStream(records())
        return stream

    def list_models(self) -> Sequence[ModelDescriptor]:
        request = self._request(self._models_endpoint, None, method="GET")
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                document = _read_json(response, MAX_CATALOG_BYTES)
        except HTTPError as exc:
            raise _http_error(exc, catalog=True) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeoutError(
                "The local OpenAI-compatible model catalog timed out."
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError(
                    "The local OpenAI-compatible model catalog timed out."
                ) from exc
            raise ProviderConnectionError(
                "The local OpenAI-compatible model catalog is unavailable."
            ) from exc
        except OSError as exc:
            raise ProviderConnectionError(
                "The local OpenAI-compatible model catalog is unavailable."
            ) from exc
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            raise ProviderMalformedResponseError(
                "The local OpenAI-compatible model catalog was invalid."
            )
        records = document["data"]
        if len(records) > MAX_MODELS:
            raise ProviderMalformedResponseError(
                "The local OpenAI-compatible model catalog was oversized."
            )
        result: list[ModelDescriptor] = []
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                raise ProviderMalformedResponseError(
                    "The local OpenAI-compatible model catalog was invalid."
                )
            try:
                model = validate_model_identifier(record["id"])
            except ValueError as exc:
                raise ProviderMalformedResponseError(
                    "The local OpenAI-compatible model catalog was invalid."
                ) from exc
            if model in seen:
                raise ProviderMalformedResponseError(
                    "The local OpenAI-compatible model catalog contained duplicates."
                )
            seen.add(model)
            result.append(ModelDescriptor(self._profile_id, model, model))
        return tuple(result)

    def _payload(
        self, messages: Sequence[ChatMessage], *, model: str, stream: bool
    ) -> dict[str, object]:
        return {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": stream,
        }

    def _request(
        self,
        endpoint: str,
        payload: dict[str, object] | None,
        *,
        method: str = "POST",
    ) -> Request:
        headers = {
            "Accept": "application/json" if payload is None else "text/event-stream, application/json",
            "User-Agent": f"Tori/{__version__}",
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if self._bearer_token is not None:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        elif self._authentication == "dummy_bearer":
            headers["Authorization"] = f"Bearer {DUMMY_BEARER_TOKEN}"
        elif self._authentication == "environment_bearer":
            if self._bearer_token is None:
                raise ProviderAuthenticationError(
                    "The local OpenAI-compatible provider requires its configured local API token."
                )
        return Request(endpoint, data=data, headers=headers, method=method)


def _valid_bearer_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 4096
        and "\r" not in value
        and "\n" not in value
        and "\x00" not in value
    )


def _http_error(error: HTTPError, *, catalog: bool = False) -> ProviderError:
    if error.code in {401, 403}:
        return ProviderAuthenticationError(
            "The local OpenAI-compatible provider requires valid authentication."
        )
    if catalog:
        return ProviderResponseError(
            "The local OpenAI-compatible model catalog is unavailable."
        )
    return ProviderResponseError(
        f"The local OpenAI-compatible provider returned HTTP {error.code}."
    )


def _canonical_api_root(value: object) -> str:
    """Require the adapter's one canonical API-root form: ``.../v1``.

    Administrator configuration may accept an origin and normalize it before
    provider construction.  The adapter never guesses whether another path is
    an API root, so relative resources can only become ``/v1/models`` and
    ``/v1/chat/completions``.
    """

    if not isinstance(value, str) or not value or value != value.rstrip("/"):
        raise ValueError("OpenAI-compatible base URL must be a canonical /v1 API root.")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "OpenAI-compatible base URL must be a canonical /v1 API root."
        ) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or port is None
        or parsed.path != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OpenAI-compatible base URL must be a canonical /v1 API root.")
    return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))


def _read_json(response: object, maximum: int) -> object:
    body = response.read(maximum + 1)  # type: ignore[attr-defined]
    if len(body) > maximum:
        raise ProviderResponseError("The local model provider response was oversized.")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderMalformedResponseError(
            "The local model provider returned invalid JSON."
        ) from exc


def _complete_content(document: object, selected: str) -> tuple[str, str]:
    if not isinstance(document, dict) or document.get("model") != selected:
        raise ProviderMalformedResponseError(
            "The local OpenAI-compatible provider returned an unexpected model."
        )
    choices = document.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderMalformedResponseError(
            "The local OpenAI-compatible provider returned an invalid response."
        )
    message = choices[0].get("message")
    if not isinstance(message, dict) or message.get("role") not in {None, "assistant"}:
        raise ProviderMalformedResponseError(
            "The local OpenAI-compatible provider returned an invalid response."
        )
    _reject_unsupported(message)
    if choices[0].get("finish_reason") != "stop":
        raise ProviderResponseError(
            "The local OpenAI-compatible provider did not complete normally."
        )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderMalformedResponseError(
            "The local OpenAI-compatible provider returned an empty response."
        )
    return content.strip(), selected


def _stream_content(
    document: object, selected: str
) -> tuple[str, ProviderUsage | None, bool]:
    if not isinstance(document, dict):
        raise ProviderMalformedResponseError("The local OpenAI-compatible stream was invalid.")
    response_model = document.get("model")
    if response_model is not None and response_model != selected:
        raise ProviderMalformedResponseError(
            "The local OpenAI-compatible stream returned an unexpected model."
        )
    usage = _usage(document)
    choices = document.get("choices")
    if choices == [] and usage is not None:
        return "", usage, False
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderMalformedResponseError("The local OpenAI-compatible stream was invalid.")
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        raise ProviderMalformedResponseError("The local OpenAI-compatible stream was invalid.")
    _reject_unsupported(delta)
    finish_reason = choices[0].get("finish_reason")
    if finish_reason not in (None, "stop"):
        raise ProviderResponseError(
            "The local OpenAI-compatible stream did not complete normally."
        )
    content = delta.get("content", "")
    if not isinstance(content, str):
        raise ProviderMalformedResponseError("The local OpenAI-compatible stream was invalid.")
    return content, usage, finish_reason == "stop"


def _reject_unsupported(message: dict[str, object]) -> None:
    for field in ("tool_calls", "function_call"):
        if message.get(field) not in (None, [], {}):
            raise ProviderUnsupportedResponseError(
                "The local OpenAI-compatible provider returned unsupported tool data."
            )
    for field in ("reasoning", "reasoning_content", "thinking"):
        reasoning = message.get(field)
        if reasoning is not None and not isinstance(reasoning, str):
            raise ProviderMalformedResponseError(
                "The local OpenAI-compatible provider returned invalid reasoning metadata."
            )
    if isinstance(message.get("content"), list):
        raise ProviderUnsupportedResponseError(
            "The local OpenAI-compatible provider returned unsupported multimodal data."
        )


def _usage(document: dict[str, object]) -> ProviderUsage | None:
    raw = document.get("usage")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProviderMalformedResponseError("The local model provider returned invalid usage metadata.")
    values = (
        raw.get("prompt_tokens"),
        raw.get("completion_tokens"),
        raw.get("total_tokens"),
    )
    if all(value is None for value in values):
        return None
    try:
        return ProviderUsage(*values)
    except ValueError as exc:
        raise ProviderMalformedResponseError(
            "The local model provider returned invalid usage metadata."
        ) from exc
