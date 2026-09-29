"""Metadata-only durable terminal lifecycle receipts; no PTY bytes or tickets."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat


DEFAULT_TERMINAL_RECEIPTS = Path("runtime/supervised_terminal/tori_terminal_receipts.db")


class TerminalReceiptError(RuntimeError):
    pass


class TerminalReceiptStore:
    def __init__(self, path: Path = DEFAULT_TERMINAL_RECEIPTS) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        target = Path(os.path.abspath(self.path))
        if ".." in self.path.parts or "\x00" in os.fspath(self.path):
            raise TerminalReceiptError("Unsafe terminal receipt path.")
        current = Path(target.anchor)
        for part in target.parts[1:-1]:
            current /= part
            try:
                mode = os.lstat(current).st_mode
            except FileNotFoundError:
                break
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise TerminalReceiptError("Unsafe terminal receipt path.")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise TerminalReceiptError("Terminal receipt directory is unavailable.") from exc
        created = False
        try:
            mode = os.lstat(self.path).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise TerminalReceiptError("Unsafe terminal receipt path.")
        except FileNotFoundError:
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(descriptor)
            except OSError as exc:
                raise TerminalReceiptError("Terminal receipt file is unavailable.") from exc
            created = True
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            if created:
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute("PRAGMA secure_delete=ON")
                connection.execute("CREATE TABLE receipt_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO receipt_metadata VALUES ('schema_version','2')")
                connection.execute("""CREATE TABLE terminal_receipts (
                session_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                owner_digest TEXT NOT NULL, grant_digest TEXT NOT NULL,
                scope TEXT NOT NULL, cwd TEXT NOT NULL, started_at REAL NOT NULL,
                ended_at REAL, exit_code INTEGER, termination_reason TEXT,
                state TEXT NOT NULL CHECK(state IN ('starting','running','exited','failed','interrupted')),
                conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                private_interval_count INTEGER NOT NULL DEFAULT 0
            )""")
                connection.commit()
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables != {"receipt_metadata", "terminal_receipts"}:
                raise TerminalReceiptError("Terminal receipt schema is incompatible.")
            version = connection.execute("SELECT key,value FROM receipt_metadata").fetchall()
            if version not in ([("schema_version", "1")], [("schema_version", "2")]):
                raise TerminalReceiptError("Terminal receipt schema is incompatible.")
            names = tuple(row[1] for row in connection.execute("PRAGMA table_info(terminal_receipts)"))
            base = ("session_id", "request_digest", "owner_digest", "grant_digest", "scope", "cwd", "started_at", "ended_at", "exit_code", "termination_reason", "state")
            if version == [("schema_version", "1")] and names == base:
                with connection:
                    connection.execute("ALTER TABLE terminal_receipts ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'legacy-unbound'")
                    connection.execute("ALTER TABLE terminal_receipts ADD COLUMN turn_id TEXT NOT NULL DEFAULT 'legacy-unbound'")
                    connection.execute("ALTER TABLE terminal_receipts ADD COLUMN private_interval_count INTEGER NOT NULL DEFAULT 0")
                    connection.execute("UPDATE receipt_metadata SET value='2' WHERE key='schema_version'")
                names = tuple(row[1] for row in connection.execute("PRAGMA table_info(terminal_receipts)"))
            if names != base + ("conversation_id", "turn_id", "private_interval_count"):
                raise TerminalReceiptError("Terminal receipt schema is incompatible.")
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise TerminalReceiptError("Terminal receipts are corrupt.")
            return connection
        except (sqlite3.Error, OSError, TerminalReceiptError) as exc:
            if "connection" in locals():
                connection.close()
            raise TerminalReceiptError("Terminal receipts are unavailable.") from exc

    def start(self, session_id: str, request_digest: str, owner_digest: str,
              grant_digest: str, scope: str, cwd: str, started_at: float,
              conversation_id: str, turn_id: str) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("""INSERT INTO terminal_receipts
                    (session_id,request_digest,owner_digest,grant_digest,scope,cwd,started_at,state,conversation_id,turn_id)
                    VALUES (?,?,?,?,?,?,?,'starting',?,?)""",
                    (session_id, request_digest, owner_digest, grant_digest, scope, cwd,
                     started_at, conversation_id, turn_id))
        except sqlite3.Error as exc:
            raise TerminalReceiptError("Terminal receipt start failed.") from exc

    def finish(self, session_id: str, *, state: str, ended_at: float,
               exit_code: int | None, reason: str | None) -> None:
        if state not in {"exited", "failed"}:
            raise TerminalReceiptError("Invalid terminal receipt state.")
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("UPDATE terminal_receipts SET state=?,ended_at=?,exit_code=?,termination_reason=? WHERE session_id=?",
                                   (state, ended_at, exit_code, reason, session_id))
        except sqlite3.Error as exc:
            raise TerminalReceiptError("Terminal receipt completion failed.") from exc

    def mark_running(self, session_id: str) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("UPDATE terminal_receipts SET state='running' WHERE session_id=?", (session_id,))
        except sqlite3.Error as exc:
            raise TerminalReceiptError("Terminal receipt update failed.") from exc

    def mark_private(self, session_id: str) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute("""UPDATE terminal_receipts
                    SET private_interval_count=private_interval_count+1
                    WHERE session_id=? AND state='running'""", (session_id,))
                if cursor.rowcount != 1:
                    raise TerminalReceiptError("Terminal private interval is unavailable.")
        except sqlite3.Error as exc:
            raise TerminalReceiptError("Terminal private interval update failed.") from exc

    def reconcile_restart(self, now: float) -> None:
        """Mark old ownership as unverified; never signal a stored PID."""
        if not os.path.lexists(self.path):
            return
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("UPDATE terminal_receipts SET state='interrupted',ended_at=?,termination_reason='backend_restart_unverified' WHERE state IN ('starting','running')", (now,))
        except sqlite3.Error as exc:
            raise TerminalReceiptError("Terminal receipt reconciliation failed.") from exc
