# Tori Search Provider Contract

**Project:** Tori

**Document:** Search Provider Contract

**Status:** Accepted and implemented for Phase I; bounded source retrieval and browser-path attribution are human accepted, while provider profiles and migrations remain unauthorized

**Authority:** Subordinate to `docs/00_MISSION.md` through
`docs/06_ARCHITECTURE.md`, `docs/ARCHITECTURE_GOVERNANCE.md`, and
`docs/TARGET_ARCHITECTURE.md`

## 1. Purpose

This document defines the Tori-owned boundary between search policy and
replaceable search implementations.

Search finds current or external information. It does not own research policy,
page retrieval, document ingestion, knowledge authority, or Tori's judgment.
SearXNG is the current adapter behind this capability, not the architecture.
A future conforming local or explicitly configured network provider should be
replaceable through configuration, profile selection, and one adapter without
changing Conversation, consent, attribution, or unrelated capabilities.

This is a capability-specific contract. It does not create a generic plugin
system, capability registry, MCP layer, marketplace, provider discovery service,
database, migration, or frontend workflow.

## 2. Governing principles

- Tori owns user intent, search consent, capability enablement, provider
  selection, query bounds, provenance, attribution, context construction, and
  failure presentation.
- A provider performs one bounded, already-authorized search and returns
  untrusted candidate records.
- Search results are evidence, not instructions, permissions, canonical truth,
  memory, or knowledge registration.
- Configuration and provider selection are explicit user-controlled operations.
- No provider is added, selected, contacted, tested, or enabled automatically.
- No failed provider is silently replaced by another provider.
- External transmission is limited to the selected query and the minimum
  protocol metadata required by the explicitly configured provider.
- Provider output cannot trigger actions, grant permission, rewrite the query,
  modify canonical state, or select another capability.
- Local and self-hosted providers are preferred where they meet the product need.

## 3. Scope and non-goals

This contract covers:

- provider identity and portable capability description;
- profile configuration and active selection semantics;
- offline validation and observed availability;
- bounded search requests and normalized results;
- timeouts, cancellation, response limits, errors, and status;
- security, privacy, provenance, and attribution boundaries; and
- a migration direction from the current single configured SearXNG service.

This provider contract does not define:

- multi-step autonomous research;
- the transport and extraction implementation for opening result pages, which is
  owned by the separate bounded source-retrieval boundary;
- recursive crawling or autonomous research;
- downloading or ingesting documents;
- using search results as durable knowledge or memory;
- provider recommendation, installation, or network discovery;
- credentials or public/cloud provider authorization;
- automatic routing, aggregation across providers, or fallback;
- search-engine-specific categories, engines, ranking controls, or payloads as
  portable Tori concepts; or
- implementation of profiles, persistence, APIs, Settings, or schemas.

## 4. Ownership boundary

### 4.1 Tori-owned responsibilities

Tori owns:

- administrator permission, user enablement, and effective capability state;
- direct-request and conversation-bound approval policy;
- which valid enabled profile is active;
- request admission and normalization;
- query, result-count, response-size, and time limits;
- request identity and cancellation policy;
- provider construction through an explicit allowlist;
- endpoint and network-boundary policy;
- normalization, validation, deduplication, and bounding of provider results;
- source identifiers, provenance, observation time, and safe public documents;
- context supplied to the model and the rule that provider data is untrusted;
- application-owned citation validation and rendered source lists;
- archival semantics for a completed authorized search;
- availability and error presentation; and
- all authority, privacy, audit, and no-fallback policy.

The existing `SearchApplicationPolicy`, conversation-bound `SearchConsent`, user
capability preference, query validation, source-attribution enforcement, and
search-context construction are Tori policy and should remain outside adapters.

### 4.2 Provider-adapter responsibilities

A search adapter owns only:

- translating one provider-neutral request into its native protocol;
- endpoint paths, HTTP methods, request parameters, headers, and native formats;
- provider-specific authentication translation if separately authorized later;
- parsing native responses;
- mapping native transport and protocol failures to the contract error taxonomy;
- releasing transport resources on success, failure, timeout, and cancellation;
  and
- truthfully reporting supported optional features.

The adapter must not decide whether search is permitted, broaden a query, perform
a second search, open result pages, persist results, or expose native response
objects to Conversation or the browser.

### 4.3 Client responsibilities

A frontend may display canonical profiles and status, submit explicit profile or
enablement actions, show search progress, and render Tori-normalized sources. It
does not own consent, provider configuration, active selection, result trust,
attribution, or persistence.

## 5. Provider-neutral interface

A future strengthened search port should remain narrow and presentation-neutral.
Conceptually it provides:

- `identity`: stable adapter type and safe display name;
- `validate_configuration()`: offline shape and adapter validation with no
  provider contact;
- `capabilities()`: portable supported features, not current availability;
- `status()`: bounded observed availability with a reason and observation time;
- `search(request)`: one authorized bounded request returning normalized
  candidates or a typed failure; and
- `cancel(request_id)` or an equivalent closeable request lifecycle where the
  transport supports prompt cancellation.

The interface must not expose HTTP request objects, SearXNG parameter names,
provider-native JSON, native engine lists, endpoint path assumptions, or browser
presentation details.

The current `SearchPort.search(query) -> CapabilityResult` is a useful initial
replacement seam. It can remain while typed identity, status, request, and result
values are introduced only when an implementation phase requires them.

## 6. Request contract

A provider-neutral `SearchRequest` should contain only Tori-approved portable
values:

- an opaque bounded request identifier;
- the normalized query;
- a Tori-owned maximum result count;
- an overall deadline or bounded timeout policy;
- an optional requested language or locale only if its semantics are stable
  across providers; and
- optional freshness intent only when Tori can define it without pretending all
  providers implement the same filtering semantics.

Provider-specific engine names, categories, safesearch numbers, native ranking
knobs, arbitrary headers, and raw query parameters do not belong in the portable
request. An adapter may use fixed validated internal choices, or later receive
bounded adapter-scoped configuration that is never interpreted by core consumers.

Only the selected query is transmitted. Conversation history, memory, Projects,
tasks, identity prompts, hidden reasoning, other search results, and unrelated
user data are excluded.

## 7. Result and provenance contract

A normalized search result set should contain:

- the opaque request identifier;
- the exact normalized query Tori authorized;
- the selected profile identifier and profile revision;
- a completion status;
- an observation timestamp;
- zero or more ordered source candidates; and
- bounded provider-neutral objective metadata.

Each source candidate may contain:

- a Tori-assigned source identifier for the current result set;
- a bounded title;
- a validated absolute source URL;
- a bounded snippet, if supplied;
- an optional provider-reported publication time kept distinct from retrieval
  time; and
- optional objective fields such as native position or score, explicitly labeled
  as provider-reported rather than truth.

Provider-native fields are discarded unless a reviewed portable meaning exists.
Results are untrusted data. They cannot contain executable instructions, UI
controls, permissions, provider-selected follow-up queries, or canonical state
mutations.

Search snippets do not prove page contents. Tori must not claim a page was opened,
read, or verified when only a result record was returned. Page retrieval remains a
separate future capability with its own permission and safety contract.

## 8. Profiles and active selection

A future canonical `SearchProviderProfile` should conceptually contain:

- `identifier`: stable opaque Tori-owned identity;
- `display_name`: human-readable profile name;
- `provider_type`: explicit allowlisted adapter type;
- `endpoint`: normalized service location where applicable;
- `enabled`: whether the profile may be selected or contacted;
- `result_limit`: bounded portable maximum;
- `timeout_seconds`: bounded overall request timeout;
- `network_boundary`: Tori-derived classification such as loopback, trusted LAN,
  or explicitly approved external service;
- `authentication_mode`: allowlisted mode only, with future secrets referenced
  through a separate approved secret boundary;
- `provider_options`: bounded adapter-scoped configuration only where no portable
  field exists;
- `revision`, `created_at`, and `updated_at`; and
- optional cached capability metadata with an observation time.

No profile stores raw credentials, arbitrary headers, cookies, executable code,
or provider-native response data.

Active selection is a separate canonical record with its own revision. Creating,
editing, enabling, disabling, deleting, or selecting a profile requires an
explicit user operation and optimistic concurrency. A stale operation fails and
refreshes from authoritative state; the client does not retry silently.

A disabled, missing, invalid, unsupported, or unavailable selected profile makes
search unavailable honestly. Tori does not choose another profile. Provider
selection does not replace per-request consent where current policy requires it.

This design does not authorize profile persistence or a schema. An implementation
phase must inspect whether existing settings storage can safely represent these
semantics or whether a separately approved store and compatibility path are
necessary.

## 9. Enablement and permission behavior

Search has distinct gates:

1. the administrator permits the search capability;
2. the user enables search;
3. one valid profile is explicitly selected and enabled;
4. the current request is directly authorized or receives the required
   conversation-bound approval; and
5. the provider is contacted only within its configured network boundary.

Failure at any gate means no provider contact. Disabling search clears pending
consent and rejects new requests. It does not delete profiles or archived source
attribution. Re-enabling search does not silently select or probe a provider.

An explicitly configured local or trusted-LAN profile authorizes only bounded
search queries after Tori's request policy admits them. A future external profile
requires clear disclosure that the query leaves the local environment and a
separately reviewed credential/privacy design.

## 10. Availability and capability discovery

Status must distinguish:

- `configured`: offline configuration is valid;
- `enabled`: user permits selection and use;
- `selected`: profile is the active choice;
- `unknown`: no current operational observation exists;
- `available`: a bounded operation or explicit check recently succeeded;
- `unavailable`: a bounded operation or explicit check failed;
- `degraded`: core search works but an optional feature does not; and
- `observed_at`: when operational status was learned.

Construction is not proof of availability. A failure updates only the selected
profile's derived status and never edits canonical configuration. Cancellation is
not provider failure. Later success may restore observed availability.

Capability discovery may report stable portable facts such as maximum supported
result count or support for language/freshness hints. It must be bounded, treated
as untrusted, and initiated only by an explicit check or justified selected-profile
refresh. It never discovers or adds providers on the network.

## 11. Timeout, cancellation, and error boundaries

Tori owns cumulative limits even if an adapter also enforces defensive limits:

- normalized query length;
- maximum result count;
- maximum title, snippet, URL, and metadata lengths;
- maximum response bytes;
- connect and overall request deadlines;
- redirect policy;
- maximum retries, initially zero unless separately justified; and
- prompt transport cleanup on timeout, cancellation, or consumer abandonment.

Adapters map native failures into safe categories such as:

- `invalid_configuration`;
- `authentication_failed`;
- `provider_unreachable`;
- `provider_timeout`;
- `rate_limited`;
- `unsupported_feature`;
- `invalid_response`;
- `response_too_large`; and
- `cancelled`.

Raw bodies, endpoint credentials, query-bearing URLs, stack traces, provider
internals, and transcript content do not cross the public error boundary.

Search failure does not roll back or corrupt Conversation, archives, memory,
knowledge, Projects, tasks, or other capabilities. Tori reports the limitation and
continues without pretending current external information was obtained.

## 12. Security and privacy

- Endpoint validation rejects unsafe schemes, embedded credentials, ambiguous
  hosts, uncontrolled redirects, query/fragment injection, and access outside the
  profile's approved network policy.
- Environment proxies, ambient cookies, browser credentials, and provider-supplied
  redirects are not inherited implicitly.
- Public/external provider support requires HTTPS, explicit selection, data-boundary
  disclosure, secret handling, revocation, and logging review in a separate phase.
- Tori sends no more than the authorized query and required protocol metadata.
- Results are bounded and normalized before reaching model context or clients.
- Provider output cannot authorize page retrieval, document ingestion, file access,
  Search enablement, another provider, or another capability.
- Search findings never become memory or registered knowledge automatically.
- Logs use opaque request/profile identifiers and safe reason codes rather than
  query text or raw responses unless a separately approved diagnostic mode defines
  redaction and user control.

## 13. Current architecture assessment

### 13.1 Existing responsibilities that should remain

- `SearchPort` as the initial execution seam;
- `SearchApplicationPolicy` as presentation-neutral authority policy;
- process-local, conversation-bound, expiring `SearchConsent`;
- administrator permission plus durable user enablement;
- conservative explicit/freshness/external-knowledge proposal behavior;
- Tori-owned query validation and bounded `CapabilityResult`/`SourceRecord` values;
- strict source URL and response validation;
- application-owned context labeling, citation validation, and rendered Sources;
- archive attribution for completed searches; and
- ordinary conversation remaining usable when search is disabled or unavailable.

### 13.2 Responsibilities that should move behind the adapter boundary

- SearXNG request paths, query parameters, content types, and JSON field names;
- native transport construction and SearXNG-specific error interpretation;
- current construction of exactly one SearXNG implementation; and
- any future provider-native category, engine, ranking, authentication, or
  discovery translation.

`SearXNGSearch` should become or remain the compatibility adapter. Neither its
current endpoint nor its JSON protocol defines the provider contract.

### 13.3 Responsibilities that remain unchanged

- current consent language and direct `/search` semantics;
- user Web Search enable/disable behavior;
- source-attribution and archive format;
- no recursive crawling, automatic research, or ingestion;
- bounded current-turn public page retrieval remaining separate from SearchPort
  and the SearXNG adapter;
- current local endpoint restriction until a separate network-security design;
- Conversation and Settings layout; and
- all memory, Project, task, and M23/M24/M25 behavior.

## 14. Migration direction

Any implementation should proceed in bounded reviewed stages:

1. Strengthen provider-neutral identity, request, status, result, and typed-error
   values while preserving current SearXNG behavior.
2. Move all SearXNG transport and native parsing into an explicit adapter and keep
   Tori normalization/attribution outside it.
3. Add an explicit allowlisted factory and shared fake-adapter conformance tests.
4. Design profile persistence and an active-selection compatibility path only after
   inspecting existing storage; do not migrate canonical runtime implicitly.
5. Add Settings profile management only after the complete desktop/mobile workflow
   and revision semantics are approved.
6. Evaluate a second current open-source/self-hostable provider and prove
   substitution without changing Conversation.
7. Consider public search providers, credentials, aggregation, or autonomous
   research only as separate permission and privacy phases. Bounded public source
   retrieval remains its own reviewed current-turn evidence capability.

No stage silently changes the current configured provider, performs an external
connection during initialization, or weakens existing consent.

## 15. Conformance strategy

Future implementation tests should prove:

- fake and real adapters satisfy the same contract;
- SearXNG-specific names do not appear in the provider-neutral port;
- authorization and disabled states cause zero provider contact;
- profile and selection mutations are revision-safe if persistence is approved;
- no silent fallback or cross-provider retry occurs;
- request and response limits are enforced by Tori;
- timeouts, cancellation, redirects, malformed data, duplicates, and oversized
  responses fail safely;
- native availability transitions do not mutate profiles;
- attribution remains application-owned and source-bound;
- provider output cannot trigger retrieval, ingestion, actions, or state changes;
- Search failure leaves Conversation and unrelated domains usable; and
- tests use isolated temporary state and preserve canonical runtime.

## 16. Deferred decisions

- profile persistence and compatibility initialization;
- provider/model or engine discovery;
- a second provider selection;
- external HTTPS providers and credential storage;
- portable language, region, freshness, or safesearch controls;
- generalized crawling, document download, and permanent research storage;
- result aggregation or explicit fallback policy;
- multi-step research; and
- frontend profile management.

## 17. Decision summary

Tori should retain its current search consent, provenance, attribution, and
capability policy while treating SearXNG as the first replaceable adapter. Search
profiles and active selection should be canonical, explicit, revision-safe, and
fail without fallback, but their persistence is not authorized by this document.
Search returns bounded candidates only. A separately authorized source-retrieval
boundary may open a small number of selected public pages for the current request;
neither capability grants permission to crawl, ingest documents, act, or modify
canonical state.

## 18. Phase I source-retrieval implementation status

Phase I adds a separate provider-neutral `SourceRetrievalPort` and Tori-owned
bounded service after Search result selection. The current public HTTP/HTTPS
adapter validates every initial and redirect destination, pins transport to an
already validated public address, rejects non-public and unsupported content,
extracts bounded UTF-8 HTML/text/Markdown, and returns normalized untrusted
evidence. SearchConsent and SearchApplicationPolicy remain authoritative.

An explicit request to read a supplied public HTTP/HTTPS URL grants one-use
current-request retrieval authority and bypasses SearXNG rediscovery. Retrieved
material remains transient supplemental context with application-owned citations;
it is never automatically registered as Knowledge or written to Memory. Search
profiles, recursive crawling, permanent research storage, and ingestion remain
deferred.

After retrieval, Tori preserves the authorized candidate order and assigns the
bounded records stable current-result source IDs `[1]`, `[2]`, and `[3]`. A
redirect may replace a record's visible URL with its validated final URL but does
not change its source ID. Model output may refer only to those IDs. If a local
model redundantly emits a trailing Sources/References appendix or repeats an
exact supplied URL, Tori validates every recognizable ID and URL against the
authoritative map, discards the redundant model metadata, and renders its own
source block. URL literals inside closed Markdown code spans or blocks are
instructional content rather than source metadata and remain outside attribution
parsing. An unknown ID, stale pre-redirect URL, invented prose/source URL,
malformed marker, or unbound answer still fails closed.

Final human acceptance passed through the real streamed browser application path
on a physical iPhone after a fresh Tori start. The accepted request used local
SearXNG, local Ollama `gemma4:12b`, and retrieved Oobabooga repository evidence to
produce installation guidance with canonical visible and archived attribution.
This acceptance does not authorize Search profiles, another provider, crawling,
research persistence, or automatic Knowledge/Memory promotion.
