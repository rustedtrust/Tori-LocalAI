"""Provider-neutral local model catalog and model-identity validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import unicodedata

from .providers.base import (
    ModelDescriptor,
    ModelIdentity,
    ModelProvider,
    ProviderAuthenticationError,
    ProviderError,
    validate_model_identifier as _validate_model_identifier,
    validate_model_identity as _validate_model_identity,
    validate_provider_identifier as _validate_provider_identifier,
)


MODEL_STATUSES = frozenset({"available", "configured", "unavailable", "unresolved"})


class ModelCatalogError(RuntimeError):
    """Safe provider-neutral catalog or selection failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """One deterministic catalog view."""

    models: tuple[ModelDescriptor, ...]
    refreshed: bool
    error: str | None = None
    unavailable_providers: tuple[str, ...] = ()
    provider_errors: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderProfileDescriptor:
    """One browser-safe administrator-configured model profile."""

    identifier: str
    display_name: str
    status: str
    reason_code: str | None = None


class ModelCatalogService:
    """Normalize provider inventories without exposing provider response shapes."""

    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        *,
        configured: ModelIdentity,
        configured_models: Mapping[str, Sequence[ModelDescriptor]] | None = None,
        profile_display_names: Mapping[str, str] | None = None,
    ) -> None:
        self._providers = {
            validate_provider_identifier(name): provider
            for name, provider in providers.items()
        }
        self._configured = validate_model_identity(
            configured.provider, configured.model
        )
        self._configured_models = {
            validate_provider_identifier(name): _validated_descriptors(name, records)
            for name, records in (configured_models or {}).items()
        }
        supplied_names = profile_display_names or {}
        if set(supplied_names) - set(self._providers):
            raise ModelCatalogError(
                "A model profile display name has no configured provider.",
                code="invalid_catalog",
            )
        self._profile_display_names = {
            identifier: _validate_display_name(supplied_names.get(identifier, identifier))
            for identifier in self._providers
        }
        self._catalog: ModelCatalog | None = None

    @property
    def configured(self) -> ModelIdentity:
        return self._configured

    @property
    def provider_identifiers(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def catalog(self, *, refresh: bool = False) -> ModelCatalog:
        if self._catalog is None or refresh:
            self._catalog = self._refresh()
        return self._catalog

    def catalog_with(
        self, identity: ModelIdentity, *, refresh: bool = False
    ) -> ModelCatalog:
        """Return a catalog that always represents the current selection."""

        catalog = self.catalog(refresh=refresh)
        if any(
            item.provider == identity.provider and item.model == identity.model
            for item in catalog.models
        ):
            return catalog
        extra = ModelDescriptor(
            provider=identity.provider,
            model=identity.model,
            display_name=identity.model,
            status=self.known_status(identity),
        )
        return replace(
            catalog,
            models=tuple(
                sorted(
                    (*catalog.models, extra),
                    key=lambda item: (
                        item.provider.casefold(),
                        item.display_name.casefold(),
                        item.model,
                    ),
                )
            ),
        )

    def validate_selection(
        self, provider: object, model: object, *, require_available: bool = True
    ) -> ModelIdentity:
        identity = validate_model_identity(provider, model)
        if identity.provider not in self._providers:
            raise ModelCatalogError(
                "The selected model provider is not supported.",
                code="unsupported_provider",
            )
        if require_available:
            catalog = self.catalog()
            match = next(
                (
                    item
                    for item in catalog.models
                    if item.provider == identity.provider
                    and item.model == identity.model
                ),
                None,
            )
            if match is None or match.status not in {"available", "configured"}:
                raise ModelCatalogError(
                    "The selected model is not available locally.",
                    code="model_unavailable",
                )
        return identity

    def descriptor_for(self, identity: ModelIdentity) -> ModelDescriptor | None:
        catalog = self.catalog_with(identity)
        return next(
            (
                item for item in catalog.models
                if item.provider == identity.provider and item.model == identity.model
            ),
            None,
        )

    def known_capacity(self, identity: ModelIdentity) -> int | None:
        descriptor = self.descriptor_for(identity)
        return None if descriptor is None else descriptor.context_window_tokens

    def provider_for(self, identity: ModelIdentity) -> ModelProvider:
        try:
            return self._providers[identity.provider]
        except KeyError as exc:
            raise ModelCatalogError(
                "The selected model provider is not supported.",
                code="unsupported_provider",
            ) from exc

    def profile_descriptors_with(
        self, identity: ModelIdentity
    ) -> tuple[ProviderProfileDescriptor, ...]:
        """Describe configured profiles plus an unavailable durable selection."""

        catalog = self.catalog_with(identity)
        return self._profile_descriptors(identity, catalog)

    def profile_descriptors_snapshot_with(
        self, identity: ModelIdentity
    ) -> tuple[ProviderProfileDescriptor, ...]:
        """Describe only already-observed provider state without discovery."""

        catalog = self._catalog
        if catalog is None:
            catalog = ModelCatalog(
                models=tuple(
                    replace(item, status="configured")
                    for records in self._configured_models.values()
                    for item in records
                ),
                refreshed=False,
            )
        return self._profile_descriptors(identity, catalog)

    def _profile_descriptors(
        self, identity: ModelIdentity, catalog: ModelCatalog
    ) -> tuple[ProviderProfileDescriptor, ...]:
        identifiers = set(self._providers)
        identifiers.add(identity.provider)
        result = []
        for identifier in sorted(identifiers):
            records = [item for item in catalog.models if item.provider == identifier]
            if identifier not in self._providers:
                status = "unavailable"
            elif identifier in catalog.unavailable_providers:
                status = "unavailable"
            elif any(item.status == "available" for item in records):
                status = "available"
            elif any(item.status == "configured" for item in records):
                status = "configured"
            else:
                status = "unresolved"
            result.append(ProviderProfileDescriptor(
                identifier,
                self._profile_display_names.get(identifier, identifier),
                status,
                self.provider_error(identifier),
            ))
        return tuple(result)

    def provider_error(self, identifier: str) -> str | None:
        catalog = self._catalog
        if catalog is None:
            return None
        return dict(catalog.provider_errors).get(identifier)

    def profile_display_name(self, identifier: str) -> str:
        return self._profile_display_names.get(identifier, identifier)

    def known_status(self, identity: ModelIdentity) -> str:
        catalog = self._catalog
        if catalog is None:
            return "unresolved"
        return next(
            (
                item.status
                for item in catalog.models
                if item.provider == identity.provider and item.model == identity.model
            ),
            "unavailable",
        )

    def _refresh(self) -> ModelCatalog:
        normalized: list[ModelDescriptor] = [
            replace(item, status="configured")
            for provider_name in sorted(self._configured_models)
            for item in self._configured_models[provider_name]
        ]
        unavailable_providers: list[str] = []
        provider_errors: list[tuple[str, str]] = []
        for provider_name in sorted(self._providers):
            try:
                records = self._providers[provider_name].list_models()
                normalized.extend(
                    _validated_descriptors(provider_name, records)
                )
            except ProviderAuthenticationError:
                unavailable_providers.append(provider_name)
                provider_errors.append((provider_name, "authentication_required"))
            except Exception:
                unavailable_providers.append(provider_name)
                provider_errors.append((provider_name, "catalog_unavailable"))
        by_identity: dict[tuple[str, str], ModelDescriptor] = {
            (item.provider, item.model): item for item in normalized
        }
        # Successful discovery wins availability while administrator-declared
        # capacity remains authoritative when discovery omits it.
        for item in normalized:
            key = (item.provider, item.model)
            configured = next(
                (
                    known
                    for known in self._configured_models.get(item.provider, ())
                    if known.model == item.model
                ),
                None,
            )
            if item.status == "available" and configured is not None:
                by_identity[key] = replace(
                    item,
                    display_name=configured.display_name,
                    context_window_tokens=(
                        configured.context_window_tokens
                        if configured.context_window_tokens is not None
                        else item.context_window_tokens
                    ),
                )
        configured_key = (self._configured.provider, self._configured.model)
        if configured_key not in by_identity:
            by_identity[configured_key] = ModelDescriptor(
                provider=self._configured.provider,
                model=self._configured.model,
                display_name=self._configured.model,
                status=(
                    "unresolved"
                    if self._configured.provider in unavailable_providers
                    else "unavailable"
                ),
            )
        ordered = tuple(
            sorted(
                by_identity.values(),
                key=lambda item: (
                    item.provider.casefold(),
                    item.display_name.casefold(),
                    item.model,
                ),
            )
        )
        return ModelCatalog(
            models=ordered,
            refreshed=True,
            error=(
                "The local model catalog is unavailable."
                if unavailable_providers
                and len(unavailable_providers) == len(self._providers)
                else None
            ),
            unavailable_providers=tuple(unavailable_providers),
            provider_errors=tuple(provider_errors),
        )


def validate_provider_identifier(value: object) -> str:
    try:
        return _validate_provider_identifier(value)
    except ValueError as exc:
        raise ModelCatalogError(str(exc), code="invalid_model") from exc


def validate_model_identifier(value: object) -> str:
    try:
        return _validate_model_identifier(value)
    except ValueError as exc:
        raise ModelCatalogError(str(exc), code="invalid_model") from exc


def validate_model_identity(provider: object, model: object) -> ModelIdentity:
    try:
        return _validate_model_identity(provider, model)
    except ValueError as exc:
        raise ModelCatalogError(str(exc), code="invalid_model") from exc


def parse_model_selection(
    value: object,
    *,
    default_provider: str,
    known_providers: Sequence[str] = (),
) -> ModelIdentity:
    raw = validate_model_identifier(value)
    prefix, separator, remainder = raw.partition("/")
    if separator and prefix in set(known_providers):
        return validate_model_identity(prefix, remainder)
    return validate_model_identity(default_provider, raw)


def _validated_descriptors(
    provider_name: str, records: Sequence[object]
) -> tuple[ModelDescriptor, ...]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise ModelCatalogError(
            "The model provider returned an invalid catalog.",
            code="invalid_catalog",
        )
    result: dict[str, ModelDescriptor] = {}
    for record in records:
        if not isinstance(record, ModelDescriptor):
            raise ModelCatalogError(
                "The model provider returned an invalid catalog.",
                code="invalid_catalog",
            )
        if validate_provider_identifier(record.provider) != provider_name:
            raise ModelCatalogError(
                "The model provider returned an invalid catalog.",
                code="invalid_catalog",
            )
        model = validate_model_identifier(record.model)
        display = _validate_display_name(record.display_name)
        if record.status not in MODEL_STATUSES:
            raise ModelCatalogError(
                "The model provider returned an invalid catalog.",
                code="invalid_catalog",
            )
        if record.storage_size is not None and (
            isinstance(record.storage_size, bool)
            or not isinstance(record.storage_size, int)
            or record.storage_size < 0
        ):
            raise ModelCatalogError(
                "The model provider returned an invalid catalog.",
                code="invalid_catalog",
            )
        if record.context_window_tokens is not None and (
            isinstance(record.context_window_tokens, bool)
            or not isinstance(record.context_window_tokens, int)
            or not 4096 <= record.context_window_tokens <= 1_048_576
        ):
            raise ModelCatalogError(
                "The model provider returned an invalid catalog.",
                code="invalid_catalog",
            )
        family = _optional_descriptor_text(record.family)
        parameter_size = _optional_descriptor_text(record.parameter_size)
        quantization = _optional_descriptor_text(record.quantization)
        modified_at = _optional_descriptor_text(record.modified_at)
        if not isinstance(record.provider_metadata, tuple):
            raise ModelCatalogError(
                "The model provider returned an invalid catalog.",
                code="invalid_catalog",
            )
        metadata: list[tuple[str, str | int | float | bool | None]] = []
        seen_metadata: set[str] = set()
        for item in record.provider_metadata:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not item[0]
                or len(item[0]) > 64
                or item[0] in seen_metadata
                or any(ord(character) < 33 or ord(character) == 127 for character in item[0])
                or not isinstance(item[1], (str, int, float, bool, type(None)))
                or (isinstance(item[1], str) and _optional_descriptor_text(item[1]) is None)
            ):
                raise ModelCatalogError(
                    "The model provider returned an invalid catalog.",
                    code="invalid_catalog",
                )
            seen_metadata.add(item[0])
            metadata.append(item)
        descriptor = replace(
            record,
            model=model,
            display_name=display,
            family=family,
            parameter_size=parameter_size,
            quantization=quantization,
            modified_at=modified_at,
            provider_metadata=tuple(metadata),
        )
        if model in result:
            raise ModelCatalogError(
                "The model provider returned duplicate model identifiers.",
                code="duplicate_model",
            )
        result[model] = descriptor
    return tuple(result.values())


def _validate_display_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise ModelCatalogError(
            "The model provider returned an invalid catalog.",
            code="invalid_catalog",
        )
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value):
        raise ModelCatalogError(
            "The model provider returned an invalid catalog.",
            code="invalid_catalog",
        )
    return value


def _optional_descriptor_text(value: object) -> str | None:
    if value is None:
        return None
    return _validate_display_name(value)
