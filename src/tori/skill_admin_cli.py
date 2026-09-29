"""Local-only administration for staged instruction Agent Skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .agent_skills import (
    AgentInstructionSkillAdapter,
    AgentSkillAdministration,
    AgentSkillImporter,
    AgentSkillPackageStore,
    DEFAULT_AGENT_SKILL_PACKAGES,
)
from .request_origin import RequestOrigin
from .github_skills import (
    GitHubSkillAcquisitionService,
    GitHubSkillLifecycleService,
)
from .skills_sh import SkillsShDiscoveryService
from .skills import (
    DEFAULT_SKILL_DATABASE,
    SQLiteSkillRegistry,
    SkillApplicationService,
    SkillComponentKind,
    SkillError,
    SkillValidationError,
    SkillVersionRef,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    registry = SQLiteSkillRegistry(arguments.registry)
    packages = AgentSkillPackageStore(arguments.packages)
    importer = AgentSkillImporter()
    adapter = AgentInstructionSkillAdapter(packages)
    application = SkillApplicationService(
        registry, {SkillComponentKind.INSTRUCTION_ONLY: adapter}
    )
    administration = AgentSkillAdministration(application, packages)
    github = GitHubSkillLifecycleService(
        GitHubSkillAcquisitionService(importer), administration
    )
    discovery = SkillsShDiscoveryService()
    origin = RequestOrigin.local_cli()
    try:
        if arguments.command == "search":
            _emit(discovery.search(arguments.query, limit=arguments.limit, origin=origin).document())
            return 0
        if arguments.command == "inspect-url":
            _emit(github.inspect(arguments.url, origin=origin).document())
            return 0
        if arguments.command == "install-url":
            if not arguments.approve:
                parser.error(
                    "install-url requires --approve after reviewing inspect-url output"
                )
            proposal = github.propose_install(arguments.url, origin=origin)
            entry = github.decide_install(proposal.token, "confirm", origin=origin)
            assert entry is not None
            document = _entry_document(entry)
            document["inspection"] = proposal.summary.document()
            document["notice"] = (
                "Installed disabled. Use the separate enable command with the exact "
                "identity, version, digest, and registry revision after review."
            )
            _emit(document)
            return 0
        if arguments.command == "inspect":
            inspected = _inspect(importer, arguments)
            _emit(_inspection_document(inspected))
            return 0
        if not registry.exists:
            if arguments.command != "install":
                parser.error("the Skill registry does not exist; install a Skill first")
            registry.initialize()
        if arguments.command == "install":
            inspected = _inspect(importer, arguments)
            entry = administration.install(inspected, origin=origin)
            _emit(_entry_document(entry))
        elif arguments.command == "list":
            _emit([_entry_document(entry) for entry in registry.list_entries()])
        else:
            reference = SkillVersionRef(
                arguments.skill_id, arguments.version, arguments.digest
            )
            if arguments.command == "show":
                entry = registry.get(reference)
            elif arguments.command == "enable":
                entry = application.enable(
                    reference,
                    expected_revision=arguments.revision,
                    granted_permissions=(),
                    origin=origin,
                )
            elif arguments.command == "disable":
                entry = application.disable(
                    reference,
                    expected_revision=arguments.revision,
                    origin=origin,
                )
            else:  # pragma: no cover - argparse owns the command set
                raise AssertionError(arguments.command)
            _emit(_entry_document(entry))
        return 0
    except SkillError as exc:
        parser.exit(2, f"{exc.code}: {exc}\n")


def _inspect(importer: AgentSkillImporter, arguments: argparse.Namespace):
    if arguments.commit is None:
        return importer.inspect_local(
            arguments.directory,
            publisher=arguments.publisher,
            source_namespace=arguments.namespace,
            source_locator=arguments.source,
        )
    if arguments.repository is None or arguments.package_path is None:
        raise SkillValidationError(
            "Pinned Git inspection requires --repository and --package-path."
        )
    return importer.inspect_pinned_git_snapshot(
        arguments.directory,
        repository=arguments.repository,
        commit=arguments.commit,
        package_path=arguments.package_path,
        publisher=arguments.publisher,
        source_namespace=arguments.namespace,
        publisher_verified=False,
    )


def _inspection_document(value) -> dict[str, object]:
    return {
        "manifest": value.manifest.document(),
        "compatibility": value.compatibility,
        "compatibility_reasons": list(value.compatibility_reasons),
        "skill_md_digest": value.skill_md_digest,
        "files": [
            {
                "path": item.path,
                "size": item.size,
                "digest": item.digest,
                "component": item.component,
            }
            for item in value.files
        ],
        "external_metadata": dict(value.external_metadata),
        "notice": "All external metadata and guidance are untrusted; bundled code was not executed.",
    }


def _entry_document(entry) -> dict[str, object]:
    return {
        "skill_id": entry.manifest.identity.canonical_id,
        "display_name": entry.manifest.display_name,
        "version": entry.manifest.version,
        "content_digest": entry.manifest.content_digest,
        "source": entry.manifest.source.document(),
        "state": entry.state,
        "revision": entry.revision,
        "granted_permissions": [item.document() for item in entry.granted_permissions],
        "inspection": entry.manifest.inspection.document(),
    }


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tori.skill_admin_cli",
        description=(
            "Inspect and administer local staged or explicitly selected public "
            "GitHub instruction Agent Skills."
        ),
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_SKILL_DATABASE)
    parser.add_argument("--packages", type=Path, default=DEFAULT_AGENT_SKILL_PACKAGES)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "install"):
        command = commands.add_parser(name)
        command.add_argument("directory", type=Path)
        command.add_argument("--publisher", required=True)
        command.add_argument("--namespace", default="local")
        source = command.add_mutually_exclusive_group()
        source.add_argument("--source")
        source.add_argument("--commit")
        command.add_argument("--repository")
        command.add_argument("--package-path")
    inspect_url = commands.add_parser("inspect-url")
    inspect_url.add_argument("url")
    install_url = commands.add_parser("install-url")
    install_url.add_argument("url")
    install_url.add_argument(
        "--approve",
        action="store_true",
        help="explicitly approve installing the inspected immutable bytes disabled",
    )
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    commands.add_parser("list")
    for name in ("show", "enable", "disable"):
        command = commands.add_parser(name)
        command.add_argument("skill_id")
        command.add_argument("version")
        command.add_argument("digest")
        if name in {"enable", "disable"}:
            command.add_argument("--revision", required=True, type=int)
    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
