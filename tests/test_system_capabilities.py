from __future__ import annotations

from collections import namedtuple
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tori.system_capabilities import (
    CPUStatus,
    GPUInfo,
    GPUStatus,
    HealthSignal,
    MemoryStatus,
    ServiceActionProposal,
    SystemCapabilities,
    SystemCapabilityError,
    SystemConversationService,
    ToriHealth,
    UptimeStatus,
)


Usage = namedtuple("Usage", "total used free")


class SystemCapabilityTests(unittest.TestCase):
    def test_host_status_is_read_only_and_each_metric_fails_independently(self) -> None:
        capabilities = SystemCapabilities(
            memory_status_function=lambda: MemoryStatus(
                total_bytes=16 * 1024**3, used_bytes=5 * 1024**3,
                available_bytes=11 * 1024**3, used_percent=31.25,
            ),
            cpu_status_function=lambda: CPUStatus(None, 8, 12.5, ()),
            gpu_status_function=lambda: GPUStatus((
                GPUInfo("GPU A", 24 * 1024**3, 4 * 1024**3, 20 * 1024**3, 25.0, None),
                GPUInfo("GPU B", 16 * 1024**3, 2 * 1024**3, 14 * 1024**3, None, None),
            )),
        )
        document = SystemConversationService(capabilities).host_status()
        self.assertEqual(document["cpu"], {"available": True, "utilization_percent": 12.5})
        self.assertEqual(document["memory"]["used_bytes"], 5 * 1024**3)  # type: ignore[index]
        self.assertEqual(len(document["gpus"]), 2)  # type: ignore[arg-type]

        unavailable = SystemConversationService(SystemCapabilities(
            gpu_status_function=lambda: (_ for _ in ()).throw(SystemCapabilityError("no gpu")),
        )).host_status()
        self.assertEqual(unavailable["gpus"], [])
    def test_available_ram_is_host_info_not_curated_memory(self) -> None:
        service = SystemConversationService(SystemCapabilities())
        for text in (
            "How much RAM is available?", "How much memory is available?",
            "How much RAM is free?", "How much RAM is in use?",
            "Can you tell me how much RAM is available?",
        ):
            with self.subTest(text=text):
                self.assertEqual(service.interpret(text).operation, "system.memory_status")
        for text in (
            "Create a memory that I like root beer.", "How many memories are available?",
            "How much memory is available about my holiday?",
            "Delete the available memory.", "I remember how much RAM is available.",
            "Is curated Memory available?", "A memory of free time.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(service.interpret(text))

    def test_disk_recognition_and_human_result(self) -> None:
        capabilities = SystemCapabilities(
            disk_usage_function=lambda path: Usage(2 * 1024**3, 1 * 1024**3, 1 * 1024**3)
        )
        service = SystemConversationService(capabilities)

        request = service.interpret("Tori, how much disk space do I have left?")
        self.assertIsNotNone(request)
        self.assertEqual(request.operation, "disk_usage")  # type: ignore[union-attr]
        result = service.handle("How much disk space do I have left?")
        self.assertIsNotNone(result)
        self.assertIn("1.0 GB free out of 2.0 GB", result.text)  # type: ignore[union-attr]
        for prompt in (
            "Can you tell me how much disk space is currently left on my host?",
            "Hi Tori, can you tell me how much disk space is currently left on my host?",
            "By the way, how much disk space do I have left?",
            "Before I leave, can you check how much disk space is left?",
        ):
            with self.subTest(prompt=prompt):
                polite_request = service.interpret(prompt)
                self.assertEqual(polite_request.operation, "disk_usage")  # type: ignore[union-attr]

    def test_disk_explicit_existing_path_and_missing_path(self) -> None:
        with TemporaryDirectory() as temporary:
            seen: list[str] = []

            def usage(path: str) -> Usage:
                seen.append(path)
                return Usage(1024, 512, 512)

            capabilities = SystemCapabilities(disk_usage_function=usage)
            result = SystemConversationService(capabilities).handle(
                f"How much space is left on `{temporary}`?"
            )
            self.assertIsNotNone(result)
            self.assertEqual(seen, [str(Path(temporary).resolve())])
            self.assertIn(str(Path(temporary).resolve()), result.text)  # type: ignore[union-attr]

            missing = str(Path(temporary) / "missing")
            failed = SystemConversationService(capabilities).handle(
                f"How much space is left on {missing}?"
            )
            self.assertIsNotNone(failed)
            self.assertEqual(failed.code, "disk_usage_failed")  # type: ignore[union-attr]

    def test_network_prefers_non_loopback_private_addresses_without_network_io(self) -> None:
        def addresses(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
            return [
                (None, None, None, None, ("127.0.0.1", 0)),
                (None, None, None, None, ("192.168.1.20", 0)),
                (None, None, None, None, ("10.0.0.5", 0)),
                (None, None, None, None, ("not-an-ip", 0)),
            ]

        capabilities = SystemCapabilities(
            address_function=addresses,
            hostname_function=lambda: "tori-test-host",
        )
        result = SystemConversationService(capabilities).handle("What's my local IP?")
        self.assertEqual(result.text, "Your LAN IPs are 10.0.0.5, 192.168.1.20.")  # type: ignore[union-attr]

    def test_network_without_useful_address_is_truthful(self) -> None:
        capabilities = SystemCapabilities(
            address_function=lambda *_args, **_kwargs: [
                (None, None, None, None, ("127.0.0.1", 0))
            ]
        )
        result = SystemConversationService(capabilities).handle("What is the IP of this computer?")
        self.assertIn("couldn't determine", result.text)  # type: ignore[union-attr]

    def test_brave_allowlist_uses_exact_argv_without_shell(self) -> None:
        launched: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def launch(*args: object, **kwargs: object) -> None:
            launched.append((args, kwargs))

        capabilities = SystemCapabilities(
            executable_resolver=lambda name: "/opt/brave/brave-browser" if name == "brave-browser" else None,
            process_launcher=launch,
        )
        result = SystemConversationService(capabilities).handle("Launch Brave browser.")
        self.assertEqual(result.text, "Opening Brave.")  # type: ignore[union-attr]
        self.assertEqual(launched[0][0], (["/opt/brave/brave-browser"],))
        self.assertFalse(launched[0][1]["shell"])

        with self.assertRaises(SystemCapabilityError) as unknown:
            capabilities.open_application("firefox")
        self.assertEqual(unknown.exception.code, "unknown_application")

    def test_brave_unavailable_and_unrelated_text_do_not_trigger(self) -> None:
        service = SystemConversationService(
            SystemCapabilities(
                executable_resolver=lambda _name: None,
                brave_fallback_resolver=lambda: None,
            )
        )
        unavailable = service.handle("Open Brave.")
        self.assertEqual(unavailable.code, "system_capability_unavailable")  # type: ignore[union-attr]
        self.assertIsNone(service.interpret("There is plenty of space at this address."))
        self.assertIsNone(service.interpret("Brave ideas are welcome."))
        self.assertIsNone(service.interpret("Open the project notes."))

    def test_allowlisted_desktop_apps_use_fixed_launch_vectors(self) -> None:
        launched: list[tuple[tuple[object, ...], dict[str, object]]] = []
        executables = {
            "dolphin": "/usr/bin/dolphin",
            "x-terminal-emulator": "/usr/bin/x-terminal-emulator",
            "lm-studio": "/usr/bin/lm-studio",
        }

        def launch(*args: object, **kwargs: object) -> None:
            launched.append((args, kwargs))

        service = SystemConversationService(
            SystemCapabilities(
                executable_resolver=lambda name: executables.get(name),
                process_launcher=launch,
            )
        )
        for text, application, expected in (
            ("Open Dolphin.", "dolphin", "Opening Dolphin."),
            ("Open a terminal.", "terminal", "Opening a terminal."),
            ("Launch LM Studio.", "lm_studio", "Opening LM Studio."),
        ):
            with self.subTest(text=text):
                request = service.interpret(text)
                self.assertEqual(request.application, application)  # type: ignore[union-attr]
                self.assertEqual(service.handle(text).text, expected)  # type: ignore[union-attr]
        self.assertEqual(
            [call[0][0] for call in launched],
            [
                ["/usr/bin/dolphin"],
                ["/usr/bin/x-terminal-emulator"],
                ["/usr/bin/lm-studio"],
            ],
        )
        self.assertTrue(all(call[1]["shell"] is False for call in launched))

    def test_known_folder_alias_and_absolute_directory_are_bounded(self) -> None:
        launched: list[tuple[object, dict[str, object]]] = []

        def launch(argv: object, **kwargs: object) -> None:
            launched.append((argv, kwargs))

        service = SystemConversationService(
            SystemCapabilities(
                executable_resolver=lambda name: (
                    "/usr/bin/dolphin" if name == "dolphin" else None
                ),
                process_launcher=launch,
            )
        )
        alias = service.interpret("Open my Tori project folder.")
        self.assertEqual(alias.operation, "open_folder")  # type: ignore[union-attr]
        self.assertEqual(alias.path, str(Path(__file__).resolve().parents[1]))  # type: ignore[union-attr]
        with TemporaryDirectory() as temporary:
            result = service.handle(f"Open `{temporary}`.")
            self.assertIn(f"Opening {Path(temporary).resolve()} in Dolphin.", result.text)  # type: ignore[union-attr]
            self.assertEqual(launched[-1][0], ["/usr/bin/dolphin", str(Path(temporary).resolve())])
        missing = service.handle("Open /path/that/does/not/exist.")
        self.assertEqual(missing.code, "directory_not_found")  # type: ignore[union-attr]
        executable = service.handle("Open /bin/sh.")
        self.assertEqual(executable.code, "invalid_directory")  # type: ignore[union-attr]
        self.assertEqual(len(launched), 1)
        self.assertIsNone(service.interpret("Open /workspaces/Tori; touch /tmp/nope"))

    def test_service_actions_are_allowlisted_and_not_executed_before_confirmation(self) -> None:
        calls: list[tuple[object, dict[str, object]]] = []
        state = {"running": True}

        def runner(argv: object, **kwargs: object) -> object:
            calls.append((argv, kwargs))
            state["running"] = True
            return SimpleNamespace(returncode=0)

        capabilities = SystemCapabilities(
            systemctl_path_function=lambda: "/usr/bin/systemctl",
            systemctl_runner=runner,
            radicale_status_function=lambda: state["running"],
            action_sleep_function=lambda _seconds: None,
        )
        service = SystemConversationService(capabilities)
        turn = service.handle("Tori, restart Radicale.")
        self.assertEqual(turn.request.action, "restart")  # type: ignore[union-attr]
        self.assertIsNotNone(turn.proposal)  # type: ignore[union-attr]
        proposal = turn.proposal  # type: ignore[union-attr]
        self.assertEqual(proposal.unit, "tori-radicale.service")
        self.assertEqual(proposal.scope, "user")
        self.assertIn("System target: tori-radicale.service", turn.text)  # type: ignore[union-attr]
        self.assertEqual(calls, [])

        result = service.execute_service_action(proposal)
        self.assertTrue(result.succeeded)
        self.assertTrue(result.verified)
        self.assertEqual(calls[0][0], ["/usr/bin/systemctl", "--user", "restart", "tori-radicale.service"])
        self.assertFalse(calls[0][1]["shell"])

        ollama = capabilities.service_action_proposal("ollama", "restart")
        self.assertEqual(ollama.unit, "ollama.service")
        self.assertEqual(ollama.scope, "system")
        for text in (
            "Restart Ollama.",
            "Stop Ollama.",
            "Start Ollama.",
            "Restart the Planning server.",
            "Stop the calendar backend.",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(service.interpret(text))
        self.assertEqual(len(calls), 1)

    def test_service_action_failure_and_binding_are_truthful(self) -> None:
        capabilities = SystemCapabilities(
            systemctl_path_function=lambda: "/usr/bin/systemctl",
            systemctl_runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
            radicale_status_function=lambda: True,
            action_sleep_function=lambda _seconds: None,
        )
        proposal = capabilities.service_action_proposal("radicale", "restart")
        result = capabilities.execute_service_action(proposal)
        self.assertFalse(result.succeeded)
        self.assertIn("could not be restarted", result.text)
        forged = ServiceActionProposal(
            "radicale", "restart", "Radicale", "ollama.service", "user"
        )
        with self.assertRaises(SystemCapabilityError) as raised:
            capabilities.execute_service_action(forged)
        self.assertEqual(raised.exception.code, "invalid_service_action")
        with self.assertRaises(SystemCapabilityError) as raised:
            capabilities.service_action_proposal("redis", "restart")
        self.assertEqual(raised.exception.code, "unknown_service")
        with self.assertRaises(SystemCapabilityError) as raised:
            capabilities.service_action_proposal("ollama", "enable")
        self.assertEqual(raised.exception.code, "unknown_service_action")
        service = SystemConversationService(capabilities)
        for text in (
            "I restarted my computer yesterday.",
            "Ollama restart behavior is interesting.",
            "Dolphins are intelligent.",
            "The terminal phase of the project.",
            "Planning should start with good architecture.",
            "Restart Redis.",
            "Restart Tori.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(service.interpret(text))

    def test_ollama_start_stop_restart_use_the_exact_system_unit_and_verify(self) -> None:
        calls: list[tuple[object, dict[str, object]]] = []
        state = {"running": True}

        def runner(argv: object, **kwargs: object) -> object:
            calls.append((argv, kwargs))
            action = argv[-1]  # type: ignore[index]
            state["running"] = action != "stop"
            return SimpleNamespace(returncode=0)

        capabilities = SystemCapabilities(
            systemctl_path_function=lambda: "/usr/bin/systemctl",
            systemctl_runner=runner,
            sudo_path_function=lambda: "/usr/bin/sudo",
            ollama_service_helper_path_function=lambda: "/usr/local/libexec/tori-ollama-service",
            ollama_service_runner=runner,
            ollama_status_function=lambda: state["running"],
            action_sleep_function=lambda _seconds: None,
        )
        for action, expected in (
            ("restart", True),
            ("stop", False),
            ("start", True),
        ):
            result = capabilities.execute_service_action(
                capabilities.service_action_proposal("ollama", action)
            )
            with self.subTest(action=action):
                self.assertTrue(result.succeeded)
                self.assertTrue(result.verified)
                self.assertEqual(state["running"], expected)
        self.assertEqual(
            [call[0] for call in calls],
            [
                ["/usr/bin/sudo", "-n", "/usr/local/libexec/tori-ollama-service", "restart"],
                ["/usr/bin/sudo", "-n", "/usr/local/libexec/tori-ollama-service", "stop"],
                ["/usr/bin/sudo", "-n", "/usr/local/libexec/tori-ollama-service", "start"],
            ],
        )
        self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_ollama_privileged_helper_fails_closed_and_cannot_select_a_unit(self) -> None:
        calls: list[object] = []
        capabilities = SystemCapabilities(
            sudo_path_function=lambda: "/usr/bin/sudo",
            ollama_service_helper_path_function=lambda: None,
            ollama_service_runner=lambda argv, **_kwargs: calls.append(argv),
            ollama_status_function=lambda: True,
        )
        result = capabilities.execute_service_action(
            capabilities.service_action_proposal("ollama", "restart")
        )
        self.assertFalse(result.succeeded)
        self.assertFalse(result.verified)
        self.assertIn("service control is unavailable", result.text)
        self.assertEqual(calls, [])
        with self.assertRaises(SystemCapabilityError) as raised:
            capabilities.service_action_proposal("ollama.service", "restart")
        self.assertEqual(raised.exception.code, "unknown_service")

    def test_privileged_helper_source_rejects_invalid_and_extra_arguments(self) -> None:
        helper = Path(__file__).parents[1] / "deploy/system/tori-ollama-service"
        for arguments in ((), ("status",), ("restart", "ollama.service"), ("restart;id",)):
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    ["/bin/sh", str(helper), *arguments],
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                self.assertEqual(completed.returncode, 64)

    def test_service_action_reports_post_action_verification_failure(self) -> None:
        capabilities = SystemCapabilities(
            systemctl_path_function=lambda: "/usr/bin/systemctl",
            systemctl_runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
            radicale_status_function=lambda: False,
            action_sleep_function=lambda _seconds: None,
        )
        result = capabilities.execute_service_action(
            capabilities.service_action_proposal("radicale", "restart")
        )
        self.assertFalse(result.succeeded)
        self.assertFalse(result.verified)
        self.assertIn("expected state could not be verified", result.text)

    def test_memory_status_is_read_only_and_human_readable(self) -> None:
        capabilities = SystemCapabilities(
            memory_status_function=lambda: MemoryStatus(
                total_bytes=64 * 1024**3,
                used_bytes=21 * 1024**3,
                available_bytes=43 * 1024**3,
                used_percent=32.8125,
            )
        )
        service = SystemConversationService(capabilities)

        request = service.interpret("Tori, how much RAM am I using?")
        self.assertEqual(request.operation, "system.memory_status")  # type: ignore[union-attr]
        for prompt in (
            "Can you tell me how much RAM is in use right now?",
            "Hi Tori, can you tell me how much RAM is in use right now?",
            "Hey Tori, how much RAM am I using?",
            "By the way, can you tell me how much RAM is in use?",
            "Before I go, can you tell me how much RAM is in use right now?",
            "Could you check how much RAM I'm using?",
        ):
            with self.subTest(prompt=prompt):
                polite_request = service.interpret(prompt)
                self.assertEqual(polite_request.operation, "system.memory_status")  # type: ignore[union-attr]
        result = service.handle("How much memory do I have free?")
        self.assertIn("21.0 GB of 64.0 GB RAM", result.text)  # type: ignore[union-attr]
        self.assertIn("43.0 GB available", result.text)  # type: ignore[union-attr]
        self.assertIn("33% used", result.text)  # type: ignore[union-attr]

    def test_host_information_framing_does_not_match_topic_discussion(self) -> None:
        service = SystemConversationService()
        for prompt in (
            "RAM prices have really gone up.",
            "I was thinking about adding more RAM.",
            "What do you think about disk space requirements for this project?",
            "We were talking about RAM earlier.",
            "Tell me how RAM works.",
            "I want to buy a larger hard drive.",
            "Hi Tori, tell me how RAM works.",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(service.interpret(prompt))

    def test_cpu_status_keeps_utilization_and_load_distinct(self) -> None:
        capabilities = SystemCapabilities(
            cpu_status_function=lambda: CPUStatus(
                "Test CPU 9000", 16, 18.0, (1.2, 0.9, 0.8)
            )
        )
        service = SystemConversationService(capabilities)
        request = service.interpret("What's my CPU usage?")
        self.assertEqual(request.operation, "system.cpu_status")  # type: ignore[union-attr]
        result = service.handle("What processor do I have?")
        self.assertIn("Test CPU 9000", result.text)  # type: ignore[union-attr]
        self.assertIn("around 18% right now", result.text)  # type: ignore[union-attr]
        self.assertIn("System load is 1.20", result.text)  # type: ignore[union-attr]
        self.assertIn("16 logical CPUs", result.text)  # type: ignore[union-attr]

    def test_uptime_status_formats_a_natural_duration(self) -> None:
        capabilities = SystemCapabilities(
            uptime_function=lambda: UptimeStatus(2 * 86400 + 6 * 3600 + 30 * 60)
        )
        result = SystemConversationService(capabilities).handle(
            "How long has this computer been running?"
        )
        self.assertEqual(
            result.text,  # type: ignore[union-attr]
            "Your computer has been running for 2 days, 6 hours.",
        )

    def test_gpu_status_parses_multiple_gpus_and_uses_fixed_command(self) -> None:
        calls: list[tuple[object, dict[str, object]]] = []

        def runner(argv: object, **kwargs: object) -> object:
            calls.append((argv, kwargs))
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "NVIDIA RTX 3090, 24576, 7920, 16656, 12, 42\n"
                    "NVIDIA RTX 3080, 10240, 1024, 9216, 4, 39\n"
                ),
            )

        capabilities = SystemCapabilities(
            nvidia_smi_path_function=lambda: "/usr/bin/nvidia-smi",
            nvidia_smi_runner=runner,
        )
        service = SystemConversationService(capabilities)
        request = service.interpret("How much VRAM do I have free?")
        self.assertEqual(request.operation, "system.gpu_status")  # type: ignore[union-attr]
        result = service.handle("What GPU am I using?")
        self.assertIn("GPU 0 (NVIDIA RTX 3090)", result.text)  # type: ignore[union-attr]
        self.assertIn("7.7 GB of 24.0 GB VRAM", result.text)  # type: ignore[union-attr]
        self.assertIn("16.3 GB free", result.text)  # type: ignore[union-attr]
        self.assertIn("GPU 1 (NVIDIA RTX 3080)", result.text)  # type: ignore[union-attr]
        self.assertIn("12%", result.text)  # type: ignore[union-attr]
        self.assertEqual(calls[0][0][0], "/usr/bin/nvidia-smi")  # type: ignore[index]
        self.assertEqual(
            tuple(calls[0][0][1:]),  # type: ignore[index]
            (
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ),
        )
        self.assertFalse(calls[0][1]["shell"])

    def test_gpu_status_unavailable_is_bounded(self) -> None:
        service = SystemConversationService(
            SystemCapabilities(nvidia_smi_path_function=lambda: None)
        )
        result = service.handle("What's my GPU temperature?")
        self.assertEqual(result.code, "system_capability_unavailable")  # type: ignore[union-attr]
        self.assertEqual(result.text, "GPU status is unavailable on this host.")  # type: ignore[union-attr]

    def test_known_service_status_and_tori_health_are_allowlisted(self) -> None:
        health = ToriHealth(
            (
                HealthSignal("Tori", "available"),
                HealthSignal("Conversation", "available"),
                HealthSignal("Planning", "available"),
                HealthSignal("Scheduled Work", "available"),
            )
        )
        capabilities = SystemCapabilities(
            ollama_status_function=lambda: True,
            radicale_status_function=lambda: False,
            tori_health_function=lambda: health,
        )
        service = SystemConversationService(capabilities)
        self.assertEqual(
            service.handle("Is Ollama running?").text,  # type: ignore[union-attr]
            "Ollama is running.",
        )
        self.assertEqual(
            service.handle("Is Radicale running?").text,  # type: ignore[union-attr]
            "Planning backend appears unavailable.",
        )
        self.assertIn("Tori is healthy", service.handle("Is Tori healthy?").text)  # type: ignore[union-attr]
        self.assertIsNone(service.interpret("Is PostgreSQL running?"))
        with self.assertRaises(SystemCapabilityError) as raised:
            capabilities.service_status("postgresql")
        self.assertEqual(raised.exception.code, "unknown_service")

    def test_radicale_status_can_use_existing_planning_readiness(self) -> None:
        capabilities = SystemCapabilities(
            radicale_status_function=lambda: False,
            planning_status_function=lambda: SimpleNamespace(
                availability=SimpleNamespace(value="available")
            ),
        )
        result = SystemConversationService(capabilities).handle(
            "Is the Planning server up?"
        )
        self.assertEqual(
            result.text,  # type: ignore[union-attr]
            "Radicale is running and Planning is reachable.",
        )

    def test_known_service_unavailability_and_false_positives_do_not_intercept(self) -> None:
        service = SystemConversationService(
            SystemCapabilities(
                ollama_status_function=lambda: False,
                radicale_status_function=lambda: False,
            )
        )
        self.assertEqual(
            service.handle("Is Ollama up?").text,  # type: ignore[union-attr]
            "Ollama appears unavailable.",
        )
        for text in (
            "I can't remember what he said.",
            "That was a hot GPU discussion.",
            "We've been running around all day.",
            "Is this planning idea healthy?",
            "Ollama models are getting better.",
            "Is Redis running?",
        ):
            with self.subTest(text=text):
                self.assertIsNone(service.interpret(text))

    def test_capability_failure_does_not_escape_system_boundary(self) -> None:
        service = SystemConversationService(
            SystemCapabilities(
                memory_status_function=lambda: (_ for _ in ()).throw(RuntimeError("private"))
            )
        )
        result = service.handle("What's my memory usage?")
        self.assertEqual(result.code, "system_capability_unavailable")  # type: ignore[union-attr]
        self.assertEqual(result.text, "Memory status is unavailable right now.")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
