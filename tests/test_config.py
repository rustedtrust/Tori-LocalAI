from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.config import ConfigError, load_settings


class ConfigTests(unittest.TestCase):
    def test_mcp_time_configuration_is_exact_and_closed(self) -> None:
        document = """
[mcp.time]
enabled = true
executable = "/opt/tori/mcp-server-time"
executable_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
package_version = "2026.8.18"
server_info_version = "1.30.0"
approved_schema_digest = "sha256:f3a11b4c49a2326a4d93fd4da437be913276dee8f824db07ca0eec24a6ed1205"
bubblewrap_executable = "/usr/bin/bwrap"
bubblewrap_digest = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
timeout_seconds = 4
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            path.write_text(document, encoding="utf-8")
            settings = load_settings(path, environ={})
            self.assertTrue(settings.mcp_time.enabled)
            self.assertEqual(settings.mcp_time.package_version, "2026.8.18")
            self.assertEqual(settings.mcp_time.timeout_seconds, 4)
            path.write_text(document + "unknown = true\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "unsupported fields"):
                load_settings(path, environ={})

    def test_disabled_mcp_time_has_no_retained_authority(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            path.write_text("[mcp.time]\nenabled = false\n", encoding="utf-8")
            self.assertFalse(load_settings(path, environ={}).mcp_time.enabled)
            path.write_text(
                '[mcp.time]\nenabled = false\nexecutable = "/tmp/server"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "must not retain authority"):
                load_settings(path, environ={})

    def test_loopback_lm_studio_profile_uses_only_the_token_environment_reference(self) -> None:
        profile = """
[model]
default_profile = "ollama"
default_model = "gemma4:12b"

[[model.profiles]]
id = "ollama"
display_name = "Local Ollama"
type = "ollama"
base_url = "http://127.0.0.1:11434"
keep_alive = "5m"

[[model.profiles]]
id = "lm_studio"
display_name = "LM Studio"
type = "openai_compatible"
base_url = "http://127.0.0.1:1234/v1"
authentication = "environment_bearer"
credential_environment = "LM_API_TOKEN"
structured_output = "prompt_only"
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            path.write_text(profile, encoding="utf-8")
            settings = load_settings(path, environ={})
            lm_studio = settings.profile("lm_studio")
            self.assertEqual(lm_studio.base_url, "http://127.0.0.1:1234/v1")
            self.assertEqual(lm_studio.authentication, "environment_bearer")
            self.assertEqual(lm_studio.credential_environment, "LM_API_TOKEN")
            self.assertEqual(lm_studio.structured_output, "prompt_only")

            invalid_documents = (
                profile.replace(
                    'credential_environment = "LM_API_TOKEN"',
                    'credential_environment = "OTHER_TOKEN"',
                ),
                profile.replace(
                    'base_url = "http://127.0.0.1:1234/v1"',
                    'base_url = "http://192.168.1.20:1234/v1"',
                ),
            )
            for document in invalid_documents:
                with self.subTest(document=document):
                    path.write_text(document, encoding="utf-8")
                    with self.assertRaisesRegex(ConfigError, "environment_bearer"):
                        load_settings(path, environ={})

    def test_planning_configuration_is_optional_bounded_and_secret_free(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            path.write_text("""
[planning]
enabled = true
backend = "radicale"
url = "http://127.0.0.1:5232/caldav"
username = "tori"
credential_environment = "TORI_CALDAV_PASSWORD"
default_task_list = "tasks"
default_calendar = "calendar"
timeout_seconds = 3
""", encoding="utf-8")
            settings = load_settings(path, environ={})
        self.assertTrue(settings.planning.enabled)
        self.assertEqual(settings.planning.backend, "radicale")
        self.assertEqual(
            settings.planning.credential_environment, "TORI_CALDAV_PASSWORD"
        )
        self.assertFalse(hasattr(settings.planning, "password"))

        for line in (
            'url = "http://localhost:5232"',
            'url = "http://192.168.1.2:5232"',
            'backend = "custom"',
            'credential_environment = "PASSWORD"',
        ):
            with self.subTest(line=line), TemporaryDirectory() as directory:
                path = Path(directory) / "tori.toml"
                path.write_text(
                    "[planning]\nenabled = true\n" + line, encoding="utf-8"
                )
                with self.assertRaises(ConfigError):
                    load_settings(path, environ={})
    def test_coding_work_configuration_is_explicit_and_separate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tori.toml"
            path.write_text(f"""
[coding_work]
runtime_root = "{root}/runtime/coding_work"
opencode_executable = "/opt/opencode"
opencode_version = "1.18.31"
bubblewrap_executable = "/usr/bin/bwrap"
provider_upstream = "http://127.0.0.1:11434/v1"
model = "qwen3.8:latest"
""", encoding="utf-8")
            settings = load_settings(path, environ={})
            self.assertIsNotNone(settings.coding_work)
            assert settings.coding_work is not None
            self.assertEqual(settings.coding_work.model, "qwen3.8:latest")
            self.assertNotEqual(settings.coding_work.model, settings.model_name)
            path.write_text(path.read_text(encoding="utf-8").replace(
                'model = "qwen3.8:latest"', 'model = "qwen3.8:latest"\nfallback = "other"'
            ), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "unsupported fields"):
                load_settings(path, environ={})

    def test_research_configuration_is_explicit_local_and_separate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            worker = root / "GPT-Researcher-Tori-PoC"
            path = root / "tori.toml"
            path.write_text(f"""
[research]
runtime_root = "{root}/runtime/research"
worker_root = "{worker}"
python_executable = "{worker}/.venv/bin/python"
worker_entrypoint = "{worker}/supervisor.py"
bubblewrap_executable = "/usr/bin/bwrap"
ollama_url = "http://127.0.0.1:11434"
model = "qwen3.8:latest"
embedding_model = "nomic-embed-text:latest"
""", encoding="utf-8")
            settings = load_settings(path, environ={})
            self.assertIsNotNone(settings.research)
            assert settings.research is not None
            self.assertEqual(settings.research.model, "qwen3.8:latest")
            self.assertEqual(settings.research.ollama_url, "http://127.0.0.1:11434")
            self.assertEqual(settings.research.searxng_url, "http://127.0.0.1:8080")
            self.assertEqual(
                settings.research.search_providers,
                ("github", "huggingface", "searxng"),
            )
            path.write_text(path.read_text().replace(
                'ollama_url = "http://127.0.0.1:11434"',
                'ollama_url = "https://ollama.example.com"',
            ))
            with self.assertRaisesRegex(ConfigError, "loopback"):
                load_settings(path, environ={})

    def test_loads_toml_and_environment_override(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "tori.toml"
            path.write_text(
                """
[model]
provider = "ollama"
name = "model-from-file"
base_url = "http://127.0.0.1:11434/"
timeout_seconds = 42
keep_alive = "1m"

[logging]
level = "warning"
""".strip(),
                encoding="utf-8",
            )

            settings = load_settings(
                path,
                environ={"TORI_MODEL_NAME": "model-from-environment"},
            )

        self.assertEqual(settings.provider, "ollama")
        self.assertEqual(settings.model_name, "model-from-environment")
        self.assertEqual(settings.base_url, "http://127.0.0.1:11434")
        self.assertEqual(settings.timeout_seconds, 42.0)
        self.assertEqual(settings.keep_alive, "1m")
        self.assertEqual(settings.log_level, "WARNING")
        self.assertTrue(settings.tts_enabled)
        self.assertEqual(settings.tts_provider, "qwen")
        self.assertEqual(settings.tts_endpoint, "http://127.0.0.1:8000")
        self.assertEqual(settings.tts_voice, "tori")

    def test_rejects_invalid_base_url(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "tori.toml"
            path.write_text(
                '[model]\nbase_url = "not-a-url"\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "LOCAL/LAN"):
                load_settings(path, environ={})

    def test_rejects_unapproved_endpoint_forms(self) -> None:
        for value in (
            "http://localhost:11434",
            "http://user@127.0.0.1:11434",
            "http://127.0.0.1:11434/private",
            "http://100.64.0.1:11434",
            "http://169.254.1.1:11434",
            "http://8.8.8.8:11434",
            "http://[::1]:11434",
            "http://10.0.0.1:11434?x=1",
        ):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                load_settings(
                    Path("absent.toml"),
                    environ={"TORI_MODEL_BASE_URL": value},
                )

    def test_accepts_exact_approved_numeric_networks_and_https(self) -> None:
        for value in (
            "http://127.0.0.2:11434", "https://10.0.0.8:443",
            "http://172.16.1.2:8080", "http://172.31.255.254:8080",
            "http://192.168.4.2:11434",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    load_settings(Path("absent.toml"), environ={"TORI_MODEL_BASE_URL": value}).base_url,
                    value,
                )

    def test_explicit_profiles_and_legacy_mixing(self) -> None:
        document = """
[model]
default_profile = "lab"
default_model = "shared"
[[model.profiles]]
id = "ollama"
display_name = "Office Ollama"
type = "ollama"
base_url = "http://127.0.0.1:11434"
keep_alive = "5m"
[[model.profiles]]
id = "lab"
display_name = "Lab Server"
type = "openai_compatible"
base_url = "https://192.168.1.8:8443"
authentication = "dummy_bearer"
structured_output = "prompt_only"
known_models = [{id="shared", display_name="Shared", context_window_tokens=32768}]
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            path.write_text(document, encoding="utf-8")
            settings = load_settings(path, environ={})
            self.assertEqual(settings.provider, "lab")
            self.assertEqual([item.identifier for item in settings.profiles], ["ollama", "lab"])
            self.assertEqual(settings.profile("lab").base_url, "https://192.168.1.8:8443/v1")
            self.assertEqual(settings.profile("lab").known_models[0].context_window_tokens, 32768)
            path.write_text(document.replace(
                'default_model = "shared"',
                'default_model = "shared"\nbase_url = "http://127.0.0.1:11434"',
            ), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "cannot be mixed"):
                load_settings(path, environ={})

    def test_openai_configured_api_root_forms_normalize_once_and_reject_ambiguity(self) -> None:
        template = """
[model]
default_profile = "lab"
default_model = "shared"
[[model.profiles]]
id = "lab"
type = "openai_compatible"
base_url = "{base_url}"
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            for value in (
                "http://10.0.0.8:8000",
                "http://10.0.0.8:8000/",
                "http://10.0.0.8:8000/v1",
                "http://10.0.0.8:8000/v1/",
            ):
                with self.subTest(value=value):
                    path.write_text(template.format(base_url=value), encoding="utf-8")
                    settings = load_settings(path, environ={})
                    self.assertEqual(
                        settings.profile("lab").base_url,
                        "http://10.0.0.8:8000/v1",
                    )
            for value in (
                "http://10.0.0.8:8000/api",
                "http://10.0.0.8:8000/v1/v1",
                "http://10.0.0.8:8000/v1/models",
            ):
                with self.subTest(value=value), self.assertRaises(ConfigError):
                    path.write_text(template.format(base_url=value), encoding="utf-8")
                    load_settings(path, environ={})

    def test_explicit_profiles_reject_model_environment_overrides(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            path.write_text("""
[model]
default_profile = "lab"
default_model = "m"
[[model.profiles]]
id = "lab"
type = "openai_compatible"
base_url = "http://10.0.0.2:8000/v1"
""", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "legacy single-provider"):
                load_settings(path, environ={"TORI_MODEL_NAME": "other"})

    def test_tts_configuration_is_bounded_to_the_approved_local_provider(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "tori.toml"
            path.write_text(
                """
[tts]
enabled = false
provider = "qwen"
endpoint = "http://127.0.0.1:8000"
voice = "tori_alt"
connect_timeout_seconds = 2
read_timeout_seconds = 40
""".strip(),
                encoding="utf-8",
            )
            settings = load_settings(path, environ={})
        self.assertFalse(settings.tts_enabled)
        self.assertEqual(settings.tts_voice, "tori_alt")
        self.assertEqual(settings.tts_connect_timeout_seconds, 2.0)
        self.assertEqual(settings.tts_read_timeout_seconds, 40.0)

        invalid_values = {
            "TORI_TTS_PROVIDER": "cloud",
            "TORI_TTS_ENDPOINT": "http://169.254.169.254:8000",
            "TORI_TTS_VOICE": "../../voice",
            "TORI_TTS_CONNECT_TIMEOUT_SECONDS": "0",
            "TORI_TTS_READ_TIMEOUT_SECONDS": "121",
        }
        for key, value in invalid_values.items():
            with self.subTest(key=key), self.assertRaises(ConfigError):
                load_settings(Path("absent.toml"), environ={key: value})

        private_lan = "http://" + ".".join(("192", "168", "5", "50")) + ":8000"
        self.assertEqual(
            load_settings(
                Path("absent.toml"),
                environ={"TORI_TTS_ENDPOINT": private_lan},
            ).tts_endpoint,
            private_lan,
        )

    def test_kokoro_tts_requires_an_explicit_bounded_local_endpoint(self) -> None:
        settings = load_settings(
            Path("absent.toml"),
            environ={
                "TORI_TTS_PROVIDER": "kokoro",
                "TORI_TTS_ENDPOINT": "http://192.168.1.50:8880/",
                "TORI_TTS_VOICE": "af_heart",
            },
        )

        self.assertEqual(settings.tts_provider, "kokoro")
        self.assertEqual(settings.tts_endpoint, "http://192.168.1.50:8880")
        self.assertEqual(settings.tts_voice, "af_heart")

        with self.assertRaises(ConfigError):
            load_settings(
                Path("absent.toml"),
                environ={"TORI_TTS_PROVIDER": "kokoro"},
            )
        for endpoint in (
            "http://localhost:8880",
            "http://user@192.168.1.50:8880",
            "http://192.168.1.50:8880/v1",
            "https://192.168.1.50:8880",
            "http://8.8.8.8:8880",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ConfigError):
                load_settings(
                    Path("absent.toml"),
                    environ={
                        "TORI_TTS_PROVIDER": "kokoro",
                        "TORI_TTS_ENDPOINT": endpoint,
                    },
                )

    def test_finance_configuration_requires_explicit_absolute_root_when_enabled(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tori.toml"
            finance_root = Path(directory) / "finance"
            path.write_text(
                f'[finance]\nenabled = true\ndata_root = "{finance_root}"\ncurrency = "usd"\n',
                encoding="utf-8",
            )
            settings = load_settings(path, environ={})
            self.assertTrue(settings.finance.enabled)
            self.assertEqual(settings.finance.data_root, finance_root)
            self.assertEqual(settings.finance.currency, "USD")
            path.write_text('[finance]\nenabled = true\n', encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "data_root"):
                load_settings(path, environ={})

    def test_finance_is_disabled_without_creating_or_assuming_a_root(self) -> None:
        settings = load_settings(Path("absent.toml"), environ={})
        self.assertFalse(settings.finance.enabled)
        self.assertIsNone(settings.finance.data_root)


if __name__ == "__main__":
    unittest.main()
