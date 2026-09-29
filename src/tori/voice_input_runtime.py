"""Optional isolated recognition deployment; never installs or downloads on On."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from .speech_recognition import RecognitionError


@dataclass(frozen=True, slots=True)
class VoiceRuntimeSettings:
    environment_root: Path | None = None
    model_root: Path | None = None
    port: int = 8013
    readiness_seconds: float = 90.0
    shutdown_seconds: float = 5.0

    def __post_init__(self) -> None:
        for root in (self.environment_root, self.model_root):
            if root is not None and (
                not isinstance(root, Path) or not root.is_absolute()
                or ".." in root.parts or "RealtimeSTT-PoC" in root.parts
                or "runtime" in root.parts
            ):
                raise ValueError("Voice assets require an explicit non-runtime absolute root.")
        if (self.environment_root is None) != (self.model_root is None):
            raise ValueError("Voice environment and model roots must both be configured.")
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("Voice worker port must be unprivileged.")
        if not 0 < self.readiness_seconds <= 90 or not 0 < self.shutdown_seconds <= 5:
            raise ValueError("Voice runtime deadlines are invalid.")

    @property
    def configured(self) -> bool:
        return self.environment_root is not None and self.model_root is not None

    def prerequisites(self) -> tuple[Path, Path]:
        if not self.configured:
            raise RecognitionError("runtime_unavailable")
        assert self.environment_root is not None and self.model_root is not None
        for root in (self.environment_root, self.model_root):
            _directory(root)
        _regular(self.environment_root / "pyvenv.cfg")
        _directory(self.environment_root / "bin")
        executable = self.environment_root / "bin" / "python"
        # Standard venv interpreters are symlinks; only this fixed entry may resolve one.
        try:
            target = executable.resolve(strict=True)
        except OSError:
            raise RecognitionError("runtime_unavailable") from None
        _regular(target, interpreter=True)
        if not os.access(target, os.X_OK):
            raise RecognitionError("runtime_unavailable")
        for model in ("tiny.en", "small.en"):
            _directory(self.model_root / model)
            _asset_tree(self.model_root / model)
            for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
                _regular(self.model_root / model / name)
        _regular(self.model_root / "silero_vad.onnx")
        return executable, self.model_root


def _directory(path: Path) -> None:
    try:
        for parent in reversed((path, *path.parents)):
            entry = parent.lstat()
            trusted_parent_group = (parent != path and entry.st_uid == os.getuid()
                                    and entry.st_gid == os.getgid() and not entry.st_mode & 0o002)
            if not stat.S_ISDIR(entry.st_mode) or (entry.st_mode & 0o022 and not trusted_parent_group):
                # /tmp is an explicitly disposable test parent, never an asset root.
                if parent != Path("/tmp") or parent == path:
                    raise RecognitionError("runtime_unavailable")
        if path.stat().st_uid not in {0, os.getuid()}:
            raise RecognitionError("runtime_unavailable")
    except OSError:
        raise RecognitionError("runtime_unavailable") from None


def _regular(path: Path, *, interpreter: bool = False) -> None:
    try:
        entry = path.lstat()
        if (
            not stat.S_ISREG(entry.st_mode) or entry.st_mode & 0o022
            or (not interpreter and entry.st_uid not in {0, os.getuid()})
        ):
            raise RecognitionError("runtime_unavailable")
    except OSError:
        raise RecognitionError("runtime_unavailable") from None


def _asset_tree(root: Path) -> None:
    # Extra vocabulary/config/license assets may also be read by the engine.
    # Validate their no-follow metadata, not only the four required filenames.
    pending = [root]
    count = 0
    try:
        while pending:
            directory = pending.pop()
            for entry in directory.iterdir():
                count += 1
                if count > 256:
                    raise RecognitionError("runtime_unavailable")
                if stat.S_ISDIR(entry.lstat().st_mode):
                    _directory(entry)
                    pending.append(entry)
                else:
                    _regular(entry)
    except OSError:
        raise RecognitionError("runtime_unavailable") from None
