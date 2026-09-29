"""Focused security and behavior tests for the bounded media.inspect Skill."""

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from tori.media_inspect import (
    BWRAP_PATH,
    FFPROBE_PATH,
    MEDIA_INSPECT_OPERATION,
    FFprobeRunResult,
    FFprobeRunner,
    ExecutableIdentity,
    MediaInspectAdapter,
    MediaInspectConversationService,
    MediaInspectError,
    MediaSelectionRegistry,
    build_media_inspect_manifest,
    inspect_ffprobe_executable,
    media_inspect_permissions,
    media_path_from_text,
    normalize_ffprobe_json,
)
from tori.request_origin import OriginAuthorityError, RequestOrigin
from tori.skills import (
    SQLiteSkillRegistry,
    SkillApplicationService,
    SkillComponentKind,
    SkillIdentity,
    SkillPermissionError,
    SkillUnavailableError,
)


NOW = datetime(2026, 9, 5, 20, 0, tzinfo=timezone.utc)
IDENTITY = ExecutableIdentity(
    "/usr/bin/ffprobe",
    "ffprobe version test-6.1",
    "sha256:" + "a" * 64,
    1,
    2,
    191_888,
    3,
)


def ffprobe_document():
    return {
        "streams": [
            {
                "codec_name": "h264",
                "codec_type": "video",
                "width": 320,
                "height": 180,
                "avg_frame_rate": "30/1",
            },
            {
                "codec_name": "aac",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
            },
        ],
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "format_long_name": "QuickTime / MOV",
            "duration": "1.250000",
            "bit_rate": "123456",
            "tags": {"title": "Disposable fixture", "encoder": "fixture"},
        },
    }


class FakeRunner:
    def __init__(self, result=None):
        self.result = result or FFprobeRunResult(
            0, json.dumps(ffprobe_document()).encode("utf-8"), b""
        )
        self.descriptors = []
        self.bound_bytes = []

    def run(self, descriptor):
        self.descriptors.append(descriptor)
        self.bound_bytes.append(os.pread(descriptor, 128, 0))
        return self.result


class MediaInspectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.media = self.root / "fixture.bin"
        self.media.write_bytes(b"synthetic disposable media")
        self.selections = MediaSelectionRegistry()
        self.runner = FakeRunner()
        self.registry = SQLiteSkillRegistry(
            self.root / "skills" / "registry.sqlite3", clock=lambda: NOW
        )
        self.registry.initialize()
        self.adapter = MediaInspectAdapter(
            self.selections,
            runner=self.runner,
            executable_inspector=lambda: IDENTITY,
        )
        self.service = SkillApplicationService(
            self.registry,
            {SkillComponentKind.BOUNDED_EXECUTABLE: self.adapter},
        )
        self.manifest = build_media_inspect_manifest(IDENTITY, inspected_at=NOW)
        self.local = RequestOrigin.local_web()
        self.remote = RequestOrigin.discord_remote(
            connector_id="discord-primary",
            external_message_id="message-1",
            external_actor_id="actor-1",
            external_conversation_id="channel-1",
        )

    def install_and_enable(self, grants=None):
        installed = self.service.install(self.manifest, origin=self.local)
        return self.service.enable(
            self.manifest.version_ref,
            expected_revision=installed.revision,
            granted_permissions=(
                media_inspect_permissions() if grants is None else grants
            ),
            origin=self.local,
        )

    def invoke(self, path=None, *, origin=None):
        token = self.selections.select(str(path or self.media))
        try:
            return self.service.invoke(
                self.manifest.version_ref,
                MEDIA_INSPECT_OPERATION,
                {"selection": token},
                origin=origin or self.local,
            )
        finally:
            self.selections.revoke(token)

    def test_manifest_is_bounded_installed_disabled_and_uses_exact_permissions(self):
        installed = self.service.install(self.manifest, origin=self.local)
        self.assertEqual(installed.state, "installed_disabled")
        self.assertEqual(
            [item.kind for item in self.manifest.requested_permissions],
            ["file.read.selected", "process.execute.approved"],
        )
        self.assertEqual(self.manifest.requirements.network_destinations, ())
        self.assertEqual(self.manifest.requirements.secret_handles, ())
        self.assertIn("/usr/bin/ffprobe", self.manifest.requirements.executables[0])

    def test_success_normalizes_fixture_and_binds_only_opaque_selection(self):
        self.install_and_enable()
        result = self.invoke()
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.metadata["format"], "mov,mp4,m4a,3gp,3g2,mj2")
        self.assertEqual(result.metadata["duration_seconds"], 1.25)
        self.assertEqual(result.metadata["video_codec"], "h264")
        self.assertEqual((result.metadata["width"], result.metadata["height"]), (320, 180))
        self.assertEqual(result.metadata["frame_rate_fps"], 30.0)
        self.assertEqual(result.metadata["audio_codec"], "aac")
        self.assertEqual(self.runner.bound_bytes, [b"synthetic disposable media"])
        self.assertNotIn(str(self.media), result.input_text)

    def test_nonexistent_directory_symlink_and_fifo_are_rejected(self):
        for path in (self.root / "missing", self.root):
            with self.subTest(path=path), self.assertRaises(MediaInspectError):
                self.selections.select(str(path))
        symlink = self.root / "link"
        symlink.symlink_to(self.media)
        with self.assertRaises(MediaInspectError):
            self.selections.select(str(symlink))
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(MediaInspectError):
            self.selections.select(str(fifo))

    def test_parent_symlink_traversal_and_non_normal_paths_are_rejected(self):
        linked_parent = self.root / "linked"
        linked_parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(MediaInspectError):
            self.selections.select(str(linked_parent / self.media.name))
        with self.assertRaises(MediaInspectError):
            self.selections.select(str(self.root / ".." / self.root.name / self.media.name))
        with self.assertRaises(MediaInspectError):
            self.selections.select("relative.mp4")

    def test_open_file_identity_survives_path_replacement(self):
        self.install_and_enable()
        token = self.selections.select(str(self.media))
        replacement = self.root / "replacement"
        replacement.write_bytes(b"replacement bytes")
        os.replace(replacement, self.media)
        try:
            result = self.service.invoke(
                self.manifest.version_ref,
                MEDIA_INSPECT_OPERATION,
                {"selection": token},
                origin=self.local,
            )
        finally:
            self.selections.revoke(token)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(self.runner.bound_bytes, [b"synthetic disposable media"])

    def test_malformed_nonzero_timeout_and_output_limit_fail_honestly(self):
        cases = (
            (FFprobeRunResult(0, b"not-json", b""), "media_output_invalid"),
            (FFprobeRunResult(2, b"", b"bad media"), "media_probe_failed"),
            (FFprobeRunResult(None, b"", b"", timed_out=True), "media_timeout"),
            (FFprobeRunResult(-15, b"x", b"", stdout_truncated=True), "media_output_limit"),
            (FFprobeRunResult(1, b"", b"bwrap: unavailable", containment_failed=True), "media_isolation_unavailable"),
        )
        for run_result, code in cases:
            with self.subTest(code=code):
                runner = FakeRunner(run_result)
                adapter = MediaInspectAdapter(
                    self.selections,
                    runner=runner,
                    executable_inspector=lambda: IDENTITY,
                )
                service = SkillApplicationService(
                    self.registry,
                    {SkillComponentKind.BOUNDED_EXECUTABLE: adapter},
                )
                try:
                    self.registry.get(self.manifest.version_ref)
                except Exception:
                    installed = service.install(self.manifest, origin=self.local)
                    service.enable(
                        self.manifest.version_ref,
                        expected_revision=installed.revision,
                        granted_permissions=media_inspect_permissions(),
                        origin=self.local,
                    )
                token = self.selections.select(str(self.media))
                result = service.invoke(
                    self.manifest.version_ref,
                    MEDIA_INSPECT_OPERATION,
                    {"selection": token},
                    origin=self.local,
                )
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.metadata["error_code"], code)

    def test_disabled_missing_permission_and_remote_origin_cannot_invoke(self):
        self.service.install(self.manifest, origin=self.local)
        with self.assertRaises(SkillUnavailableError):
            self.invoke()
        installed = self.registry.get(self.manifest.version_ref)
        self.service.enable(
            self.manifest.version_ref,
            expected_revision=installed.revision,
            granted_permissions=(media_inspect_permissions()[0],),
            origin=self.local,
        )
        with self.assertRaises(SkillPermissionError):
            self.invoke()
        with self.assertRaises(OriginAuthorityError):
            self.invoke(origin=self.remote)

    def test_executable_identity_drift_requires_new_immutable_version(self):
        self.install_and_enable()
        changed = ExecutableIdentity(
            IDENTITY.path, IDENTITY.version + ".changed", "sha256:" + "b" * 64,
            IDENTITY.device, IDENTITY.inode + 1, IDENTITY.size, IDENTITY.mtime_ns + 1,
        )
        adapter = MediaInspectAdapter(
            self.selections,
            runner=self.runner,
            executable_inspector=lambda: changed,
        )
        service = SkillApplicationService(
            self.registry, {SkillComponentKind.BOUNDED_EXECUTABLE: adapter}
        )
        token = self.selections.select(str(self.media))
        try:
            with self.assertRaises(SkillUnavailableError) as raised:
                service.invoke(
                    self.manifest.version_ref,
                    MEDIA_INSPECT_OPERATION,
                    {"selection": token},
                    origin=self.local,
                )
            self.assertEqual(raised.exception.code, "skill_unavailable")
            self.assertIn("unavailable on this host", str(raised.exception))
        finally:
            self.selections.revoke(token)

    def test_bounded_adapter_does_not_admit_a_different_executable_skill(self):
        other = replace(
            self.manifest,
            identity=SkillIdentity("local", "tests", "other-executable"),
        )
        installed = self.service.install(other, origin=self.local)
        self.service.enable(
            other.version_ref,
            expected_revision=installed.revision,
            granted_permissions=media_inspect_permissions(),
            origin=self.local,
        )
        self.assertEqual(self.service.eligible_capabilities(origin=self.local), ())
        token = self.selections.select(str(self.media))
        try:
            with self.assertRaises(SkillUnavailableError):
                self.service.invoke(
                    other.version_ref,
                    MEDIA_INSPECT_OPERATION,
                    {"selection": token},
                    origin=self.local,
                )
        finally:
            self.selections.revoke(token)

    def test_builtin_identity_cannot_remove_the_tori_owned_permission_contract(self):
        operation = self.manifest.operations[0]
        weakened = replace(
            self.manifest,
            requested_permissions=(),
            operations=(replace(operation, required_permissions=()),),
        )
        installed = self.service.install(weakened, origin=self.local)
        self.service.enable(
            weakened.version_ref,
            expected_revision=installed.revision,
            granted_permissions=(),
            origin=self.local,
        )
        self.assertEqual(self.service.eligible_capabilities(origin=self.local), ())

    def test_fixed_runner_has_no_shell_or_user_controlled_argv(self):
        argv = FFprobeRunner.argv(19)
        self.assertEqual(argv[0], str(BWRAP_PATH))
        self.assertNotIn("-c", argv)
        self.assertEqual(argv[-8:], (
            str(FFPROBE_PATH), "-v", "error", "-show_format", "-show_streams",
            "-of", "json", "/input/media",
        ))
        self.assertIn("--unshare-all", argv)
        self.assertIn("--ro-bind-fd", argv)
        self.assertNotIn("/etc/passwd", argv)
        self.assertNotIn(str(self.media), argv)

    def test_normalizer_rejects_invalid_types_and_unbounded_streams(self):
        invalid = ffprobe_document()
        invalid["streams"][0]["width"] = "not-an-integer"
        with self.assertRaises(MediaInspectError):
            normalize_ffprobe_json(json.dumps(invalid).encode())
        with self.assertRaises(MediaInspectError):
            normalize_ffprobe_json(json.dumps({"streams": [{}] * 257, "format": {}}).encode())
        nested = {}
        cursor = nested
        for _ in range(10):
            cursor["nested"] = {}
            cursor = cursor["nested"]
        with self.assertRaises(MediaInspectError):
            normalize_ffprobe_json(json.dumps(nested).encode())

    def test_conversation_bridge_routes_clear_local_intent_without_provider_path_authority(self):
        self.install_and_enable()
        outcomes = []
        conversation = MediaInspectConversationService(
            self.service,
            self.manifest.version_ref,
            self.selections,
            outcome_recorder=outcomes.append,
        )
        self.assertIsNone(conversation.handle("Hello Tori", origin=self.local))
        clarification = conversation.handle("Inspect this video file", origin=self.local)
        self.assertIn("absolute path", clarification)
        answer = conversation.handle(
            f'What codec is this media file using? "{self.media}"', origin=self.local
        )
        self.assertIn("video h264 at 320×180", answer)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].status, "succeeded")

    def test_intent_parser_keeps_one_exact_path(self):
        self.assertEqual(media_path_from_text("/media-inspect /tmp/a.mp4"), ("/tmp/a.mp4", True))
        self.assertEqual(media_path_from_text("inspect this video"), (None, True))
        self.assertEqual(media_path_from_text("ordinary conversation"), (None, False))

    @unittest.skipUnless(FFPROBE_PATH.exists(), "host FFprobe is unavailable")
    def test_host_ffprobe_identity_is_regular_executable_and_versioned(self):
        identity = inspect_ffprobe_executable()
        self.assertEqual(identity.path, str(FFPROBE_PATH))
        self.assertTrue(identity.version.startswith("ffprobe version "))
        self.assertRegex(identity.sha256, r"^sha256:[0-9a-f]{64}$")
        details = FFPROBE_PATH.stat()
        self.assertTrue(stat.S_ISREG(details.st_mode))
        self.assertFalse(details.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


if __name__ == "__main__":
    unittest.main()
