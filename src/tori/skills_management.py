"""Browser-safe Skills and MCP inventory projections.

The browser receives application-owned summaries, never manifests as authority,
secret values, ambient environment, or mutable backend objects.
"""

from __future__ import annotations

from collections.abc import Mapping

from .mcp import MCPServerRegistry
from .request_origin import RequestOrigin
from .skills import SkillApplicationService, SkillPermission, SkillRegistryEntry


def skills_management_document(
    application: SkillApplicationService | None, *, origin: RequestOrigin
) -> dict[str, object]:
    if application is None:
        return {"available": False, "skills": [], "message": "Skills are not configured."}
    application.require_administration(origin)
    entries = application.registry.list_entries()
    return {
        "available": True,
        "skills": [_skill_document(entry, application, origin) for entry in entries],
        "message": None,
    }


def mcp_management_document(
    registry: MCPServerRegistry | None,
    *,
    origin: RequestOrigin,
    credential_status: Mapping[str, bool] | None = None,
) -> dict[str, object]:
    if registry is None:
        return {
            "available": False,
            "servers": [],
            "message": "No MCP servers are configured in this runtime.",
        }
    registry.require_administration(origin)
    configured = dict(credential_status or {})
    return {
        "available": True,
        "servers": [
            _mcp_document(registry.document(server_id), configured.get(server_id, False))
            for server_id in registry.server_ids()
        ],
        "message": None,
    }


def _skill_document(
    entry: SkillRegistryEntry,
    application: SkillApplicationService,
    origin: RequestOrigin,
) -> dict[str, object]:
    manifest = entry.manifest
    requested = tuple(manifest.requested_permissions)
    granted = tuple(entry.granted_permissions)
    eligible = application.eligible_operations(manifest.version_ref, origin=origin)
    component_names = _finding(manifest.inspection.findings, "component_types")
    components = (
        tuple(value for value in component_names.split(",") if value)
        if component_names
        else tuple(sorted({item.kind.value for item in manifest.components}))
    )
    compatibility = application.compatibility_status(manifest)
    effective = granted if entry.state == "enabled" else ()
    access = _permission_summary(requested, manifest.requirements.network_destinations)
    privacy = _privacy_summary(requested, manifest.requirements.network_destinations)
    source = manifest.source.document()
    return {
        "display_name": manifest.display_name,
        "canonical_identity": manifest.identity.canonical_id,
        "version": manifest.version,
        "source": source,
        "format": manifest.import_metadata.format,
        "compatibility": compatibility,
        "state": entry.state,
        "enabled": entry.state == "enabled",
        "revision": entry.revision,
        "local_only": not access["network"],
        "location_label": "Local only" if not access["network"] else "Internet-connected",
        "external_access_label": _external_access_label(access["destinations"]),
        "access": access,
        "privacy": privacy,
        "requested_permissions": [item.document() for item in requested],
        "granted_permissions": [item.document() for item in granted],
        "effective_permissions": [item.document() for item in effective],
        "components": list(components),
        "scripts_present": "scripts" in components,
        "scripts_status": "Inert; not executable by the instruction-Skill importer" if "scripts" in components else "None detected",
        "digest": manifest.content_digest,
        "pinned_revision": manifest.source.pinned_revision,
        "inspected_at": manifest.inspection.inspected_at,
        "health": (
            "available"
            if entry.state == "enabled" and eligible
            else "disabled"
            if entry.state in {"installed_disabled", "disabled"}
            else "uninstalled"
            if entry.state == "uninstalled"
            else "unavailable"
        ),
        "eligible_operations": list(eligible),
        "controls": {
            "enable": entry.state in {"installed_disabled", "disabled"},
            "disable": entry.state == "enabled",
            "uninstall": entry.state != "uninstalled",
            "uninstall_reason": (
                None
                if entry.state != "uninstalled"
                else "This exact Skill version is already removed; its provenance tombstone is retained."
            ),
        },
    }


def _mcp_document(value: Mapping[str, object], credential_configured: bool) -> dict[str, object]:
    requested = _permissions(value.get("requested_permissions"))
    granted = _permissions(value.get("granted_permissions"))
    snapshots = value.get("schema_snapshots")
    approved = value.get("approved_tools")
    snapshots = snapshots if isinstance(snapshots, Mapping) else {}
    approved = approved if isinstance(approved, Mapping) else {}
    tools: list[dict[str, object]] = []
    drifted = 0
    for name in sorted(snapshots):
        raw = snapshots[name]
        if not isinstance(raw, Mapping):
            continue
        digest = raw.get("schema_digest")
        approved_digest = approved.get(name)
        drift = isinstance(approved_digest, str) and approved_digest != digest
        drifted += int(drift)
        schema = raw.get("input_schema")
        schema = schema if isinstance(schema, Mapping) else {}
        properties = schema.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        required = schema.get("required")
        tools.append({
            "name": name,
            "description": raw.get("description") if isinstance(raw.get("description"), str) else "",
            "description_trust": "untrusted_server_text",
            "approved": name in approved,
            "schema_digest": digest,
            "schema_drift": drift,
            "input_fields": sorted(str(item) for item in properties)[:32],
            "required_fields": [str(item) for item in required][:32] if isinstance(required, list) else [],
            "classification": _trusted_tool_classification(value, name),
        })
    destinations = _network_destinations(requested)
    access = _permission_summary(requested, destinations)
    fixed_argv = tuple(value.get("fixed_argv", ()))
    read_only = "--read-only" in fixed_argv or value.get("server_id") == "modelcontextprotocol.time.readonly"
    credential_required = value.get("credential_handle") is not None or any(
        isinstance(item, str) and item.startswith("--oauth-scopes=")
        for item in fixed_argv
    )
    enabled = value.get("enabled") is True
    configuration_managed = value.get("server_id") == "modelcontextprotocol.time.readonly"
    return {
        "server_id": value.get("server_id"),
        "display_name": value.get("display_name"),
        "enabled": enabled,
        "transport": value.get("transport"),
        "transport_label": "Local MCP process" if value.get("transport") == "stdio" else "Unsupported transport",
        "executable": value.get("executable"),
        "executable_digest": value.get("executable_digest"),
        "server_version": value.get("server_version"),
        "configuration_digest": value.get("configuration_digest"),
        "external_access_label": _external_access_label(destinations),
        "access": access,
        "network_destinations": list(destinations),
        "credential_required": credential_required,
        "credential_status": (
            "Credential configured"
            if credential_configured
            else "Credential not configured"
            if credential_required
            else "Credential not required"
        ),
        "read_write_classification": "Read-only" if read_only else "Not classified",
        "approved_tool_count": len(approved),
        "discovered_unapproved_tool_count": sum(1 for item in tools if not item["approved"]),
        "schema_drift_count": drifted,
        "health": (
            "schema drift" if drifted
            else "available" if enabled and approved and value.get("ready") is True
            else "failed" if value.get("process_state") == "failed"
            else "disabled" if not enabled
            else "not ready"
        ),
        "available": enabled and bool(approved) and drifted == 0 and value.get("ready") is True,
        "running": value.get("ready") is True,
        "process_state": value.get("process_state"),
        "protocol_version": value.get("protocol_version"),
        "tool_count": len(tools),
        "permitted_tool_count": len(approved),
        "last_error": value.get("last_error"),
        "sandboxed": value.get("sandboxed") is True,
        "filesystem_scope": list(value.get("filesystem_scope", ())),
        "network_access": value.get("network_access") is True,
        "requested_permissions": [item.document() for item in requested],
        "granted_permissions": [item.document() for item in granted],
        "privacy": {
            "tori_memory": "No",
            "conversation_history": "No",
            "local_filesystem": "One selected file" if access["file_read"] else "No",
            "internet": _external_access_label(destinations),
            "writes": "New approved output only" if access["file_write"] else "No" if read_only else "Not classified",
            "background_access": "No",
            "secrets": "Credential boundary only" if credential_required else "No",
        },
        "tools": tools,
        "controls": {
            "enable": not configuration_managed and not enabled and bool(approved) and drifted == 0,
            "disable": not configuration_managed and enabled,
            "approve_tools": False,
            "start_stop": False,
            "unavailable_reason": (
                "This reviewed MCP server is managed by tori.toml and restart validation."
                if configuration_managed
                else "Tool approval and process start/stop are not exposed until their durable approval lifecycle is implemented."
            ),
        },
    }


def _permissions(value: object) -> tuple[SkillPermission, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(SkillPermission.from_document(item) for item in value)


def _permission_summary(
    permissions: tuple[SkillPermission, ...], destinations: tuple[str, ...]
) -> dict[str, object]:
    kinds = {item.kind for item in permissions}
    network = tuple(sorted(set(destinations) | set(_network_destinations(permissions))))
    return {
        "file_read": "file.read.selected" in kinds,
        "file_write": "file.write.new" in kinds,
        "process_execution": "process.execute.approved" in kinds,
        "network": bool(network),
        "secret_use": "secret.use.named" in kinds,
        "destinations": list(network),
    }


def _privacy_summary(
    permissions: tuple[SkillPermission, ...], destinations: tuple[str, ...]
) -> dict[str, str]:
    access = _permission_summary(permissions, destinations)
    return {
        "tori_memory": "No",
        "conversation_history": "No",
        "local_filesystem": "One selected file" if access["file_read"] else "No",
        "internet": _external_access_label(tuple(access["destinations"])),
        "writes": "New approved output only" if access["file_write"] else "No",
        "background_access": "No",
        "secrets": "Named handle only" if access["secret_use"] else "No",
    }


def _network_destinations(permissions: tuple[SkillPermission, ...]) -> tuple[str, ...]:
    destinations = []
    for permission in permissions:
        if permission.kind != "network.connect.exact":
            continue
        host = permission.scope.get("host")
        if isinstance(host, str):
            destinations.append(host)
    return tuple(sorted(set(destinations)))


def _external_access_label(destinations: tuple[str, ...] | list[str]) -> str:
    unique = tuple(sorted(set(destinations)))
    if not unique:
        return "No network access"
    return "Internet: " + ", ".join(unique)


def _finding(findings: tuple[str, ...], name: str) -> str | None:
    prefix = name + "="
    return next((item[len(prefix):] for item in findings if item.startswith(prefix)), None)


def _trusted_tool_classification(server: Mapping[str, object], name: str) -> str:
    argv = server.get("fixed_argv")
    allowed = server.get("allowed_tools")
    if (
        isinstance(argv, list)
        and ("--read-only" in argv or server.get("server_id") == "modelcontextprotocol.time.readonly")
        and isinstance(allowed, list)
        and name in allowed
    ):
        return "read-only"
    return "not classified"
