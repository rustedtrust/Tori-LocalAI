# Tori Skills V1 Architecture

**Project:** Tori
**Document:** Skills V1 Architecture Decision Record
**Status:** Initial Skills V1 complete and human accepted; post-V1 enhancements remain deferred
**Authority:** Subordinate to `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`
**Decision date:** 2026-09-05

## 1. Purpose and decision

This document defines the smallest useful Skills V1 architecture. The Core
Foundation now implements the closed normalized model, immutable manifest and
revisioned registry separation, local origin and permission gates, generic
application-owned adapter contract, and capability-awareness projection. The
first reviewed bounded adapter, `media.inspect`, is implemented with a fixed
FFprobe contract, exact selected-file binding, executable drift admission,
native isolation, bounded normalization, and a narrow local Conversation seam.
The external Agent Skills seam now inspects explicitly selected local or
already-staged pinned-Git package bytes, normalizes supported `SKILL.md`
metadata, installs immutable evidence disabled, and lazily supplies only a
selected instruction body through one generic Tori-owned adapter. It is not
silently installed or enabled, and bundled scripts remain inert. A first
local-stdio MCP boundary now supports explicit server registration, bounded
inspection, individual-tool approval, schema-drift admission, provider-neutral
projection, normalized calls, and deterministic shutdown. This is not a claim
that Agent Plugins, arbitrary MCP-server administration, remote HTTP MCP, a
generic executable loader, a secret broker, backup integration, or a complete
complete MCP administration or credential workflow exists. A responsive local
**Skills & MCP** view now projects Tori-owned lifecycle, provenance, permissions,
privacy/network labels, and approved-versus-discovered tool state. It reuses the
existing exact proposal boundary for GitHub installation and Skill/MCP
enablement or disablement; it does not move policy into the browser.

Tori remains the sole authority. Skills provide capability and evidence; they
do not own identity, personality, canonical Memory, Conversation truth,
permissions, provider or model selection, Project or task meaning, execution
policy, installation, updates, or their own enablement.

Skills V1 will use existing formats at replaceable boundaries:

- Agent Skills is the preferred portable instruction-Skill format.
- Agent Plugins 1.0 is an import and package format.
- MCP is an optional interoperability protocol, not Tori's core.
- Provider function/tool schemas are projections of Tori-approved operations.
- Tori owns the normalized manifest, lifecycle, permissions, provenance,
  execution decision, result validation, receipts, and user experience.

External packages, manifests, descriptions, prompts, Agent Skills instructions,
Agent Plugins metadata, MCP schemas, server annotations, and results are
untrusted data. Registry or catalog presence is not trust. Installation grants
no permission and does not enable a Skill.

## 2. Scope and product decisions

V1 supports explicitly selected local content and Git sources pinned to an
immutable revision. It has no marketplace installation integration, automatic
installation, automatic update, dependency resolver, or automatic enablement.
The implemented skills.sh seam is a read-only catalog search convenience, not
a registry trust relationship or acquisition path.

Remote request origins cannot discover, install, enable, invoke, update,
disable, roll back, uninstall, or administer Skills in V1. Skill operations are
local-only application operations. A future expansion requires a new origin
policy and architecture review rather than a manifest change.

Executable Skills are not arbitrary scripts. V1 may expose only individually
reviewed, application-coded bounded executable adapters. The first proof is the
implemented read-only `media.inspect` adapter using `/usr/bin/ffprobe`; it
remains subject to explicit installation and enablement.

## 3. Ownership and trust boundaries

Tori core owns:

- canonical Skill identity and collision handling;
- source admission, inspection, and trust status;
- lifecycle state and immutable version selection;
- permission vocabulary, grants, and per-invocation resource bindings;
- origin and conversation eligibility;
- proposal, confirmation, and revision checks;
- provider-facing operation selection and schemas;
- adapter selection, execution containment, cancellation, and limits;
- secrets and credential release;
- output validation, truth claims, provenance, and receipts;
- backup consistency and restore validation.

Replaceable importers translate external formats into a normalized candidate.
Replaceable execution adapters perform one approved operation. Neither is an
authority source. Unknown fields are preserved for inspection where safe but do
not affect permissions or execution.

The existing `CapabilityRegistry` may describe enabled Skill capabilities and
their availability. It remains a non-mutating awareness projection, not the
Skill registry, policy engine, installer, or executor.

## 4. Normalized `SkillManifest v0`

`SkillManifest v0` is Tori's immutable internal description of one inspected
Skill version. It is independent of Agent Skills, Agent Plugins, MCP, and any
provider API. The serialized form uses an exact schema: unknown values cannot
silently acquire semantics, and required strings and collections have explicit
size and count limits.

The minimal record is:

| Field | Meaning |
| --- | --- |
| `schema_version` | Exact value `0` for this internal contract. |
| `identity` | Canonical source namespace, publisher when known, and package name. |
| `display_name` | Bounded user-facing label; never used for authorization. |
| `version` | Publisher-supplied version string, retained as provenance rather than trusted ordering. |
| `source` | `local` or `git`, normalized source locator, pinned revision, acquisition evidence, and publisher claim. |
| `content_digest` | Algorithm plus digest of a canonical, no-follow, path-sorted tree representation of every package entry and byte. V1 uses SHA-256. |
| `import` | Source format, importer implementation version, and external specification version. |
| `description` | Bounded untrusted descriptive text for inspection. Provider descriptions are separately Tori-authored. |
| `operations` | Stable operation IDs, bounded summaries, closed input/output JSON Schemas, component reference, and requested permission references. |
| `components` | Instruction-only, MCP-backed, or named bounded-executable component declarations. |
| `requested_permissions` | Normalized requests expressed only in Tori's permission vocabulary. These are not grants. |
| `requirements` | Declared executable identities, network destinations, and named secret handles. Undeclared requirements fail closed. |
| `inspection` | Inspection timestamp, inspector version, findings, warnings, and inspected external metadata. |
| `compatibility` | Required Tori Skill contract version and explicitly supported local platform constraints. |

Mutable lifecycle state is deliberately not stored in the immutable manifest.
A separate revisioned `SkillRegistryEntry` binds a manifest digest to lifecycle
state, approved permission-grant revision, enablement revision, health, and
timestamps. This prevents an enable/disable action from rewriting package
evidence.

Instruction text and external `allowed-tools` declarations may be retained as
inspection evidence. They never create an operation, permission, executable
argument, secret access, or provider tool by themselves.

## 5. Identity and provenance

The stable canonical Skill identity is:

`source-namespace / publisher-or-unverified / package-name`

The immutable version identity adds:

`publisher-version / sha256-content-digest`

The source namespace is Tori-normalized and distinguishes at least selected
local content from each normalized Git remote. Display names and bare package
names are not identifiers. Tori-reserved namespaces cannot be imported. A name
collision is shown to the user; source precedence never silently replaces an
installed package.

Each immutable version retains:

- source kind and normalized locator;
- publisher or owner claim and its verification status;
- package name and publisher version;
- complete content digest;
- exact Git commit for Git sources, not a movable branch or tag alone;
- importer name/version and external specification version;
- acquisition and inspection timestamps;
- acquisition evidence and inspection findings;
- parent version when staged as an update;
- permission and schema differences from that parent.

A selected local directory is copied through no-follow inspection into
quarantine and then into an immutable managed package. A Git source is resolved
to an exact commit before proposal; a branch or tag is only discovery input.
Submodules, Git LFS fetching, symlinks, special files, and content outside the
selected package root are rejected in V1. No importer executes package content.

Checksums establish byte identity, not publisher identity, safety, quality, or
truth. Every trust conclusion remains an explicit Tori-owned inspection result.

## 6. Permission vocabulary

V1 uses a closed, small vocabulary. Every grant is bound to an immutable Skill
digest, named operation, component, revision, and local origin policy. Requested
permissions in a manifest are compared with, but cannot modify, the grant.

| Permission | Required enforceable scope |
| --- | --- |
| `file.read.selected` | One existing regular file selected locally for this invocation, represented by an opaque Tori resource binding; no model-supplied path, directory, recursion, or symlink following. |
| `file.write.new` | One exact locally approved output path that is absent at authorization time; parent policy and atomic creation are fixed; no overwrite. |
| `process.execute.approved` | One absolute, inspected executable identity plus a Tori-coded fixed argument template, sanitized environment, containment profile, and resource limits; never a shell string. |
| `network.connect.exact` | Exact scheme, normalized host/IP policy, port, and when applicable path/API audience; redirects and resolved destinations must remain within scope. |
| `secret.use.named` | One Tori-owned secret handle, one component, and one approved destination/audience; the value is never returned to the Skill manifest, model, browser, log, or receipt. |
| `tori.read.operation` | One explicitly enumerated read-only Tori application operation and resource scope; never raw store or database access. |

There is no V1 permission for arbitrary directories, arbitrary commands,
shells, interpreters, package installation, ambient environment, unrestricted
network, direct canonical-store access, or another Skill. A future permission
kind requires a schema revision and architecture review.

Permission evaluation occurs twice: an install/enable grant defines the maximum
scope, then each invocation binds concrete resources within that maximum.
Current origin, Skill state, grant revision, Conversation state, and resource
identity are revalidated immediately before execution. Installation and
enablement proposals are exact, expiring, one-use, local-origin-bound, and
revision-bound. Materially effectful invocations use the same proposal pattern.

## 7. Lifecycle state machine

One immutable version follows this state model:

```text
discovered
    -> quarantined
    -> inspected
    -> proposed
    -> installed_disabled
    -> enabled <-> disabled
    -> uninstall_proposed
    -> uninstalled

quarantined -> quarantine_failed
inspected   -> inspection_failed | rejected
proposed    -> rejected | expired | install_failed

installed_disabled | enabled | disabled
    -> update_staged(new immutable version: quarantined -> inspected -> proposed)
    -> new installed_disabled version

rollback = disable current version + enable a retained previous immutable
           version through a new exact proposal; no version is rewritten.
```

Discovery is non-authorizing metadata. Quarantine contains no executable trust.
Inspection is successful only when the complete bounded tree, normalized
manifest, operations, requirements, provenance, and warnings are available.
The proposed state is bound to the inspected digest and exact requested grant.

Installation atomically publishes package content and registry state as
`installed_disabled`; it never enables the Skill. Enablement is a separate
revisioned action. Disablement immediately blocks new admissions, revokes
credential leases, cancels or contains owned in-flight work according to the
adapter contract, and then records the terminal state. Uninstall first disables
the version, proves no owned execution remains, removes only the exact managed
package, and retains a minimal provenance tombstone and receipts.

An update is always another immutable version. Fetching or inspecting it does
not alter the active version. The user reviews content, operation-schema,
executable, dependency, secret, network, and permission differences. Failed or
abandoned staging cannot damage the active version.

## 8. Component classes

### 8.1 Instruction-only Skill

An instruction-only Skill contains `SKILL.md`-style guidance, references, and
assets. Tori may load only the bounded content needed for an already-authorized
operation. It is labeled as untrusted Skill content below Tori-owned identity,
authority, Conversation, Memory, and policy context.

Scripts included in an Agent Skill or Agent Plugin remain inert package files.
Their presence does not change component class. An instruction-only Skill has
no process, network, secret, direct store, or filesystem authority.

The implemented Agent Skills importer uses bounded name and description text
for local selection. It loads the full `SKILL.md` body only after the exact
installed version is enabled, locally eligible, selected, and admitted through
the generic `apply` operation. The body is wrapped as untrusted advisory data
below Tori-owned authority. `references/`, `assets/`, `scripts/`, and other
package files are inventoried and hashed but never automatically injected,
imported, or executed. Compatibility findings are informational and cannot
grant authority.

The implemented acquisition seam accepts only an explicit public
`https://github.com/OWNER/REPO/tree/REV/path/to/skill` source. GitHub branch or
tag text is discovery input only: Tori resolves it to a 40-character commit,
binds provenance to that commit, traverses the immutable Git tree only to the
exact selected package subtree, and retrieves bounded blobs through constructed
GitHub API endpoints without ambient proxies or credentials. Tori rejects
truncated trees, links, submodules, special modes, excessive depth/count/size,
invalid base64, and content whose declared size or Git blob identity does not
verify. Only the selected package is published into disposable owner-private
quarantine; the repository archive and unrelated monorepo content are never
downloaded. The normal importer performs the authoritative package inspection.
Acquisition neither installs nor executes content. A one-use local installation proposal binds the
exact repository, commit, package path, manifest schema, digest, permissions,
compatibility and registry revision; approval installs disabled. Enablement is
a separate one-use proposal bound to the installed entry revision and grants.
Remote origins are rejected before acquisition transport.

The implemented skills.sh discovery seam is narrower still. It issues bounded
HTTPS searches only to the verified public local-client endpoint
`https://skills.sh/api/search`, accepts catalog records only when their source
is a syntactically valid GitHub `owner/repository`, and keeps descriptions,
install counts, duplicate flags, and catalog links as untrusted ephemeral
evidence. The endpoint currently exposes `source` and `skillId`, but no pinned
revision or authoritative package path; Tori therefore labels its conventional
`skills/<skillId>` mapping as unverified. Selecting a stored candidate invokes
the normal GitHub URL flow with mutable `HEAD` only as discovery input. GitHub
must resolve the exact commit, quarantine the bytes, and pass normal inspection
before Tori can make an installation proposal. skills.sh has no permission,
installation, enablement, execution, provenance, or trust-root role.

### 8.2 MCP-backed Skill or tool

An MCP component identifies one inspected server and an allowlist of individual
tools. The server may be a separately bounded local process or an exact remote
endpoint. Tori owns connection policy, credentials, tool exposure, call
admission, validation, and receipts. MCP resources, prompts, descriptions,
annotations, schemas, and results remain untrusted external data.

The implemented first slice is deliberately narrower: one application-defined
local stdio server record fixes an absolute executable identity and argument
vector, while a separate Tori-owned registry records bounded live snapshots,
individual approvals, exact grants, and enabled state. It implements only the
MCP initialization, `tools/list`, `tools/call`, cancellation, and shutdown
subset needed for this boundary; it is not a complete MCP framework or an
arbitrary command facility. The official GitHub profile is read-only and has a
four-tool application allowlist. No canonical server registration or user
credential is created by this slice.

### 8.3 Bounded local executable Skill

A bounded executable component is backed by application-reviewed adapter code.
The adapter fixes the executable identity, argument construction, input
bindings, output parser, sandbox profile, limits, and success evidence. The
model cannot supply executable paths or raw arguments. Unavailable containment
or executable drift makes the capability unavailable.

V1 has no generic Python, shell, executable, hook, or plugin loader. Importing a
package containing a script cannot create this component class. Each new
bounded executable adapter is production code requiring its own threat model,
tests, and architecture review.

## 9. MCP trust boundary

An MCP server identity includes transport, normalized endpoint or exact local
launch identity, configuration digest, package/image or executable provenance,
and credential audience. A friendly server name is not identity.

Before enablement Tori must:

- inspect and snapshot `tools/list` for only the proposed tools;
- store each tool name, description digest, input schema, output schema when
  present, and relevant annotations as untrusted evidence;
- bind an allowlist to exact Tori operation IDs;
- require a separate grant for local process execution or exact network access;
- prohibit token passthrough and ambient credentials;
- set connection, call, idle, and total timeouts plus cancellation behavior;
- set request, response, log, and aggregate result-size limits;
- validate inputs before calls and structured outputs before use;
- label free-form output as untrusted evidence;
- record server/version/configuration, tool, schema snapshot, call ID, timing,
  termination, validation, truncation, and result status in the receipt.

Tori compares the live catalog with the approved snapshot at connection and
before use. Added tools are invisible. Removed tools make their operations
unavailable. Any changed approved name, description, schema, annotation, or
server identity causes catalog drift and disables the affected mapping pending
inspection and approval.

MCP discovery never creates a provider tool, CapabilityRegistry entry, grant,
or model-visible instruction automatically. One MCP tool cannot invoke another
Skill through Tori in V1.

The implementation re-lists tools immediately before each admitted call.
Removed or changed approved snapshots cease to project and calls fail pending
reinspection and explicit reapproval. Local origin, enabled server state,
individual approval, current schema digest, exact grants, executable digest,
and transport readiness are application checks. Server-initiated JSON-RPC
requests are rejected rather than allowing sampling, elicitation, or a reverse
authority path. Bounded free text and structured content are returned as
untrusted `CapabilityResult` evidence; raw MCP objects do not enter Skill,
origin, Memory, Conversation, or provider-policy authority.

## 10. Provider projection and invocation

Tori creates a provider-facing function only after all of these are true:

- the immutable Skill version is enabled;
- the operation and component are approved;
- the current `RequestOrigin` is local and permitted;
- the current grant revision covers the operation;
- the current Conversation/context policy permits exposure;
- required health, executable, server, and secret checks pass.

The function name is a collision-resistant Tori-owned projection of canonical
Skill and operation identity. Its bounded description is authored or normalized
by Tori, not copied as authority-bearing prose. Its JSON Schema is closed,
versioned, and normally uses opaque Tori selection/resource tokens rather than
paths, secrets, commands, URLs, or provider-selected authority values.

The model sees only the eligible projection for the current turn. A model tool
call is a proposal containing candidate operation arguments. Tori validates the
exact schema, resolves opaque bindings, rechecks origin/state/grant/revision,
applies confirmation policy, and only then invokes an adapter. Rejected calls
have no side effect. The provider never chooses the adapter, expands a grant,
or determines whether execution succeeded.

Adapter output is normalized into `CapabilityResult`-style status, sources,
bounded metadata, and evidence. User-visible claims are made only from validated
results and independent postconditions required by that operation.

## 11. Self-learning boundary

Self-learning in V1 is advisory gap recognition, not self-modification:

```text
recurring capability gap
    -> candidate research
    -> evidence, provenance, maintenance, permission and risk summary
    -> local user proposal
```

The detector may use bounded non-sensitive capability-failure metadata and
explicit user requests. It cannot inspect or promote arbitrary Conversation or
Memory content merely to find work. Its output is untrusted advisory evidence.

Self-learning cannot install, enable, update, roll back, disable, uninstall,
write package content, create an operation, grant a permission, release a
secret, change provider selection, or modify identity, Memory, Conversation
truth, Projects, tasks, configuration, or execution policy. If the user accepts
a suggestion, the ordinary source-selection and Skill lifecycle starts at
discovery with no inherited authority.

The implemented first slice is local and Conversation-driven. A closed
application-owned recognizer admits only a small set of explicit file-
transformation requests after existing native/domain routing has declined. It
does not ask a model to declare a gap. Existing matching enabled Skill and
approved MCP identifiers suppress duplicate suggestions; informational or
Search requests, general uncertainty, unavailable configuration, and
security/policy denials do not become gaps. Tori asks before contacting
skills.sh, requests at most three candidates through the existing bounded
service, and labels every result uninspected. The exact candidate list is
ephemeral, bound to the current local Conversation, and cleared by expiry,
decline, Conversation change, or selection. Selection performs only the
existing GitHub commit-pinning, quarantine, and inspection operation. It does
not propose installation; the normal separate installation and enablement
workflow must begin afterward under user authority. No request history,
behavioral profile, background discovery, or canonical learning state is
stored by this original narrow gap flow.

The later, separately authorized Capability Growth / Self-Improvement V1
extension does not change that flow's ephemeral consent and selection state.
It adds a distinct application-owned Improvement Journal for bounded normalized
operational evidence and advisory recommendation history, plus a manually
triggered reusable Skills Review service. Its fixed authority remains
`OBSERVE -> EVIDENCE -> PATTERN -> RESEARCH -> RECOMMEND -> USER DECIDES`;
review acceptance cannot invoke Skill lifecycle or grant authority. See
`docs/CAPABILITY_GROWTH_V1_ARCHITECTURE.md` for the exact storage, research,
deduplication, reconciliation, backup, UI, and deferred-work decisions.
Capability Growth V1 is complete and human accepted; it does not change Skills
V1 lifecycle, permissions, Remote restrictions, or the original gap flow.

## 12. Storage, secrets, and backup

The proposed durable layout is:

```text
runtime/skills/
    registry.sqlite3                 # revisioned lifecycle/grant state
    packages/<identity>/<version>/<digest>/
                                      # immutable inspected package bytes
    receipts/                         # bounded lifecycle/invocation evidence
    tombstones/                       # minimal removed-version provenance
```

Exact escaping and filesystem-safe identity encodings are application-owned;
untrusted names never become path fragments directly. Every path is owner-only,
no-follow validated, and published through same-filesystem atomic rename after
complete validation. Installed trees reject links and special files and become
application-immutable. Store reopen validates schema, ownership, modes, paths,
tree digests, registry/package correspondence, and current-version references;
it does not repair unknown state automatically.

Quarantine and update acquisition content live only in owner-private disposable
`/tmp/tori-skill-quarantine-*` directories. They are never executable, never
backed up, and are removed only when ownership and exact disposable root are
proved. Proposals expire across restart and can be restaged from their pinned
source. Failed or ambiguous quarantine content is preserved only long enough
for bounded inspection during the current workflow, then safely discarded.

Skill secrets live outside packages and outside `runtime/`, under the proposed
owner-private host location `%h/.local/share/tori/skill-secrets/`. Tori stores
values by opaque handle and brokers a bounded lease to one component and
audience. Packages, manifests, provider context, browser responses, ordinary
logs, receipts, and Skill backup never contain secret values. Secret backup, if
ever supported, requires a separate encrypted and explicitly authorized design.

Normal verified Tori backup should include the registry, immutable installed
and retained rollback packages, non-secret provenance, grants, lifecycle
receipts, and tombstones as one consistent generation. It should exclude
quarantine, temporary execution state, sockets, caches, fetched Git metadata,
secret values, and external user source files. `/usr/bin/ffprobe` and other host
executables are not copied; backup retains their required identity and version
evidence so restore reports the Skill unavailable until the host dependency is
revalidated.

Backup must take the Skill lifecycle consistency guard, reject incomplete
publication, validate copied digests, and never enable a Skill during restore.
Restored Skills return as `installed_disabled` until package, executable,
permission, origin, and secret requirements are revalidated locally.

The implemented closeout uses the existing verified whole-project backup. It
registers `runtime/skills/registry.sqlite3` for an online SQLite snapshot and
takes the shared Agent Skill administration guard across registry lifecycle and
managed-package publication/removal. Fixed `runtime/skills/{quarantine,
discovery,self_learning,secrets,tmp}` subtrees are excluded; current acquisition
quarantine remains disposable under `/tmp`. A restore starts only from a payload
that the backup service has reverified against every manifest path, type, mode,
size, digest, and SQLite integrity record. It publishes only into an absent,
owner-controlled `runtime/skills` destination, validates every installed Agent
Skill against its digest-derived managed package, and changes all restored
`enabled` entries to `disabled` with a new revision. Existing Skills state is
never overwritten or repaired. Current schema terminology retains `disabled`
rather than rewriting restored entries to `installed_disabled`; both require a
fresh explicit enable proposal and local revalidation.

## 13. `media.inspect` proof and threat model

### 13.1 Contract

`media.inspect` accepts one opaque, local, user-created selection binding for an
existing regular file. It returns a bounded deterministic document containing
recognized container/format and stream metadata reported by `ffprobe`.

It has no network, secret, write, recursive-directory, arbitrary argument,
provider-selected path, or remote-origin authority. The fixed logical command
is equivalent to:

```text
/usr/bin/ffprobe -v error -show_format -show_streams -of json /input/media
```

The adapter builds an argument vector with `shell=False`; neither the model nor
Skill content contributes arguments. The output claim is limited to metadata
successfully reported for that exact input. It does not claim that media is
safe, authentic, complete, or playable.

### 13.2 Threat controls

| Threat | Required control |
| --- | --- |
| Malformed hostile media | Run `ffprobe` inside a fresh native isolation boundary with private PID, IPC, UTS, cgroup, working directory, and network namespaces; expose only required read-only executable/libraries and one read-only input. No repository, canonical runtime, backups, home, sockets, devices, or secrets are visible. Missing isolation fails closed. |
| Traversal, symlinks, and TOCTOU | Accept only an opaque local selection binding. Validate every path component without following links, open the final regular file with no-follow semantics, record device/inode/size/mtime, and bind that opened identity read-only at `/input/media`. Reject directories, links, devices, FIFOs, sockets, procfs-like sources, and identity changes. |
| Unexpected file types | Do not trust extensions or MIME supplied by the model. Permit only a bounded regular file; `ffprobe` must recognize it and produce valid expected JSON, otherwise report unsupported/unreadable without fallback execution. Embedded content is never launched. |
| Resource exhaustion | Initial hard bounds: 4 GiB input, 15-second wall timeout, 10 CPU seconds, 512 MiB address space, one process family, 1 MiB stdout, and 64 KiB stderr. Terminate the complete owned process group on timeout or limit breach and report the exact bounded failure. Limits may change only through reviewed Tori code and tests. |
| Environment leakage | Use an explicit minimal environment, deterministic locale, no inherited `HOME`, tokens, proxy variables, provider keys, user paths, or ambient file descriptors; stdin is closed. |
| Executable replacement | Require absolute `/usr/bin/ffprobe`, a regular root-owned executable not writable by group/other, an approved version, and a stored SHA-256 identity. Revalidate immediately before admission; drift makes the component unavailable pending review. |
| Output abuse | Capture bytes under independent stdout/stderr caps, reject invalid UTF-8 or JSON, enforce an exact normalized output schema and count/string/depth limits, and never inject raw stderr or unbounded tags into model context. |
| False success | Success requires clean exit, untruncated valid JSON, schema normalization, matching input identity, and a receipt. Nonzero exit, signal, timeout, truncation, drift, or validation failure is not success. |

### 13.3 Acceptance evidence

Implementation is not accepted until disposable tests prove:

1. local-origin-only admission and remote-origin rejection;
2. no model-controlled path, executable, option, or raw argument reaches argv;
3. normal media produces the documented normalized schema and receipt;
4. malformed, unsupported, oversized, slow, deeply nested, invalid-JSON, huge
   stdout/stderr, crash, signal, and timeout cases fail honestly;
5. directory, symlink, special-file, path-swap, and recursive access attempts are
   rejected without following or mutation;
6. the sandbox cannot see the repository, canonical runtime, backups, home,
   secrets, external filesystem, host sockets, or network;
7. executable ownership, mode, version, and digest drift disable the Skill;
8. source file bytes/metadata, canonical runtime, configuration, and unrelated
   paths remain unchanged;
9. disablement blocks new work and leaves no owned process;
10. backup and restore retain package/provenance but restore it disabled and
    require host-executable revalidation.

Use a fake executable adapter for contract tests and a disposable real
`ffprobe` gate for integration evidence. No canonical user media or runtime
state is a test fixture.

## 14. Existing component reuse

| Existing component or pattern | Skills V1 use |
| --- | --- |
| `CapabilityRegistry` | Non-mutating awareness and availability projection for enabled Skill operations; never policy or execution. |
| `CapabilityDescriptor` | Basis for stable operation identity, description, availability, and authorization summary. |
| `CapabilityResult` | Basis for normalized visible status, sources, bounded metadata, and evidence. |
| `RequestOrigin` / `OriginAuthority` | Add explicit local Skill administration/invocation operations; remote origins remain denied by default. |
| Proposal/confirmation services | Reuse exact target, expiry, one-use token, origin/chat binding, and current-revision revalidation patterns. |
| Supervised command/Coding Work isolation | Reuse fail-closed native containment, sanitized environment, bounded output, process ownership, cancellation, and honest failure patterns—not the generic `/run` input surface. |
| Provider-neutral ports/adapters | Keep import, MCP, and executable technologies behind narrow application-owned contracts. |
| Provenance/receipts | Reuse immutable authorization, revision, evidence, postcondition, and redacted failure conventions. |
| Runtime/backup conventions | Reuse owner-private no-follow stores, strict reopen validation, atomic publication, consistency guards, transactional backup, and no implicit repair. |

## 15. New infrastructure required

V1 genuinely requires:

- normalized immutable manifest and provenance validation;
- revisioned Skill Registry and lifecycle application service;
- Tori-owned requested-versus-granted permission records and evaluator;
- quarantine, inspection, atomic install, and exact confirmed uninstall logic;
- provider projection and per-turn eligibility filtering;
- adapter contracts plus normalized result validation and receipts;
- owner-private secret handles and lease broker before any secret-using Skill;
- backup integration and restore-disabled validation;
- later update/rollback and durable-secret presentation after their backend
  lifecycles exist; the implemented local view covers discovery, inspection,
  exact install, enable/disable/uninstall proposals, lifecycle, health,
  provenance, privacy, and authority summaries;
- malicious fixture and contract-test suites.

MCP, catalog discovery, advisory self-learning, and a general dependency system
were not prerequisites for the first usable Skill. Their implemented seams
remain optional and cannot grant lifecycle authority.

## 16. Minimal implementation slices

Each slice requires fresh Git/runtime integrity capture, focused adversarial
tests, full offline verification at integration checkpoints, and human review.

1. **Registry, manifest, permissions, lifecycle, UI, and backup foundation — implemented**
   Implement immutable local-source records, installed-disabled versus enabled,
   exact local proposals, non-secret receipts, restore-disabled backup behavior,
   a fake instruction component, and capability-awareness projection. No
   executable or MCP support. Suggested Codex: `gpt-5.6-sol`, high reasoning.

2. **Bounded `media.inspect` executable adapter**
   Implement only the threat-modeled fixed `ffprobe` operation and its real
   disposable isolation gate. Do not generalize it into a command loader.
   Suggested Codex: `gpt-5.6-sol`, high reasoning.

3. **Agent Skills instruction import — implemented**
   Import bounded `SKILL.md` directories from explicit local staging or an
   already-staged exact Git revision. Scripts and optional resources remain
   inert; canonical tree hashing, no-follow path rejection, lazy untrusted
   guidance, source/version collisions, local administration, and generic
   Conversation selection are covered by focused tests and two pinned upstream
   acceptance packages. Agent Plugins remain a separate future slice.

4. **Safe public GitHub acquisition — implemented**
   Resolve an explicit GitHub Skill URL to an immutable commit, quarantine and
   inspect the selected package, then use separate local install and enable
   confirmations. No hooks, package code, credentials, dependency acquisition,
   marketplace, or mutable installed identity are admitted.

5. **Read-only skills.sh discovery — implemented**
   Search a bounded public catalog for locally selected candidates, retain only
   ephemeral untrusted catalog evidence, and pass a deliberate choice through
   the existing GitHub acquisition/inspection/proposal flow. It is not a
   marketplace installer or trust root.

6. **Agent Plugins import, later**
   Normalize the packaging envelope without expanding instruction or executable
   authority. No Agent Plugins package is accepted by the current importer.

7. **First MCP interoperability boundary — implemented**
   A reusable local-stdio client and separate Tori-owned server/tool registry
   implement bounded initialization, inspection, individual approval, schema
   drift rejection, exact permission/origin gates, provider projection, call
   normalization, cancellation, child-failure handling, and shutdown. A fake
   server proves the full contract. The official GitHub MCP Server v1.12.0
   read-only profile was inspected in disposable storage with exactly four read
   tools. Later live acceptance used a masked, temporary fine-grained PAT to
   call only approved `get_me` and `get_file_contents` against the public
   `github/github-mcp-server` README; no write tool or credential persisted.
   Arbitrary server administration, remote HTTP transport, write tools,
   persistent credential handling, and broader MCP coverage remain later work.

8. **Local Skills & MCP management UI — implemented**
   A dedicated responsive local view consumes application-owned safe projections
   for installed Skills and configured MCP servers. It exposes network and
   permission scope, lifecycle, provenance, privacy, compatibility, health,
   approved versus discovered tools, and schema drift. Existing skills.sh and
   public-GitHub inspection services remain the only discovery/acquisition paths.
   Install and enable remain separate exact confirmations; disablement and exact
   managed-package uninstall are revision-bound. Uninstall disables first,
   retains the registry tombstone/provenance, and removes only the verified
   digest-derived package. MCP tool approval, server start/stop, and durable
   credentials remain visibly unavailable rather than UI shortcuts.

9. **Advisory capability-gap Skill suggestions — implemented**
   A closed local recognizer can offer an explicit skills.sh search after
   existing capabilities decline a concrete supported gap class. Search requires
   current-turn consent, returns at most three uninspected candidates, and binds
   candidate selection to the current Conversation. Selection reuses only the
   existing GitHub inspection boundary. There is no autonomous installation,
   enablement, execution, update, Skill writing, background monitoring, durable
   behavioral profiling, or remote-origin access.

## 17. Explicit non-goals

Skills V1 is not:

- another agent framework or orchestration core;
- a marketplace, hosted registry, or public catalog;
- an autonomous Skill writer or self-modification system;
- an automatic installer or updater;
- a general package or dependency manager;
- a generic shell, Python, hook, executable, or plugin loader;
- a workflow graph or multi-agent composition system;
- a permission system controlled by manifests, prompts, tool descriptions, or
  model output;
- a route for Skills to directly mutate identity, personality, Memory,
  Conversation truth, Projects, tasks, permissions, provider/model settings,
  configuration, or execution policy;
- a route for remote origins or one Skill to invoke another Skill;
- a claim that MCP or a post-V1 enhancement is complete merely because the
  bounded initial Skills milestone exists.

## 18. Skills V1 closeout and human acceptance

The defined initial Skills V1 implementation and human acceptance are complete.
Desktop acceptance verified direct and hard-refreshed `/skills` routing, truthful
`media.inspect` permissions/privacy and disable/enable confirmation, skills.sh
discovery, selective GitHub inspection, real third-party Agent Skill installation
and separate enablement, plus archive health after lifecycle activity. iPhone
acceptance verified readable populated details, usable controls, and no problematic
horizontal overflow. The canonical runtime intentionally contains enabled
`builtin/tori/media.inspect` v1.0.0 and enabled
`github/github/documentation-writer`; no MCP credential was persisted.

Desktop:

1. Open **Skills & MCP** and confirm `media.inspect` shows local-only, one
   selected-file read, no writes, and no network.
2. Confirm one disposable imported Agent Skill shows source, version,
   compatibility, state, and inert bundled-script status.
3. Enable and disable that disposable Skill; search skills.sh; inspect a public
   GitHub candidate; confirm installation remains approval-gated.
4. Start uninstall for the disposable Skill, verify the exact identity/version/
   digest and unrelated-data warning, then cancel or confirm as desired.

iPhone:

1. Open **Skills & MCP**, expand one Skill detail, and confirm the layout remains
   readable without horizontal overflow.
2. Use one inspect or enable/disable control and verify its confirmation remains
   usable on the narrow viewport.

These completed checks close the initial Skills V1 milestone. It does not include
Agent Plugins, durable/reusable MCP credential brokering,
MCP writes or additional transports, background self-improvement research,
Night Owl, autonomous Skill
writing, automatic updates, or Remote Skill administration.

## 19. Architecture-gate conclusion

This design identifies Tori core ownership, external/import boundaries,
authoritative and derived state, permission and origin controls, lifecycle,
configuration/storage direction, replacement strategy, UI responsibilities,
security tests, and the first bounded proof. It is sufficiently explicit to
plan implementation slices without making MCP or another agent framework the
core.

Each post-V1 implementation slice still requires separate authorization.
Any material expansion of permissions, origins, executable classes, automatic
behavior, source types, or persistent data beyond this document returns to
architecture review.
