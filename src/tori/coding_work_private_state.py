"""Import stopped OpenCode snapshot output through a pinned, per-launch scope.

Not a runtime repair tool: a scope must be armed on an already-private tree
before an owned worker starts, then finalized only after its writers stop.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .coding_worker import CodingWorkerError


def _unsafe() -> CodingWorkerError:
    return CodingWorkerError(
        "OpenCode snapshot output could not be finalized safely.",
        code="private_state_import_unsafe",
    )


def _directory(parent: int, name: str) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid,
            metadata.st_gid, metadata.st_nlink, metadata.st_size, metadata.st_mtime_ns)


class SnapshotImport:
    """One-use authority tied to the exact pre-launch snapshot directory inode."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._fd = -1
        if (not root.is_absolute() or ".." in root.parts
                or tuple(root.parts[-4:]) != ("state", "data", "opencode", "snapshot")):
            raise _unsafe()
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                child = _directory(descriptor, part)
                os.close(descriptor)
                descriptor = child
            self._fd = descriptor
            self._root_identity = _identity(os.fstat(descriptor))[:2]
            self._scan(private_only=True)
        except BaseException:
            os.close(descriptor)
            self._fd = -1
            raise

    def close(self) -> None:
        descriptor, self._fd = self._fd, -1
        if descriptor >= 0:
            os.close(descriptor)

    def _scan(self, *, private_only: bool) -> list[tuple[tuple[str, ...], tuple[int, ...]]]:
        records: list[tuple[tuple[str, ...], tuple[int, ...]]] = []
        count = 0

        def walk(descriptor: int, relative: tuple[str, ...]) -> None:
            nonlocal count
            directory = os.fstat(descriptor)
            if (directory.st_uid != os.geteuid() or directory.st_gid != os.getegid()
                    or stat.S_IMODE(directory.st_mode) != 0o700 or len(relative) > 64):
                raise _unsafe()
            names = []
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    count += 1
                    if count > 50_000:
                        raise _unsafe()
                    names.append(entry.name)
            for name in sorted(names):
                metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                path = relative + (name,)
                if stat.S_ISDIR(metadata.st_mode):
                    child = _directory(descriptor, name)
                    try:
                        if _identity(os.fstat(child)) != _identity(metadata):
                            raise _unsafe()
                        walk(child, path)
                    finally:
                        os.close(child)
                else:
                    allowed = {0o600} if private_only else {0o400, 0o444, 0o600, 0o644, 0o664, 0o700}
                    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                            or metadata.st_uid != os.geteuid() or metadata.st_gid != os.getegid()
                            or stat.S_IMODE(metadata.st_mode) not in allowed):
                        raise _unsafe()
                    records.append((path, _identity(metadata)))

        if self._fd < 0:
            raise _unsafe()
        walk(self._fd, ())
        return records

    def finish(self) -> None:
        """Validate all incoming objects, then change only pinned regular-file modes."""
        try:
            # Re-open every ancestor without following links; a moved/replaced
            # root must not turn the recorded scope into authority elsewhere.
            descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in self.root.parts[1:]:
                    child = _directory(descriptor, part)
                    os.close(descriptor)
                    descriptor = child
                if _identity(os.fstat(descriptor))[:2] != self._root_identity:
                    raise _unsafe()
            finally:
                os.close(descriptor)
            records = self._scan(private_only=False)
            for path, expected in records:
                parent = os.dup(self._fd)
                try:
                    for part in path[:-1]:
                        child = _directory(parent, part)
                        os.close(parent)
                        parent = child
                    descriptor = os.open(path[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        if _identity(os.fstat(descriptor)) != expected:
                            raise _unsafe()
                        if stat.S_IMODE(expected[2]) != 0o600:
                            os.fchmod(descriptor, 0o600)
                            os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                finally:
                    os.close(parent)
            self._scan(private_only=True)
        except OSError as exc:
            raise _unsafe() from exc
        finally:
            self.close()
