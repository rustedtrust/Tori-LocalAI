"""Durable owner-private Remote Chat admission and delivery ledger."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib, json, os, secrets, sqlite3, stat
from pathlib import Path
from urllib.parse import quote
from .remote_chat_transport import RemoteInboundEnvelope

REMOTE_LEDGER_SCHEMA_VERSION = 2
DEFAULT_REMOTE_LEDGER = Path("runtime/remote_chat/tori_remote_chat.db")
INBOUND_STATES = frozenset({"accepted", "processing", "reconciliation_required", "completed", "failed", "cancelled"})
OUTBOUND_STATES = frozenset({"pending", "sending", "delivered_acknowledged", "ambiguous", "failed", "suppressed"})

class RemoteLedgerError(RuntimeError):
    code = "remote_ledger_error"

class RemoteAdmissionConflict(RemoteLedgerError):
    code = "remote_identity_conflict"

@dataclass(frozen=True, slots=True)
class InboundRecord:
    transport: str
    connector_id: str
    external_message_id: str
    external_actor_id: str
    external_conversation_id: str
    immutable_hash: str
    text: str | None
    received_at: str
    admitted_at: str
    receipt_order: int
    state: str
    connector_generation: int
    archive_base_revision: int | None
    archive_completed_revision: int | None
    error_code: str | None

@dataclass(frozen=True, slots=True)
class OutboundRecord:
    application_request_id: str
    inbound_transport: str
    inbound_connector_id: str
    inbound_external_message_id: str
    destination_id: str
    text: str | None
    text_hash: str
    state: str
    connector_generation: int
    chunk_count: int
    error_code: str | None

@dataclass(frozen=True, slots=True)
class OutboundChunkRecord:
    chunk_id: str
    application_request_id: str
    chunk_index: int
    text: str | None
    text_hash: str
    state: str
    connector_generation: int
    external_message_id: str | None
    error_code: str | None
    inbound_connector_id: str
    destination_id: str

_SCHEMA = """
CREATE TABLE remote_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE remote_binding (
 singleton INTEGER PRIMARY KEY CHECK (singleton = 1), chat_id TEXT NOT NULL UNIQUE,
 provenance_event_id TEXT NOT NULL UNIQUE,
 binding_state TEXT NOT NULL CHECK (binding_state IN ('reserved', 'bound')),
 binding_generation INTEGER NOT NULL CHECK (binding_generation >= 1), dm_channel_id TEXT
);
CREATE TABLE remote_inbound (
 transport TEXT NOT NULL, connector_id TEXT NOT NULL, external_message_id TEXT NOT NULL,
 external_actor_id TEXT NOT NULL, external_conversation_id TEXT NOT NULL,
 immutable_hash TEXT NOT NULL, text TEXT, received_at TEXT NOT NULL, admitted_at TEXT NOT NULL,
 receipt_order INTEGER NOT NULL UNIQUE CHECK (receipt_order >= 1),
 state TEXT NOT NULL CHECK (state IN ('accepted','processing','reconciliation_required','completed','failed','cancelled')),
 connector_generation INTEGER NOT NULL CHECK (connector_generation >= 1),
 archive_base_revision INTEGER, archive_completed_revision INTEGER, error_code TEXT,
 PRIMARY KEY (transport, connector_id, external_message_id)
);
CREATE INDEX remote_inbound_fifo ON remote_inbound(state, receipt_order);
CREATE TABLE remote_outbound (
 application_request_id TEXT PRIMARY KEY, inbound_transport TEXT NOT NULL,
 inbound_connector_id TEXT NOT NULL, inbound_external_message_id TEXT NOT NULL,
 destination_id TEXT NOT NULL, text TEXT, text_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('pending','sending','delivered_acknowledged','ambiguous','failed','suppressed')),
 connector_generation INTEGER NOT NULL CHECK (connector_generation >= 1),
 chunk_count INTEGER NOT NULL CHECK (chunk_count >= 1), error_code TEXT,
 FOREIGN KEY (inbound_transport, inbound_connector_id, inbound_external_message_id)
  REFERENCES remote_inbound(transport, connector_id, external_message_id)
);
CREATE TABLE remote_outbound_chunk (
 chunk_id TEXT PRIMARY KEY, application_request_id TEXT NOT NULL,
 chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0), text TEXT, text_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('pending','sending','delivered_acknowledged','ambiguous','failed','suppressed')),
 connector_generation INTEGER NOT NULL CHECK (connector_generation >= 1),
 external_message_id TEXT, error_code TEXT, UNIQUE(application_request_id, chunk_index),
 FOREIGN KEY (application_request_id) REFERENCES remote_outbound(application_request_id)
);
CREATE INDEX remote_outbound_chunk_fifo ON remote_outbound_chunk(state, application_request_id, chunk_index);
"""

class _RemoteConnection(sqlite3.Connection):
    _safe_descriptors: tuple[int, ...] = ()
    def close(self) -> None:
        try: super().close()
        finally:
            descriptors, self._safe_descriptors = self._safe_descriptors, ()
            for descriptor in descriptors:
                try: os.close(descriptor)
                except OSError: pass

class RemoteChatLedger:
    """SQLite state machine with deterministic admission and chunk delivery truth."""
    def __init__(self, path: Path = DEFAULT_REMOTE_LEDGER) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        try:
            with closing(self._connect()) as connection: self._validate(connection)
        except (OSError, sqlite3.Error) as exc:
            raise RemoteLedgerError("Remote Chat ledger could not initialize safely.") from exc

    def reserve_chat(self, identifier: str | None = None) -> str:
        selected = identifier or f"chat-{secrets.token_hex(16)}"
        if len(selected) != 37 or not selected.startswith("chat-"):
            raise RemoteLedgerError("Remote Chat reservation identifier is invalid.")
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT chat_id FROM remote_binding WHERE singleton=1").fetchone()
            if row is not None: return str(row[0])
            provenance = f"event-{secrets.token_hex(16)}"
            connection.execute(
                "INSERT INTO remote_binding VALUES (1, ?, ?, 'reserved', ?, NULL)",
                (selected, provenance, self.generation(connection)))
        return selected

    def binding(self) -> tuple[str, str, int, str | None, str] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT chat_id,binding_state,binding_generation,dm_channel_id,provenance_event_id FROM remote_binding WHERE singleton=1").fetchone()
        return None if row is None else (str(row[0]), str(row[1]), int(row[2]), row[3], str(row[4]))

    def mark_chat_bound(self, chat_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE remote_binding SET binding_state='bound' WHERE singleton=1 AND chat_id=?", (chat_id,))
            if cursor.rowcount != 1: raise RemoteLedgerError("Remote Chat binding conflicts with its reservation.")

    def bind_dm(self, dm_channel_id: str) -> str:
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT dm_channel_id FROM remote_binding WHERE singleton=1").fetchone()
            if row is None: raise RemoteLedgerError("Remote Chat has no conversation reservation.")
            if row[0] is not None and row[0] != dm_channel_id:
                raise RemoteAdmissionConflict("Remote Chat DM identity changed unexpectedly.")
            if row[0] is None:
                connection.execute("UPDATE remote_binding SET dm_channel_id=? WHERE singleton=1", (dm_channel_id,))
        return dm_channel_id

    def current_generation(self) -> int:
        with closing(self._connect()) as connection: return self.generation(connection)

    @staticmethod
    def generation(connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT value FROM remote_metadata WHERE key='generation'").fetchone()
        if row is None or not str(row[0]).isdigit(): raise RemoteLedgerError("Remote Chat connector generation is invalid.")
        return int(row[0])

    def fence_generation(self, generation: int, *, code: str = "connector_fenced") -> int:
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("Remote Chat generation is invalid.")
        with closing(self._connect()) as connection, connection:
            current = self.generation(connection)
            if generation < current: raise RemoteLedgerError("Remote Chat connector generation cannot move backward.")
            if generation > current:
                connection.execute("UPDATE remote_metadata SET value=? WHERE key='generation'", (str(generation),))
            connection.execute(
                "UPDATE remote_inbound SET state='cancelled',error_code=?,text=NULL WHERE connector_generation<? AND state IN ('accepted','processing')",
                (code, generation))
            connection.execute(
                "UPDATE remote_outbound_chunk SET state='suppressed',error_code=?,text=NULL WHERE connector_generation<? AND state='pending'",
                (code, generation))
            connection.execute(
                "UPDATE remote_outbound_chunk SET state='ambiguous',error_code=? WHERE connector_generation<? AND state='sending'",
                (code + "_during_send", generation))
            self._refresh_all(connection)
        return generation

    def advance_generation_and_cancel(self) -> int:
        return self.fence_generation(self.current_generation() + 1, code="connector_killed")

    def admit(self, envelope: RemoteInboundEnvelope, generation: int) -> tuple[InboundRecord, bool]:
        immutable_hash, admitted_at = _envelope_hash(envelope), _now()
        with closing(self._connect()) as connection, connection:
            if generation != self.generation(connection): raise RemoteLedgerError("Remote Chat connector generation is stale.")
            key = (envelope.transport, envelope.connector_id, envelope.external_message_id)
            row = connection.execute(
                "SELECT * FROM remote_inbound WHERE transport=? AND connector_id=? AND external_message_id=?", key).fetchone()
            if row is not None:
                existing = _inbound(row)
                if existing.immutable_hash != immutable_hash:
                    raise RemoteAdmissionConflict("A Remote Chat message ID was replayed with changed immutable data.")
                return existing, False
            order = int(connection.execute("SELECT COALESCE(MAX(receipt_order),0)+1 FROM remote_inbound").fetchone()[0])
            connection.execute("""INSERT INTO remote_inbound VALUES
                (?,?,?,?,?,?,?,?,?,?,'accepted',?,NULL,NULL,NULL)""", (
                *key, envelope.external_actor_id, envelope.external_conversation_id,
                immutable_hash, envelope.text.strip(), envelope.received_at, admitted_at, order, generation))
            row = connection.execute(
                "SELECT * FROM remote_inbound WHERE transport=? AND connector_id=? AND external_message_id=?", key).fetchone()
        return _inbound(row), True

    def claim_next(self, archive_base_revision: int, generation: int | None = None) -> InboundRecord | None:
        with closing(self._connect()) as connection, connection:
            current = self.generation(connection); selected = current if generation is None else generation
            if selected != current: raise RemoteLedgerError("Remote Chat claim belongs to a stale generation.")
            row = connection.execute(
                "SELECT * FROM remote_inbound WHERE state='accepted' AND connector_generation=? ORDER BY receipt_order LIMIT 1", (selected,)).fetchone()
            if row is None: return None
            key = tuple(row[:3])
            cursor = connection.execute(
                "UPDATE remote_inbound SET state='processing',archive_base_revision=? WHERE transport=? AND connector_id=? AND external_message_id=? AND state='accepted' AND connector_generation=?",
                (archive_base_revision, *key, selected))
            if cursor.rowcount != 1: raise RemoteLedgerError("Remote Chat inbound claim was lost.")
            row = connection.execute(
                "SELECT * FROM remote_inbound WHERE transport=? AND connector_id=? AND external_message_id=?", key).fetchone()
        return _inbound(row)

    def complete(self, record: InboundRecord, *, archive_completed_revision: int, reply: str,
                 generation: int, chunks: tuple[str, ...] | None = None) -> OutboundRecord:
        request_id = "remote-send-" + hashlib.sha256(
            f"{record.transport}\0{record.connector_id}\0{record.external_message_id}".encode()).hexdigest()[:32]
        physical = chunks or (reply,)
        if not physical or any(not isinstance(item, str) or not item for item in physical):
            raise RemoteLedgerError("Remote Chat physical delivery plan is invalid.")
        with closing(self._connect()) as connection, connection:
            if self.generation(connection) != generation: raise RemoteLedgerError("Remote Chat completion belongs to a fenced generation.")
            cursor = connection.execute(
                "UPDATE remote_inbound SET state='completed',archive_completed_revision=?,error_code=NULL WHERE transport=? AND connector_id=? AND external_message_id=? AND state IN ('processing','reconciliation_required') AND connector_generation=?",
                (archive_completed_revision, record.transport, record.connector_id, record.external_message_id, generation))
            if cursor.rowcount != 1: raise RemoteLedgerError("Remote Chat completion no longer owns processing state.")
            connection.execute("""INSERT INTO remote_outbound VALUES
                (?,?,?,?,?,?,?,'pending',?,?,NULL)""", (
                request_id, record.transport, record.connector_id, record.external_message_id,
                record.external_conversation_id, reply, hashlib.sha256(reply.encode()).hexdigest(), generation, len(physical)))
            for index, text in enumerate(physical):
                chunk_id = f"{request_id}-chunk-{index + 1}"
                connection.execute("""INSERT INTO remote_outbound_chunk VALUES
                    (?,?,?,?,?,'pending',?,NULL,NULL)""", (
                    chunk_id, request_id, index, text, hashlib.sha256(text.encode()).hexdigest(), generation))
            row = connection.execute("SELECT * FROM remote_outbound WHERE application_request_id=?", (request_id,)).fetchone()
        return _outbound(row)

    def fail(self, record: InboundRecord, code: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE remote_inbound SET state='failed',error_code=?,text=NULL WHERE transport=? AND connector_id=? AND external_message_id=? AND state IN ('accepted','processing','reconciliation_required')",
                (code, record.transport, record.connector_id, record.external_message_id))

    def require_reconciliation(self, record: InboundRecord, code: str) -> None:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE remote_inbound SET state='reconciliation_required',error_code=? WHERE transport=? AND connector_id=? AND external_message_id=? AND state='processing'",
                (code, record.transport, record.connector_id, record.external_message_id))
            if cursor.rowcount != 1:
                raise RemoteLedgerError("Remote Chat reconciliation transition is stale.")

    def pending_outbound(self) -> tuple[OutboundRecord, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM remote_outbound WHERE state='pending' ORDER BY rowid").fetchall()
        return tuple(_outbound(row) for row in rows)

    def pending_chunks(self) -> tuple[OutboundChunkRecord, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("""SELECT c.*,o.inbound_connector_id,o.destination_id
                FROM remote_outbound_chunk c JOIN remote_outbound o USING(application_request_id)
                WHERE c.state='pending' ORDER BY o.rowid,c.chunk_index""").fetchall()
        return tuple(_chunk(row) for row in rows)

    def claim_chunk(self, chunk_id: str, generation: int) -> OutboundChunkRecord:
        with closing(self._connect()) as connection, connection:
            if self.generation(connection) != generation: raise RemoteLedgerError("Remote Chat send belongs to a fenced generation.")
            cursor = connection.execute(
                "UPDATE remote_outbound_chunk SET state='sending' WHERE chunk_id=? AND state='pending' AND connector_generation=?", (chunk_id, generation))
            if cursor.rowcount != 1: raise RemoteLedgerError("Remote Chat chunk is not sendable.")
            request_id = str(connection.execute("SELECT application_request_id FROM remote_outbound_chunk WHERE chunk_id=?", (chunk_id,)).fetchone()[0])
            self._refresh(connection, request_id)
            row = self._select_chunk(connection, chunk_id)
        return _chunk(row)

    def finish_chunk(self, chunk_id: str, *, state: str, external_message_id: str | None = None,
                     error_code: str | None = None) -> OutboundChunkRecord:
        if state not in {"delivered_acknowledged", "ambiguous", "failed", "suppressed"}:
            raise ValueError("Remote Chat terminal chunk state is invalid.")
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT application_request_id,chunk_index FROM remote_outbound_chunk WHERE chunk_id=?", (chunk_id,)).fetchone()
            if row is None: raise RemoteLedgerError("Remote Chat chunk does not exist.")
            request_id, index = str(row[0]), int(row[1])
            cursor = connection.execute(
                "UPDATE remote_outbound_chunk SET state=?,external_message_id=?,error_code=?,text=CASE WHEN ? THEN NULL ELSE text END WHERE chunk_id=? AND state IN ('pending','sending')",
                (state, external_message_id, error_code, int(state in {"delivered_acknowledged", "suppressed"}), chunk_id))
            if cursor.rowcount != 1: raise RemoteLedgerError("Remote Chat chunk transition is stale.")
            if state in {"ambiguous", "failed"}:
                connection.execute(
                    "UPDATE remote_outbound_chunk SET state='suppressed',error_code='earlier_chunk_not_acknowledged',text=NULL WHERE application_request_id=? AND chunk_index>? AND state='pending'", (request_id, index))
            self._refresh(connection, request_id)
            row = self._select_chunk(connection, chunk_id)
        return _chunk(row)

    def claim_outbound(self, request_id: str, generation: int) -> OutboundRecord:
        chunks = [x for x in self.pending_chunks() if x.application_request_id == request_id]
        if not chunks: raise RemoteLedgerError("Remote Chat outbound state is not sendable.")
        self.claim_chunk(chunks[0].chunk_id, generation)
        return next(x for x in self.outbound_records() if x.application_request_id == request_id)

    def finish_outbound(self, request_id: str, *, state: str, external_message_id: str | None = None,
                        error_code: str | None = None) -> OutboundRecord:
        chunks = self.outbound_chunks(request_id)
        target = next((x for x in chunks if x.state == "sending"), None) or next((x for x in chunks if x.state == "pending"), None)
        if target is None: raise RemoteLedgerError("Remote Chat outbound transition is stale.")
        self.finish_chunk(target.chunk_id, state=state, external_message_id=external_message_id, error_code=error_code)
        return next(x for x in self.outbound_records() if x.application_request_id == request_id)

    def outbound_chunks(self, request_id: str | None = None) -> tuple[OutboundChunkRecord, ...]:
        with closing(self._connect()) as connection:
            where, args = ("", ()) if request_id is None else ("WHERE c.application_request_id=?", (request_id,))
            rows = connection.execute(f"""SELECT c.*,o.inbound_connector_id,o.destination_id
                FROM remote_outbound_chunk c JOIN remote_outbound o USING(application_request_id)
                {where} ORDER BY o.rowid,c.chunk_index""", args).fetchall()
        return tuple(_chunk(row) for row in rows)

    def reconcile_uncertain_sends(self) -> int:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute("SELECT chunk_id,application_request_id,chunk_index FROM remote_outbound_chunk WHERE state='sending'").fetchall()
            for chunk_id, request_id, index in rows:
                connection.execute("UPDATE remote_outbound_chunk SET state='ambiguous',error_code='restart_during_send' WHERE chunk_id=?", (chunk_id,))
                connection.execute("UPDATE remote_outbound_chunk SET state='suppressed',error_code='earlier_chunk_ambiguous',text=NULL WHERE application_request_id=? AND chunk_index>? AND state='pending'", (request_id, index))
            self._refresh_all(connection)
        return len(rows)

    def processing_records(self) -> tuple[InboundRecord, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM remote_inbound WHERE state IN ('processing','reconciliation_required') ORDER BY receipt_order").fetchall()
        return tuple(_inbound(row) for row in rows)

    def inbound_records(self) -> tuple[InboundRecord, ...]:
        with closing(self._connect()) as connection: rows = connection.execute("SELECT * FROM remote_inbound ORDER BY receipt_order").fetchall()
        return tuple(_inbound(row) for row in rows)

    def outbound_records(self) -> tuple[OutboundRecord, ...]:
        with closing(self._connect()) as connection: rows = connection.execute("SELECT * FROM remote_outbound ORDER BY rowid").fetchall()
        return tuple(_outbound(row) for row in rows)

    def checkpoint(self) -> None:
        with closing(self._connect()) as connection: connection.execute("PRAGMA optimize")

    @staticmethod
    def _select_chunk(connection: sqlite3.Connection, chunk_id: str):
        return connection.execute("""SELECT c.*,o.inbound_connector_id,o.destination_id
            FROM remote_outbound_chunk c JOIN remote_outbound o USING(application_request_id)
            WHERE c.chunk_id=?""", (chunk_id,)).fetchone()

    @staticmethod
    def _refresh_all(connection: sqlite3.Connection) -> None:
        for (request_id,) in connection.execute("SELECT application_request_id FROM remote_outbound"):
            RemoteChatLedger._refresh(connection, str(request_id))

    @staticmethod
    def _refresh(connection: sqlite3.Connection, request_id: str) -> None:
        states = [str(row[0]) for row in connection.execute(
            "SELECT state FROM remote_outbound_chunk WHERE application_request_id=? ORDER BY chunk_index", (request_id,))]
        if not states: raise RemoteLedgerError("Remote Chat logical reply has no physical chunks.")
        if "ambiguous" in states: state, error = "ambiguous", "physical_delivery_ambiguous"
        elif "failed" in states: state, error = "failed", "physical_delivery_failed"
        elif "sending" in states: state, error = "sending", None
        elif "pending" in states: state, error = "pending", None
        elif all(x == "delivered_acknowledged" for x in states): state, error = "delivered_acknowledged", None
        else: state, error = "suppressed", "physical_delivery_suppressed"
        connection.execute("UPDATE remote_outbound SET state=?,error_code=?,text=CASE WHEN ? THEN NULL ELSE text END WHERE application_request_id=?",
                           (state, error, int(state in {"delivered_acknowledged", "suppressed"}), request_id))
        if state == "delivered_acknowledged":
            inbound = connection.execute("SELECT inbound_transport,inbound_connector_id,inbound_external_message_id FROM remote_outbound WHERE application_request_id=?", (request_id,)).fetchone()
            connection.execute("UPDATE remote_inbound SET text=NULL WHERE transport=? AND connector_id=? AND external_message_id=?", tuple(inbound))

    def _connect(self) -> sqlite3.Connection:
        parent = database = None; connection = None
        try:
            parent, name = self._open_parent(create=True)
            sidecars = {s: _stat_at(parent, name+s) for s in ("-journal", "-wal", "-shm")}
            existing = _stat_at(parent, name)
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            if existing is None:
                if any(sidecars.values()): raise OSError("orphaned Remote Chat ledger sidecar")
                self._initialize_then_publish(parent, name, flags); existing = _stat_at(parent, name)
            if existing is None or not _private_regular_file(existing): raise OSError("unsafe Remote Chat ledger entry")
            for suffix, info in sidecars.items():
                if (suffix == "-journal" and info is not None and info.st_nlink == 0
                        and stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                        and stat.S_IMODE(info.st_mode) == 0o600):
                    # SQLite may unlink its private rollback journal between
                    # the first no-follow stat and validation. Recheck the
                    # *path*: an absent entry is harmless; any replacement
                    # must still satisfy the full private-file check below.
                    info = _stat_at(parent, name + suffix)
                    sidecars[suffix] = info
                if info is not None and not _private_regular_file(info): raise OSError(f"unsafe Remote Chat ledger {suffix} sidecar")
            if sidecars["-wal"] is not None or sidecars["-shm"] is not None: raise OSError("unexpected WAL-mode ledger sidecar")
            database = os.open(name, flags, dir_fd=parent)
            if not _same_file(existing, os.fstat(database)): raise OSError("Remote Chat ledger changed during safe open")
            sqlite_path = f"/proc/self/fd/{parent}/{name}"
            readonly = sqlite3.connect("file:" + quote(sqlite_path, safe="/") + "?mode=ro", uri=True)
            try: self._validate(readonly)
            finally: readonly.close()
            connection = sqlite3.connect(sqlite_path, timeout=5.0, factory=_RemoteConnection)
            if not _same_file(os.fstat(database), _stat_at(parent, name)): raise OSError("Remote Chat ledger changed during SQLite open")
            self._apply_settings(connection); self._validate(connection); connection.row_factory = sqlite3.Row
            connection._safe_descriptors = (parent, database)
            return connection
        except RemoteLedgerError: raise
        except (OSError, sqlite3.Error) as exc: raise RemoteLedgerError("Remote Chat ledger is unavailable or unsafe.") from exc
        finally:
            if connection is None:
                for descriptor in (database, parent):
                    if descriptor is not None:
                        try: os.close(descriptor)
                        except OSError: pass

    def _initialize_then_publish(self, parent: int, name: str, flags: int) -> None:
        temporary = f".{name}.incomplete-{secrets.token_hex(16)}"; published = False; connection = None
        descriptor = os.open(temporary, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
        try:
            original = os.fstat(descriptor); sqlite_path = f"/proc/self/fd/{parent}/{temporary}"
            connection = sqlite3.connect(sqlite_path); self._apply_settings(connection)
            with connection:
                connection.executescript(_SCHEMA)
                connection.executemany("INSERT INTO remote_metadata VALUES (?,?)", (("schema_version", str(REMOTE_LEDGER_SCHEMA_VERSION)), ("generation", "1")))
            self._validate(connection); connection.close(); connection = None
            if any(_stat_at(parent, temporary+s) is not None for s in ("-journal", "-wal", "-shm")): raise OSError("initialization sidecar remains")
            if not _same_file(original, _stat_at(parent, temporary)): raise OSError("initialization entry changed")
            os.fsync(descriptor); os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            published = True; os.unlink(temporary, dir_fd=parent); os.fsync(parent)
        except BaseException as exc:
            if not published: raise RemoteLedgerError(f"Remote Chat ledger initialization failed; isolated artifact {temporary!r} was preserved.") from exc
            raise
        finally:
            if connection is not None: connection.close()
            os.close(descriptor)

    def _open_parent(self, *, create: bool) -> tuple[int, str]:
        raw = os.fspath(self.path)
        if not isinstance(raw, str) or "\0" in raw or ".." in Path(raw).parts: raise RemoteLedgerError("Remote Chat ledger path is unsafe.")
        absolute = Path(os.path.abspath(os.path.normpath(raw)))
        if not absolute.name: raise RemoteLedgerError("Remote Chat ledger path is unsafe.")
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open("/", flags)
        try:
            for index, part in enumerate(absolute.parent.parts[1:]):
                try: child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create: raise
                    try: os.mkdir(part, 0o700, dir_fd=descriptor)
                    except FileExistsError: pass
                    child = os.open(part, flags, dir_fd=descriptor)
                info = os.fstat(child)
                if not stat.S_ISDIR(info.st_mode): os.close(child); raise OSError("unsafe ledger ancestor")
                if index == len(absolute.parent.parts[1:])-1 and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
                    os.close(child); raise OSError("ledger directory is not owner-private")
                os.close(descriptor); descriptor = child
            return descriptor, absolute.name
        except BaseException: os.close(descriptor); raise

    @staticmethod
    def _apply_settings(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON"); connection.execute("PRAGMA secure_delete=ON"); connection.execute("PRAGMA journal_mode=DELETE")

    @staticmethod
    def _validate(connection: sqlite3.Connection) -> None:
        expected = {}
        for statement in _SCHEMA.split(";"):
            normalized = statement.strip()
            if normalized: expected[normalized.split()[2]] = normalized
        actual = {name: sql for kind,name,sql in connection.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_autoindex_%'") if kind in {"table","index"}}
        if set(actual) != set(expected) or any(not isinstance(actual[n], str) or _normalize_sql(actual[n]) != _normalize_sql(expected[n]) for n in expected):
            raise RemoteLedgerError("Remote Chat ledger schema is invalid.")
        version = connection.execute("SELECT value FROM remote_metadata WHERE key='schema_version'").fetchone()
        if version is None or version[0] != str(REMOTE_LEDGER_SCHEMA_VERSION): raise RemoteLedgerError("Remote Chat ledger schema is unsupported.")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise RemoteLedgerError("Remote Chat ledger integrity check failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None: raise RemoteLedgerError("Remote Chat ledger foreign keys are invalid.")

def _envelope_hash(envelope: RemoteInboundEnvelope) -> str:
    document = {n: getattr(envelope, n) for n in RemoteInboundEnvelope.__dataclass_fields__}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def _inbound(row: sqlite3.Row) -> InboundRecord: return InboundRecord(*tuple(row))
def _outbound(row: sqlite3.Row) -> OutboundRecord: return OutboundRecord(*tuple(row))
def _chunk(row: sqlite3.Row) -> OutboundChunkRecord: return OutboundChunkRecord(*tuple(row))
def _now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def _stat_at(parent: int, name: str) -> os.stat_result | None:
    try: return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError: return None
def _same_file(left: os.stat_result | None, right: os.stat_result | None) -> bool:
    return left is not None and right is not None and left.st_dev == right.st_dev and left.st_ino == right.st_ino and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
def _private_regular_file(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
def _normalize_sql(value: str) -> str: return " ".join(value.replace("\n", " ").split()).casefold()
