"""Local-only administration for Remote Chat private configuration."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import getpass
import json

from .remote_chat_config import RemoteChatConfigStore, RemoteConfigError


def main(
    argv: Sequence[str] | None = None,
    *,
    store: RemoteChatConfigStore | None = None,
    secret_reader: Callable[[str], str] = getpass.getpass,
) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    private = store or RemoteChatConfigStore()
    try:
        if arguments.command == "status":
            _print_status(private.combined_status())
        elif arguments.command == "configure-identity":
            for label, value in (
                ("application ID", arguments.application_id),
                ("bot user ID", arguments.bot_user_id),
                ("installation ID", arguments.installation_id),
                ("owner user ID", arguments.owner_user_id),
                ("DM channel ID", arguments.dm_channel_id),
            ):
                if value is not None:
                    _require_discord_id(value, label)
            private.configure_identity(
                connector_id=arguments.connector_id,
                application_id=arguments.application_id,
                bot_user_id=arguments.bot_user_id,
                installation_id=arguments.installation_id,
                owner_user_id=arguments.owner_user_id,
                dm_channel_id=arguments.dm_channel_id,
            )
            print("Remote Chat identity configuration replaced; Remote Chat remains disabled.")
        elif arguments.command == "set-token":
            first = secret_reader("Remote Chat token: ")
            second = secret_reader("Repeat Remote Chat token: ")
            if first != second:
                raise RemoteConfigError("Remote Chat token entries did not match.")
            private.set_token(first)
            print("Remote Chat token replaced; its value cannot be read back and Remote Chat remains disabled.")
        elif arguments.command == "clear-token":
            private.clear_token()
            print("Remote Chat token cleared; Remote Chat remains disabled.")
        elif arguments.command == "permit":
            private.set_administrator_ceiling(True)
            print("Remote Chat administrator ceiling permitted; owner enablement is still required.")
        elif arguments.command == "revoke":
            private.set_administrator_ceiling(False)
            print("Remote Chat administrator ceiling revoked and Remote Chat disabled.")
        elif arguments.command == "enable":
            private.set_enabled(True)
            print("Remote Chat owner enablement is on.")
        elif arguments.command in {"disable", "kill"}:
            private.set_enabled(False)
            print("Remote Chat owner enablement is off.")
        else:  # pragma: no cover - argparse owns this boundary
            parser.error("a Remote Chat administration command is required")
    except RemoteConfigError as exc:
        print(f"Remote Chat configuration error: {exc}")
        return 2
    return 0


def _print_status(document: dict[str, object]) -> None:
    safe = dict(document)
    if "token" in safe:
        raise RemoteConfigError("Remote Chat status attempted to disclose a secret.")
    print(json.dumps(safe, sort_keys=True, indent=2))


def _require_discord_id(value: str, label: str) -> None:
    if (
        not value.isascii()
        or not value.isdecimal()
        or value != str(int(value))
        or not 0 < int(value) < 2**64
    ):
        raise RemoteConfigError(f"Discord {label} must be a canonical numeric ID.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tori-remote-chat",
        description="Administer Tori Remote Chat locally without starting a transport.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "status", help="Show redacted configuration and live connector status."
    )
    identity = commands.add_parser(
        "configure-identity", help="Replace bounded connector and owner identifiers."
    )
    identity.add_argument("--connector-id", required=True)
    identity.add_argument("--application-id", required=True)
    identity.add_argument("--bot-user-id", required=True)
    identity.add_argument("--installation-id", required=True)
    identity.add_argument("--owner-user-id", required=True)
    identity.add_argument("--dm-channel-id")
    commands.add_parser("set-token", help="Prompt twice without echo and replace the token.")
    commands.add_parser("clear-token", help="Clear the token and disable Remote Chat.")
    commands.add_parser("permit", help="Raise the local administrator ceiling only.")
    commands.add_parser("revoke", help="Lower the administrator ceiling and disable.")
    commands.add_parser("enable", help="Enable only beneath a complete permitted configuration.")
    commands.add_parser("disable", help="Disable owner enablement.")
    commands.add_parser("kill", help="Persist local disablement for the running kill switch.")
    return parser
