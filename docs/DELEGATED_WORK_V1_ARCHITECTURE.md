# Delegated Work / OpenCode Orchestration V1

**Status:** Complete and physically accepted

## Purpose

Delegated Work lets the user give Tori a bounded coding objective in ordinary
Conversation, explicitly approve the proposed authority, let the existing
OpenCode integration perform implementation mechanics, and later ask Tori for
authoritative status or a concise terminal receipt.

The architectural rule is: **Tori delegates work; OpenCode does not become
Tori.** Tori owns objective, authority, workspace identity, restrictions,
lifecycle, durable history, evidence interpretation, and user presentation.
OpenCode remains one replaceable coding worker.

## Reused architecture

V1 extends the accepted Coding Work foundation rather than renaming or
duplicating it:

- `CodingWork` is the Tori-owned durable delegated-coding aggregate and keeps
  its immutable `coding-work-*` identity.
- `CodingWorkApplicationService` owns use cases and lifecycle policy.
- `CodingWorkerAdapter` is the application-owned worker port.
- `OpenCodeCodingWorkerAdapter` remains the first production adapter, using
  OpenCode 1.18.21 ACP behind Tori's supervisor, local inference relay, and
  Bubblewrap boundary.
- `CodingWorkRuntime` owns readiness, restart reconciliation, mutation
  admission, backup coordination, and shutdown.

No generic Job framework, worker-to-worker delegation, new database, or schema
migration was introduced. “Delegated Work” is the user-facing workflow over
the existing concrete coding domain, not a second source of truth.

## User workflow

One clear coding request with one existing absolute workspace can enter the
deterministic Coding Work recognizer. Tori displays objective, workspace,
acceptance criteria when supplied, read/modify intent, sandboxed execution,
and explicit exclusions including commit, push, release, deploy, publish,
network, host credentials, and external filesystems. Nothing is created until
the conversation-bound proposal is confirmed.

After confirmation, the browser may disconnect or navigate elsewhere. The
canonical record, worker binding, events, evidence, and terminal result live in
Tori's store. Ordinary Conversation supports bounded provider-free questions
such as:

- `How is that fix going?`
- `What did OpenCode change?`
- `Did the tests pass?`
- `Stop that coding job.`
- `Continue that work and fix the remaining test.`

Status reads and stop requests select chat-bound work first. A stop request is
authority-reducing and uses the existing revision-bound durable cancellation
directive. If more than one candidate is active and current context does not
identify one, Tori refuses to guess.

A related follow-up never silently inherits authority. Tori proposes a fresh
bounded Coding Work item in the same workspace and records the prior work ID in
the new item's durable `created` event. Confirmation produces a new immutable
authorization and worker run. This is truthful for the current ACP adapter,
whose normal `end_turn` is terminal; V1 does not claim that a closed OpenCode
session resumed.

## Authority and security

The accepted Coding Work authority envelope remains unchanged. Authority is
bound to one exact resolved existing directory, read/modify decisions, and
sandboxed tool execution. Proposal application revalidates canonical path,
directory type, device, and inode. Project/chat association is provenance and
organization only.

OpenCode receives no general network, host HOME, credentials, caches, external
filesystem, writable authoritative `.git`, Git remote, commit, push, release,
deployment, publication, package acquisition, or workspace-creation authority.
Bubblewrap availability and every unsafe mount condition fail closed. Worker
permission requests are checked against the immutable Tori envelope; worker
output, a model, Project context, Skills, Night Owl, Capability Growth,
Companion Initiative, and Scheduled Work cannot expand it.

Night Owl and other proactive systems remain advisory. They cannot create,
authorize, start, continue, or cancel Delegated Work.

## Durable state and lifecycle

Schema 1 remains authoritative. It stores work aggregates, immutable authority
snapshots, adapter/session runs, directives, and bounded semantic events.
Lifecycle remains:

```text
awaiting_authorization -> queued -> starting -> running/waiting
                                            -> cancelling/reconciling
                                            -> completed/failed/cancelled
```

`waiting` is attention-needed when the adapter reports that additional
authority is required. Pause/resume is not invented. Terminal records remain
queryable, and the Workspace projection shows active, attention-needed, and
recent terminal records after browser reconnection.

On startup, prior nonterminal observations become `reconciling`. A proven
quiescent session may reattach; an interrupted active turn is not replayed or
promoted to success. Missing workspace/session, unavailable worker or sandbox,
malformed worker output, and cancellation remain durable truthful outcomes.

## Terminal receipt and evidence

The receipt combines Tori-owned fields and bounded adapter evidence:

- requested objective, workspace, and acceptance criteria;
- lifecycle and start/update/terminal timestamps;
- changed paths observed through bounded workspace snapshots;
- structured verification and artifacts;
- terminal summary or failure;
- relationship to prior work; and
- the standing fact that commit/push was not authorized.

Worker prose alone is not treated as complete proof. Workspace snapshot
evidence is independently observed by the adapter boundary; other worker/tool
verification remains labeled structured recorded evidence. When no structured
proof establishes every acceptance criterion, Tori says that it was not
independently verified instead of manufacturing success.

## UI and API

The existing responsive Workspace utility card is retained and renamed
“Delegated Work.” It lists up to the bounded current projection as Active,
Needs attention, or Recent. Selecting an item shows objective, workspace,
authorization state, acceptance assessment, related work, changed files,
verification, activity, result, and revision-safe Stop when valid. Raw ACP,
process, provider, socket, stderr, reasoning, and token-stream details remain
outside the normal projection.

The existing `/api/coding-work` and `/api/coding-work/cancel` routes remain the
stable transport. Browser code does not own authority or lifecycle truth.

## Backup and restore

No new store was added. The existing coordinated Coding Work backup guard and
known SQLite coverage therefore include Delegated Work records and related-work
events. Active writers and provider sockets still make backup busy rather than
causing cancellation or an incoherent copy. Whole-runtime restore copies the
same generation and performs SQLite integrity verification.

## Explicit non-goals

V1 does not add autonomous coding, generic agents, generic Jobs, multi-repo
orchestration, worker-to-worker delegation, pause/resume, arbitrary MCP,
workspace creation, package acquisition, general network, Git commit/push,
release/deploy/publish, or proactive initiation by Night Owl, Capability
Growth, Companion Initiative, Projects, Skills, or Scheduled Work.
