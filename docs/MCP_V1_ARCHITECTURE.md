# MCP V1 architecture and acceptance

**Status:** Implemented and physically accepted on 2026-09-21

## Purpose

MCP is a capability transport beneath Tori's authority, not an authority source.
The implemented path is:

```text
local MCP stdio server
        -> bounded Tori MCP client
        -> MCP server registry and approved snapshot
        -> central Tori Capability Registry state
        -> local Conversation policy
        -> schema validation and approved tool call
        -> bounded, validated CapabilityResult
```

Server descriptions, schemas, annotations, and returned text are untrusted data.
Discovery never creates a grant. The model never receives a raw MCP connection
or the ability to select an unapproved tool.

## Reconnaissance baseline

Before this milestone, `src/tori/mcp.py` already implemented the MCP 2025-11-25
initialize, paginated `tools/list`, and `tools/call` subset over local stdio. It
already had bounded JSON-RPC, schema snapshots, schema-digest approvals, a
Tori-owned registry, local-origin administration/invocation gates, minimal
environment construction, process-group shutdown, and a Skills & MCP
projection. Fake-server tests covered most protocol failures, and a reviewed
GitHub profile had passed disposable acceptance.

The boundary was not instantiated by production startup, was not connected to
ordinary Conversation or the central capability-state projection, had no
durable production server configuration, and had no installed low-risk server.
Process readiness and failure were not visible as live management truth. The
implementation also launched its child without a per-server filesystem/network
sandbox.

## V1 transport and lifecycle

V1 supports only one Tori-launched local **stdio** server. The protocol version
is exactly `2025-11-25`; other negotiated versions fail closed. Tori owns
initialization, discovery, invocation, timeout/cancellation, stderr draining,
normal shutdown, and unexpected-exit reporting. There is no automatic restart
loop. A fresh Tori start revalidates configuration, package version, executable
hash, sandbox hash, implementation identity/version, protocol, and approved
schema before the capability becomes available.

The production process runs in Bubblewrap with a new session, all namespaces
unshared, no network, a temporary `/tmp`, `/nonexistent` home, and read-only
binds only for the system runtime and Tori `.venv`. It receives exactly `HOME`,
`LANG`, `LC_ALL`, `PATH`, Python safe/no-user-site/no-bytecode flags, `TMPDIR`,
and `TZ`; ambient provider keys, cloud credentials, proxy variables, SSH agent
state, and unrelated tokens are absent.

## First server selection and identity

The selected server is the official open-source `modelcontextprotocol/servers`
Time server. The compared alternatives were:

| Candidate | Useful proof | Rejected V1 risk |
| --- | --- | --- |
| Time | Account-free local time-zone read | Selected; no filesystem or network requirement |
| Filesystem | File reads and mutations | Grants host-path authority and advertises writes/deletes |
| GitHub | Repository reads | Requires an account token and external network |

The reviewed identity is:

- project: `modelcontextprotocol/servers`, `src/time`, MIT;
- upstream release: `v2026.8.18`, commit
  `644cbe65648f1d6c687b3b647683e1aaa4ed1eba`;
- PyPI package: `mcp-server-time==2026.8.18`;
- published wheel SHA-256:
  `1407583af42dc0163909d855c9ef20114a12b4981c3975033721a7906cdd212a`;
- MCP SDK: `mcp==1.30.0`;
- installed Time-server Python-source digest:
  `sha256:f5ebffa4f2a9a0cf17e54caa6220b5f57062b5c917ee03cd46e771968ca41827`;
- installed MCP-SDK Python-source digest:
  `sha256:7047a8f379335332a3b4f50e55decd1c9985e89595a5d97f4149b930327357b4`;
- expected protocol identity: `mcp-time` / `1.30.0`;
- executable digest: configured and verified locally by the owner, not bundled
  from a developer machine;
- transport: local stdio;
- working directory: isolated `/tmp`;
- network: none;
- secrets: none.

The server advertises `get_current_time` and `convert_time`. Tori permits only
`get_current_time`, bound to schema digest
`sha256:f3a11b4c49a2326a4d93fd4da437be913276dee8f824db07ca0eec24a6ed1205`.
`convert_time` remains discovered but unapproved and is rejected before any tool
call. MCP annotations do not affect that decision.

## Authority, validation, and Conversation

The one approved operation is a bounded read and requires no per-call
confirmation after the administrator has supplied the exact reviewed local
configuration. Enabling the server grants only the exact process executable and
approved schema. Tori also no-follow hashes the installed Time-server and MCP
SDK Python source inventories. Any executable, sandbox, package source,
implementation, protocol, or schema change makes the capability unavailable
pending human review.

The Conversation route recognizes an explicit MCP Time request and extracts one
IANA time-zone name. It rejects malformed/path-like values, validates arguments
against the approved server schema, re-lists tools immediately before use, and
rechecks identity, approval, drift, and enabled grants. Response bytes, content
count, text size, JSON shape, timezone, timestamp, weekday, and DST type are
bounded and validated. Returned text such as “ignore previous instructions” is
data and fails the Time result contract; it cannot become a Tori instruction.

## Configuration, status, backup, and limits

Production configuration belongs in the existing per-machine `tori.toml` under
`[mcp.time]`. The portable template is disabled. Tori performs no server
installation and never auto-approves inventory changes. `tori.toml` already has
machine-local preservation semantics: normal backups exclude it, and verified
restore preserves the current machine's copy. Process/session state, protocol
messages, stderr, and caches are transient and are not backed up.

**Skills & MCP** reports configured/enabled state, live readiness, protocol and
server version, transport, sandbox/network/filesystem posture, discovered and
permitted counts, schema drift, health, and last error. V1 has no marketplace,
remote HTTP/SSE transport, arbitrary URL/server UI, automatic installation,
credential broker, resources/prompts/sampling/elicitation, writes, destructive
tools, tool chaining, or autonomous MCP jobs.

## Physical acceptance evidence

Using the real Tori Web application and the real contained server:

1. startup reported MCP Time available and the browser displayed ready;
2. initialization negotiated `2025-11-25` and discovered two tools;
3. the browser displayed exactly one permitted and one discovered/unapproved;
4. ordinary Conversation request `Use MCP Time to get the current time in
   America/Chicago` returned a real validated timestamp without a model call;
5. direct `convert_time` resolution failed with `MCPPermissionError`;
6. terminating only the owned MCP process group changed the browser status to
   `No (failed)` and surfaced `The MCP server exited unexpectedly.`;
7. a full Tori restart restored the same two-discovered/one-permitted authority;
8. orderly shutdown left no `mcp-server-time` process.

Automated coverage includes protocol initialization/discovery/invocation,
errors, malformed messages, timeout/crash, lifecycle and shutdown, stable
identity, drift/new-tool denial, disabled state, authority and annotation
resistance, argument/result bounds, hostile output, minimal environment,
sandbox scope, central registry projection, management status, configuration,
and ordinary Conversation routing.
