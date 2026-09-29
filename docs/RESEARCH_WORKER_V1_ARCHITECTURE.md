# Research Worker V1 architecture

Status: complete and physically accepted on 2026-09-21.

Deployment note: On the accepted host the Git-ignored per-machine configuration
points to the separately prepared `GPT-Researcher-Tori-PoC` project directory,
including its own `.venv` and `supervisor.py`. Core Tori does not need this
external source tree; Research Worker does. Removing it disables Research Worker.
The separate upstream `GPT-Researcher` checkout is not a production dependency,
and `install.sh` does not provision the wrapper. See [Current State](FINAL_STATE.md#deployment-data-and-recovery-boundaries)
for the current local path and the deferred installer/portability gate.

Architecture review, 2026-09-24: the sections through **Acceptance state**
describe the original accepted implementation. The claim/evidence ledger
refinement below is now implemented for new reports in schema 3; the remaining
contract refinements are proposals. Historical schema-2 reports remain readable
without invented evidence. The 2026-09-21 acceptance claim is unchanged.

## Boundary

Research Worker is not Search, Night Owl, Coding Work, or MCP. Search remains the
short `SearchPort → results → answer` path. Night Owl remains fixed-scope advisory
discovery. Research is a user-authorized, durable, long-running public-web job.
It cannot launch Coding Work, alter a Project, ingest its report into Memory or
Knowledge, or grant itself authority.

Tori owns the canonical `research-*` job ID, authorization snapshot, limits,
lifecycle, progress, sources, validation summary, final report, cancellation,
and restart truth in `runtime/research/tori_research.db`. GPT Researcher remains
a replaceable specialist behind `ResearchWorkerPort`. Its process ID and session
ID are operational handles, never canonical identity.

## Authorization and disclosure

Conversation recognition creates a durable `awaiting_authorization` proposal.
The confirmation is bound to the exact chat and revision and discloses:

- public web only;
- public objective only;
- no private Tori data, Memory, Knowledge, local files, archives, or secrets;
- local Ollama only and bounded authoritative plus secondary public retrieval;
- bounded duration, searches, results, pages, bytes, concurrency, and report size.

Decline creates a durable cancelled receipt without starting a process. Project
association is organizational only and is never copied into the worker request.

## Worker protocol

### Canonical production contract

The adapter and wrapper use protocol version 1. Tori's domain names are not
passed through implicitly; every field has one explicit wire representation:

| Tori-owned value | Start/status wire field | Wrapper interpretation | Completion/result field | Tori expectation |
| --- | --- | --- | --- | --- |
| canonical work ID | `job_id` | opaque correlation ID | `job_id` | exact match |
| process attempt ID | `attempt_id` | one supervised attempt | `attempt_id` | exact match |
| authorized objective | `objective` | immutable research subject | `objective_fidelity` | named subject preserved or degraded/failure |
| configured local model | `model` | Ollama model for all LLM roles | `effective_runtime.model` | exact match |
| configured embedding model | `embedding_model` | local Ollama embeddings | `effective_runtime.embedding_model` | exact match |
| local-only provider policy | `provider=ollama`, `retriever=authoritative_source`, ordered `search_providers` | GitHub/Hugging Face primaries plus SearXNG secondary discovery | `effective_runtime` | exact match |
| `maximum_duration_seconds` | `max_duration_seconds` | monotonic job deadline | `effective_limits.max_duration_seconds` | exact match |
| `maximum_search_queries` | `max_search_queries` | search reservation ceiling | `effective_limits.max_search_queries` | exact match |
| `maximum_results_considered` | `max_results_considered` | result ceiling | `effective_limits.max_results_considered` | exact match |
| `maximum_sources_fetched` | `max_sources_fetched` | fetch ceiling | `effective_limits.max_sources_fetched` | exact match |
| `maximum_bytes_per_page` | `max_bytes_per_page` | per-page byte ceiling | `effective_limits.max_bytes_per_page` | exact match |
| `maximum_total_fetched_bytes` | `max_total_fetched_bytes` | total byte ceiling | `effective_limits.max_total_fetched_bytes` | exact match |
| `maximum_concurrent_fetches` | `max_concurrent_fetches` | fetch semaphore | `effective_limits.max_concurrent_fetches` | exact match |
| `maximum_report_characters` | `max_report_chars` | final report ceiling | `effective_limits.max_report_chars` | exact match |
| public-web authority snapshot | `authority` | exact public-only/no-private-data policy | retained in Tori authorization | valid schema/digest before launch |
| `start` | `type=start` | starts exactly one attempt | `accepted` | effective runtime and limits must match |
| `status` | `type=status` | reports current phase/state | `status` | matching job and attempt |
| `cancel` | `type=cancel` | cooperative stop, then supervised escalation | `cancelled` | exactly one terminal outcome |
| `result` | `type=result` | replays retained terminal object | `result.terminal` | identical terminal state and payload |
| normalized progress | — | bounded phase/message | `progress` | known phase, no raw chatter |
| evidence source | — | fetched/ranked evidence | `source` and completion `sources` | exact URL and boolean `used_in_report` |
| completion gate | — | final claim repair/validation | `validation_gate_passed`, `validation_summary.unsupported_presented_as_fact` | true and zero respectively |

Unknown fields, missing required fields, or an effective-runtime/limits mismatch
fail the attempt closed. The adapter never invents evidence-validation fields.

The subprocess receives one NDJSON `start` document and may receive `cancel`.
Normalized events are `accepted`, `progress`, `source`, `status`, `completed`,
`completed_with_limits`, `cancelled`, `failed`, and `error`. Tori rejects unknown,
oversized, malformed, cross-job, and cross-attempt events. Cancellation is
cooperative first, then process-group `SIGTERM`, then `SIGKILL` after the configured
grace period. Only one terminal event is persisted.

The worker environment is a complete allowlist. It contains local Ollama model
settings, local embedding settings, the approved authoritative provider order, the Tori-owned proxy endpoints,
and no ambient cloud credentials or arbitrary proxy values.

## Process ownership

Authorized attempts are registered with one durable, application-owned Research
supervision thread. Web request threads enqueue immutable launch records and do
not call `Popen`. The supervision owner alone creates Bubblewrap, retains process
ownership for the Research runtime lifetime, and hands stdout, stderr, terminal
observation, cancellation, and cleanup to the existing bounded session machinery.

Bubblewrap deliberately retains `--die-with-parent`. Linux associates that
protection with the particular thread that created the child, so the durable
owner remains alive after an authorization HTTP request returns. If that owner
dies unexpectedly, the kernel still terminates Bubblewrap and its namespace.
Queued cancellation is checked before process creation, duplicate job attempts
are rejected, and orderly application shutdown stops admission and terminates the
owned process without recording a user cancellation. Startup then reconciles the
still-nonterminal durable job to `interrupted`; V1 never resumes it automatically.

## Network isolation

The worker runs under Bubblewrap with all namespaces unshared and no direct host,
LAN, or internet network. Inside that private network it sees only a loopback
HTTP/HTTPS CONNECT proxy and a loopback Ollama relay. Both cross the namespace
through one per-job Unix socket to a Tori-owned broker.

For public traffic the broker resolves the requested hostname, rejects the entire
answer set if any address is loopback, private, link-local, reserved, multicast,
unspecified, or metadata, then connects the already-validated numeric sockaddr.
Redirects create a new proxied request and are revalidated. This removes the PoC's
DNS-validation-to-later-resolution TOCTOU window. Ollama relay traffic can reach
only the configured exact loopback endpoint. The namespace has no route for a
worker-controlled direct connection.

The Ollama relay additionally allowlists inference and embedding endpoints,
accepts one bounded non-chunked HTTP request per connection, and relays only the
response afterward. This prevents request pipelining from reaching model-management
operations such as pull, create, or delete.

TLS remains end-to-end between the worker HTTP client and the public server. The
broker tunnels HTTPS and does not install a CA, disable verification, or inspect
credentials. Browser profiles, cookies, shell access, Tori runtime, and unrelated
filesystem paths are absent from the sandbox.

## Evidence and completion

Source events persist exact URL, title, primary/secondary/other classification,
authority reason, retrieval timestamp, optional content hash, and whether the
source was used in the report. Fetched page bodies remain bounded per-job worker
evidence rather than entering normal Tori backups.

The original V1 gate required a non-empty worker report, validation summary,
successful worker finalization assertion, zero worker-reported unsupported facts,
and exact used-source URLs already observed by Tori. The schema-3 gate retains
the source and finalization checks but builds the user-visible report from
validated claims, not from worker prose. The hardened worker remains responsible
for primary-first selection, hostile-page instruction isolation, and proposing
supported/partial/unsupported/conflicting classifications.

For reports admitted after the schema-3 refinement, Tori also requires a
bounded per-claim ledger and retained excerpts from exact observed source URLs.
The result is committed atomically with its source links. `SUPPORTED` and
`PARTIALLY_SUPPORTED` each require retained evidence; `CONFLICTED` requires
evidence from at least two distinct sources; `UNSUPPORTED` is rendered as
unverified regardless of worker prose or its finalization assertion.
Limited claims turn an otherwise `completed` terminal into
`completed_with_limits`, now presented as completion with limitations. A new
report with no retained usable evidence fails, even if its prose is qualified.
This is structural provenance validation, not independent semantic proof of a
source's truth. Reports completed before this gate are `legacy_report_only` and keep
their original historical state.

## Persistence, backup, and restart

The Research SQLite database participates in verified backup snapshots under a
maintenance guard. Per-attempt session directories and sockets are operational
and are not durable evidence. On startup every nonterminal job is marked
`interrupted`; V1 never invents resume. Completed and limited reports remain
queryable with exact source provenance.

## Configuration

Research is opt-in:

```toml
[research]
runtime_root = "/path/to/Tori/runtime/research"
worker_root = "/path/to/research-worker"
python_executable = "/path/to/research-worker/.venv/bin/python"
worker_entrypoint = "/path/to/research-worker/supervisor.py"
bubblewrap_executable = "/usr/bin/bwrap"
ollama_url = "http://127.0.0.1:11434"
model = "qwen3.8:latest"
embedding_model = "nomic-embed-text:latest"
search_providers = ["github", "huggingface", "searxng"]
cancellation_grace_seconds = 5.0
```

GitHub and Hugging Face are queried without tokens for identity-verified project
and model discovery. SearXNG supplies only broad secondary context through a
Tori-owned exact-destination relay; its failure never discards successful primary
evidence. Provider operations consume the ordinary bounded discovery budget and
every source retains its true `github`, `huggingface`, or `searxng` provenance.
There is no DDGS, browser-search, account-backed, paid, or cloud fallback.

## Acceptance state

Research Worker V1 passed production-path Piper and broad local-TTS smokes through
the final authoritative retriever, physical browser authorization and report
completion, a five-claim citation audit, cooperative Workspace cancellation with
one durable terminal event, active-job restart reconciliation to `interrupted`,
Workspace evidence/provenance inspection, public-only network regression, wrapper
tests, and the complete milestone verifier. The authoritative-source benchmark
also passed 12/12 queries, 17/17 provider operations, and 10/10 named-project
primary-source discoveries without credentials. Exact evidence is recorded in
  private acceptance evidence, which is not included in the public candidate.

## Proposed contract refinements and implemented ledger slice

### Implemented claim/evidence ledger (schema 3)

Schema 3 adds `research_claims`, `research_evidence`, and
`research_claim_evidence` to the existing Research store. Claim and evidence IDs
are stable `(job_id, sequence)` pairs; evidence references the existing
`research_sources(job_id, sequence)` key and retains a bounded excerpt, source
URL locator, extract position, and SHA-256 excerpt fingerprint. A joined
Research-owned read API resolves a claim to evidence and its source. The
Workspace status API labels completed pre-ledger reports `legacy_report_only`;
it does not synthesize missing evidence. The schema-2-to-3 upgrade uses one
explicit transaction for all new DDL and the version update; failed migration
rolls back to the original schema-2 data and metadata.

The terminal adapter uses the existing worker protocol's `validation` claim
entries, `source_urls`, and source `relevant_extracts`. No external wrapper or
worker protocol version was changed. Tori checks exact observed same-job URLs,
source-fingerprint consistency when both worker messages supply one, support
states, and worker-summary agreement before committing. Stored support counts
are recomputed from the validated ledger. Bounds are 64
claims, 1,000 characters per claim, 12 evidence links per claim, 128 evidence
records and 64,000 retained evidence characters per report, and 1,600
characters per excerpt. At least one retained evidence record is required for
any new terminal report. Terminal event receipts omit the excerpt copy; raw page
bodies and private model reasoning remain outside the ledger. New terminal
reports lacking this structure fail with `semantic_validation_failed`.

For new reports, `research_jobs.report` is a deterministic Findings section
rendered only from persisted claim states, texts, and linked source IDs. Each
finding visibly carries `SUPPORTED`, `PARTIALLY SUPPORTED`, `CONFLICTED`, or
`UNSUPPORTED` wording. Unsupported claims are never presented as unqualified
facts. The free worker narrative, if supplied, remains separately retained in
the terminal event as `unverified_worker_narrative`; it cannot satisfy the
evidence gate or appear as validated findings. `report_location` is merely a
worker narrative locator. Historical report prose remains unchanged.

The retained extracts are supplied by the worker for cited sources, and source
events remain worker observations rather than independent Tori fetch receipts.
Structural checks prove ownership, bounded retention, and inspectability; they
cannot prove that an excerpt semantically entails a claim or authenticate remote
content. Optional source hashes are consistency metadata, not proof of content
origin; an omitted repeated hash is not treated as verification. Workspace
labels the counts as worker classifications with retained provenance.
Independent semantic review, source quality,
candidate/fetch receipts, and direct chat evidence lookup remain future work.

### Remaining proposed contract refinement

### Baseline audit and reuse map

At `private revision omitted`, the tracked worktree was
clean. Research Worker is already a production capability. This review uses the
repository's accepted implementation as its starting point, not a hypothetical
pre-Research baseline. The separately documented GPT-Researcher v0.14.7 local
  proof and external wrapper established a local
LLM, local embeddings, keyless retrieval, wrapper-owned source policy, and
evaluated citations. This review did not read or change those external trees.
The accepted production path and its limits are recorded above and in
  the configuration and acceptance summary above.

| Existing component | Reuse for the refined contract | Boundary not to reuse |
| --- | --- | --- |
| `SQLiteResearchStore`, `ResearchApplicationService`, `ResearchWorkerPort`, `SupervisedResearchWorker`, `ResearchRuntime` | Extend the Research-owned job, authority, event, source, backup, supervision, and restart truth. Keep the replaceable worker port and exact attempt correlation. | Do not make the external wrapper or its process/session ID canonical state. Schema 3 has bounded claim/evidence tables but no separate original request or continuation table. |
| `SQLiteCodingWorkStore`, `CodingWorkApplicationService`, `CodingWorkProcessSupervisor`, `BubblewrapCodingWorkSandbox` | Borrow tested design patterns for optimistic revisions, durable receipts, owner lifetime, cancellation escalation, and cleanup. | Do not reuse Coding Work authority, writable workspace mounts, command directives, repository access, OpenCode transport, or its permission profile. Research has its own store and sandbox. |
| `ProjectApplicationService`, `ProjectRelatedSources`, `ProjectContextService`, `ConversationArchiveStore` | Keep source-owned `project_id`, Project Home metadata projection, bounded context planning/receipts, and durable chat origin. | Project membership, brief, transcript, links, and context must not become research input or grant authority. Do not duplicate a report in the Project store. |
| `CompanionAttentionSources` and Workspace research status | Show active/terminal work and needs-attention signals with links to Research-owned details. | Do not make Attention the job owner or let it start follow-up work. |
| `NightOwlResearchRunner`, `DiscoveryPort`, `SearchPort`, `SourceRetrievalPort` / `SourceRetrievalService` | Reuse provider-neutral discovery and public-source validation patterns where budgets and policy fit. Shared low-level transport may serve both products. | Ordinary Search has current-turn limits; Night Owl has fixed categories and its own grants. Neither owns arbitrary user-directed Research jobs. Do not route Research through Search consent or Night Owl scheduling. |
| `CapabilityInventory`, `CapabilityGrowthApplicationService`, `KnowledgeRegistry`, Skills/MCP services | Read their existing contracts to avoid authority confusion and preserve explicit promotion paths. | No automatic journal evidence, recommendation, Knowledge registration, Skill/MCP invocation, installation, or capability promotion from a report. |
| `BackupService` and conversation archive | Continue guarded Research DB backup and lightweight proposal/completion chat receipts. | Do not treat a chat transcript, raw worker session, temporary downloaded page, or model reasoning as the authoritative Research result. |

### User flow and ResearchRequest

The user can say, for example, “Research current local speech-to-speech
projects suitable for Tori.” Tori detects a substantial research request,
shows the normalized scope and public-source boundary when confirmation is
needed, creates one durable job, runs within its grant, shows phase and source
counts, accepts cancellation, and presents a report with claim and source
details. Later chat and Project Home can retrieve that job by a short label,
recent-work selection, or exact ID. The user decides every next action.

The proposed immutable `ResearchRequest` is a Research-owned record:

| Field | Contract |
| --- | --- |
| `job_id`, `created_at_utc` | Tori-assigned durable identity and UTC creation time. |
| `original_user_request`, `origin_chat_id`, `origin_chat_revision` | Verbatim user text and source turn; distinct from any model/app interpretation. Preserve even if normalization changes. |
| `normalized_question` | Bounded, displayable interpretation; the user may correct it before launch. It cannot silently add topics, sources, or actions. |
| `project_id`, `parent_job_id` | Optional organizational link and immutable continuation predecessor; neither grants access. |
| `scope`, `exclusions`, `source_constraints`, `time_window`, `depth`, `output_form` | Small structured policy: question/topic, excluded topics/domains, public-source/time preferences, `standard` or `deep`, and report shape. V1 need not support arbitrary policy language. |
| `limits`, `authorization_id`, `authorization_revision`, `authority_digest` | Frozen resource/policy snapshot and exact user grant. |
| `engine_id`, `engine_version`, `model_profile_id`, `discovery_profile_id` | Reproducible selected backend identities; operational details never determine job authority. |

Interpretation may suggest a narrower scope; an ambiguous referent requires
clarification. Existing production asks for exact chat-bound confirmation
before every job. A later refinement may avoid another confirmation for a
routine explicit “Research X” using the already disclosed, unchanged default
public-only/local profile, if the original turn itself is retained as the
grant. Confirmation remains required for a model-proposed topic, ambiguous or
broadened scope, new source class, altered resource ceiling, continuation that
changes authority, or any optional external/cloud disclosure. The confirmation
must show scope, exclusions, limits, external retrieval, and data disclosure.
Stale chat or job revisions invalidate it. No confirmation can authorize
installing, configuring, editing, contacting a person, or spending money as a
side effect of Research.

### Lifecycle, owner, and result truth

`SQLiteResearchStore` remains the authoritative lifecycle owner; the adapter
reports observations. The proposed user-facing lifecycle maps onto existing
states instead of introducing a second controller:

| Contract state | Existing representation / refinement |
| --- | --- |
| `AWAITING_AUTHORIZATION`, `QUEUED`, `STARTING` | Existing `awaiting_authorization`, `queued`, `starting`. |
| `RESEARCHING`, `SYNTHESIZING` | Existing `running` plus validated `phase`; expose these as phases, not competing durable states. |
| `CANCEL_REQUESTED`, `CANCELLED` | Existing `cancelling`, `cancelled`; persist request and acknowledgement receipts. |
| `COMPLETED` | Existing `completed`, after artifact and support gates pass. |
| `PARTIAL` | Map existing `completed_with_limits` to a user-visible partial only when a usable bounded result survives; use a new explicit partial reason for other coverage gaps. This requires a reviewed schema/protocol change. |
| `FAILED` | Existing `failed`; `interrupted` remains a distinct truthful crash/restart terminal outcome. |

The durable owner queues exactly one attempt, leases it to the supervised
process, and records attempts/events with monotonically increasing sequence
and optimistic job revision. A phase receipt includes time and attempt ID.
Heartbeats/status have a bounded freshness threshold; stale or missing process
ownership triggers supervised termination and an interruption/failure reason,
never automatic success. On restart, current V1 marks active jobs `interrupted`
and does not resume; retain that safe policy. A future retry or continuation is
a newly authorized job linked to the old one. Cancellation first records intent,
then sends protocol cancel, then terminates the process group after the grace
period and verifies exit/cleanup. A late completion after cancellation is
rejected. Timeout follows the same termination path with a distinct reason;
usable persisted evidence may support `PARTIAL` only after validation.
Temporary sessions and sockets are removed only after ownership is proven and
the process is gone. Terminal report, sources, claims, and evidence survive.

`COMPLETED` means all required artifacts were durably committed, scope coverage
was adequate, and no material unsupported assertion was presented as fact.
`PARTIAL` means a readable, validated, useful result exists but coverage,
retrieval, timeliness, or support was incomplete; the report names each gap.
`FAILED` means no trustworthy usable result exists. A precondition failure
(worker/model/search unavailable before collection) is `FAILED` with a
precondition code, never `PARTIAL`. A model-emitted prose blob alone never
qualifies as completion. `CANCELLED` and `interrupted` are not synonyms for
`PARTIAL`, even if sources collected before termination remain inspectable.

### Engine, models, discovery, and source policy

`ResearchWorkerPort` is the existing process-level seam. Refine its typed
request/result protocol as the replaceable `ResearchEnginePort`: Tori owns
authorization, job ID, policy, egress, result schema, validation, persistence,
status, cancellation, and presentation; the engine only executes the bounded
question and returns candidate sources/evidence/analysis through validated
events. The first adapter remains the hardened GPT-Researcher-style wrapper.
Its version and effective settings must match the grant; an alternate engine
must satisfy the same protocol and acceptance suite. It cannot write Tori's
database or call application mutation APIs.

The runtime profile selects provider-neutral roles: research LLM, optional
synthesis LLM, embedding provider/model (or explicit `none` if the engine
supports it), and discovery backend. Local endpoints are first-class and the
V1 usable path requires no paid cloud API. The accepted adapter is deliberately
local Ollama with configured model names and GitHub/Hugging Face/SearXNG
discovery; those model names are defaults, not part of the domain contract.
As built, `ResearchWorkerStartRequest.wire_document()` pins Ollama and
`ResearchProcessSettings` requires that exact discovery sequence. Provider
neutrality beyond the existing process port therefore needs a versioned wire
change, not just a configuration-file edit.
Optional future cloud roles require a separate explicit disclosure and
credential/network architecture review; they are not an automatic fallback.

A `SearchDiscoveryPort` returns bounded URL candidates with query, provider,
rank, and discovery time. Discovery is not evidence. A separate guarded fetch
obtains the final document; extraction creates bounded locators/excerpts;
claim validation decides support. A search snippet may guide selection but
cannot substantiate a material report claim. Reuse the existing SearXNG
capability only as a discovery adapter, and preserve the proven unauthenticated
GitHub/Hugging Face route. SearXNG tuning is a separate milestone. If SearXNG
is down, successful independent discovery may still proceed; the report says
which coverage was lost.

`ResearchSourcePolicy` is a Tori-owned, versioned snapshot enforced at candidate
admission, every redirect, broker connection, fetched response, and final
source commit:

- Allow only public `http`/`https` on approved ports, with HTTPS preferred;
  reject `file`, `data`, `ftp`, custom schemes, URL credentials, fragments for
  identity, and non-public literal hosts. V1 has no local file, authenticated
  page, cookie, browser profile, or credential source class.
- Reject localhost, loopback, RFC1918/LAN, link-local, metadata, reserved,
  multicast, and mixed DNS answer sets. The broker connects the validated
  numeric address; each redirect is rechecked with a small hop ceiling and
  loop detection. TLS validation stays end-to-end. No ambient proxies.
- Canonicalize URL identity conservatively after redirect; retain discovered
  and final URLs plus redirect provenance, deduplicate by canonical final URL
  and content fingerprint without erasing distinct publisher context.
- Limit request time, response bytes, decompressed bytes and expansion ratio,
  document types, parse depth, total pages, and concurrent fetches. Abort
  unsupported binary, malformed, encrypted, login-gated, or oversized content
  with a safe reason code. Respect robots/site errors where applicable; do not
  evade blocks or retry indefinitely.
- Treat page text, titles, snippets, metadata, and citations as untrusted data.
  Remove executable markup from extraction, keep data delimited in model input,
  and never interpret source text as a tool call, new system instruction,
  source-policy exception, or command. A page asking for secrets or a new URL
  does not authorize either.

The network design keeps the current private Bubblewrap network and Tori-owned
Unix-socket egress broker. An engine with general public egress could bypass
candidate/fetch budgets and complicate provenance; brokered search/fetch gives
Tori a single policy point and attempt-scoped accounting. The broker permits
outbound public HTTP/HTTPS on ports 80/443 only, plus exact local inference and
configured SearXNG relay operations. It exposes no arbitrary LAN route,
inbound listener, shell network tool, cookies, or environment credentials.
Backend compromise is contained by read-only minimal mounts, a disposable
private work directory, allowlisted environment, no canonical runtime mount,
no Coding Work authority, per-job budgets, process-group termination, and
validation before any result is accepted. If containment is unavailable,
readiness fails closed.

### Persisted evidence, claims, and presentation

The implemented schema 3 supplies a bounded first-class answer to “Which
retained excerpt and source did the worker associate with finding #3?” through
the application service. The richer records and direct conversation lookup
below remain proposed. Historical jobs with no claim map are labeled
`legacy_report_only`, not retroactively marked supported.

| Record | Minimum durable fields |
| --- | --- |
| `ResearchSource` | Stable source ID, job ID, discovered/final canonical URL, title, publisher/domain, discovery provider, source class, fetched/rejected status and reason, retrieval time, content type, fingerprint. Existing source rows map forward without inventing missing facts. |
| `ResearchEvidence` | Evidence ID, job/source IDs, bounded excerpt or normalized observation, page/section/anchor locator, retrieval fingerprint, extraction time. Retain enough to inspect support after the page disappears, within excerpt limits. |
| `ResearchClaim` | Claim ID, job ID, stable finding order, atomic claim text, support state, evidence IDs, uncertainty/conflict note. A report sentence with multiple substantive propositions is split or explicitly qualified. |
| `ResearchReport` | Job ID, executive summary, ordered findings/claim IDs, limitations, unresolved questions, source IDs, generated time, schema version, completion/partial rationale. Preserve the original narrative as a readable artifact. |

`SUPPORTED` requires at least one retained excerpt or normalized observation
that directly supports the bounded claim; a primary source is preferred for
technical specifics. `PARTIALLY_SUPPORTED` means the evidence supports only a
qualified subset. `CONFLICTED` records both sides and limits any conclusion.
`UNSUPPORTED` means no retained support; it may appear only as an explicitly
marked open question or rejected candidate, not as an established fact.
Corroboration and source quality are separate metadata, not a fabricated
confidence number. Low-quality sources lower the conclusion; conflicting
credible sources remain visible with dates and scope. If a source disappears,
the stored URL, fingerprint, retrieval time, locator, and bounded excerpt still
explain what was used, while current availability is reported separately.
Fabricated or unobserved URLs fail validation. If evidence is inadequate, the
answer is an explicit limitation or `PARTIAL`/`FAILED` outcome.

The validator, not the model, binds claim IDs to retained evidence and source
IDs. It checks references, excerpt fingerprints/locators where available,
claim support state, source usage, objective fidelity, and result completeness
before atomic terminal commit. The worker can propose classifications, but
Tori owns the acceptance gate. UI links jump from finding to claim to evidence
and exact source; source detail distinguishes retrieved, rejected, and only
discovered candidates. Ordinary chat can render a concise report and a
deterministic “show sources” or “which source supports finding #3?” lookup.
Semantic support may require a separate bounded local-model check; structural
validation alone cannot prove a statement true. Weak or ambiguous evidence is
qualified or omitted rather than given a false certainty label.

Keep job metadata, report, claims, bounded excerpts, source fingerprints,
status and receipts locally. Raw web bodies are transient by default and
removed with their disposable session after terminal validation. Never persist
model hidden reasoning. A user-requested delete must target exact job IDs,
account for continuation links, and use the ordinary data-deletion authority;
there is no automatic historical rewrite or silent pruning in V1. Extend the
existing guarded Research backup/restore to the new durable tables and verify
foreign keys, hashes, and readback; exclude sockets, scratch, and raw cache.

### Projects, conversation, follow-up, and UI

An explicit Project association is captured at creation, or later changed
through a user-authorized Research-owned association operation with revision
checks. `ProjectRelatedSources` projects only ID, question/title, state, brief
result/limitation, and time into Project Home and recent activity. A later
Project chat can resolve that job and request its full report or evidence by
ID; `ProjectContextService` selects at most a small summary and a few relevant
claim/source anchors under its existing token budget and writes an omission
receipt. It never inserts every report into every Project prompt. Cross-Project
selectors require exact authorization and visibility checks; a Project link
does not change web, filesystem, model, or action permissions.

Deterministic application behavior owns ID/revision resolution, recent/active
selectors, status, cancel, source listing, claim-to-evidence lookup, report
readback, Project association, and continuation linkage. Model interpretation
may propose that “research X” is a substantial request, clarify the scope of
“this,” or suggest a normalized question; it cannot resolve an ambiguous job
silently or initiate a new grant. “How is that research going?”, “Cancel that
research”, “What did you find?”, “Show me the sources”, and “Which source
supports finding #3?” should work with a human-readable recent-job selector
and exact ID fallback. If two jobs fit, present a short choice. Ordinary chat
is sufficient; Workspace shows current phase, counts, stop control, recent
results, and needs-attention state, with a result detail and evidence drilldown.
No large research dashboard is required.

“Research this further,” a six-month filter, or an option-B comparison creates
a new request with `parent_job_id` and explicit new scope. Existing report,
evidence, citations, and timestamps remain immutable. A later report may
supersede a conclusion by linking claim IDs and explaining the new evidence;
it does not rewrite the older record. No automatic Knowledge write occurs.
Future explicit promotion can quote selected claims and evidence into a
separate user-authorized Knowledge or Project workflow while retaining Research
provenance. Research completion never launches Coding Work, installs software,
changes settings, promotes capabilities, contacts a person, spends money, or
executes a recommendation.

Night Owl remains Tori-initiated, fixed-category, periodic/on-demand advisory
discovery with its own grant and finding policy. Research Worker remains a
user-directed substantial question with a job/report/evidence lifecycle.
They may share policy-checked discovery/fetch primitives but neither may
inherit the other's authority or present its result as the other's artifact.

### Bounds, degraded behavior, and receipts

Retain the accepted default ceiling of 30 minutes, 20 searches, 100 results
considered, 30 fetched sources, 2 MB per page, 25 MB total, four concurrent
fetches, and 100,000 report characters, with the existing configured hard
ceilings. Add a small redirect ceiling (three), bounded retries (two per
transient source), bounded extracted characters/evidence per source, and a
model input/output token budget set by the selected local profile before the
attempt. These are proposed defaults; implementers must ensure decompressed
bytes, intermediate engine output, event count, and persistent evidence also
count toward ceilings. Exceeding a budget stops new work and yields `PARTIAL`
only if a valid useful artifact exists.

No internet or all discovery unavailable before evidence: precondition
`FAILED`. SearXNG down with usable approved primary sources: proceed and name
the missing broad coverage. Backend or selected local model unavailable at
readiness: no process launch and `FAILED`/unavailable receipt. Embeddings
failure: use a validated engine mode without embeddings if granted and able to
maintain evidence quality; otherwise `FAILED` or `PARTIAL` based on retained
usable evidence. Individual source failures produce safe per-source reasons.
Cancellation mid-fetch closes the request and process, records `CANCELLED`,
and never publishes an unvalidated report. Restart marks active work
`interrupted` and preserves previously committed records.

Persist bounded content-free receipts for proposal, authorization, launch,
search, source fetched/rejected, evidence extraction, synthesis start,
validation result, terminal state, cancellation acknowledgement, and cleanup.
Include attempt ID, timestamp, phase, counts, reason code, and limit use; do
not log query secrets, fetched page bodies, credentials, environment values,
raw prompts, hidden chain-of-thought, or unbounded stderr. Report any omission
or unsupported claim in the user-visible limitations.

### Threat review and fail-closed gates

| Threat | Required boundary |
| --- | --- |
| Web prompt injection, poisoned citations, fabricated URLs | Untrusted content remains data; exact source/claim/evidence IDs, observed fetch receipts, URL and support validation, no source-driven tool calls. |
| SSRF, malicious redirects, DNS rebinding, private/LAN/metadata reach | Public-only broker validates every DNS answer and connects the validated address; each redirect repeats the check; worker has private networking. |
| Oversized downloads, decompression bombs, parser abuse | Wire/decompressed/text/parse and total ceilings, limited MIME types, deadlines, limited concurrency, terminate on budget breach. |
| Credential/environment leakage, filesystem/subprocess escape | Allowlisted environment and mounts, no secrets/browser profile/canonical runtime, no shell capability, read-only engine code and disposable work area; unavailable containment prevents launch. |
| Inherited Coding Work authority or backend compromise | Research-specific grant, process profile and narrow port; backend cannot mutate Tori stores or request commands; Tori validates all events. |
| Source/result tampering, stale authorization, cross-Project leak | Immutable grant digest/revision, attempt-bound sequenced receipts, atomic validated writes, source fingerprints, exact Project/selector checks, guarded backup. |
| Worker survival after cancellation or crash | Durable process owner, process-group escalation and exit verification, parent-death containment, startup interruption reconciliation, cleanup receipt. |

### Incremental implementation sequence and acceptance gates

These are **proposed follow-up slices** from the architecture review. The
bounded claim/evidence subset of slice 1 is now implemented; the other parts
remain proposals.
Because an accepted Research Worker already exists, they extend it rather than
recreating its lifecycle or deploying a second orchestration framework.

1. **Request and normalized artifact domain.** Add original request,
   continuation, scope, claim/evidence/report schemas through an append-only
   migration and fake engine fixtures. Gate: legacy reports read unchanged;
   claim-to-source lookup works after restart and backup/restore; malformed
   references fail closed in isolated temporary stores.
2. **Engine and source-policy refinement.** Version the worker contract, retain
   the hardened GPT-Researcher adapter, make discovery/fetch receipts and
   normalized evidence explicit, and meter the additional bounds. Gate: local
   proof, fake engine, malicious redirect/private IP/oversize/injection tests,
   and exact grant/effective-runtime checks pass.
3. **Conversation, Workspace, and result detail.** Add deterministic selectors,
   result/source/evidence readback, nuanced partial state, and cancellation
   receipts. Gate: complete chat flow including ambiguous selectors, truthful
   partial/failure, no auto-action, and UI cancellation works without a model.
4. **Projects and continuations.** Add explicit association and parent link,
   bounded Project context projection, and source-owned Home detail. Gate: a
   later Project chat retrieves exact evidence; cross-Project context is not
   leaked; old reports stay unchanged after follow-up.
5. **Hardening and acceptance.** Exercise restart, stale workers, timeout,
   backup/restore, source disappearance, backend outage, and physical local
   path. Gate: verifier and runtime-preservation checks pass plus the scenarios
   below. No slice changes the founding documents or silently installs an
   external backend.

Final acceptance scenarios: (A) current local speech-to-speech survey with
verified sources and retrievable findings; (B) conflicting credible sources
reported as conflict; (C) partial fetch failure with explicit coverage gap;
(D) cancellation with no surviving process or false report; (E) restart and
single interruption reconciliation; (F) Project association and later
retrieval; (G) linked six-month or option-B follow-up preserving history;
(H) hostile page instructions ignored; (I) private/LAN URL and redirected
private address rejected; (J) fabricated URL/unsupported claim blocked from
established findings; (K) backend/model unavailable before launch reported as
precondition failure; (L) completed report/claims/evidence survive verified
backup/restore; (M) recommendation never changes Tori without a separate
user-authorized workflow.

V1 non-goals: autonomous installs, code edits, Coding Work creation, automatic
Capability Growth or Knowledge promotion, paid API requirement, account-backed
browsing, arbitrary browser automation, unrestricted LAN/file research,
permanent page mirroring, autonomous recurring jobs, multi-agent swarms,
replacing Night Owl/Knowledge/ordinary Search, or automatic action on a
recommendation.
