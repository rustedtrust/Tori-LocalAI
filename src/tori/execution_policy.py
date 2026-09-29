"""Durable exact policy and one-use authority for future Tori terminal requests.

This module never launches a process. Callers must keep approval and spawn behind
application-owned boundaries; model and tool output are not authority sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import sqlite3
import stat
import threading
import time
from urllib.parse import quote


DEFAULT_POLICY_DATABASE = Path("runtime/supervised_terminal/tori_execution_policy.db")
POLICY_SCHEMA_VERSION = 1
_MAX_COMMAND = 2_000
_MAX_OWNER = 256
_MAX_ENV = 16
_TOKEN_TTL = 300


class PolicyError(RuntimeError):
    """Safe policy/authority failure; no process was authorized."""


class PolicyClass(str, Enum):
    BLACKLIST = "BLACKLIST"
    ALWAYS_ASK = "ALWAYS_ASK"
    WHITELIST = "WHITELIST"
    DEFAULT_ASK = "DEFAULT_ASK"


class ExecutionScope(str, Enum):
    HOST_USER = "HOST_USER"
    PROJECT_SANDBOX = "PROJECT_SANDBOX"


def _canonical(document: object) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lex(command: str) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = tuple(lexer)
    except ValueError:
        return (), (), True
    operators = tuple(token for token in tokens if token and all(c in ";&|<>()" for c in token))
    if "\n" in command or "\r" in command:
        operators += ("newline",)
    # Shell expansion is opaque even if the lexical argv appears benign.
    opaque = bool(re.search(r"\$[{(A-Za-z_0-9?*!@#-]|`|[?*\[]", command))
    return tokens, operators, opaque


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    command: str
    argv: tuple[str, ...]
    shell_operators: tuple[str, ...]
    opaque: bool
    cwd: str
    scope: ExecutionScope
    environment_names: tuple[str, ...]
    environment_digest: str
    origin: str

    def __post_init__(self) -> None:
        lexical = _lex(self.command) if isinstance(self.command, str) else None
        if (
            lexical is None
            or not self.command or self.command != self.command.strip()
            or "\x00" in self.command or len(self.command) > _MAX_COMMAND
            or (self.argv, self.shell_operators, self.opaque) != lexical
            or not isinstance(self.scope, ExecutionScope)
            or self.origin not in {"tori", "untrusted_output", "human_terminal"}
            or not isinstance(self.cwd, str) or not Path(self.cwd).is_absolute()
            or not isinstance(self.environment_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.environment_digest)
        ):
            raise PolicyError("The execution request representation is invalid.")

    @classmethod
    def create(
        cls, command: str, cwd: str | Path, scope: ExecutionScope,
        *, environment: dict[str, str] | None = None, origin: str = "tori",
    ) -> ExecutionRequest:
        if (
            not isinstance(command, str) or not command or command != command.strip()
            or "\x00" in command or len(command) > _MAX_COMMAND
            or not isinstance(scope, ExecutionScope)
            or origin not in {"tori", "untrusted_output", "human_terminal"}
        ):
            raise PolicyError("The execution request is invalid.")
        directory = Path(cwd)
        if not directory.is_absolute() or ".." in directory.parts:
            raise PolicyError("An absolute working directory is required.")
        # Resolving a cwd is identity normalization, not a sandbox guarantee.
        try:
            resolved = directory.resolve(strict=True)
        except OSError as exc:
            raise PolicyError("The working directory is unavailable.") from exc
        if not resolved.is_dir():
            raise PolicyError("The working directory is unavailable.")
        requested = {} if environment is None else environment
        if (
            not isinstance(requested, dict) or len(requested) > _MAX_ENV
            or any(
                not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key)
                or not isinstance(value, str) or "\x00" in value or len(value) > 4096
                for key, value in requested.items()
            )
        ):
            raise PolicyError("The requested environment is invalid.")
        argv, operators, opaque = _lex(command)
        return cls(
            command, argv, operators, opaque, str(resolved), scope,
            tuple(sorted(requested)), _digest(_canonical(requested)), origin,
        )

    @property
    def matcher(self) -> dict[str, object]:
        return {
            "version": 1, "command": self.command, "cwd": self.cwd,
            "scope": self.scope.value, "environment_names": list(self.environment_names),
            "environment_digest": self.environment_digest,
        }

    @property
    def identity_digest(self) -> str:
        return _digest(_canonical(self.matcher))


@dataclass(frozen=True, slots=True)
class PolicyRule:
    identifier: str
    policy_class: PolicyClass
    matcher: dict[str, object]
    source: str
    enabled: bool
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    outcome: PolicyClass
    rule_id: str | None
    source: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionGrant:
    token: str
    request_digest: str
    owner_digest: str
    expires_at: float


_SCHEMA = """
CREATE TABLE policy_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE policy_rules (
    identifier TEXT PRIMARY KEY,
    policy_class TEXT NOT NULL,
    matcher_json TEXT NOT NULL,
    matcher_digest TEXT NOT NULL,
    source TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX policy_rules_matcher ON policy_rules(matcher_digest);
CREATE TABLE execution_grants (
    token_digest TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    owner_digest TEXT NOT NULL,
    scope TEXT NOT NULL,
    expires_at REAL NOT NULL,
    approved INTEGER NOT NULL CHECK(approved IN (0,1)),
    provenance TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','consumed')),
    created_at REAL NOT NULL,
    consumed_at REAL
);
"""


def _high_risk_reason(request: ExecutionRequest) -> str | None:
    argv = request.argv
    if not argv:
        return "Shell syntax could not be parsed conservatively."
    if re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", argv[0]):
        return "Inline environment assignments bypass explicit environment metadata."
    if argv[0] in {".", "!"}:
        return "Shell builtins can hide or execute another command."
    executable = Path(argv[0]).name.casefold()
    if executable in {"sudo", "su"}:
        return "Privilege or account switching requires each-time approval."
    if executable in {"env", "xargs", "find", "nohup", "timeout", "command", "exec", "builtin", "eval", "source", "time"}:
        return "Command-launching wrappers can hide the executed program."
    if executable in {"sh", "bash", "dash", "zsh", "fish", "ksh"}:
        return "Shell invocation, including -c and script forms, can execute arbitrary code."
    if executable in {"python", "python3", "node", "perl", "ruby", "php"} or re.fullmatch(r"python3?\.\d+", executable):
        return "Interpreter invocation, including eval and script forms, can execute arbitrary code."
    if executable in {"rm", "shred", "dd", "wipefs", "fdisk", "parted", "sfdisk"} or executable.startswith("mkfs"):
        return "Destructive filesystem or storage command requires each-time approval."
    if executable in {"apt", "apt-get", "dnf", "pacman", "pip", "pip3", "npm", "systemctl", "mount", "umount"}:
        return "Package, service, or mount changes require each-time approval."
    if request.shell_operators:
        return "Shell control operators or redirection require each-time approval."
    if request.opaque:
        return "Shell expansion or substitution makes the effects opaque."
    return None


class ExecutionPolicyService:
    """The single durable decision authority for generalized Tori commands.

    Read-only calls do not create an absent database. A malformed existing store
    fails closed. No method executes a process or accepts output as authority.
    """

    def __init__(self, path: Path = DEFAULT_POLICY_DATABASE, *, clock=time.time) -> None:
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()

    def _safe_path(self) -> Path | None:
        if ".." in self.path.parts or "\x00" in os.fspath(self.path):
            raise PolicyError("The policy path is unsafe.")
        target = Path(os.path.abspath(self.path))
        current = Path(target.anchor)
        for part in target.parts[1:-1]:
            current /= part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                break
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise PolicyError("The policy path is unsafe.")
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise PolicyError("The policy database is unsafe.")
        return target

    def _connect(self, *, write: bool) -> sqlite3.Connection | None:
        existing = self._safe_path()
        if existing is None and not write:
            return None
        if existing is None:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self._safe_path() is not None:
                raise PolicyError("The policy path changed during creation.")
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    0o600,
                )
                os.close(descriptor)
            except OSError as exc:
                raise PolicyError("The policy database could not be created safely.") from exc
        try:
            if write:
                connection = sqlite3.connect(self.path, timeout=5)
            else:
                uri = f"file:{quote(os.fspath(existing), safe='/')}?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=5)
            connection.execute("PRAGMA foreign_keys=ON")
            if existing is None:
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute("PRAGMA secure_delete=ON")
                connection.executescript(_SCHEMA)
                connection.execute(
                    "INSERT INTO policy_metadata VALUES ('schema_version',?)",
                    (str(POLICY_SCHEMA_VERSION),),
                )
                connection.commit()
            self._validate(connection)
            return connection
        except (sqlite3.Error, OSError, PolicyError) as exc:
            if "connection" in locals():
                connection.close()
            raise PolicyError("The execution policy store is unavailable or incompatible.") from exc

    @staticmethod
    def _validate(connection: sqlite3.Connection) -> None:
        metadata = connection.execute("SELECT key,value FROM policy_metadata").fetchall()
        if metadata != [("schema_version", str(POLICY_SCHEMA_VERSION))]:
            raise PolicyError("The execution policy schema is incompatible.")
        expected = {"policy_metadata", "policy_rules", "execution_grants"}
        actual = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        if actual != expected:
            raise PolicyError("The execution policy schema is incompatible.")
        columns = {
            "policy_rules": ("identifier", "policy_class", "matcher_json", "matcher_digest", "source", "enabled", "created_at", "updated_at"),
            "execution_grants": ("token_digest", "request_digest", "owner_digest", "scope", "expires_at", "approved", "provenance", "state", "created_at", "consumed_at"),
        }
        for table, names in columns.items():
            if tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})")) != names:
                raise PolicyError("The execution policy schema is incompatible.")
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise PolicyError("The execution policy store is corrupt.")

    def _rows(self) -> list[tuple[object, ...]]:
        connection = self._connect(write=False)
        if connection is None:
            return []
        try:
            return connection.execute("SELECT * FROM policy_rules ORDER BY created_at,identifier").fetchall()
        except sqlite3.Error as exc:
            raise PolicyError("The execution policy rules could not be read.") from exc
        finally:
            connection.close()

    @staticmethod
    def _rule(row: tuple[object, ...]) -> PolicyRule:
        try:
            identifier, value, matcher_json, digest, source, enabled, created, updated = row
            matcher = json.loads(matcher_json)
            if (
                not isinstance(matcher, dict) or _digest(_canonical(matcher)) != digest
                or source not in {"user", "legacy"} or enabled not in {0, 1}
                or not isinstance(identifier, str) or not identifier.startswith("policy-")
            ):
                raise ValueError("invalid matcher")
            return PolicyRule(str(identifier), PolicyClass(value), matcher, str(source), bool(enabled), float(created), float(updated))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PolicyError("A persisted execution rule is malformed.") from exc

    def list_rules(self) -> tuple[PolicyRule, ...]:
        with self._lock:
            return tuple(self._rule(row) for row in self._rows())

    @classmethod
    def _whitelist_blocked(
        cls, request: ExecutionRequest, rows: list[tuple[object, ...]],
        *, exclude_id: str | None = None,
    ) -> bool:
        if _high_risk_reason(request) is not None:
            return True
        for row in rows:
            if row[0] == exclude_id or row[3] != request.identity_digest or row[5] != 1:
                continue
            try:
                rule = cls._rule(row)
            except PolicyError:
                return True
            if rule.matcher != request.matcher or rule.policy_class is PolicyClass.ALWAYS_ASK:
                return True
        return False

    def evaluate(self, request: ExecutionRequest) -> PolicyDecision:
        if not isinstance(request, ExecutionRequest) or request.origin != "tori":
            raise PolicyError("Only a Tori-originated request can be evaluated for Tori execution.")
        with self._lock:
            rows = self._rows()
        return self._decision_from_rows(request, rows)

    @classmethod
    def _decision_from_rows(
        cls, request: ExecutionRequest, rows: list[tuple[object, ...]]
    ) -> PolicyDecision:
        matches: list[PolicyRule] = []
        for row in rows:
            try:
                rule = cls._rule(row)
            except PolicyError:
                return PolicyDecision(PolicyClass.BLACKLIST, str(row[0]), "corrupt", "A persisted rule is malformed; execution is blocked.")
            if not rule.enabled or row[3] != request.identity_digest:
                continue
            if rule.matcher != request.matcher:
                return PolicyDecision(PolicyClass.BLACKLIST, rule.identifier, "corrupt", "A matching persisted rule conflicts with its identity; execution is blocked.")
            matches.append(rule)
        for policy_class in (PolicyClass.BLACKLIST, PolicyClass.ALWAYS_ASK):
            selected = next((rule for rule in matches if rule.policy_class is policy_class), None)
            if selected is not None:
                return PolicyDecision(policy_class, selected.identifier, selected.source, f"Exact {policy_class.value} rule matched.")
        high_risk = _high_risk_reason(request)
        if high_risk is not None:
            return PolicyDecision(PolicyClass.ALWAYS_ASK, "application.high_risk", "application", high_risk)
        selected = next((rule for rule in matches if rule.policy_class is PolicyClass.WHITELIST), None)
        if selected is not None:
            return PolicyDecision(PolicyClass.WHITELIST, selected.identifier, selected.source, "Exact WHITELIST rule matched.")
        return PolicyDecision(PolicyClass.DEFAULT_ASK, None, "default", "No enabled exact rule matched.")

    def create_rule(self, request: ExecutionRequest, policy_class: PolicyClass, *, source: str = "user", enabled: bool = True) -> PolicyRule:
        if not isinstance(policy_class, PolicyClass) or policy_class is PolicyClass.DEFAULT_ASK or source not in {"user", "legacy"}:
            raise PolicyError("The policy rule is invalid.")
        with self._lock:
            stamp = float(self._clock())
            identifier = "policy-" + secrets.token_hex(16)
            connection = self._connect(write=True)
            assert connection is not None
            try:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    rows = connection.execute("SELECT * FROM policy_rules").fetchall()
                    if policy_class is PolicyClass.WHITELIST and self._whitelist_blocked(request, rows):
                        raise PolicyError("An Always Ask request cannot be whitelisted.")
                    connection.execute(
                        "INSERT INTO policy_rules VALUES (?,?,?,?,?,?,?,?)",
                        (identifier, policy_class.value, _canonical(request.matcher), request.identity_digest, source, int(enabled), stamp, stamp),
                    )
            except sqlite3.Error as exc:
                raise PolicyError("The policy rule could not be saved.") from exc
            finally:
                connection.close()
            return next(rule for rule in self.list_rules() if rule.identifier == identifier)

    def update_rule(self, identifier: str, request: ExecutionRequest, policy_class: PolicyClass, *, enabled: bool = True) -> PolicyRule:
        with self._lock:
            existing = next((rule for rule in self.list_rules() if rule.identifier == identifier), None)
            if existing is None or existing.source != "user":
                raise PolicyError("That editable policy rule was not found.")
            if not isinstance(policy_class, PolicyClass) or policy_class is PolicyClass.DEFAULT_ASK:
                raise PolicyError("The policy rule is invalid.")
            connection = self._connect(write=True)
            assert connection is not None
            try:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    rows = connection.execute("SELECT * FROM policy_rules").fetchall()
                    if policy_class is PolicyClass.WHITELIST and self._whitelist_blocked(request, rows, exclude_id=identifier):
                        raise PolicyError("An Always Ask request cannot be whitelisted.")
                    connection.execute(
                        "UPDATE policy_rules SET policy_class=?,matcher_json=?,matcher_digest=?,enabled=?,updated_at=? WHERE identifier=?",
                        (policy_class.value, _canonical(request.matcher), request.identity_digest, int(enabled), float(self._clock()), identifier),
                    )
            except sqlite3.Error as exc:
                raise PolicyError("The policy rule could not be updated.") from exc
            finally:
                connection.close()
            return next(rule for rule in self.list_rules() if rule.identifier == identifier)

    def remove_rule(self, identifier: str) -> None:
        with self._lock:
            existing = next((rule for rule in self.list_rules() if rule.identifier == identifier), None)
            if existing is None or existing.source != "user":
                raise PolicyError("That editable policy rule was not found.")
            connection = self._connect(write=True)
            assert connection is not None
            try:
                with connection:
                    connection.execute("DELETE FROM policy_rules WHERE identifier=?", (identifier,))
            except sqlite3.Error as exc:
                raise PolicyError("The policy rule could not be removed.") from exc
            finally:
                connection.close()

    @staticmethod
    def _owner_digest(owner: str) -> str:
        if not isinstance(owner, str) or not owner or len(owner) > _MAX_OWNER:
            raise PolicyError("An owner/session binding is required.")
        return _digest(owner)

    def issue_grant(self, request: ExecutionRequest, owner: str, *, approved: bool = False, provenance: str = "policy", lifetime_seconds: float = 60) -> ExecutionGrant:
        owner_digest = self._owner_digest(owner)
        if not 0 < lifetime_seconds <= _TOKEN_TTL or not isinstance(approved, bool) or not isinstance(provenance, str) or not provenance or len(provenance) > 128:
            raise PolicyError("The execution grant is invalid.")
        with self._lock:
            decision = self.evaluate(request)
            if decision.outcome is PolicyClass.BLACKLIST:
                raise PolicyError("This request is blacklisted.")
            if decision.outcome is not PolicyClass.WHITELIST and not approved:
                raise PolicyError("Explicit approval is required for this execution.")
            stamp = float(self._clock())
            token = secrets.token_urlsafe(32)
            grant = ExecutionGrant(token, request.identity_digest, owner_digest, stamp + lifetime_seconds)
            connection = self._connect(write=True)
            assert connection is not None
            try:
                with connection:
                    connection.execute(
                        "INSERT INTO execution_grants VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                        (_digest(token), grant.request_digest, owner_digest, request.scope.value, grant.expires_at, int(approved), provenance, "pending", stamp),
                    )
            except sqlite3.Error as exc:
                raise PolicyError("The execution grant could not be recorded.") from exc
            finally:
                connection.close()
            return grant

    def consume_grant(self, token: str, request: ExecutionRequest, owner: str) -> bool:
        if not isinstance(token, str) or not token:
            return False
        if not isinstance(request, ExecutionRequest) or request.origin != "tori":
            raise PolicyError("Only a Tori-originated request can consume a grant.")
        owner_digest = self._owner_digest(owner)
        with self._lock:
            connection = self._connect(write=False)
            if connection is None:
                return False
            connection.close()
            connection = self._connect(write=True)
            assert connection is not None
            try:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    rules = connection.execute(
                        "SELECT * FROM policy_rules ORDER BY created_at,identifier"
                    ).fetchall()
                    decision = self._decision_from_rows(request, rules)
                    row = connection.execute(
                        "SELECT request_digest,owner_digest,scope,expires_at,approved,state FROM execution_grants WHERE token_digest=?",
                        (_digest(token),),
                    ).fetchone()
                    if row is None or row[5] != "pending":
                        return False
                    # A presented token is spent even if its binding or policy changed.
                    connection.execute(
                        "UPDATE execution_grants SET state='consumed',consumed_at=? WHERE token_digest=? AND state='pending'",
                        (float(self._clock()), _digest(token)),
                    )
                    return bool(
                        row[0] == request.identity_digest
                        and row[1] == owner_digest
                        and row[2] == request.scope.value
                        and float(row[3]) > float(self._clock())
                        and decision.outcome is not PolicyClass.BLACKLIST
                        and (decision.outcome is PolicyClass.WHITELIST or row[4] == 1)
                    )
            except sqlite3.Error as exc:
                raise PolicyError("The execution grant could not be consumed safely.") from exc
            finally:
                connection.close()
