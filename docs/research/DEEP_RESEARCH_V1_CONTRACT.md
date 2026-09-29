# Tori Deep Research V1 Contract

**Status:** Historical, superseded design of an uncommitted experiment; the separately scoped [Research Worker V1](../RESEARCH_WORKER_V1_ARCHITECTURE.md) is implemented and physically accepted. “Not implemented” in this file refers to **this proposed Deep Research contract**, not to Tori's current Research Worker.
**Authority:** Historical design evidence subordinate to the founding documents and the current Research Worker architecture; not standing implementation authorization
**Evidence:** `docs/research/DEEP_RESEARCH_TECHNOLOGY_AUDIT_2026-08.md` and the completed standalone GPT Researcher POC report dated 2026-08-30

> **Historical deferral decision (2026-08-31):** The experiment then under review was not committed and its trial state was removed. Its no-account discovery paths had failed acceptance. This decision was later superseded by a different, explicitly authorized Research Worker using direct unauthenticated GitHub/Hugging Face primary discovery and bounded SearXNG secondary context. The current external wrapper is separately deployed; see [Current State](../FINAL_STATE.md#deployment-data-and-recovery-boundaries). Subsequent worker state is not the removed experimental runtime described here.

## 1. Purpose

Deep Research V1 lets the user ask Tori for a bounded, multi-step investigation while ordinary Conversation remains available. Tori owns the request, authority, lifecycle, evidence acceptance, durable state, and final presentation. A replaceable external worker performs research mechanics only.

The V1 architecture is:

```text
Conversation
    |
    v
ResearchService
    |
    v
Tori-owned durable ResearchRun / ResearchAttempt state
    |
    v
ResearchPort
    |
    v
isolated GPTResearcherAdapter
    |
    v
one external worker process per attempt
    |
    v
versioned NDJSON
    |
    v
GPT Researcher
```

GPT Researcher is the first worker implementation, not a Tori subsystem identity. Replacing it must not require redesigning Conversation, Projects, Knowledge, Memory, authority, lifecycle, or presentation.

This document authorizes design only. It creates no runtime schema, worker installation, process, dependency, provider profile, search service, endpoint, or UI.

## 2. POC evidence and V1 decision

The standalone POC established the following evidence:

- GPT Researcher package `0.14.7`, upstream release `v3.6.1`, revision `6f998577d547b1e54ec662dac63583aa11e3b84b`, ran behind an isolated Option B process boundary.
- A generic OpenAI-compatible path through LM Studio completed with the already-loaded `gemma-4-12b-it` Q8 model at a configured 32,768-token context. That backend, model, quantization, and context are proof only, not V1 architecture or universal defaults.
- One model served fast, smart, and strategic roles. Transport compatibility still does not imply that every OpenAI-compatible endpoint or locally loaded model is behaviorally capable.
- No Ollama provider, process, model, embedding path, or fallback was used.
- No-key `ddgs` search and public-page retrieval completed real research. SearXNG configuration was inspected but no SearXNG deployment was performed.
- Two corrected live research runs completed with normal model finish state, nonempty useful reports, reviewed evidence, and seven total citations all belonging to reviewed evidence.
- GPT Researcher can swallow synthesis failures and return an empty report. The first POC wrapper falsely treated that return as completion, proving that Tori must own semantic success.
- Explicit context budgeting prevented a repeat of a roughly 37,003-token synthesis prompt against a 32,768-token model context.
- Bounded useful research completed without embeddings.
- Graceful process cancellation during active research stopped in approximately 514 milliseconds, emitted one cancelled terminal, and left no orphan worker.
- Progress is usable but coarse: start, planning, synthesis, final reviewed-source totals, and terminal state are reliable; live query text, page reads, and precise branch percentages are not.
- The external environment was approximately 1.2 GB and 193 distributions. Its dependency weight, including unused package-level Ollama dependencies, remains outside Tori's venv.

The result is approval to design and later implement a bounded V1 adapter profile. It is not approval to expose GPT Researcher's UI/API, adopt its persistence, or treat its output as trusted without Tori validation.

## 3. Product rules

Deep Research V1 follows these rules:

- Conversation remains the primary interface and remains usable while research runs in the background.
- A natural explicit request such as “Deep research the best local TTS options for Tori” may authorize one bounded research run.
- One accepted request authorizes bounded generated subqueries within the stated public research scope. Tori does not interrupt for confirmation before every subquery.
- Research never gains authority to modify external systems or Tori canonical domains.
- Every run is bound durably to its originating conversation and originating user turn. Completion is never redirected to whichever conversation is active later.
- A terminal result or terminal notice is delivered to the origin exactly once at the application layer.
- Tori never equates “worker returned” with “research succeeded.”
- No provider, model, retriever, or transport fallback occurs silently.
- Worker output, retrieved pages, and model-generated text are untrusted evidence, not instructions or authority.
- Research artifacts do not automatically become curated Memory, registered Knowledge, Second Brain content, Project context, tasks, or executable policy.
- Failure, cancellation, interruption, weak sources, and incomplete evidence are presented honestly.

## 4. Ownership and replacement boundaries

### 4.1 Tori-owned responsibilities

Tori owns:

- interpretation of the user's research intent and public scope;
- admission, authority, privacy review, and bounded budgets;
- origin conversation, user-turn, and optional Project association;
- provider/model and retrieval-profile selection with no fallback;
- durable `ResearchRun`, `ResearchAttempt`, evidence-ledger, outcome, and delivery state;
- attempt supervision, cancellation, deadlines, restart reconciliation, and retry authority;
- normalization and validation of worker protocol messages;
- semantic success, context-budget, source, and citation acceptance;
- final conversational framing and exactly-once origin delivery;
- user-visible status, errors, warnings, and source-quality disclosure;
- retention and deletion policy for Tori-owned research records; and
- any future user-approved promotion into Knowledge or Second Brain.

### 4.2 `ResearchService`

`ResearchService` is the presentation-neutral application boundary. It accepts Tori domain values, not GPT Researcher, LangChain, LM Studio, SearXNG, subprocess, or browser types.

It must support these semantics:

- admit a bounded request and durably bind its origin before worker launch;
- enqueue work without occupying Conversation's foreground generation boundary;
- expose a durable snapshot and bounded event history for status presentation;
- start at most one live attempt for a run at a time;
- request cancellation and supervise bounded cleanup;
- reconcile interrupted attempts after restart;
- validate and durably accept one terminal run outcome;
- deliver one terminal result or notice to the origin conversation; and
- reject stale, duplicate, malformed, mismatched, or post-terminal worker messages.

No client calls `ResearchPort` directly.

### 4.3 Tori-owned research repository

A dedicated repository stores research lifecycle truth separately from the Conversation archive, Memory, Knowledge registry, Project records, and worker files. The implementation mission must define its exact schema and configured runtime location using normal migration, backup, temporary-test, and canonical-runtime preservation rules.

The repository owns atomic compare-and-set transitions, unique run/attempt identities, one terminal run outcome, one attempt terminal per attempt, and one origin-delivery record. Worker report stores, indexes, logs, caches, and artifact folders are derived and noncanonical.

### 4.4 `ResearchPort`

`ResearchPort` is the replaceable worker contract. Conceptually it provides:

- capability/version inspection without starting research;
- `start_attempt(request, event_sink)`;
- `cancel_attempt(attempt_id)`;
- bounded termination/cleanup status; and
- a normalized terminal result or typed failure.

The exact Python interface may vary, but native worker objects never cross it. A fake adapter and the GPT Researcher adapter must pass the same application contract tests.

### 4.5 `GPTResearcherAdapter` and external worker

The adapter translates portable request fields into the pinned worker's configuration, launches exactly one process group per attempt, validates NDJSON, maintains the adapter-side evidence ledger, and maps worker behavior into Tori values.

The worker owns only bounded research mechanics:

- query decomposition;
- search iteration;
- public-page retrieval;
- evidence collection;
- bounded synthesis input preparation; and
- report generation.

It owns no identity, conversation, authority, durable Tori truth, memory, Knowledge, Project semantics, provider fallback, or final acceptance.

## 5. Portable domain contract

### 5.1 `ResearchRequest`

A normalized request contains only bounded portable values:

- opaque `run_id` and `attempt_id`;
- research question and public scope statement;
- research profile and version;
- model-role profile identifiers and resolved capability requirements;
- retrieval profile identifier and revision;
- depth, breadth, query, source, concurrency, time, and output limits;
- context/evidence budget;
- acceptance thresholds;
- optional approved public seed URLs; and
- run-specific deadline and artifact locator assigned by the adapter.

Conversation text, Tori identity prompts, memory, Project content, Knowledge content, local file paths, browser state, and secret values are not worker request fields.

### 5.2 `ResearchRun`

`ResearchRun` represents one user-authorized investigation. It retains at least:

- stable run ID and creation time;
- origin conversation ID, origin user-turn/entry ID, and origin revision evidence;
- optional Project ID association as organization metadata only;
- user-visible question and approved public research projection;
- immutable request/profile/budget snapshot;
- lifecycle state and current attempt ID;
- attempt identities in ordinal order;
- cancellation state;
- one immutable terminal outcome when established;
- accepted report, evidence-ledger revision, warnings, and reproducibility metadata when completed; and
- origin-delivery state and correlated Conversation entry ID.

Run lifecycle states are:

```text
accepted -> queued -> running
                    |-> awaiting_retry
                    |-> cancellation_requested
                    `-> terminal
```

`terminal` carries exactly one outcome: `completed`, `failed`, or `cancelled`. Terminal outcome is immutable.

### 5.3 `ResearchAttempt`

An attempt represents one worker-process execution. It retains:

- stable attempt ID, run ID, and ordinal;
- exact worker adapter/protocol/upstream revision;
- resolved non-secret provider/model and retrieval configuration;
- request and budget snapshot hashes;
- start/end timestamps and last accepted event sequence;
- process-supervision state and bounded non-secret diagnostic reason;
- context-budget measurements and model completion metadata;
- evidence/artifact acceptance state; and
- one immutable attempt outcome.

Attempt states are `created`, `starting`, `running`, `cancellation_requested`, then exactly one of `completed`, `failed`, `cancelled`, or `interrupted`.

Retry after interruption always creates a new attempt ID and ordinal. It never reuses a worker process, rewrites the previous attempt, or claims checkpoint resume.

### 5.4 Evidence record

Tori's evidence ledger preserves, where available:

- normalized run-scoped source ID;
- requested URL and validated final URL;
- bounded title;
- outbound discovery query and provider-reported rank when available;
- discovery, retrieval, review, and synthesis-retention state;
- retrieval observation time;
- content type, bounded content length, and content hash;
- bounded evidence excerpt or snippet according to retention policy;
- redirect and duplicate relationship where relevant;
- bounded warnings or failure reason; and
- whether the final accepted report cites the source.

Raw full-page content need not become durable Tori truth. Retention must be explicit and minimal.

### 5.5 `ResearchResult`

A normalized successful result contains:

- run and attempt IDs;
- accepted final report;
- evidence ledger and citation-validation result;
- reviewed, retained, failed, and cited source counts;
- actual model role/profile identifiers and worker version;
- actual retrieval profile and bounded outbound-query audit;
- context estimates, observed input/output usage where available, and reserves;
- model completion/finish state;
- elapsed time and warnings; and
- semantic-acceptance version.

It contains no native GPT Researcher, LangChain, model-server, retriever, subprocess, or filesystem objects.

## 6. Admission, authority, and privacy

### 6.1 Explicit research authority

Deep Research performs external network activity and therefore requires an explicit current user request to research. Ordinary questions, mentions of current information, Project association, or an enabled Search capability do not automatically start Deep Research.

The request authorizes only:

- bounded generated public-search subqueries necessary for the stated scope;
- retrieval of bounded public HTTP(S) sources selected under the retrieval policy; and
- local synthesis through the explicitly selected provider/model profile.

It does not authorize another research topic, recurring work, proactive follow-up, local file access, durable promotion, or host execution.

### 6.2 Public research projection

Before dispatch, Tori constructs a minimal public research projection from the explicit request. It excludes information unnecessary to public research. If fulfilling the request would require transmitting private personal, Project, Memory, Knowledge, local-file, credential, or conversation information, Tori must omit it, ask for an explicit bounded public formulation, or refuse the external portion.

The worker never receives ambient Conversation history. A user may deliberately include a fact in the current research request, but access to that text does not authorize adding related private context from elsewhere.

### 6.3 Project association

A run may retain the Project ID associated with its origin conversation for organization, status, and later presentation. Project association alone sends no Project instructions, files, summaries, paths, repository data, or private metadata to the worker or search backend.

Arbitrary Project-context research is deferred until a separate contract defines explicit source selection, staging, redaction, and revocation.

## 7. Provider and retrieval neutrality

### 7.1 Model selection

ResearchService refers to Tori-owned model profiles, role requirements, context capability, and output limits. `GPTResearcherAdapter` translates fast, smart, and strategic roles into its worker configuration. Another adapter may use different roles without changing ResearchService.

V1 requirements are:

- explicit provider profile, profile revision, and model identifier;
- capability validation before launch where practical;
- no silent selection of another model/provider;
- no cloud or hosted fallback when the configured model fails;
- actual provider/model attribution stored with the attempt; and
- credentials resolved by Tori's owner-private boundary and injected only into the attempt environment or an equivalently bounded channel.

LM Studio is the currently tested generic OpenAI-compatible backend. It is not named in `ResearchPort` domain types. Ollama is neither a required nor approved V1 research architecture. A future OpenAI-compatible server, llama.cpp adapter, hosted provider, or Tori model proxy may replace the tested backend after separate configuration/privacy review and contract acceptance.

### 7.2 Retrieval selection

The research request names a Tori-owned retrieval profile. The adapter translates that profile to a worker-native no-key retriever or a future narrow Tori retrieval bridge. Paid Tavily, Exa, Jina, or another hosted search API is not mandatory.

V1 may use the proven no-key `ddgs` path. Because `ddgs` automatic backend selection may contact more than DuckDuckGo, the implementation must either pin an approved backend or disclose and enforce the effective network policy. SearXNG remains a preferred future self-hosted profile but its deployment is outside this contract.

No failed retriever is silently replaced. Partial search/retrieval failures may produce warnings and continue only when the remaining reviewed evidence satisfies all success thresholds.

### 7.3 Relationship to existing Search

`SearchPort` remains one bounded search operation. Deep Research does not stretch it into an autonomous workflow. Research may reuse Search and `SourceRetrievalPort` policy concepts, SSRF protections, normalized provenance, or a future custom retrieval bridge, while `ResearchPort` remains the multi-step lifecycle boundary.

## 8. Context and evidence budget

Every attempt carries an explicit provider-neutral budget:

- `model_context_tokens`;
- `reply_reserve_tokens`;
- `prompt_reserve_tokens`;
- `uncertainty_reserve_tokens`;
- `evidence_budget_tokens`;
- `retained_source_limit`; and
- a named/versioned token-estimation method.

The core invariant is:

```text
evidence budget
    <= model context
       - reply reserve
       - prompt/instruction reserve
       - uncertainty reserve
```

The adapter must then construct or account for the actual synthesis prompt and verify before model submission that its conservative estimated input plus output and uncertainty reserves fit the selected model's declared context. It must reduce evidence deterministically within approved limits or fail `context_budget_exceeded`. It must never knowingly submit an oversized prompt and interpret the resulting empty/truncated response as success.

Exact provider tokenization is preferred when available behind a replaceable estimator. Otherwise the adapter uses a documented conservative estimator and nonzero uncertainty reserve. Estimates and observed usage remain attempt evidence.

The POC's 32K/8K/4K/4K/12K settings prove one combination only. V1 defaults must be reviewed against the selected model profile rather than copied universally.

Bounded V1 research must work without embeddings. Embedding-based compression and very-large-context profiles are deferred. A future separately approved `EmbeddingPort` may provide replaceable compression support without changing ResearchService semantics.

## 9. Versioned process protocol

Each attempt launches an exact allowlisted executable with no model-generated arguments. The worker accepts one bounded request over stdin or another run-specific file descriptor and emits NDJSON on stdout.

Every protocol message contains:

- protocol version;
- run ID and attempt ID;
- monotonically increasing attempt sequence;
- event type;
- timestamp; and
- a bounded event-specific payload.

Stdout is protocol-only. Human-readable worker logs go to a bounded attempt-local diagnostic channel and are never parsed to manufacture product state. Maximum line count, line bytes, total protocol bytes, event rate, and field sizes are implementation constants enforced by the adapter.

Malformed JSON, wrong version, wrong run/attempt identity, duplicate or decreasing sequence, oversized data, an unsupported event, or any event after an accepted attempt terminal causes `protocol_invalid` and process termination.

The attempt protocol has exactly one terminal event: `completed`, `failed`, or `cancelled`. That event is evidence for Tori validation; it does not itself establish the run's terminal outcome.

## 10. Async lifecycle and durable state

### 10.1 Admission and start ordering

ResearchService must durably write the run, origin binding, immutable request snapshot, and first attempt record before spawning the worker. A worker cannot exist without a Tori-owned attempt identity.

The initial application response acknowledges that research started or queued. It does not block the Conversation request until research finishes.

### 10.2 Background concurrency

Research runs use a dedicated bounded background coordinator, not Conversation's foreground model-operation lock. Normal Conversation may continue in the same or another conversation while research runs.

The coordinator enforces explicit global and per-conversation run limits. V1 defaults to conservative concurrency and never launches unlimited attempts or worker branches. Background research must not starve foreground Conversation of configured model or machine resources; admission may queue or refuse truthfully when capacity is unavailable.

### 10.3 Attempt completion ordering

On worker return, ResearchService:

1. stops accepting further attempt events;
2. validates protocol terminal uniqueness and identity;
3. validates context, report, evidence, citations, model completion, and failure state;
4. durably writes accepted artifacts and attempt outcome;
5. atomically establishes the run terminal outcome if allowed; and
6. creates the origin-delivery record.

No completion is visible as successful before durable semantic acceptance.

### 10.4 Retry model

There is no unlimited or automatic full-run retry. A worker interruption may end its attempt as `interrupted` and place the nonterminal run in `awaiting_retry`. An explicit user Retry creates a new attempt with a new ID and ordinal under the same run. The previous attempt remains immutable.

If the user cancels or declines retry, the run receives one cancelled or failed terminal outcome. Retrying a run that already has a terminal outcome creates a new run, not a new attempt on the closed run.

## 11. Origin binding and exactly-once delivery

Every run is durably bound to the exact originating conversation ID and user-turn/entry ID. Labels, active browser selection, current route, recent chat, and Project name are never delivery targets.

Terminal delivery has a separate state:

```text
not_ready -> pending -> delivered
                    |-> failed
                    `-> suppressed
```

Research completion and delivery are distinct facts. A semantically completed run may be `delivery_failed`; it does not become a failed research result or get silently inserted elsewhere.

Application-level exactly-once delivery requires:

- a stable unique delivery ID derived from the run and delivery kind;
- atomic or reconciliation-safe linkage to one Conversation archive entry;
- revision-aware append to the origin without changing active browser chat;
- duplicate delivery attempts returning the existing correlated entry;
- no second report message after acknowledgement; and
- restart reconciliation before any resend.

If the origin conversation was deleted, unavailable, or irreconcilably conflicted, delivery fails closed. Tori retains the run result according to research retention policy and exposes a repair/export decision through research status; it never recreates, retargets, or appends to another conversation automatically.

The final origin entry is Tori's presentation of the accepted result, not the worker speaking as another assistant. Deterministic framing may identify scope, source count, warnings, and report. Any later model-authored rewriting that changes claims or citations requires the same evidence validation again.

A nonintrusive global completion indicator may link to the origin, but the report itself is delivered only there.

## 12. Truthful progress contract

V1 exposes only stages supported by structured evidence:

- `research_started`;
- `planning`;
- `retrieving` or `reviewing_sources` as a coarse phase;
- `synthesis_started`;
- final reviewed-source count; and
- `completed`, `failed`, or `cancelled`.

Progress events are hints for presentation; durable state remains authoritative. Repeated upstream planning signals are coalesced. Tori may show elapsed time and verified final counts, but not fabricated percentages.

V1 does not promise exact live query text, live per-page read events, live source counts, conflict-comparison stages, detailed recursive branches, or precise percentages. Those may be added only after an implementation proves stable structured events without prose-log parsing.

## 13. Evidence and citation rules

### 13.1 Source states

- `discovered`: a normalized candidate URL was returned; it was not necessarily opened.
- `retrieved`: page retrieval completed and bounded content was obtained.
- `reviewed`: retrieval had no recorded failure and produced at least the versioned V1 minimum usable content; the initial contract threshold is 100 non-whitespace characters.
- `retained_for_synthesis`: bounded content from the reviewed source was included in synthesis input.
- `cited`: the accepted report contains a citation bound to that source record.

Discovery, snippets, failed retrieval, duplicate URLs, report-only URLs, and content below the review threshold do not count as reviewed.

### 13.2 Citation acceptance

Every Web research acceptance profile has a positive `minimum_citations`; zero is invalid. Completion requires:

- the configured minimum unique accepted citations;
- canonical URL/source-ID membership for every accepted citation in the reviewed evidence set;
- no invented, stale-run, malformed, or report-only citation;
- a nonempty accepted report and successful synthesis; and
- deterministic source-list rendering from Tori's ledger.

The profile may require more citations for broader work. Minimum count is an acceptance floor, not a quality score.

Citation membership proves provenance only. It does not prove that the source is correct, authoritative, current, unbiased, or that it entails the report's claim. Tori should prefer primary and official sources where practical, preserve source-quality warnings, and disclose material dependence on secondary or weak sources.

## 14. Semantic success contract

Only ResearchService may establish a completed run. All applicable conditions must be true:

1. The worker attempt emitted exactly one matching completed terminal event.
2. No provider, model, synthesis, protocol, security, or context-budget failure was captured.
3. Synthesis actually ran and returned an accepted normalized completion state equivalent to a normal stop.
4. The final report is nonblank and meets the configured minimum content threshold.
5. At least one source is reviewed for Web research.
6. The positive minimum citation count is met.
7. Every accepted citation belongs to reviewed evidence.
8. The final prompt respected the configured model/evidence budget.
9. The actual provider/model/retrieval profile matches the admitted configuration with no fallback.
10. Tori durably accepts exactly one terminal run outcome.

`length`, truncation, content-filter refusal, unknown/missing finish state, empty output, swallowed upstream exception, invalid citations, or an unverifiable provider/retriever substitution cannot complete a run.

Partial evidence may be retained as explicitly incomplete diagnostic/retry material. It is never labeled a completed report or delivered as one.

## 15. Cancellation and race behavior

Cancellation is a durable Tori operation:

1. atomically record `cancellation_requested` if no run terminal exists;
2. stop new worker event acceptance except cancellation/cleanup evidence;
3. request graceful adapter/worker cancellation;
4. wait one bounded grace interval;
5. terminate the entire process group with a bounded hard kill if needed;
6. verify no child or orphan remains; and
7. durably record the attempt and run cancellation outcome.

If semantic completion was durably accepted before the cancellation transition, completion wins and cancel reports `already completed`. If cancellation was durably accepted first, a later worker completion is ignored as noncanonical and the process is cleaned up.

Cancellation does not delete accepted prior attempts, canonical run metadata, or unrelated Conversation content. Only proven run-specific transient worker artifacts may be removed under a separately defined retention policy.

## 16. Failure contract

Failures map into stable Tori categories such as:

- `invalid_request` or `not_authorized`;
- `provider_unavailable`, `provider_authentication_failed`, or `model_incompatible`;
- `search_unavailable`, `search_rate_limited`, or `insufficient_evidence`;
- `retrieval_failed` or `unsafe_source`;
- `context_budget_exceeded` or `resource_limit`;
- `worker_timeout`, `worker_crashed`, or `worker_interrupted`;
- `protocol_invalid`;
- `synthesis_failed` or `completion_truncated`;
- `citation_validation_failed`;
- `security_policy_violation`;
- `cancelled`; and
- `result_delivery_failed`.

Raw provider bodies, page content, prompts, credentials, environment values, stack traces, and arbitrary upstream prose do not cross the user-visible error boundary.

Search/retrieval failures may be recorded per source. A run may continue only if remaining evidence passes all acceptance rules. Provider/model failure, protocol failure, context overflow, synthesis failure, citation failure, worker crash without an approved retry, or security violation cannot be downgraded into completion.

Any adapter-internal transport retry must be fixed, small, idempotent, confined to the same admitted provider/retriever profile, and recorded in attempt evidence. It cannot restart the whole attempt, change provider/model/retriever, or continue past the attempt deadline.

Failures do not corrupt or block normal Conversation, Projects, Memory, Knowledge, Search, or other runs. No failure triggers a silent provider, model, retriever, service, or cloud fallback.

## 17. Restart and durability

On Tori startup, ResearchService reconciles durable state before launching or delivering research:

- `accepted` or `queued` runs may return to the bounded queue.
- An attempt recorded `starting` or `running` without a positively owned live process is marked `interrupted`; its run enters `awaiting_retry` or a terminal failure according to policy.
- Tori never adopts an unknown worker or claims transparent worker checkpoint resume.
- A worker process must be configured not to survive its owning supervisor unexpectedly; startup also detects and safely handles any positively identified orphan according to the implementation's reviewed process boundary.
- A durably accepted completed result with pending delivery is reconciled against the Conversation archive and delivered once.
- An acknowledged delivery is never repeated.
- An ambiguous archive append is reconciled by stable delivery ID before retry.
- Cancellation requested before shutdown remains cancellation after restart; it does not resume work.

The worker is transient. Tori's run/attempt repository is durable truth. Retry may repeat search and model work and is always represented as a new attempt.

## 18. Worker security boundary

The approved worker capability is:

```text
search -> retrieve -> synthesize
```

The V1 worker must not expose or activate:

- shell execution;
- Python/code execution tools;
- MCP;
- browser automation;
- arbitrary filesystem reads or paths supplied by the model;
- image generation;
- local file/document ingestion;
- file upload/delete/report-export APIs;
- runtime dependency installation;
- worker UI, assistant chat, memory, vector store, or report store; or
- telemetry/tracing and undeclared network fallback.

The process supervisor must enforce or fail closed on:

- an exact pinned executable/worker revision and protocol version;
- a dedicated external venv outside Tori's venv;
- exact argument construction without shell interpolation;
- one process group per attempt;
- a run-specific working/artifact directory outside Tori's repository and canonical runtime;
- a minimal environment allowlist with an isolated home/cache/temp boundary;
- credentials for only the explicitly selected provider/retriever, never protocol fields or logs;
- no inherited ambient provider credentials, proxies, cookies, browser sessions, or unrelated secrets;
- bounded wall time, process count, concurrency, memory/CPU where the host boundary supports it, protocol bytes, fetched bytes, sources, queries, redirects, and report size;
- approved network destinations: the selected model endpoint, selected search endpoint/service class, and validated public HTTP(S) source pages;
- public-destination and redirect revalidation that blocks loopback, link-local, private, metadata, and otherwise disallowed retrieval targets; and
- graceful cancellation followed by process-group hard termination and orphan verification.

Retrieved content cannot change these rules. If native filesystem or network isolation required by the implementation is unavailable, the worker fails closed; it does not run unrestricted merely because the wrapper has a denylist.

The worker's approximately 1.2 GB dependency environment remains external and separately pinned. No GPT Researcher dependency enters Tori's venv or production dependency declarations.

## 19. Conversation and UX contract

### 19.1 Invocation

Natural explicit requests are the primary entry point. Tori may clarify ambiguous scope, budget, recency, or privacy before admission. If slash commands are introduced, every supported command and argument must appear in Tori's Commands view and use the same ResearchService path.

### 19.2 Minimal presentation

The origin conversation shows a compact research item with:

- question/scope summary;
- queued or current coarse stage;
- elapsed time;
- final reviewed-source count when known;
- Cancel while cancellation remains possible;
- Retry only for an eligible interrupted attempt;
- terminal status and bounded failure/warnings; and
- the accepted report and source list after exactly-once delivery.

The item must work in the existing desktop Conversation and mobile presentation without turning Conversation into a research dashboard. A global lightweight activity/completion indicator may link to the origin, but it carries no duplicate report and does not change active chat.

### 19.3 Continued conversation

Starting research does not freeze the originating chat or another chat. Later turns do not mutate the admitted research request. A user may ask for a separate run, inspect status, or cancel by stable run association. Ordinary conversation responses must not impersonate intermediate worker reasoning.

## 20. Project, Memory, and Knowledge behavior

- A run may retain origin Project association without receiving Project content.
- Project rename, navigation, or active selection does not retarget a run.
- Project deletion or origin-conversation deletion is reconciled explicitly and never redirects delivery.
- Research artifacts and reports are not curated Memory.
- Research artifacts and reports are not registered Knowledge or Second Brain content.
- Worker memory, indexes, caches, report stores, and vector data are never canonical Tori state.
- The normal Conversation archive may retain the user's request, status/result presentation, report, citations, and source provenance according to its own semantics.
- Future promotion of a report, finding, or source requires a separate Tori-owned, user-approved workflow with provenance review. It is not part of V1.

## 21. Configuration and availability

Deep Research is unavailable until a later implementation supplies and validates:

- enabled Tori capability state;
- one selected pinned worker adapter/profile;
- external worker environment and executable revision;
- one explicit provider/model profile with adequate context/output capability;
- one explicit retrieval profile;
- context, research, source, resource, and acceptance budgets;
- artifact and durable-repository configuration; and
- effective security/process/network controls.

Configured, enabled, available, busy/queued, degraded, and failed are distinct states. Construction is not availability. A profile check does not start research. A later provider/retriever success may restore observed availability but never edits selected configuration automatically.

## 22. Human acceptance plan

Implementation is not accepted until a human verifies, using non-sensitive public topics:

1. Starting research returns promptly and Conversation remains usable in the same and another chat.
2. The run remains bound to its origin while the user switches chats; the accepted result appears there exactly once.
3. The configured provider/model is recorded accurately and an unavailable model fails without fallback.
4. Bounded Web research performs real generated subqueries, retrieves public pages, and produces a useful multi-source report.
5. A request associated with a private Project sends no Project content, Memory, Knowledge, history, local path, or local file unless a future separately approved flow exists.
6. Progress uses only the contracted coarse stages and never invents query/page/percentage detail.
7. Cancellation during active retrieval and, where the phase can be held observably, synthesis stops promptly, uses hard process-group termination when required, and leaves no orphan.
8. Empty, truncated, swallowed-error, citation-free, invented-citation, and oversized-context results all fail rather than complete.
9. Every accepted citation binds to reviewed evidence and source-quality warnings remain visible.
10. Context reduction fits the selected model's declared context while preserving a useful report; impossible budgets fail before synthesis submission.
11. Provider failure, search failure, timeout, malformed NDJSON, worker crash, restart, and delivery conflict produce truthful bounded states with no duplicate work or report.
12. An interrupted attempt is never resumed as if checkpointed; explicit Retry creates a new attempt.
13. Completed research does not mutate curated Memory, Knowledge, Second Brain, Project content, tasks, or configuration.
14. The worker cannot activate shell/Python execution, MCP, browser automation, arbitrary filesystem access, image generation, or runtime installation.
15. Worker files and dependencies remain outside Tori's repository, venv, and canonical runtime, and tests preserve canonical runtime byte-for-byte.

Human acceptance must also inspect actual outbound-query records and observed network destinations without exposing credentials or private prompt content.

## 23. Automated conformance requirements

The later implementation test suite must prove at least:

- fake and GPT Researcher adapters satisfy the same `ResearchPort` contract;
- no third-party type crosses Tori domain/service boundaries;
- admission is durable before spawn and disabled/unauthorized requests cause zero worker/network contact;
- origin IDs, not active-chat state or labels, control delivery;
- run and attempt state transitions reject illegal, duplicate, stale, and post-terminal writes;
- one live attempt per run and bounded global concurrency;
- one attempt terminal and one immutable run terminal;
- one origin delivery across duplicate events, archive conflicts, and restart;
- explicit Retry creates a new attempt and no whole-run automatic retry loops exist;
- context budgeting reduces safely or fails before oversized submission;
- normal stop, output truncation, empty report, swallowed synthesis error, and missing finish metadata are distinguished;
- positive minimum citations and evidence membership are enforced;
- discovered, retrieved, reviewed, retained, failed, and cited source states remain distinct;
- weak/partial retrieval cannot complete below evidence thresholds;
- cancellation races are deterministic and process-group cleanup leaves no orphan;
- malformed/oversized/out-of-order NDJSON fails closed;
- environment/credential allowlists and logs/artifacts exclude secrets;
- private Conversation, Project, Memory, Knowledge, and local-file data never enter worker/search requests;
- worker inability or failure leaves normal Conversation and unrelated domains operational; and
- tests use temporary repositories/artifact roots and preserve all canonical runtime entries and founding documents.

## 24. Explicit V1 exclusions

Deep Research V1 excludes:

- embeddings and very-large-context research profiles;
- unlimited or unproven recursive/deep research;
- arbitrary local files, folders, document uploads, and ambient Project files;
- proactive or Scheduled research;
- research swarms or multiple collaborating assistant identities;
- shell, Python, or other code execution;
- browser automation;
- MCP;
- image, audio, or video research;
- automatic Memory, Knowledge, or Second Brain promotion;
- GPT Researcher's bundled UI, API, report chat, persistence, memory, or report store;
- mandatory paid search services;
- SearXNG deployment or management;
- worker checkpoint resume;
- multiple live worker processes for one attempt;
- model/retriever fallback;
- a long-running Option A worker service;
- changing Search, Knowledge, Projects, Scheduled Work, Remote Chat, or Conversation architecture; and
- implementation, dependency installation, schema creation, runtime mutation, or worker deployment in this contract mission.

## 25. Later implementation sequence and stop conditions

A separately authorized implementation should proceed in this order:

1. Add Tori-owned domain values, transition rules, `ResearchPort`, fake adapter, and adversarial contract tests.
2. Add a temporary `ResearchRun`/`ResearchAttempt` repository implementation and prove restart/delivery reconciliation before canonical persistence.
3. Add the bounded background coordinator and Conversation-origin presentation using only the fake adapter.
4. Implement semantic success, context budgeting, evidence ledger, and citation validation independently of GPT Researcher.
5. Package the pinned external worker and `GPTResearcherAdapter` outside Tori's venv/runtime.
6. Add process, environment, filesystem, credential, timeout/resource, protocol, and egress enforcement.
7. Perform real provider/retrieval/cancellation/failure acceptance with public data.
8. Add canonical persistence only through a separately reviewed schema/migration/runtime mission.
9. Run the full repository and human acceptance gates with canonical-runtime preservation.

Stop for architecture/security review if implementation would require:

- importing GPT Researcher or its dependencies into Tori core/venv;
- allowing the worker to read Tori runtime, repository, Knowledge, Memory, Project files, or unrelated host data;
- exposing GPT Researcher's API/UI or another assistant identity;
- weakening provider, Search, source-retrieval, credential, archive, or capability authority;
- parsing human-readable logs as canonical progress or success;
- accepting an unverifiable finish state, citation, source, or context budget;
- adding automatic retry, fallback, proactive work, local documents, embeddings, MCP, browser automation, or execution;
- creating a long-running service without new evidence and review; or
- mutating canonical runtime before its exact path/schema/migration is separately authorized.

## 26. V1 completion definition

Deep Research V1 is complete only after implementation and human acceptance prove all of the following:

- explicit bounded research authority and private-context minimization;
- normal Conversation remains usable during background research;
- durable run/attempt truth and restart reconciliation;
- exactly-once delivery to the originating conversation;
- provider/model and retrieval selection with no fallback;
- semantic success owned by Tori;
- conservative context budgeting before synthesis;
- reviewed-evidence and positive citation acceptance;
- truthful coarse progress, cancellation, and failures;
- no orphan worker, host execution, runtime installer, or unauthorized filesystem/network access;
- no automatic Memory, Knowledge, Second Brain, Project, or task mutation;
- external worker dependencies remain outside Tori; and
- replacement of GPT Researcher remains possible through one conforming adapter.

Current status remains **designed and contracted; not implemented**.
