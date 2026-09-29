from __future__ import annotations

import unittest

from tori.model_catalog import (
    ModelCatalogError,
    ModelCatalogService,
    ModelDescriptor,
    ModelIdentity,
    parse_model_selection,
    validate_model_identity,
)
from tori.providers import (
    ModelProvider,
    ProviderAuthenticationError,
    ProviderConnectionError,
)


class CatalogProvider(ModelProvider):
    def __init__(self, records=(), error: Exception | None = None):  # type: ignore[no-untyped-def]
        self.records = records
        self.error = error
        self.calls = 0

    def chat(self, messages):  # type: ignore[no-untyped-def]
        raise AssertionError("catalog discovery must not generate or mutate models")

    def list_models(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.records


class ModelCatalogTests(unittest.TestCase):
    def test_normalizes_deterministic_objective_optional_metadata(self) -> None:
        provider = CatalogProvider(
            (
                ModelDescriptor("ollama", "z:1", "Zulu"),
                ModelDescriptor(
                    "ollama",
                    "a:1",
                    "Alpha",
                    family="family-a",
                    parameter_size="7B",
                    quantization="Q4_K_M",
                    storage_size=42,
                    modified_at="2026-08-02T00:00:00Z",
                    provider_metadata=(("format", "gguf"),),
                ),
            )
        )
        service = ModelCatalogService(
            {"ollama": provider}, configured=ModelIdentity("ollama", "a:1")
        )

        catalog = service.catalog()

        self.assertEqual([item.model for item in catalog.models], ["a:1", "z:1"])
        self.assertEqual(catalog.models[0].family, "family-a")
        self.assertIsNone(catalog.models[1].family)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(service.catalog(), catalog)
        self.assertEqual(provider.calls, 1)
        service.catalog(refresh=True)
        self.assertEqual(provider.calls, 2)

    def test_duplicate_and_malformed_catalogs_fail_safely(self) -> None:
        cases = (
            ("not-a-sequence", "invalid"),
            ((object(),), "invalid"),
            (
                (
                    ModelDescriptor("ollama", "same", "One"),
                    ModelDescriptor("ollama", "same", "Two"),
                ),
                "duplicate",
            ),
            ((ModelDescriptor("ollama", "bad", "Bad", family="bad\nfamily"),), "metadata"),
            (
                (
                    ModelDescriptor(
                        "ollama",
                        "bad-meta",
                        "Bad metadata",
                        provider_metadata=(("duplicate", "one"), ("duplicate", "two")),
                    ),
                ),
                "metadata",
            ),
        )
        for records, _label in cases:
            with self.subTest(records=records):
                service = ModelCatalogService(
                    {"ollama": CatalogProvider(records)},
                    configured=ModelIdentity("ollama", "configured"),
                )
                catalog = service.catalog()
                self.assertEqual(catalog.error, "The local model catalog is unavailable.")
                self.assertEqual(catalog.models[0].model, "configured")
                self.assertEqual(catalog.models[0].status, "unresolved")

    def test_unavailable_provider_and_absent_configured_model_remain_visible(self) -> None:
        unavailable = ModelCatalogService(
            {
                "ollama": CatalogProvider(
                    error=ProviderConnectionError("private endpoint diagnostic")
                )
            },
            configured=ModelIdentity("ollama", "configured"),
        ).catalog()
        self.assertEqual(unavailable.error, "The local model catalog is unavailable.")
        self.assertNotIn("private", unavailable.error)
        self.assertEqual(unavailable.models[0].status, "unresolved")

        absent = ModelCatalogService(
            {
                "ollama": CatalogProvider(
                    (ModelDescriptor("ollama", "installed", "Installed"),)
                )
            },
            configured=ModelIdentity("ollama", "configured"),
        ).catalog()
        self.assertEqual(
            [(item.model, item.status) for item in absent.models],
            [("configured", "unavailable"), ("installed", "available")],
        )

    def test_one_authenticated_profile_failure_does_not_poison_healthy_profile(self) -> None:
        ollama = CatalogProvider(
            (ModelDescriptor("ollama", "gemma4:12b", "Gemma 4 12B"),)
        )
        lm_studio = CatalogProvider(
            error=ProviderAuthenticationError("private token detail")
        )
        service = ModelCatalogService(
            {"ollama": ollama, "lm_studio": lm_studio},
            configured=ModelIdentity("ollama", "gemma4:12b"),
            profile_display_names={
                "ollama": "Local Ollama",
                "lm_studio": "LM Studio",
            },
        )

        catalog = service.catalog(refresh=True)

        self.assertIsNone(catalog.error)
        self.assertEqual(catalog.unavailable_providers, ("lm_studio",))
        self.assertEqual(
            dict(catalog.provider_errors),
            {"lm_studio": "authentication_required"},
        )
        ollama_model = next(item for item in catalog.models if item.provider == "ollama")
        self.assertEqual(ollama_model.status, "available")
        profiles = {
            item.identifier: item
            for item in service.profile_descriptors_with(
                ModelIdentity("ollama", "gemma4:12b")
            )
        }
        self.assertEqual(profiles["ollama"].status, "available")
        self.assertIsNone(profiles["ollama"].reason_code)
        self.assertEqual(profiles["lm_studio"].status, "unavailable")
        self.assertEqual(profiles["lm_studio"].reason_code, "authentication_required")

    def test_selection_validation_preserves_exact_native_identifiers(self) -> None:
        identity = parse_model_selection(
            "registry.example/Owner/Model:Q4", default_provider="ollama"
        )
        self.assertEqual(identity.model, "registry.example/Owner/Model:Q4")
        self.assertEqual(
            parse_model_selection(
                "ollama/model:tag",
                default_provider="ollama",
                known_providers=("ollama",),
            ),
            ModelIdentity("ollama", "model:tag"),
        )
        for bad in ("", " leading", "line\nbreak", "x" * 256):
            with self.subTest(bad=bad), self.assertRaises(ModelCatalogError):
                validate_model_identity("ollama", bad)

    def test_selection_requires_reported_availability_and_never_mutates(self) -> None:
        provider = CatalogProvider(
            (ModelDescriptor("ollama", "installed", "Installed"),)
        )
        service = ModelCatalogService(
            {"ollama": provider}, configured=ModelIdentity("ollama", "configured")
        )
        self.assertEqual(
            service.validate_selection("ollama", "installed"),
            ModelIdentity("ollama", "installed"),
        )
        with self.assertRaisesRegex(ModelCatalogError, "not available"):
            service.validate_selection("ollama", "configured")
        self.assertEqual(provider.calls, 1)

    def test_configured_known_models_survive_failed_discovery_with_capacity(self) -> None:
        service = ModelCatalogService(
            {"lab": CatalogProvider(error=ProviderConnectionError("private"))},
            configured=ModelIdentity("lab", "shared"),
            configured_models={"lab": (
                ModelDescriptor(
                    "lab", "shared", "Shared", status="configured",
                    context_window_tokens=32768,
                ),
            )},
        )
        catalog = service.catalog()
        self.assertEqual(catalog.models[0].status, "configured")
        identity = service.validate_selection("lab", "shared")
        self.assertEqual(service.known_capacity(identity), 32768)

    def test_overlapping_native_ids_are_namespaced_by_profile(self) -> None:
        left = CatalogProvider((ModelDescriptor("left", "shared", "Shared"),))
        right = CatalogProvider((ModelDescriptor("right", "shared", "Shared"),))
        service = ModelCatalogService(
            {"left": left, "right": right},
            configured=ModelIdentity("left", "shared"),
        )

        profiles = ModelCatalogService(
            {"left": left, "right": right},
            configured=ModelIdentity("left", "shared"),
            profile_display_names={"left": "Desk", "right": "Lab"},
        )
        self.assertEqual(
            [(item.identifier, item.display_name, item.status)
             for item in profiles.profile_descriptors_with(ModelIdentity("left", "shared"))],
            [("left", "Desk", "available"), ("right", "Lab", "available")],
        )
        historical = profiles.profile_descriptors_with(
            ModelIdentity("retired", "shared")
        )
        self.assertEqual(historical[-1].identifier, "right")
        self.assertIn(
            ("retired", "retired", "unavailable"),
            [(item.identifier, item.display_name, item.status) for item in historical],
        )
        self.assertEqual(
            [item.qualified_name for item in service.catalog().models],
            ["left/shared", "right/shared"],
        )
        self.assertIs(service.provider_for(ModelIdentity("right", "shared")), right)


if __name__ == "__main__":
    unittest.main()
