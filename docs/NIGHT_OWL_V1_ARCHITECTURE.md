# Night Owl V1 Architecture

**Status:** Complete and human accepted.
**Authority:** Subordinate to the seven accepted founding documents,
`docs/ARCHITECTURE_GOVERNANCE.md`, and existing capability-specific authority
contracts. This document does not amend those authorities.
**Implementation status:** Slices 1–5 are implemented: offline domain and
persistence, durable grant, source policy, run/finding/version state,
deduplication, budgets, backup guarding, and an internal explicit on-demand
runner using fixed queries, discovery-only SearXNG, exact-host skills.sh
catalog discovery, bounded public GitHub metadata/release corroboration, and a
recurring-only Scheduled Work capability with explicit nightly/weekly backend
scheduling, immutable authorization snapshots, no-catch-up missed-run policy,
overlap suppression, and interruption recovery. Slice 4 adds optional bounded
model-assisted enrichment, explicit typed Capability Growth promotion, and a
metadata-only default-Off Companion Initiative availability signal. Promotion
remains an explicit advisory service operation and Companion Initiative remains
the sole owner of proactive delivery. Slice 5 adds the local Settings controls,
attributed review/actions, explicit on-demand trigger, schedule controls,
stored-findings Conversation read, Companion type control, and the explicitly
migrated schema-2 production Capability Growth path. No UI accepts an arbitrary
research query, URL, prompt, installation, execution, or configuration action.
The first real all-category Slice 5 acceptance run completed truthfully as
partial after spending all eight GitHub fetches and produced one technically
related but weak image-generation finding. The user dismissed it. Acceptance
corrections preserve that evidence, allocate corroboration across categories
only after all bounded discovery completes, require a concrete Tori
subsystem/protocol/capability fit beyond category plus local/self-hosted
status, and add bounded reason counters. The research-depth update raises the
explicit, revisioned profile rather than weakening relevance: three fixed
discovery angles per enabled category, fair two-project-average GitHub
corroboration, and durable sanitized last-run/per-category diagnostics.
Subsequent accepted all-category runs demonstrated fair 3-search/12-result
coverage, real GitHub repository inspection, real skills.sh catalog requests,
strict relevance rejection, retained findings, human-readable summaries, and
truthful completed and partial outcomes. SearXNG/Bing discovery still often
returns GitHub-hosted root/profile/navigation pages that cannot become a
canonical repository lead for several categories. V1 retains bounded funnel
diagnostics for that limitation; SearXNG/search-quality tuning is deferred to
a separate future effort and is not a V1 completion blocker.
Within SearXNG's fixed bounded result window, approved GitHub lead shapes are
prioritized before non-GitHub discovery hints, then all selected lead URLs still
pass the normal canonicalization and source-policy fence.
Discovery may reduce only a public repository root or approved release/tag,
commit, tree, or blob lead to its repository identity for separate GitHub API
corroboration; profiles, issues, pull requests, discussions, gists, download
assets, redirects, and non-GitHub URLs remain rejected.
Approved source transports classify DNS resolution, connection, TLS, HTTP,
response, and source-policy failures separately while retaining only bounded
reason codes in durable run state. They deliberately disable ambient proxies.
The isolated engineering namespace's DNS observations are not treated as
production-host behavior; physical production acceptance established healthy
approved-host GitHub and skills.sh HTTPS connectivity without broadening egress
or alternate-DNS authority.

## 1. Decision and purpose

Night Owl V1 is a default-Off, application-owned background research
capability:

> Night Owl V1 lets Tori perform explicitly authorized, bounded background
> research on selected topics while Tori is running, retain useful findings,
> avoid repeatedly surfacing the same discoveries, and later offer those
> findings to the user without installing, enabling, or changing anything
> automatically.

Its fixed authority flow is:

```text
USER ENABLES CATEGORIES
    -> BOUNDED PUBLIC RESEARCH
    -> NORMALIZED UNTRUSTED EVIDENCE
    -> DETERMINISTIC RELEVANCE AND CHANGE CHECKS
    -> OPTIONAL BOUNDED MODEL ANALYSIS
    -> FINDING
    -> OPTIONAL CAPABILITY GROWTH RECOMMENDATION
    -> USER DECIDES
```

The governing principle is:

> **Night Owl may research and recommend. It may not install, enable, execute,
> configure, or expand its own authority.**

Night Owl is Tori keeping a deliberately small watch on useful developments.
It is not a general browser, autonomous agent, updater, or self-modification
system.

## 2. Founding-principle alignment

Night Owl advances purposeful growth and current knowledge while retaining the
founding requirements of truth, user control, privacy, local-first operation,
and conversation before automation:

- **Truth before convenience:** a failed, partial, duplicate, or unverified run
  is represented as such; a search result is not presented as a verified
  project fact.
- **The user remains in control:** background research begins only after an
  explicit, visible, revocable category grant. Every consequential follow-up
  remains a separate existing user-authority workflow.
- **Curiosity without intrusion:** research uses selected technical categories
  and Tori-owned capability metadata, not private conversation or personal
  content.
- **Grow with purpose:** novelty alone is insufficient. A retained finding must
  have a concrete, evidenced reason it could improve Tori or the user's
  local-AI environment.
- **Capabilities have no authority:** SearXNG, GitHub, skills.sh, retrieved
  pages, repositories, Skills, and models provide evidence only.
- **Honest failure and graceful degradation:** source and provider failures do
  not become fabricated completion or ungrounded recommendations.
- **Local-first and replaceable:** Tori owns policy, authorization, persistence,
  relevance, and truth. Search, source, and model implementations remain behind
  narrow ports.

## 3. Goals and non-goals

### 3.1 V1 goals

V1 must:

- default to Off and perform no Night Owl network activity until enabled;
- support on-demand, nightly, and weekly runs while Tori is running;
- bind research to a fixed set of user-selected categories;
- use only bounded public, unauthenticated sources;
- retain compact source-attributed findings and truthful run history;
- suppress unchanged discoveries while allowing meaningful updates to reappear;
- feed qualified advisory work into Capability Growth without contaminating
  operational evidence;
- make findings manually reviewable even when Companion Initiative is Off; and
- apply hard time, source, query, model, storage, and concurrency budgets.

### 3.2 V1 non-goals

Night Owl V1 does not:

- accept arbitrary autonomous topics, arbitrary URLs, or model-created searches;
- use accounts, logins, private APIs, cloud credentials, authenticated browsing,
  private repositories, or ambient proxy/credential state;
- clone a repository for execution or run repository, package, Skill, README,
  issue, release-note, or webpage instructions;
- install packages, download executable artifacts, enable or create Skills, add
  MCP servers, change permissions, edit Tori, start Coding Work, invoke `/run`,
  modify configuration, update models, restart services, or alter founding
  documents;
- read private transcript bodies, curated Memory, Knowledge documents, Finance,
  Discord history, personal files, Project objectives/briefs, credentials, or
  secrets to choose research;
- wake a stopped application or sleeping host;
- become Deep Research, continuous monitoring, a crawler, an RSS platform, a
  generic job system, or an agent framework; or
- contact the user directly. Companion Initiative separately owns whether and
  when Tori may proactively speak.

## 4. Existing implementation and reuse decisions

The architecture is based on the current repository rather than a parallel
platform.

| Existing boundary | Night Owl decision |
| --- | --- |
| `SearXNGSearch` / `SearchPort` | Reuse structured bounded search transport and normalization behind a new Night Owl-specific authorization gateway. Do not reuse interactive consent as background authority. |
| `SearchApplicationPolicy` / `SearchConsent` | Preserve unchanged for interactive Conversation. Night Owl never creates, resolves, or impersonates a conversation consent proposal. |
| `SourceRetrievalService` / `PublicSourceRetriever` | Reuse response-size, text, redirect, DNS/IP, no-credential, and SSRF controls. V1 applies a stricter source host/path policy and does not retrieve arbitrary SearXNG result pages. |
| `SkillsShDiscoveryService` | Reuse its exact-host bounded normalization through a research-only admission seam. skills.sh remains untrusted discovery evidence, never a trust root. |
| GitHub Skill acquisition/inspection | Reuse immutable commit resolution, selected-subtree quarantine, limits, no ambient credentials/proxies, static inspection, and cleanup. Do not call install/enable proposal methods or forge a local administration origin. |
| `CapabilityInventory` | Reuse its compact application-owned native/Skill/MCP projection as allowed relevance context. Model claims remain excluded. |
| Improvement Journal / Capability Growth | Preserve operational evidence and recommendation lifecycle ownership. Add a validated research-provenance ingestion boundary rather than writing journal tables directly. |
| Scheduled Work | Own scheduled timing, durable Persistent authorization, occurrence identity, missed-run policy, run execution truth, and interruption history. |
| Companion Initiative | Own proactive conversational eligibility, quiet hours, cooldowns, caps, snooze, and delivery. Night Owl exposes only a metadata-only finding anchor. |
| `OperationCoordinator` and application lifecycle | Reuse conservative foreground/readiness checks and orderly startup/shutdown composition. Do not hold the current quiet lock during long network or model work. |
| SQLite/runtime conventions | Reuse owner-private directories/files, no-follow opens, exact schemas, bounded rows, revisions, read-after-write verification, no silent repair, and backup consistency guards. |
| Operator observability | Emit bounded event names, states, counts, durations, and safe error codes only. Never log queries, source text, URLs, summaries, private context, or credentials. |
| Projects | Do not use V1 Project content or state to form research topics. Projects grant no Search or research authority. |

The existing reusable `SkillsReviewService` is not itself the background entry
point. It currently requires a local `RequestOrigin` with
`skills.administer`, which is deliberately broader than Night Owl research.
Implementation should extract or add narrow read-only discovery/inspection
ports so the manual review and Night Owl can share normalization and inspection
without sharing administration authority.

## 5. V1 research categories

V1 uses a code-owned, versioned category registry. The user may enable any
combination of these six broad interests:

1. `local_models` — local LLM runtimes, inference tooling, model-serving
   protocols, and important local-model releases;
2. `voice` — local TTS, STT, voice runtime, and speech-interface tooling;
3. `image_generation` — local/self-hosted image generation and editing tooling;
4. `coding_agents` — coding assistants, OpenCode-relevant tooling, and bounded
   agent-development infrastructure;
5. `mcp_infrastructure` — MCP protocol, servers, security, transport, and local
   integration developments; and
6. `skills_tori_tools` — useful Skills and public GitHub projects that could
   improve Tori's existing capabilities or user experience.

Each registry entry fixes:

- its stable identifier and user-facing label;
- a small set of application-authored query templates;
- permitted SearXNG categories;
- permitted source adapters;
- accepted capability-inventory and Capability Growth mappings;
- positive and negative relevance signals; and
- a policy version included in every run authorization.

Neither a model nor retrieved content may create a category, query template,
host, follow-up topic, or adjacent research objective. Changing this registry
is reviewed Tori code and a source-policy revision, not learned behavior.

## 6. Authority model

Night Owl has four cumulative ceilings. Failure of any ceiling denies the
operation:

1. **Administrator capability ceiling:** the configured SearXNG adapter and
   relevant public-source adapters must be available. Normal Web Search settings
   continue to control whether SearXNG may be used.
2. **Night Owl durable grant:** the user explicitly turns Night Owl On, selects
   categories, and accepts the disclosed bounded-public-research contract. The
   grant records exact categories, source-policy version, budgets, revision,
   status, and a digest.
3. **Trigger authority:** **Run now** is one explicit local trigger. A nightly or
   weekly trigger additionally requires a matching active Scheduled Work
   definition and immutable Scheduled authorization.
4. **Per-operation admission:** immediately before every query, source fetch,
   inspection, model call, and finding write, the Night Owl gateway rechecks the
   active grant revision, category, source policy, remaining budget, pause state,
   cancellation generation, and run lease.

The durable grant authorizes only read-only public research during Night Owl
runs. It grants no interactive Search authority, no arbitrary URL retrieval,
no Conversation operation, no Skill administration, no execution, and no
follow-up action.

Turning Night Owl Off revokes the current grant generation first, then pauses
or cancels its Scheduled Work definition. A running task observes the revoked
generation before its next external or durable step and terminates truthfully.
Re-enabling creates a new authorization revision; it does not revive a stale
grant. Pausing blocks both automatic and on-demand research without erasing
history. Disabling or pausing never deletes findings or run records.

### 6.1 Cross-store fail-closed rule

Night Owl authorization and findings belong in the Night Owl store; timing and
occurrence authorization belong in Scheduled Work. Because those are separate
SQLite owners, settings changes use an explicit staged workflow:

1. revoke or stage the Night Owl grant so it cannot yet execute;
2. create, replace, pause, or cancel the exact Scheduled Work definition;
3. activate the Night Owl revision only after the Scheduled Work identifiers,
   revision, arguments digest, and authorization match; and
4. verify both stores by fresh read.

On enable/update, an interrupted workflow remains non-executable and is shown
as needing repair. On disable, revocation happens first, so an interrupted
workflow cannot retain excess authority. Startup reconciliation may finish a
known staged transition or report it; it may not guess, broaden, or silently
repair authority.

## 7. Search authorization contract

The explicit user-facing contract is:

> By enabling Night Owl for the selected categories, the user authorizes Tori
> to perform bounded public web research for those categories during Night Owl
> runs, within the displayed source policy and run limits. This permission is
> revocable and does not authorize ordinary Conversation searches or any
> action on a finding.

Implement a `NightOwlSearchGateway` above `SearchPort`. It accepts only an
application-created `NightOwlQueryPlan` containing:

- active Night Owl grant ID/revision/digest;
- run ID and lease generation;
- one enabled category;
- one registered query-template ID and application-rendered query;
- fixed SearXNG category; and
- current budget counters.

The gateway checks Web Search's effective capability setting before calling
SearXNG. If ordinary Web Search is disabled, Night Owl cannot use SearXNG; it
does not reinterpret its own grant as a Search-settings override. Exact
skills.sh and GitHub adapters are separately disclosed Night Owl sources and
are still gated by the Night Owl grant.

`SearchApplicationPolicy`, its process-local five-minute consent, explicit
`/search`, natural-language proposal logic, and Remote Chat Search consent
remain unchanged. No Night Owl authorization object is accepted by those
paths, and no interactive `SearchDecision` is accepted by Night Owl.

## 8. Source policy

### 8.1 V1 allowlist

Night Owl V1 admits only:

- the administrator-configured local/private-numeric SearXNG endpoint through
  the existing `SearXNGSearch` adapter, for structured discovery results;
- `https://skills.sh/api/search` through the existing exact-host discovery
  transport;
- public unauthenticated `https://api.github.com` repository, release, commit,
  tree, and blob endpoints constructed by Tori; and
- canonical `https://github.com/<owner>/<repository>` pages as attribution
  links, not browser automation or executable content.

GitHub repository README or release-note text may be retrieved only through a
bounded API response tied to a verified public repository and immutable commit
or release identity. GitHub Skills inspection may retrieve only the selected
package subtree using the existing quarantine and inspection controls.

SearXNG result snippets and URLs are discovery leads. V1 does not automatically
retrieve arbitrary result hosts. A lead becomes a durable finding only after
corroboration by an admitted authoritative GitHub or inspected Skill identity.
Search-only leads are counted in the run and then discarded.

### 8.2 Network restrictions

- HTTPS is mandatory for public sources. SearXNG retains its existing approved
  local HTTP/private endpoint rules.
- No request contains cookies, login state, Authorization headers, tokens,
  cloud credentials, private repository credentials, or ambient proxy settings.
- Redirects must remain within the exact approved host and path family.
- DNS/IP validation, response limits, timeouts, UTF-8/text checks, redirect
  limits, and no-credential URL validation reuse or exceed current public-source
  controls.
- Night Owl does not download release assets, archives, models, binaries, package
  dependencies, or executable scripts.
- Rate-limit responses are source failures, not reasons to add credentials or
  bypass limits.

Additional official project sites, feeds, package registries, arbitrary static
pages, authenticated APIs, and private sources are deferred. Adding a source
requires a reviewed adapter, exact trust/provenance rules, privacy assessment,
and source-policy version change.

## 9. Untrusted-content policy

All SearXNG records, webpages, READMEs, repository files, release notes, issues,
Skills metadata/instructions, API descriptions, popularity data, and model
analysis are untrusted evidence.

Night Owl must enforce these rules structurally:

- external text is never parsed as an application command, tool call,
  permission, category, query, URL admission decision, or configuration;
- collection and model-analysis components expose no shell, filesystem write,
  Coding Work, Skill lifecycle, MCP lifecycle, service control, Search planning,
  or other action tool;
- the model receives a fixed high-authority instruction that clearly delimits
  normalized source records as data, matching the current Search and Project
  untrusted-data pattern;
- the model can analyze only already-admitted records and must return a closed,
  size-bounded schema with existing source IDs; unknown IDs, URLs, fields,
  commands, or authority claims reject the analysis;
- source text such as “run this command,” “install this package,” “add this API
  key,” “connect this MCP server,” “disable security,” or “ignore previous
  instructions” has no executable interpretation;
- recommendations use application-authored required-authority classes. External
  text and model output cannot select or reduce the required authority;
- prompt-injection indicators, malformed controls, attribution conflicts, or
  source-identity ambiguity reject that source or finding with a bounded error;
  and
- raw source bodies and raw model responses are transient. They do not become
  Memory, Knowledge, Conversation history, logs, or durable Night Owl state.

Static inspection establishes identity, structure, and compatibility evidence;
it does not prove safety, quality, publisher identity, or truth.

## 10. Persistence and findings model

Night Owl owns a separate exact-schema SQLite store at:

`runtime/night_owl/tori_night_owl.db`

It is separate from Conversation, curated Memory, Knowledge, Projects, Skills,
Scheduled Work, and the Capability Growth Improvement Journal. Conceptually it
contains:

- `night_owl_settings`: singleton revision, master state, pause state, source
  policy version, selected category set, grant generation/digest, and linked
  Scheduled Work identity/revision;
- `night_owl_runs`: run ID, trigger, optional Scheduled run ID, authorization
  revision/digest, exact category set, policy version, state, timestamps,
  budget use, counts, and bounded error codes;
- `night_owl_run_metrics`: compact aggregate and per-category counters for a
  terminal run only (no query text, URLs, snippets, or retrieved content);
- `night_owl_findings`: stable identity, category, normalized source identity,
  current material fingerprint, concise fields, relevance facts, lifecycle,
  review state, timestamps, revision, and optional Capability Growth link;
- `night_owl_finding_versions`: a bounded history of material fingerprints,
  version/release identity, source-support map, first/last observation, and
  whether that revision was surfaced; and
- `night_owl_sources`: normalized source kind, stable project/release/Skill
  identity, canonical attribution title/URL, immutable commit/release/digest
  where available, evidence level, publication time, and retrieval time;
- `night_owl_run_findings`: the exact finding version observed by one research
  run, used to prove promotion provenance and its per-run cap; and
- `night_owl_enrichments`: optional bounded advisory analysis keyed to one
  material finding version, with provider/model, prompt version, and structured
  input digest kept distinct from source-derived fields; and
- `night_owl_promotions`: the durable run/finding/version/recommendation receipt
  that preserves idempotency and the three-promotions-per-run ceiling even if a
  terminal Capability Growth recommendation later ages out of bounded history.

A finding contains only enough structured information to answer:

- **What:** bounded title and one concise summary;
- **Where:** one to three normalized source records with exact attribution;
- **Why it may matter:** application-validated relevance signals and a bounded
  rationale;
- **Category:** exactly one enabled V1 category;
- **What changed:** stable project identity plus current material version and
  change reason;
- **Unknowns/risks:** a bounded list including missing license, compatibility,
  maintenance, resource, security, or verification facts; and
- **Possible next step:** advisory wording such as review, compare, or test in a
  separate explicitly authorized workflow, plus the required authority class.

Suggested per-field limits are 200 characters for titles, 1,000 for summary or
rationale, 500 per unknown/risk, five unknowns, three source records, and no
stored page body, README body, prompt, response, chain of thought, command,
secret, or private user text.

The store follows current fail-closed runtime conventions: owner-private mode,
no symlink or unsafe hard-link admission, exact tables/columns/indexes,
foreign-key and value validation, atomic first publication, revisions,
bounded capacity, read-after-write verification, no startup migration, no
silent repair, and a backup consistency guard. An absent store reads as Off and
must not be created by a status read or ordinary startup.

## 11. Stable identity, deduplication, and resurfacing

Deduplication separates stable subject identity from material version.

### 11.1 Stable identities

- GitHub project: `github:<lower-owner>/<lower-repository>` after `.git`, case,
  fragment, and default-port normalization.
- GitHub release: project identity plus immutable GitHub release ID when
  available; tag name is retained as human-readable provenance.
- Skill: normalized skills.sh catalog identity plus GitHub owner/repository,
  selected package path, immutable commit, and inspected package digest.
- Search lead: normalized public URL only while transient; it cannot establish a
  durable finding identity by itself.

The durable finding identity is a hash of source kind, stable subject identity,
finding kind, and Night Owl category. Display names, stars, install counts, and
free-form descriptions are never identity.

### 11.2 Material fingerprints

A material fingerprint includes only normalized change-bearing fields, such as:

- new immutable release ID, tag, commit, or inspected Skill digest;
- changed compatibility or requested-permission classification;
- changed local/self-hosted or protocol-fit evidence;
- a newly linked or resolved Capability Growth gap/friction signal; or
- a material risk/source-quality classification change.

Star counts, install counts, ranking position, search snippet wording, README
copy edits, repeated discovery, or retrieval timestamps are not material on
their own.

### 11.3 Lifecycle behavior

- First admitted material creates a `new` finding revision.
- Rediscovery of the same fingerprint updates observation counts/times but does
  not re-open, duplicate, or re-surface it.
- Marking a finding seen suppresses that revision from new counts.
- Dismissal suppresses the exact revision. A linked Capability Growth
  recommendation is dismissed through Capability Growth so recommendation
  lifecycle has one owner.
- A new material fingerprint creates a new finding version, marks the old
  version superseded, and may return the finding to `new` with a concise change
  reason.
- A disappeared, archived, or no-longer-relevant project may become `stale` or
  `superseded`; history is preserved until normal bounded terminal retention.

This prevents nightly repetition without permanently hiding genuine releases,
changed risks, or newly relevant projects.

## 12. Relevance model

“New” is necessary but insufficient. The application applies a deterministic
gate before retaining or promoting a finding.

Every finding must have:

1. an enabled category match from the code-owned query/source registry;
2. a stable admitted public-source identity and sufficient attribution;
3. novelty or a material change; and
4. at least one evidenced Tori-fit signal.

Allowed positive Tori-fit signals are:

- fills a missing marker in the current `CapabilityInventory`;
- maps to an existing open Capability Growth friction, failure, regression,
  workaround, or opportunity by bounded capability area/ID only;
- supports local or self-hosted operation according to admitted evidence, as a
  supporting signal rather than sufficient Tori fit by itself;
- exposes a protocol or API already used by Tori, such as an actually evidenced
  OpenAI-compatible or MCP boundary;
- is compatible with Tori's current platform or inspected Skill contract; or
- is a material release of a project already recorded as relevant.

The current deterministic GitHub-project gate requires category match plus at
least one concrete protocol/API, known Tori-subsystem, or bounded capability-gap
signal. Category match plus `local_self_hosted` alone is intentionally rejected
after physical acceptance showed that combination admitted a technically
related project without a persuasive Tori use.

Deterministic negative signals include archived/unmaintained state, account- or
cloud-only operation, missing usable public source evidence, unsupported
executable behavior, incompatible platform/contract, unclear license, and a
duplicate existing capability with no material benefit.

The implementation should use a fixed score table only after mandatory gates;
a recommended V1 threshold is 6, with exact-category match `+2`, linked current
Capability Growth need `+3`, evidenced local/self-hosted support `+2`, existing
protocol fit `+2`, inspected compatibility `+2`, material known-project release
`+2`, cloud/account-only `-4`, unsupported execution `-4`, archived state `-4`,
and unknown license `-1`. Scores and contributing signals are stored so the
reason is auditable. A model cannot add score, waive a mandatory gate, or turn
an unknown into a fact.

## 13. Model/provider role

Night Owl does not require a model to collect, identify, deduplicate, attribute,
or authorize research. Those steps are deterministic.

V1 may use a replaceable `NightOwlAnalysisPort` for bounded classification and
concise summarization only after deterministic source admission. It receives:

- normalized public evidence for one already-admitted candidate;
- the exact enabled category;
- a compact non-private capability inventory/gap projection;
- fixed relevance definitions; and
- application-assigned source IDs.

It receives no Conversation, Memory, Knowledge, Finance, Discord, Project text,
personal file, credentials, tools, arbitrary URLs, or authority to request more
research. Its closed output is advisory: proposed summary, source-bound factual
claims, risks/unknowns, and suggested comparison questions. The application
validates source IDs, sizes, enums, and relevance support before use.

Use at most six model calls per run and prefer one candidate per call so a
malformed response cannot contaminate unrelated candidates. A provider timeout,
unavailability, malformed result, or unsupported response cannot produce a
confident recommendation. Deterministically sufficient findings may still be
retained with explicit unknowns; candidates requiring model analysis are
dropped, and the run is `partial` if useful work remains or `failed` if none
does. No automatic provider fallback occurs.

Background model use must yield to foreground Conversation. Check foreground
readiness before each model call and abort the remaining analysis as partial if
foreground work begins. Do not hold `OperationCoordinator.acquire_quiet()`
across network or model latency. A future preemptible provider-work coordinator
may improve this; it is not permission to delay or reject user Conversation.

Slice 4 implements this as a closed JSON result with exact keys, bounded text
and list sizes, no tools, and no source or capability callbacks. Input and
output accounting conservatively charges UTF-8 bytes when provider usage is
unknown. Unsupported action-seeking text or URLs are rejected. Provider or
validation failure leaves the deterministic finding intact and makes the run
truthfully partial when useful work remains.

## 14. Capability Growth integration

Night Owl owns external research findings. Capability Growth continues to own
advisory recommendations and the Improvement Journal's operational evidence.

The rules are:

- Night Owl never writes `CapabilityEvidence` for an external claim. A release,
  README, catalog result, model judgment, or popularity metric is not evidence
  that Tori succeeded, failed, regressed, or experienced friction.
- Every promoted item retains its Night Owl finding/version ID and normalized
  source provenance.
- External discoveries are normally `EXPAND` recommendations.
- `IMPROVE` is allowed only when the discovery is explicitly linked to an
  existing open Improvement Journal friction/workaround/opportunity by a fixed
  capability mapping.
- Night Owl cannot create `FIX`. FIX remains grounded in verified Tori
  failure/regression evidence.
- Existing recommendation states—`open`, `dismissed`, `accepted`, `resolved`,
  and `obsolete`—remain authoritative. `accepted` remains advisory and triggers
  no installation, enablement, execution, or configuration.
- Reconciliation can obsolete an open recommendation when its source is stale,
  capability already exists, or fit no longer passes; it never deletes the
  Night Owl finding or Improvement Journal evidence.

Slice 4 adds the typed `skill_candidate | external_research` provenance union,
an explicit Improvement Journal v1-to-v2 migration, and a
`CapabilityGrowthApplicationService` ingestion method. Normal startup does not
migrate canonical state. Night Owl submits a validated proposal to that service;
it never opens or mutates journal tables directly. A material update reuses the
stable recommendation identity while revising provenance to the newly observed
finding version; unchanged promotion is idempotent and each Night Owl run is
durably capped at three distinct promoted findings.

## 15. Scheduled Work relationship

Night Owl should use Scheduled Work for scheduled occurrences.

Scheduled Work already owns the correct concerns:

- one-shot/daily/weekly civil schedules and timezone behavior;
- immutable Persistent authorization snapshots;
- exact capability/arguments/schedule digests;
- durable definitions, revisions, occurrences, and run history;
- `run_when_available` versus `skip_if_missed` semantics;
- transactional due claims and one scheduled execution worker;
- startup conversion of uncertain running work to `interrupted`; and
- truthful terminal result notification state.

Register one application-owned scheduled capability,
`tori.night_owl.research`, with recurring eligibility and no interactive action
or shell semantics. Its closed arguments contain only Night Owl authorization
ID/revision/digest, exact category set plus digest, source-policy version, and
budget-policy version. They contain no prompt, arbitrary query, URL, command,
or user data. The executor calls the
same `NightOwlRunService` used by Run now.

Night Owl still owns category scope, query/source policy, run budgets, findings,
deduplication, relevance, and recommendation creation. Scheduled Work cannot
expand those through arguments or result data.

On-demand runs do not create disposable Scheduled Work definitions. They use a
one-use local Run-now trigger plus the active Night Owl durable grant and create
a normal Night Owl run record. This keeps Scheduled Work history meaningful and
avoids inert one-shot definition clutter.

## 16. Schedule and run lifecycle

### 16.1 Settings choices

- **On demand only** — the default after first enable; no active schedule.
- **Nightly** — one daily Scheduled Work definition; initial suggested time is
  02:00 in Tori's configured timezone.
- **Weekly** — one weekly definition; initial suggested time is Sunday 02:00.

The user may choose one local run time and, for weekly, one weekday. No cron
expression or multiple schedule editor is exposed. The Scheduled Work view may
show the underlying read-only definition/run history, but Night Owl Settings is
the owner-facing place to change this schedule.

### 16.2 Missed and overlapping runs

Nightly and weekly V1 use `skip_if_missed`. If Tori was stopped across an
occurrence, startup records a skipped Scheduled run and advances to the next
occurrence; it does not create a burst or perform stale catch-up research. The
user may Run now.

One durable Night Owl lease permits one active run across manual and scheduled
triggers. A scheduled trigger that loses the lease records
`skipped / already_running`; a manual trigger receives the existing bounded
conflict and may be retried explicitly. Neither waits, overlaps, or creates a
second worker. Scheduled Work's single worker remains an
additional serialization boundary for scheduled capabilities, not the Night
Owl concurrency authority.

Quiet Hours do not block Night Owl execution. They control Companion Initiative
interruption only. Running at 02:00 is therefore allowed when explicitly
scheduled, while any later proactive mention still waits for Companion
Initiative eligibility outside Quiet Hours.

### 16.3 Domain run states

Night Owl records:

- `pending` — durable run created, no external work started;
- `running` — lease and authorization revalidated;
- `completed` — planned bounded work finished truthfully, including a valid
  zero-findings result;
- `partial` — some useful research completed but a source, provider, budget, or
  attribution stage did not;
- `failed` — no trustworthy research result completed;
- `interrupted` — shutdown/crash or explicit revocation stopped uncertain work;
  and
- `skipped` — disabled, paused, missed, stale authorization, no categories,
  overlap, or other pre-work policy denial.

Scheduled Work keeps its own execution status. A completed or partial Night Owl
result is a successful invocation with the Night Owl status in bounded result
JSON. A failed Night Owl run raises a safe scheduled capability failure. Startup
maps a linked Scheduled `interrupted` run to Night Owl `interrupted`. The two
records remain linked rather than pretending their status vocabularies are
identical.

Graceful shutdown first cancels and joins Night Owl within its bounded deadline,
then stops Scheduled Work and dependent adapters. Crash recovery never retries
an uncertain external/model step; the prior run becomes interrupted and the
next normal occurrence is independent.

## 17. Resource budgets

Recommended hard V1 defaults per run are:

| Resource | Limit |
| --- | ---: |
| Enabled categories evaluated | 1–6 |
| SearXNG discovery queries | 3 × enabled categories (maximum 18) |
| Normalized SearXNG discovery results considered | 12 per enabled category (maximum 72; not shared across categories) |
| GitHub repository/release fetches | 4 × enabled categories (maximum 24) |
| Immutable Skill inspections | 0 unless Skills is enabled; otherwise 6 maximum |
| Model calls | 6 total |
| Cumulative model input | 32,000 estimated tokens |
| Cumulative model output | 8,000 estimated tokens |
| Transient admitted source text | 192,000 characters |
| New/materially updated findings | 5 per run |
| Capability Growth promotions | 3 per run |
| Wall-clock duration | 10 minutes |
| Active Night Owl runs | 1 |
| Durable runs retained | 50 |
| Durable findings retained | 250 |
| Versions retained per finding | 5 |
| Sources retained per finding version | 3 |

Budgets are application constants in V1, shown in explanatory text but not
individually editable. Reaching a limit stops that stage. A run is `partial` if
planned work was left incomplete, or `completed` if all applicable work
legitimately exhausted its bounded candidate set. Capacity may retire only the
oldest terminal run history, stale/superseded finding versions, and dismissed
terminal findings. It must never silently discard active grants, running runs,
new findings, or open linked recommendations. If safe capacity cannot be made,
the write/run fails honestly.

The public GitHub adapter currently accounts two fetches per inspected project:
repository metadata and latest-release metadata. The category-scaled profile
therefore admits about two fully inspected repositories per enabled category.
Discovery is completed for every enabled category first, with three distinct
fixed angles each; candidates are ranked deterministically within category,
deduplicated by canonical repository, and then interleaved across category
queues. First-round corroboration is offered across categories before
second-round capacity. This prevents one early category from exhausting shared
budget while preserving relevance ranking and without promising a finding per
category.

## 18. Privacy model

Night Owl may use only:

- explicitly enabled Night Owl category IDs;
- code-owned query templates;
- public source identities and evidence;
- compact `CapabilityInventory` identifiers, states, versions/digests, and
  approved operation names;
- bounded Improvement Journal capability area/ID, evidence kind, severity,
  error code, count, and lifecycle needed for relevance; and
- its own prior finding/source fingerprints.

Queries contain public technical terms from the category registry. They do not
contain transcript text, chat labels, user names, personal interests inferred
from conversation, Memory, Knowledge, Project content, Finance, Planning,
Discord, local file paths, hostnames/IPs, installed-model prompt history,
credentials, or secrets. Installed capability names may affect local scoring,
but are not sent to SearXNG or public sources unless already part of a fixed
public query template.

Only the admitted public evidence may be sent to the configured analysis
provider. Operator events record `run_id` only if its format is safe, trigger,
state, category count, source adapter, numeric counts, elapsed milliseconds,
and bounded error codes. They omit query text, URLs, titles, summaries, source
bodies, model output, and private state.

## 19. Companion Initiative integration

Night Owl does research. Companion Initiative decides whether Tori may
proactively approach the user.

Night Owl exposes a read-only `NightOwlAttentionProvider` with only:

- count of new actionable finding revisions, capped for wording;
- an opaque deterministic cohort digest;
- oldest/newest eligible finding timestamps; and
- whether the cohort still exists.

It exposes no source prose, URL, recommendation text, query, or authority.

Slice 4 adds the optional `night_owl_findings` initiative type, separately
default Off. Its
candidate key is `night-owl:<cohort-digest>` and its deterministic wording is:

> “I found two local-AI developments that may be useful for Tori. Want to see
> them?”

The count is application supplied. The initiative must pass the existing
master switch, per-type enable, Quiet Hours, recent-activity suppression,
global/type cooldowns, rolling caps, snooze, unresolved-message, active-chat,
readiness, claim, archive, and recovery rules. It has no special override and
cannot call Night Owl, Search, a model, or Capability Growth during delivery.

A reply may consume one opaque cohort context and deterministically show the
stored findings. It grants no install, enable, configuration, execution, or
Search authority. If Companion Initiative is Off, paused, capped, or never
enabled for Night Owl, findings remain fully available through manual review.
Night Owl runs are allowed during Quiet Hours; only proactive delivery is not.
The availability offer is represented by Companion Initiative's own durable
candidate/event lifecycle and does not mark any Night Owl finding reviewed.
Slice 5 owns the manual review surface and any deterministic cohort reply view.

## 20. User-facing review and Settings concept

The smallest useful V1 surface is **Settings → Night Owl**, not a new primary
workspace. It contains:

- master Off/On, default Off;
- pause/resume;
- six category toggles;
- schedule: On demand only / Nightly / Weekly;
- one local time and, for weekly, one weekday;
- **Run now**;
- source-policy disclosure and fixed budget summary;
- current/last run state, time, trigger, useful counts, and a compact Last Run
  Details section: duration, used/allowed budgets, GitHub-hosted results,
  canonical repository leads, queued/corroborated repositories, truthful Skills
  catalog request/candidate outcomes, sanitized rejection/failure/skip counters,
  terminal codes, and concise per-category coverage;
- next Scheduled Work occurrence;
- new and total finding counts; and
- a compact findings review panel showing What / Why / Changed / Unknowns /
  Possible next step / Sources, with Mark seen and Dismiss-current-revision.
  The primary What field is a bounded source-derived description; internal
  repository/version identities are provenance, not the user-facing summary.
  An unchanged successful rediscovery may refresh bounded display metadata
  without creating a material version. A historical fingerprint-style summary
  receives only a truthful limited read-time fallback until approved source
  metadata is observed again. If the same source is later successfully
  reassessed and fails the current deterministic relevance policy, it becomes
  non-reviewable while its history remains preserved; this is not a user
  dismissal. Details is an offline read of stored material only, and optional model
  interpretation remains visibly distinct from source-derived facts.

Promoted recommendation actions remain in **Skills & MCP → Capability Growth**,
whose existing revision-safe lifecycle is authoritative. A deterministic local
Conversation read such as “What did Night Owl find?” may return the latest
stored new findings without Search or a model call. Starting a run from
Conversation is limited to the exact configured “Run Night Owl” command and
uses the same grant, categories, budgets, and fixed templates as Settings;
extra topic, URL, or query wording is refused. A dedicated Night Owl primary
page, arbitrary category creation,
and advanced source/budget controls are deferred.

Settings state is server-authoritative, revision-safe, shared across tabs, and
read-only when its backing store is unsafe. JavaScript presents state but owns
no authorization, query, relevance, schedule, or lifecycle policy.

## 21. Failure semantics

- **SearXNG unavailable:** its planned queries fail with a safe code. Other
  admitted adapters may continue; result is partial if useful work remains,
  failed if no trustworthy path completes.
- **GitHub/skills.sh unavailable or rate-limited:** fail that source only; never
  add credentials, retry without bound, or treat a snippet as verified evidence.
- **Provider unavailable/malformed/timeout:** retain only deterministically
  sufficient findings with explicit unknowns; no model-dependent recommendation.
- **Tori shutdown mid-run:** cooperative shutdown records interrupted. Startup
  reconciles durable `running` records to interrupted without replay.
- **Stale scheduled occurrence:** Scheduled Work records skipped according to
  `skip_if_missed`; Night Owl does no catch-up.
- **Overlapping run:** later run is skipped with `already_running` before network
  or model work.
- **Malformed, hostile, or prompt-injected content:** reject the source or its
  analysis, record a bounded code, and continue within budget.
- **Duplicate unchanged finding:** count as observed duplicate; do not create,
  update material content, promote, or surface it again.
- **Material update:** create a new version, state exactly what changed, and
  permit resurfacing after full relevance/attribution checks.
- **Source attribution failure:** discard the finding/recommendation. A partial
  claim without a valid source is never retained as confident advice.
- **Storage unavailable/corrupt/unsafe/full:** stop the run and preserve state;
  never replace, repair, or report completion. If terminal status cannot be
  persisted, emit only a sanitized serious operator error and fail the linked
  Scheduled run.
- **Authorization mismatch/revocation:** skip before work or interrupt at the
  next boundary. Never fall back to an older or broader grant.
- **Budget exhaustion:** stop cleanly. Report partial only when planned work is
  unfinished; never hide the exhausted dimension.
- **No relevant findings:** completed with zero findings when all planned work
  finished. “Nothing useful found” is not a failure.

No failure in Night Owl may impair normal Conversation, manual Search,
Scheduled Work management, Skills, or Capability Growth review.

## 22. Security analysis

| Threat | Required V1 control |
| --- | --- |
| Prompt injection / external authority claims | Treat all external/model text as delimited data; expose no action tools; closed outputs; application-owned category, source, relevance, and authority checks. |
| Confused-deputy Search consent | Separate Night Owl grant and gateway; no `SearchConsent`, `SearchDecision`, fake local turn, or forged `RequestOrigin`. |
| Authority expansion through scheduling | Scheduled arguments contain only exact grant references/digests; execution revalidates the current Night Owl grant at every boundary. |
| SSRF, private-network access, or DNS rebinding | Exact-host adapters; existing public DNS/IP pinning and redirect controls; no arbitrary result-page retrieval. |
| Credential or privacy leakage | No auth headers/cookies/proxies/private sources; fixed public queries; no private context in requests, models, logs, or findings. |
| Malicious repository/package | Public API only; immutable identity; bounded selected-tree quarantine; no links/special files; no execution; no release assets or dependencies. |
| Source spoofing / attribution fabrication | Canonical identities, immutable release/commit/digest where possible, source-ID validation, search-only leads non-durable, no recommendation without admitted attribution. |
| Model hallucination or scope invention | Model cannot query or act; output references admitted source IDs only; deterministic gates/scores own retention and promotion. |
| Resource denial | One run, hard query/fetch/text/model/token/time/row budgets, exact timeouts, no unbounded retry or crawl. |
| Duplicate spam | Stable subject identity plus material fingerprint, seen/dismiss state, cohort dedupe, meaningful-change rules. |
| Revocation race | Generation fence before each I/O/model/write; disable revokes first; stale Scheduled authorization fails closed. |
| Crash ambiguity | Durable run/lease states; Scheduled Work interruption truth; no replay of uncertain external/model step; idempotent finding fingerprints. |
| Store/path attack | Owner-private exact-schema SQLite, no-follow and link checks, bounded fields, verification, no automatic repair/migration. |
| Browser policy bypass | Server-authoritative revisions and validation; existing same-origin, CSRF, safe rendering, and no-browser-storage controls. |
| Recommendation becomes action | Capability Growth acceptance stays advisory; every install/enable/config/execute workflow begins separately with existing authority. |

## 23. Implementation slices

Implementation should wait until the current Companion Initiative acceptance
work is closed and preserved. Use five cohesive slices:

1. **Night Owl foundation:** exact-schema store, settings/grant model,
   code-owned category/query registry, source-policy types, run/finding/source
   records, stable identities, material fingerprints, lifecycle, capacity,
   backup/restore guard, and fake-port contract tests. Default Off; no network.
2. **Bounded research runner:** Night Owl Search gateway, structured SearXNG
   discovery, public GitHub project/release adapter, research-only skills.sh and
   immutable Skill inspection seams, relevance engine, optional analysis port,
   budgets, cancellation, on-demand Run now, source attribution, and hostile
   content tests. No scheduling or promotion yet.
3. **Scheduled Work and lifecycle:** register `tori.night_owl.research`, staged
   cross-store authorization, on-demand/nightly/weekly settings, missed-run,
   overlap, startup interruption, shutdown, observability, and truthful linked
   status/result behavior.
4. **Capability Growth and Companion integration:** explicit Improvement Journal
   provenance-schema migration and application ingestion, EXPAND/conditional
   IMPROVE promotion, reconciliation, metadata-only Night Owl attention provider,
   separately default-Off initiative type, cohort/reply-context behavior, and
   proof that all existing initiative suppression rules still govern.
5. **Settings/review, physical acceptance, and closeout:** responsive Settings
   controls and findings panel, deterministic Conversation review command,
   multi-tab/restart behavior, complete backup/restore coverage, documentation,
   offline verification, and desktop/physical-mobile acceptance.

No slice may install, enable, configure, execute, or create a generalized
background authority path.

## 24. Automated test strategy

All stores use isolated temporary roots. Tests never depend on or mutate
canonical `runtime/`.

### 24.1 Core and persistence

- default-Off absent-store reads create no path and make no adapter call;
- exact schema, field/count limits, revision conflicts, mode/link/path rejection,
  corrupt/unknown schema preservation, atomic initialization, and read-after-
  write verification;
- run-state transitions, leases, cancellation generations, terminal-only
  pruning, full active-capacity failure, and backup guard behavior;
- canonical project/release/Skill identities, URL normalization, material
  fingerprints, unchanged dedupe, meaningful-update resurfacing, and
  seen/dismiss semantics.

### 24.2 Authority and sources

- every query template/category/source combination is allowlisted and bounded;
- disabled category, paused/off/revoked/stale grant, changed digest, exhausted
  budget, arbitrary query, arbitrary URL, wrong host/path, private IP, redirect,
  credential URL, and interactive-consent substitution fail before transport;
- Web Search Off blocks SearXNG without affecting explicitly granted exact
  GitHub/skills adapters;
- no Night Owl object authorizes normal local or Remote Search;
- GitHub and Skills fixtures cover limits, immutable identity, rate limit,
  truncated tree, link/submodule/special file, digest drift, and inert scripts.

### 24.3 Untrusted content and model analysis

- hostile READMEs/releases/Skills instructing command execution, installation,
  secret release, permission change, source expansion, or policy override cause
  no capability/action call or new query;
- closed analysis schema rejects unknown source IDs/URLs/fields, oversized text,
  instruction-shaped authority, fabricated claims, malformed output, and model
  tool-call syntax;
- provider unavailable/timeout/malformed/fallback attempts produce truthful
  deterministic/partial/failed outcomes without an ungrounded recommendation;
- private-data sentinels placed in Conversation, Memory, Knowledge, Project,
  Finance, Discord, file paths, and credentials never appear in queries,
  provider inputs, logs, findings, or errors.

### 24.4 Relevance and Capability Growth

- mandatory relevance gates and every score signal/penalty are table-driven;
- novelty without Tori fit is discarded;
- search-only snippet cannot create a finding or recommendation;
- external research never creates Capability Evidence or FIX;
- EXPAND and conditionally linked IMPROVE proposals preserve exact provenance,
  required authority, dedupe, dismissal, acceptance-with-no-action, material
  update reopening, obsolete reconciliation, and migration safety.

### 24.5 Scheduling, lifecycle, and Companion Initiative

- on-demand, nightly, and weekly local-civil schedules; DST; next occurrence;
  `skip_if_missed`; stopped-host recovery; active-run interruption; and no
  uncertain replay;
- manual/scheduled race admits one lease and skips the loser; one Night Owl run
  never blocks or overlaps another;
- quiet hours do not block research execution;
- Night Owl cannot append a Conversation event;
- the new initiative type passes master/type Off, quiet hours, recent activity,
  cooldowns, caps, snooze, unresolved delivery, readiness, multi-tab claim,
  archive recovery, manual-speech-only, and no-active-chat tests;
- findings remain visible and reviewable with Companion Initiative Off.

### 24.6 Presentation and observability

- Settings mutations are CSRF/same-origin/revision protected and JavaScript
  cannot supply policy-owned fields;
- multi-tab status and finding actions converge without duplicate runs or
  lifecycle changes;
- source links render as text-safe application data;
- normal operator events contain only allowlisted metadata, and serious errors
  remain sanitized when activity logging is Off.

Focused tests should run during each slice. The complete offline
`./scripts/verify-milestone` gate, full diff review, founding-document check,
and runtime-preservation verification apply at meaningful integration/closeout
checkpoints, not to this architecture-only document mission.

## 25. Physical acceptance checklist

- [ ] Fresh and migrated installations show Night Owl master Off, no active
      categories/schedule, no created store from reads, and no network/model call.
- [ ] Enabling requires selected categories and clearly discloses bounded public
      research, sources, schedule, budgets, privacy, and advisory-only behavior.
- [ ] **Run now** performs one bounded on-demand run and shows accurate counts,
      state, duration, sources, and zero/useful findings.
- [ ] Nightly and weekly options create exactly one matching Scheduled Work
      definition/authorization; edit, pause, resume, Off, and restart reconcile.
- [ ] A stopped application is not awakened. A missed occurrence is skipped and
      advances without catch-up; Run now remains available.
- [ ] Night Owl may execute during Quiet Hours, but no Companion Initiative
      message is delivered until all initiative policy allows it.
- [ ] Only selected categories generate code-owned queries; an arbitrary topic,
      model suggestion, webpage instruction, or user text outside Settings cannot
      expand scope.
- [ ] Ordinary interactive Search still requires its existing setting and
      current-turn consent rules; Night Owl authority cannot be used there.
- [ ] Search Off blocks Night Owl SearXNG use without silently broadening another
      source; disabling/pausing Night Owl fences new work immediately.
- [ ] SearXNG, GitHub, and skills.sh traffic stays within the documented public
      allowlist with no account, login, token, cookie, proxy credential, private
      repository, arbitrary authenticated browsing, or release-asset download.
- [ ] Malicious source text requesting command execution, installation,
      configuration, secrets, new URLs, MCP connection, security disablement, or
      self-modification causes no action or authority change.
- [ ] No package, repository, model, binary, Skill, MCP server, service, Tori
      source/config, permission, or founding document is installed, enabled,
      executed, changed, or restarted by a run or accepted recommendation.
- [ ] A useful new finding shows What, Where, Why, Category, Change, Unknowns,
      Next step, and exact admitted source attribution.
- [ ] The same unchanged repository/release/Skill is observed without another
      visible finding or proactive cohort.
- [ ] Mark seen and dismiss suppress the exact revision. A new release/commit/
      digest or other documented material change can reappear with the change
      explained.
- [ ] Search snippets alone never become a confident finding; missing or invalid
      attribution discards the item.
- [ ] Novel but irrelevant items fail the deterministic Tori-fit gate; a model
      cannot override the score or enabled category.
- [ ] A promoted discovery appears in Capability Growth with research provenance
      and EXPAND/allowed IMPROVE semantics; it creates no operational evidence or
      FIX, and Accept performs no action.
- [ ] SearXNG/source/provider outages, malformed content, rate limits, budget
      exhaustion, duplicates, and storage failures produce the documented
      completed/partial/failed truth without fabricated findings.
- [ ] Graceful shutdown and forced interruption leave no duplicate run/finding;
      startup marks uncertainty interrupted and does not replay it.
- [ ] Simultaneous Run now and scheduled occurrence admit one run; the other is
      truthfully skipped.
- [ ] Queries/provider inputs/logs contain no transcript, Memory, Knowledge,
      Finance, Discord, Project text, personal file paths, secrets, or credentials.
- [ ] With Companion Initiative enabled for Night Owl, the fixed count-only offer
      respects Quiet Hours, cooldowns, caps, pause/snooze, recent activity,
      unresolved-message, readiness, and multi-tab delivery rules.
- [ ] With Companion Initiative master or Night Owl type Off, no proactive offer
      occurs and all findings remain manually accessible in Settings and through
      the deterministic review command.
- [ ] Desktop and physical mobile Settings/findings presentation is readable,
      source-safe, nonmodal, and revision-consistent.
- [ ] Verified Backup/Restore preserves Night Owl authorization, schedule links,
      runs, findings, versions, dedupe, and Capability Growth provenance; test
      execution leaves canonical runtime byte-for-byte unchanged.

## 26. Deferred scope

Deferred beyond V1:

- arbitrary user-authored standing topics or query text;
- arbitrary webpage retrieval, crawling, RSS/feed subscriptions, package
  registries, social media, issues/discussions monitoring, or general news;
- authenticated GitHub, private repositories, logins, paid APIs, credentials,
  cookies, and cloud browsing;
- Deep Research, multi-step model-directed investigation, agents, delegated
  subtasks, autonomous follow-up queries, or model-selected sources;
- downloads of models, releases, archives, binaries, containers, dependencies,
  or executable Skill components;
- automatic install/update/enable/configure/test/benchmark/execute/restart;
- Project-, transcript-, Memory-, Knowledge-, Finance-, Planning-, Discord-, or
  filesystem-derived personalized research;
- remote Night Owl administration or Remote Chat delivery;
- OS notifications, email/SMS/push, automatic TTS, or waking a stopped host;
- learned categories, schedules, relevance weights, or user behavior profiles;
- multiple schedules, cron syntax, retry workflows, catch-up queues, or
  cross-host workers;
- a dedicated Night Owl primary workspace; and
- any source, permission, action, or retention expansion not separately reviewed.

## 27. Architecture-gate conclusion

Night Owl V1 belongs in Tori core as a bounded advisory research policy and
state owner. Replaceable adapters provide public discovery, source inspection,
and optional model analysis. Scheduled Work owns when authorized recurring work
is due and what happened to its occurrence. Capability Growth owns promoted
recommendation lifecycle. Companion Initiative alone owns proactive approach.

This split lets Tori quietly research useful developments, remember what is
genuinely worth mentioning, and bring discoveries to the user later without
ever granting herself permission to change anything.
