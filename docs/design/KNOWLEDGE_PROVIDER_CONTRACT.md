# Tori Knowledge Provider Contract

**Project:** Tori

**Document:** Knowledge Provider Contract

**Status:** Accepted Phase I design contract; the current exact-file foundation is retained, and no ingestion engine, schema, migration, folder grant, or external project is authorized

**Authority:** Subordinate to `docs/00_MISSION.md` through
`docs/06_ARCHITECTURE.md`, `docs/ARCHITECTURE_GOVERNANCE.md`, and
`docs/TARGET_ARCHITECTURE.md`

## 1. Purpose

This document defines the Tori-owned boundary for approved knowledge sources,
document access, optional ingestion/indexing, and replaceable retrieval
implementations.

Knowledge helps Tori understand the subject being discussed. It is distinct from
curated memory, conversation archives, Projects, Search, and source-file
authority. Tori owns what sources are approved, how permission is represented,
what evidence may enter context, and how provenance is presented. A parser,
indexer, embedding service, vector store, RAG engine, or external knowledge
project may assist behind an adapter; it does not own source permission or truth.

The current exact-file knowledge registry and deterministic live retrieval are a
valid local-first foundation. This contract does not select a replacement project,
create a generalized data platform, or authorize ingestion of additional files.

## 2. Governing principles

- The user explicitly controls every source boundary.
- Access to one file or folder grants no permission to another.
- Tori never silently scans, registers, copies, uploads, indexes, or watches
  arbitrary user files.
- Permission to read is separate from permission to register, index, create,
  modify, move, or delete.
- Removing a knowledge registration does not modify or delete the source.
- Source content remains untrusted evidence, never instructions or authority.
- Canonical source identity, grants, provenance, and lifecycle remain Tori-owned.
- Derived chunks, embeddings, indexes, and scores are replaceable and rebuildable;
  they do not become canonical facts.
- Retrieval supplies bounded context. Tori owns context ordering and decides how
  evidence affects an answer.
- Knowledge never silently becomes curated memory, a Project, a task, executable
  policy, or a permission.
- Local processing is preferred. Any external transmission requires explicit
  provider configuration and clear user-controlled authorization.

## 3. Scope and non-goals

This contract covers:

- exact local files and future explicitly approved folder scopes;
- source registration and access grants;
- source metadata and status;
- safe document inspection and ingestion lifecycle;
- provider-neutral retrieval requests, passages, warnings, and provenance;
- replaceable parser/index/retrieval adapters;
- permission, security, failure, and revocation behavior; and
- evaluation criteria for external open-source knowledge projects.

It does not cover:

- implementation of a new database, schema, migration, index, or provider;
- selection of an external project;
- arbitrary filesystem browsing or ambient home-directory access;
- file creation, editing, deletion, or organization;
- automatic web-page retrieval or ingestion from Search results;
- cloud synchronization, credentials, or public uploads;
- automatic memory promotion;
- a generic plugin, MCP, event, or capability framework;
- OCR, image understanding, audio transcription, or archive extraction; or
- broad frontend redesign.

## 4. Domain distinctions

### 4.1 Knowledge versus memory

Knowledge describes external subject matter and remains linked to evidence.
Memory preserves selective relationship continuity under separate Tori policy.
Retrieving a document passage does not authorize storing it as memory.

### 4.2 Knowledge versus Search

Search discovers external candidate information. A search result grants no
permission to open its URL, download a document, register it, or ingest it.
Search findings may inform the current response with source attribution, but they
do not enter the knowledge registry automatically.

### 4.3 Knowledge versus document management

Knowledge access is informational and read-only. Creating, modifying, renaming,
moving, or deleting user documents is a separate effectful capability requiring
its own explicit action contract and permission. A knowledge provider never
receives that authority.

### 4.4 Canonical source versus derived retrieval state

The source file or external source system remains authoritative for its content.
Tori's canonical records describe permission, source identity, provenance, and
observed state. Parsed text, chunks, embeddings, indexes, caches, and ranking
scores are derived. They may be discarded and rebuilt without changing the
source grant or claiming the source changed.

## 5. Ownership boundary

### 5.1 Tori-owned responsibilities

Tori owns:

- the user's source-access grants and their exact scope;
- source registration, enablement, revocation, and removal semantics;
- stable source identifiers and canonical metadata;
- validation of paths, locators, source types, sizes, and network boundaries;
- whether and when inspection, parsing, indexing, refresh, or retrieval may occur;
- the selected allowlisted retrieval/ingestion implementation;
- source-change detection and stale-index policy;
- limits on files, bytes, passages, text, time, and derived storage;
- protected-material filtering and data-minimization policy;
- normalized passage/provenance values;
- context assembly, authority ordering, and current-user-last behavior;
- warnings, conflict handling, and truthful failure presentation;
- application APIs and revision-safe user operations; and
- all permission, privacy, security, audit, and deletion policy.

### 5.2 Source-connector responsibilities

A source connector, where needed, owns only:

- safe read-only access to one already-approved source kind;
- translation from its native locator and metadata into bounded Tori values;
- observed version/change tokens when the source supplies them; and
- native read failures mapped into safe contract errors.

The current local-file connector is implemented directly by the
`KnowledgeRegistry`'s no-follow exact-path reads. A future notes/database/repository
connector must remain equally bounded and must not browse or enumerate outside its
grant.

### 5.3 Ingestion-adapter responsibilities

An optional ingestion adapter owns only:

- parsing supported approved content;
- producing bounded normalized document units and derived metadata;
- creating or updating a derived index within an authorized operation;
- returning a verifiable ingestion outcome; and
- deleting its own derived records when Tori instructs it to revoke a source.

It cannot register sources, expand grants, choose folders, retain undeclared raw
copies, mutate source files, or promote extracted statements into canonical memory.

### 5.4 Retrieval-adapter responsibilities

A retrieval adapter owns only:

- evaluating a bounded query against the approved enabled source set supplied by
  Tori;
- returning bounded candidate passages with source bindings;
- reporting objective derived scores and safe warnings; and
- releasing resources on completion, cancellation, and failure.

It does not choose which sources the user has authorized, alter context priority,
write canonical metadata, or return provider-defined instructions to the model or
frontend.

### 5.5 Client responsibilities

A frontend may show canonical sources, permission scope, status, and provenance;
submit explicit registration/revocation/refresh requests; and display conflicts or
warnings. It does not own filesystem permission, source state, ingestion state,
retrieval authority, or canonical metadata.

## 6. Provider-neutral contracts

Knowledge needs narrow capability-specific seams rather than one universal plugin
interface.

### 6.1 Retrieval port

The existing `KnowledgeRetrievalPort.retrieve(query) -> KnowledgeRetrieval` is the
correct initial Conversation seam: Conversation knows only normalized passages,
warnings, and protected-material omissions. It must not gain registry mutation,
filesystem, HTTP, database, embedding, or provider-specific methods.

A future strengthened retrieval request may include:

- an opaque request identifier;
- the bounded query;
- exact enabled source identifiers or a Tori-owned source-set revision;
- passage count, per-source count, and cumulative text limits;
- an overall deadline; and
- an optional retrieval-profile identifier and revision.

A future normalized retrieval result may add:

- source version/fingerprint observed during retrieval;
- immutable passage or locator identity;
- safe content-type and span metadata;
- an optional provider-reported relevance score clearly marked as derived; and
- observation time.

It must not expose native vector IDs, database clients, embedding objects, raw
provider responses, arbitrary metadata, or UI instructions.

### 6.2 Management/application boundary

Registration, source listing, permission change, refresh, and removal belong to a
Tori application service. Web and CLI clients must not mutate a registry, index,
or provider directly. Mutations validate exact user intent, expected revisions,
grant scope, provider configuration, and post-write verification.

The current `ManagementService` provides a useful user-operation boundary, while
the concrete registry still combines source records, local-file reading, and the
current deterministic retriever. A later implementation may separate those
responsibilities when a second adapter provides concrete evidence for the seam.

## 7. Permission and approval model

### 7.1 Permission dimensions

Knowledge permission must record at least:

- **resource scope:** one exact file, one explicitly approved folder, or one
  separately supported external collection;
- **operation:** inspect metadata, read content, register, derive/index, refresh,
  or revoke derived state;
- **provider boundary:** local Tori process, selected local/LAN service, or a future
  external service;
- **lifetime:** one operation or a visible revocable persistent grant;
- **content constraints:** allowed types, recursion policy, exclusions, file count,
  per-file bytes, and cumulative bytes; and
- **identity:** a stable grant identifier and revision.

Read permission does not imply write permission. Index permission does not imply
permission to retain raw content indefinitely. Permission for a folder does not
imply its parent, siblings, future mounts, symlink targets, or unrelated file
types.

### 7.2 Exact-file grants

The current explicit exact-file registration is a persistent informational grant
to reopen that exact resolved regular file for relevant retrieval until the user
removes the registration. It does not grant access to its directory or permit
source modification.

Registration validates the source at the time of approval. Every later read
revalidates type, path safety, size, encoding, and current availability. A symlink
or changed ancestor never expands the grant.

### 7.3 Approved-folder grants

Folder grants are a future product decision, not an implication of this contract.
If authorized later, a grant must specify:

- one canonical existing directory root;
- whether traversal is direct children only or explicitly recursive;
- allowlisted content types;
- excluded names/subtrees;
- maximum file count and cumulative bytes;
- whether new matching files may be noticed, indexed automatically under the
  persistent grant, or require separate approval;
- whether changes may be refreshed automatically or only explicitly;
- local versus external processing boundary; and
- revision, creation time, and revocation state.

Default behavior is no recursive traversal and no automatic inclusion of newly
appearing files. Symlinks and mount/boundary escapes are rejected. Tori must show
the proposed scope before approval and keep it reviewable and revocable.

### 7.4 Outside approved boundaries

When a request needs a file or folder outside current grants, Tori asks before
accessing it. A conversational mention, model output, search result, guessed path,
recent-file list, or previous permission for another resource is not consent.

Creating, modifying, moving, or deleting anything outside or inside a knowledge
grant requires a separate effectful workflow. Knowledge registration itself never
authorizes those operations.

## 8. Source model and metadata

A canonical `KnowledgeSource` should conceptually support:

- `identifier`: stable opaque Tori-owned identity;
- `display_name`: safe user-facing name;
- `source_kind`: allowlisted type such as exact local file;
- `locator`: canonical path or provider-neutral source reference, protected from
  unnecessary client disclosure where appropriate;
- `permission_grant_id` and grant revision;
- `content_type`: validated Tori-owned type;
- `enabled`: whether retrieval may use the source;
- `registered_at`, `updated_at`, and optional `last_observed_at`;
- observed byte size and modification/version metadata;
- a cryptographic content fingerprint when needed for stable ingestion and stale
  detection;
- current availability and safe reason code;
- ingestion mode such as `live` or `derived_index`;
- derived-index revision/status without native provider IDs; and
- optimistic revision for user-controlled mutations.

The record should not contain raw credentials, arbitrary provider internals,
source content merely for convenience, embeddings, native vector IDs, or mutable
permissions inferred from the filesystem.

The current schema-1 JSON registration contains stable ID, exact resolved path,
filename, file type, and registration time. It remains valid for the present
exact-file live-retrieval product. This contract does not authorize changing it.

## 9. Document inspection and ingestion lifecycle

Ingestion is optional. The current live `.txt`/`.md` retrieval path does not copy
or pre-index content and should not be relabeled as ingestion.

If a future derived ingestion path is approved, it follows this lifecycle:

1. **Propose scope.** Tori identifies the exact source or bounded folder and the
   local/LAN/external processing boundary.
2. **Approve.** The user explicitly approves the source grant and any persistent
   refresh behavior. No provider contact occurs before approval.
3. **Validate.** Tori reopens descriptors safely, rejects symlinks and special
   files, validates type/size/count, and captures a stable source observation.
4. **Inspect.** A bounded local source connector reads only approved bytes.
5. **Protect.** Tori applies secret/protected-content policy before any external
   adapter receives content. If safe minimization cannot be guaranteed, the
   external operation fails closed.
6. **Parse.** An adapter produces bounded normalized units with source spans and
   no authority-bearing metadata.
7. **Index.** Derived state is built under a new unpublished revision. Partial or
   failed output never replaces a verified current index.
8. **Verify.** Tori verifies source binding, counts, limits, expected fingerprint,
   provider outcome, and index readability.
9. **Publish.** Tori atomically marks the verified derived revision available.
10. **Observe.** Later source changes make the derived revision stale unless an
    explicitly approved refresh policy safely rebuilds it.
11. **Revoke.** Removing permission disables retrieval immediately and instructs
    adapters to remove derived state. Source files remain untouched. Failure to
    verify derived deletion is reported honestly.

No ingestion operation silently broadens scope, retries through another provider,
uploads to another boundary, or converts content into memory.

## 10. Retrieval lifecycle and context boundary

For each Conversation request:

1. Tori normalizes the user query.
2. Tori determines the exact enabled approved source set.
3. Tori invokes the selected retrieval implementation with bounded limits.
4. The adapter returns source-bound candidate passages.
5. Tori validates source identity, permission, source/index revision, text, spans,
   count, cumulative budget, and protected-content policy.
6. Tori selects optional passages under context-planning policy.
7. The model receives clearly labeled untrusted reference data.
8. Tori retains safe passage provenance for the current response where the product
   requires it.

Knowledge is optional context. Failure degrades honestly and does not fail ordinary
conversation unless the user explicitly required that source and proceeding would
misrepresent the result.

Current user input remains last in context-authority ordering. Retrieved text
cannot override Tori identity, application state, user intent, permissions, or
current instructions merely because it appears in a document.

## 11. Change, refresh, and revocation behavior

- A live source is reopened from its exact approved path for every retrieval.
- Missing, unreadable, oversized, unsupported, malformed, or path-changed sources
  become unavailable; Tori does not repair or replace them.
- Derived indexes bind to a source fingerprint or version. A mismatch is stale,
  not silently current.
- Refresh uses the same grant and scope. It cannot discover siblings or broaden a
  folder.
- A failed refresh preserves the last verified index only if Tori labels it stale
  with its observation time and policy permits stale use; otherwise retrieval is
  unavailable.
- Disabling or revoking a source immediately excludes it from future retrieval.
- Removing a registration removes only Tori-owned registration/derived state, not
  the source document.
- Provider failure never edits grants, changes active providers, or chooses another
  source.

## 12. Availability and errors

Status should distinguish:

- source configured/registered state;
- permission active/revoked state;
- source available/missing/unreadable/unsupported/oversized state;
- retrieval provider unknown/available/unavailable/degraded state;
- ingestion not required/pending/indexing/verified/stale/failed state; and
- observation timestamps for every derived claim.

Safe error categories may include:

- `permission_required`;
- `permission_revoked`;
- `invalid_source`;
- `source_missing`;
- `source_unreadable`;
- `unsupported_format`;
- `source_too_large`;
- `protected_content`;
- `provider_unavailable`;
- `provider_timeout`;
- `invalid_provider_response`;
- `index_stale`;
- `ingestion_failed`;
- `retrieval_failed`; and
- `cancelled`.

Errors do not expose protected content, credentials, unnecessary absolute paths,
raw provider responses, native index identifiers, or unrelated source names.

## 13. Security and privacy

- File access uses no-follow descriptor-based reads and revalidates every ancestor,
  type, size, and content boundary appropriate to the source.
- Directory access, if later approved, is descriptor-rooted and cannot escape via
  symlinks, `..`, mount substitution, or provider-returned locators.
- Special files, devices, sockets, pipes, and unsupported encodings fail closed.
- Source content is untrusted data and cannot grant permission or issue commands.
- Known authentication secrets and private-key material remain excluded under
  Tori-owned policy; external transmission requires stronger separately reviewed
  minimization and disclosure.
- Providers receive only approved content necessary for the current operation and
  no ambient filesystem, browser, command, memory, Project, task, or network access.
- External adapters cannot retain or train on source content unless a separately
  approved contract and explicit user consent say so.
- Logs contain source/grant/request IDs and safe reason codes, not source passages
  or secrets.
- Search results, attachments, clipboard contents, recent files, and model-proposed
  paths are never auto-registered.
- Retrieval results cannot mutate canonical source records, memory, permissions,
  identity, Projects, tasks, or execution policy.

## 14. Retrieval or ingestion provider profiles

If multiple implementations later require saved configuration, a profile should be
separate from source grants. Conceptual fields include:

- stable profile ID and display name;
- explicit allowlisted provider type;
- local process, endpoint, or service locator where applicable;
- enabled state;
- bounded timeouts and portable retrieval limits;
- Tori-derived network/data boundary;
- allowlisted authentication reference, never a raw secret;
- bounded adapter-scoped options;
- supported source/content types and capability observation; and
- revision and timestamps.

Active retrieval-provider selection is separate canonical state. Changing a
provider does not change source permission. A source approved only for local
processing cannot be sent to a LAN or external provider merely because that
provider becomes active. Each source grant and provider profile must be compatible,
or retrieval fails without fallback.

This document does not authorize profile persistence, a provider store, or
migration.

## 15. Current architecture assessment

### 15.1 Current knowledge store should remain

The current `KnowledgeRegistry` should remain the canonical exact-file source
registration and permission foundation for the present product because it already
provides:

- explicit user registration of one exact `.txt` or `.md` file;
- metadata-only schema-1 records rather than copied documents;
- live source authority and fresh reads;
- no-follow path and regular-file validation;
- strict file, registry, passage, per-source, and cumulative limits;
- deterministic retrieval with stable source/line provenance;
- protected authentication/private-key omission;
- explicit listing and verified registration removal;
- removal of registration without source deletion; and
- graceful optional-context degradation.

Replacing this canonical permission registry with a vector database or external RAG
project would conflate permission/source truth with derived retrieval technology.
No current evidence justifies that change.

### 15.2 Existing retrieval boundary should remain

`KnowledgeRetrievalPort` correctly keeps Conversation independent of the concrete
registry. Fake and current implementations already prove substitution at this
boundary. Conversation should continue to consume normalized `KnowledgeRetrieval`
only.

### 15.3 Responsibilities that may move behind adapters later

- parsing formats beyond bounded UTF-8 text and Markdown;
- chunking when formats reveal a common portable unit model;
- embeddings, indexes, ranking, and retrieval algorithms;
- external knowledge-base protocol translation;
- provider-specific status and lifecycle; and
- deletion of provider-owned derived state.

The current deterministic token-overlap retriever remains an appropriate local
adapter/reference implementation. It need not be discarded merely because a more
powerful derived retriever may later exist.

### 15.4 Responsibilities that should not change yet

- exact-file registration semantics and schema 1;
- supported `.txt`/`.md`, UTF-8, 1 MiB source boundary;
- live read rather than background indexing;
- current registry removal and confirmation behavior;
- protected-content omission;
- current context limits and graceful failure behavior;
- Conversation, memory, Project, task, Search, and archive semantics; and
- current frontend.

## 16. External project recommendation and evaluation criteria

No external project should replace the current knowledge store now. When a future
implementation phase needs richer parsing, indexing, or retrieval, evaluate current
open-source projects for integration as adapters behind Tori's canonical source and
permission boundary.

Evaluation must be refreshed at that time and include:

- **License:** OSI-approved terms, compatibility with Tori's distribution goals,
  clear dependency licensing, and no ambiguous model/data restrictions.
- **Maintenance:** recent releases, responsive maintainers, issue/PR activity,
  supported runtime versions, and a credible upgrade path.
- **Security history:** disclosed vulnerabilities, response quality, secure
  defaults, supply-chain practices, authentication model, and isolation options.
- **Local deployment:** fully local/self-hosted operation, offline behavior,
  controllable network egress, deterministic data locations, and support for Tori's
  hardware/environment.
- **Dependency footprint:** installation size, transitive services, language/runtime
  burden, native components, operational complexity, and backup implications.
- **Architecture fit:** stable API, clean source/index separation, replaceability,
  cancellation, bounded operations, typed errors, and no demand to own Conversation
  or canonical policy.
- **Data ownership:** explicit storage paths, export/deletion support, no mandatory
  cloud, no training or telemetry by default, and verifiable removal of derived
  records.
- **Permission model:** ability to restrict exact sources and collections, prevent
  ambient scanning, enforce tenant/scope boundaries, revoke access, and avoid
  provider-controlled permission expansion.
- **Provenance quality:** stable source binding, document/version identifiers,
  passage locators, and traceable retrieval results.
- **Failure and migration:** honest degraded operation, recoverable/rebuildable
  indexes, format stability, backup/restore behavior, and an exit path that preserves
  Tori-owned source metadata.

A candidate that requires surrendering source authority, broad filesystem access,
opaque cloud storage, or provider-owned permissions is unsuitable even if retrieval
quality is strong.

## 17. Conformance strategy

Future implementation tests should prove:

- Conversation substitutes fake and real retrieval adapters without importing
  their implementation;
- no source outside the exact approved grant is opened, enumerated, or transmitted;
- file/folder boundaries resist symlink, traversal, race, special-file, and size
  attacks;
- registration, grant, provider selection, and revocation are revision-safe if
  persistence is approved;
- source removal never modifies the source file;
- derived data cannot become canonical permission or truth;
- stale source/index bindings fail or are labeled honestly;
- protected material is omitted before provider transmission;
- provider output cannot trigger actions or state mutation;
- source/provider failure leaves ordinary Conversation usable;
- no automatic fallback changes processing or data boundaries;
- external adapters delete derived state verifiably on revocation;
- tests use isolated temporary sources/stores; and
- canonical runtime remains unchanged during verification.

## 18. Deferred decisions

- whether approved folders are needed and their exact persistent permission UX;
- additional document formats and parser selection;
- content fingerprints and revision schema;
- live versus indexed source modes;
- retrieval/ingestion provider profiles and active selection;
- derived index storage, backup, rebuild, and deletion semantics;
- a second retrieval adapter or external project;
- local embedding model selection;
- external providers, credentials, and content transmission;
- explicit connection testing and capability discovery;
- source refresh/watch policy;
- page retrieval and user-provided upload workflows; and
- frontend source/provider management changes.

Each requires its own product workflow, threat model, current ecosystem review,
storage decision, and human approval before implementation.

## 19. Decision summary

Tori should keep its current exact-file knowledge registry as the canonical source
and permission foundation and keep `KnowledgeRetrievalPort` as the Conversation
boundary. Richer parsers, indexes, vector stores, RAG engines, or external knowledge
projects should be evaluated later and integrated as replaceable adapters. They
must never own source grants, silently scan files, change canonical truth, or widen
permissions. No replacement project, ingestion engine, folder grant, schema,
migration, dependency, runtime change, or frontend work is authorized by this
contract.
