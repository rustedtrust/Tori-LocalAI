# Tori Implementation Roadmap

**Project:** Tori
**Document:** IMPLEMENTATION_ROADMAP.md
**Status:** Milestone history and future planning; current truth is summarized in [Current State](FINAL_STATE.md)
**Last updated:** 2026-09-28

**v0.9.0 Stable Private Testing Checkpoint source:** Gate 6 core installer
implementation and Gate 6B independent fresh-GitHub-clone acceptance passed.
Gate 7 whole-product production smoke passed with no known closeout defect;
Research Worker was available under normal owner launch. Automatic Research
Worker and Voice Input installer provisioning remain explicitly deferred.
The final tag follows verified production backup and disposable restore of this
exact source. Public Release Readiness is separate future work, not part of
the private v0.9.0 freeze.

**Gate 8E backup failure observability — candidate for review:** maintenance
failures now emit one private console operator diagnostic with stable entry,
individual guard entry/exit, backup-body or completion attribution, exception
type, and allowlisted message label. The generic browser/API response and all
guarding, publication, and restore rules are unchanged. This is not evidence
that the two historical failures have been explained; a separately authorized,
single controlled production retry and verified restore still precede the tag.

## Purpose

This roadmap preserves Tori's completed milestone and slice history and records future directions. Its dated implementation-stage language is historical evidence; the [Current State](FINAL_STATE.md) and [User Guide](USER_GUIDE.md) own the current product and its operation. An old “not yet” or “deferred” inside a slice is not a current-status assertion and does not authorize resuming that slice.

- **MCP V1 — complete and physically accepted:** The pre-existing reusable
  MCP 2025-11-25 stdio client/registry is now production-wired beneath Tori's
  central capability state and authority path. Exact per-machine configuration
  starts official `mcp-server-time==2026.8.18` in a no-network/no-write
  Bubblewrap sandbox with a scrubbed environment. Discovery finds
  `get_current_time` and `convert_time`; only the exact approved
  `get_current_time` schema becomes available. Ordinary Conversation, live
  Skills & MCP state, drift/new-tool denial, failure truth, restart
  revalidation, and orphan-free shutdown passed real browser/server acceptance.
  See `docs/MCP_V1_ARCHITECTURE.md`.

It does not replace the accepted founding documents or redefine Tori's vision.

---

## Current State

**Gate 4 entry checkpoint:** `private revision omitted` (`Fix Remote Chat generation fencing`). Gate 1–3 and Remote Chat lifecycle fencing were complete; documentation reconciliation entered review. The [current-state checkpoint](FINAL_STATE.md) records the accepted capability set, external Research Worker wrapper, intentional V1 deferrals, and remaining closeout gates. In particular, Planning projection, Security Center, Voice Input, supervised browser Terminal, backup/restore and default-Off session-explicit Remote Chat are present. The old Deep Research and frozen Milestone 25 descriptions below remain historical; accepted Research Worker and Projects & Continuity V1 supersede their incomplete product claims.

**Backup/Restore Catalog Performance V1 — accepted.**
Maintenance reads bounded structural publication metadata and trusted source
compatibility without traversing or hashing every backup payload. The catalog
labels discovered backups as not rechecked; eligible entries still require
full selected-backup verification after one-use confirmation and again before
restore handoff. Backup creation, safety-backup coordination, and Remote Chat
guards remain authoritative. No old backups were deleted or rewritten.

**Load Performance Repair V1 — accepted.** The
Recent Chats sidebar now obtains canonical Project IDs and titles through a
narrow read-only archive-backed endpoint, without constructing Project Homes
to draw badges. The full Projects workspace retains its original projection.
Global New Chat now navigates to Chat and focuses the composer after success,
including from non-Chat views; cancellation and failure stay on the current
page. Backup and restore listing remain outside this repair.

**Visual Refresh V1.1 — mobile Home accepted.** Human feedback reopened
only mobile Home after V1 closeout. The responsive correction uses a compact
hero/session block, 2×2 monitor, flat review/work rows, and practical 44px
controls. Non-shrinking layout prevents hero/status overlap. Desktop Home,
Chat, Settings, Skills & MCP, and navigation retain their accepted styles.
Private acceptance evidence is not part of this public candidate.

**Visual Refresh V1 — accepted.** Home, shared visual tokens, colored
navigation, conversation/composer refinement, readable System Monitor states,
and consistent Settings controls are accepted. Home integrates the actual
session into a stronger hero, balances ongoing work against supporting status,
and preserves single-node card/control ownership across Chat and mobile.
Speak is compact in reply metadata; Chat's secondary rail is denser without
reducing 15px message text or changing Settings/Skills & MCP sizing. The
preceding disabled Remote Chat adapter composition defect is repaired so its
  coordinated backup guard remains available. Private acceptance evidence is excluded.

The accepted capability headings in this section identify completed work. Their
multi-stage paragraphs also preserve earlier slice limitations (for example,
older category counts and missing UI); later completions supersede those stage
descriptions. For the current capability inventory use [Current State](FINAL_STATE.md).

- **Projects & Continuity V1 — complete and manually live-accepted:** Fresh conversation archives now use exact schema 7 with bounded
  Project-owned workspace state, decisions, questions, flat plan items,
  restricted links, and per-turn context-receipt persistence. The explicit
  stopped-application schema-6-to-7 migrator preserves every existing archive
  value, creates no inferred structured state, and is never called by normal
  startup. The separately authorized canonical schema-6-to-7 migration
  completed successfully on 2026-09-22 with exact preservation, integrity,
  and foreign-key verification.
  The presentation-neutral Project application boundary now provides explicit,
  aggregate-revision-fenced workspace-state, immutable linear-decision,
  question-lifecycle, flat-plan, and restricted-link mutations. Normal Project
  creation and update cannot edit the legacy continuity brief, and the former
  transcript-to-Key-decisions synthesis path is retired. Slice 3 adds a
  presentation-neutral Project Home, deterministic structured Where We Are,
  metadata-only associated-conversation navigation, and revision-checked New
  Project Chat that persists association only with the first completed turn.
  Slice 4 replaces legacy prompt assembly with the presentation-neutral
  `ProjectContextService`, deterministic Stable/Working/selective-Historical
  whole-record budgeting through the existing context planner, atomic exact
  per-turn receipts, and persisted-receipt inspection in Conversation. Receipts
  never re-enter model context, and Project content remains data without
  capability authority. Slice 4 live browser acceptance verified one real
  provider turn, its retained exact receipt, and inspection after restart.
  Slice 5 adds bounded Related Work and current-record activity from native
  Research, Coding Work, and Attention Project IDs and source-verified Night Owl,
  Scheduled Work, and Knowledge links; source failures are identified as partial.
  Fresh Coding Work proposals inherit Project organization metadata without
  changing authorization. Slice 6 adds human-readable Source and Item selectors
  for the three approved source-owned targets, stable-ID verification at the
  source owner, explicit unlink, source navigation, and clearer partial Related
  Work presentation. Manual live acceptance covered the final link/unlink,
  polling, desktop/mobile, and compact Attention behavior. Acceptance
  corrections preserve recurring Scheduled Work authorization across operational
  revision advances, distinguish **Definition ID**, respect negated Coding Work
  authority, and use matching OpenCode 1.18.31 bootstrap material. SQLite
  stayed healthy during the disposable malformed Project proposal chat
  incident: an origin-less Scheduled Work result had entered that chat; reviewed
  recovery removed only test data, and both routing and archive-write validation
  now reject incompatible special-origin event sequences. Broad structured
  editing is outside V1. Reviewed OpenCode compatibility policy, Project Home
  performance, DeepSeek Harness evaluation, Qwen3.8 Flash Next benchmarking,
  and any reproducible unrelated Remote Chat timing flake are deferred. See
  `docs/PROJECTS_CONTINUITY_V1_ARCHITECTURE.md`.

- **Research Worker V1 — complete and physically accepted:**
  A separate durable Research Job store, exact conversation authorization,
  public-objective-only disclosure, replaceable NDJSON worker port, hardened GPT
  Researcher adapter, budgets, progress, exact source provenance, semantic
  validation gate, cancellation escalation, restart interruption, Workspace
  presentation, and verified-backup coverage are implemented. Bubblewrap gives
  each worker a private network; a Unix-socket egress broker validates the full
  DNS answer and connects the validated numeric public address, while a separate
  fixed relay permits only configured loopback Ollama, and an operation-limited
  relay permits only the configured local SearXNG JSON search route. Final
  wrapper/Ollama/authoritative retrieval, public-only egress, live cancellation,
  active-job restart, Workspace, citation, and physical browser gates passed on
  2026-09-21. Search/SearXNG, Night Owl, Coding Work, and MCP remain separate.
  The 2026-09-24 architecture-only review in
  `docs/RESEARCH_WORKER_V1_ARCHITECTURE.md` records proposed refinements to
  preserve the verbatim request separately from its interpretation, persist
  claim-to-evidence relationships, make partial-result semantics explicit,
  support linked follow-up jobs, and deepen deterministic chat/Project
  retrieval. The claim/evidence subset is now implemented for new reports
  through Research schema 3: bounded excerpts, ordered support states,
  same-job source links, atomic migration and terminal gates, canonical
  claim-derived Findings, typed readback, and a truthful legacy label.
  Free worker narrative remains separately marked unverified; source hashes
  provide consistency metadata, not content authentication. Qualified limited claims use the existing
  `completed_with_limits` state. The external wrapper and worker protocol were
  unchanged. Other proposed refinements remain unimplemented. The separately
  authorized production closeout migrated only the canonical Research store
  from schema 2 to 3 after a verified pre-migration backup; all six historical
  reports remain readable as legacy records. The proposed incremental slices
  and independent gates remain in that architecture document.
  A private code-and-test gap audit identified the bounded claim/evidence ledger and terminal citation gate as
  the smallest high-value refinement. That refinement is now implemented for
  new reports; external-wrapper work still requires separate scope.

- **Night Owl V1 — complete and human accepted:**
  Settings now owns explicit master/category grant changes, bounded Run Now,
  on-demand/nightly/weekly schedule controls, truthful run status, compact
  attributed findings, review/dismiss, and explicit EXPAND or valid linked
  IMPROVE promotion. Source-derived fields and optional model interpretation
  remain visibly separate. Bounded Conversation phrases read stored findings
  without starting research, while the separately default-Off Companion Night
  Owl type remains governed by the existing master, Quiet Hours, activity,
  cooldown, caps, snooze, and unresolved-event rules. The canonical Improvement
  Journal was explicitly safety-copied, migrated from schema 1 to schema 2, and
  integrity/content verified. Slice 5 does not install, clone, execute, enable,
  configure, send TTS/Discord, accept arbitrary research text, create a final
  backup, or close the milestone. The first real all-category physical run was
  truthfully partial at the eight-fetch GitHub ceiling and retained one weak
  image-generation match, which the user dismissed. Acceptance corrections now
  project active research into the existing Workspace activity card, remove
  dismissed findings from the reviewable surface, preserve stored-findings
  Conversation as a successful provider-free application event, and clarify
  Settings hierarchy/alignment. Research discovery now completes across enabled
  categories before a deterministic fair corroboration pass, with content-free
  reason counters, and local/self-hosted category match alone is no longer enough
  without a concrete Tori subsystem/protocol/capability fit. A revisioned
  research-depth profile now provides three fixed discovery angles per enabled
  category and scales search/result/GitHub ceilings as 3/12/4 × category count
  (18/72/24 maximum), with a conditional six-Skills limit, six model calls,
  32,000/8,000 model-token limits, and 192,000 retrieved characters. Fair
  first-round corroboration remains intact. Terminal runs persist only
  sanitized aggregate/per-category counters for Settings’ compact Last Run
  Details, so zero/partial outcomes reveal whether discovery, policy,
  relevance, budget, or corroboration removed candidates. Existing grants and
  schedules require revision-safe reauthorization for this expanded bounded
  authority. The authorized all-category depth run spent 16.5 seconds on all
  18 searches/72 considered results but found only off-allowlist discovery URLs
  and an unavailable skills.sh path, so it correctly made no GitHub/model calls
  and retained no finding. Final physical acceptance and milestone closeout
  remain separate. SearXNG consideration is now independently capped at 12
  results for every enabled category; Skills catalog candidates use their own
  budget and cannot borrow that allowance. A normal complete 72-result plan is
  `completed`, not partial merely because it reaches its authorized ceiling.
  Last Run Details presents the safe GitHub-hosted → canonical repository →
  queued → corroborated funnel plus truthful Skills request/candidate outcomes
  in a compact layout.
  Finding cards now lead with a safe source-derived explanation of what a
  project is, not an internal material identity; Details reads only stored
  attribution, version, risks, unknowns, and clearly labeled optional model
  interpretation. Conversation can read or clarify stored findings and may
  explicitly start the same configured bounded run, but cannot turn extra
  topic/query/URL wording into research authority. Enrichment tolerates a
  single harmless JSON fence while retaining fail-closed malformed/instruction
  handling; GitHub HTTP outcomes retain rate-limit/not-found/forbidden/server
  distinctions for safe diagnostics. Unchanged rediscovery can refresh bounded
  source-derived presentation fields without creating a material version, while
  legacy records use a truthful limited display fallback until rediscovery. A
  finding is removed from active review only after its own successful
  current-policy reassessment fails; historical state remains and is not
  rewritten as a user dismissal. Numbered/punctuated/natural named-finding
  Conversation details are resolved from stored data before generic Search,
  and conversational backend query normalization preserves the named subject.
  Physical acceptance demonstrated master/category configuration, all-category
  on-demand and nightly execution, persisted schedules/next-run display,
  Workspace visibility, fair allocation, real GitHub/skills.sh activity,
  retained advisory findings, dismissal, provider-free Conversation events,
  stored detail routing, and bounded Conversation Run Night Owl control. No
  automatic install, execution, configuration, TTS, or Discord action occurred.
  Current SearXNG/Bing quality can still yield GitHub-hosted pages that do not
  canonicalize to repositories for several categories; the durable funnel
  diagnostics make this visible, and tuning is deferred to later Research work
  rather than blocking Night Owl V1.

- **Night Owl V1 — GitHub-targeted discovery diagnostic:** The local SearXNG
  deployment's Bing upstream returned no GitHub results for `site:github.com`
  (and similarly unhelpful `inurl:`) constrained queries. The fixed literal
  `github.com` form returned GitHub-host entries, but the observed Bing results
  were root/profile forms rather than canonical projects. The
  three application-owned discovery angles for each category now use that
  compatible bounded form; within each bounded SearXNG response, already
  approved GitHub lead shapes are selected before non-GitHub hints. No user,
  transcript, model, or private text enters a query. Only allowed public repository/release/tag/commit/tree/blob lead
  forms can canonicalize to a repository for the existing GitHub API
  corroboration; profiles, issues, PRs, discussions, gists, downloads, and
  non-GitHub sources remain discovery rejections. The exact skills.sh failure
  was a DNS network error, now surfaced with a specific safe reason code.

- **Night Owl V1 — approved-source connectivity diagnostic:** Direct GitHub
  and skills.sh traffic is already limited to exact unauthenticated approved
  hosts and explicitly disables ambient proxies. The observed failure occurs
  before HTTPS in the local execution environment: its resolver configuration
  links to an absent systemd-resolved stub, so both host/Python resolution fail.
  The private-LAN SearXNG endpoint remains reachable and runs outside the
  visible execution namespace. GitHub/skills transports now distinguish DNS,
  connect, TLS, HTTP, response, and source-policy outcomes without exposing
  endpoint detail to the user. Repairing host DNS requires separate host-level
  authority; no broad egress or source-policy change was made.

- **Night Owl V1 — Slice 4 implemented, bounded advisory integrations:**
  Already-admitted findings may receive optional provider-neutral analysis from
  a closed structured input contract. The runner enforces the existing three
  calls, 32,000 input tokens, and 8,000 output tokens per run; deterministic
  findings remain valid when analysis is unavailable or rejected, and analysis
  provenance is stored separately from source-derived fields. Explicit selected
  findings can enter Capability Growth only through a typed external-research
  proposal. EXPAND is the default, IMPROVE requires a matching open operational
  friction finding, FIX is rejected, promotions are idempotent and limited to
  three per research run, and no external claim becomes `CapabilityEvidence`.
  Companion Initiative can inspect only capped finding count, opaque cohort
  digest, and oldest/newest timestamps through a read-only provider. Its new
  `night_owl_findings` type is separately default Off and inherits all existing
  interruption policy and exactly-once delivery fencing. Slice 5 now supplies
  the Settings/category/schedule controls, findings review, and stored-findings
  Conversation command; Night Owl V1 is now closed out separately from future
  research expansion.

- **Night Owl V1 — Slice 3 implemented, Scheduled Work lifecycle:**
  Scheduled Work now registers the recurring-only
  `tori.night_owl.research` capability with an immutable grant/category/source-
  policy/budget-policy snapshot. A backend service can explicitly create or
  revision-safely replace one nightly or weekly local-civil schedule, initially
  suggesting 02:00 and Sunday 02:00, with `skip_if_missed`. The capability
  revalidates current Night Owl authority before calling the same runner with a
  scheduled trigger; linked bounded results preserve Night Owl status and run
  identity. Existing Scheduled Work owns occurrence, DST, missed-run, and
  interrupted history. Scheduled overlap is recorded as
  `skipped / already_running`; manual overlap remains a bounded refusal. There
  is no default schedule or catch-up research. Slice 4 now supplies optional
  enrichment and advisory integrations; final Settings/review UI remains absent.

- **Night Owl V1 — Slice 2 implemented, explicit on-demand research seam:**
  The internal runner now admits only six fixed application query templates,
  uses configured SearXNG as discovery-only evidence, admits skills.sh only
  through its exact read-only catalog transport, and corroborates candidates
  through bounded unauthenticated public GitHub repository/release metadata.
  It revalidates the Slice 1 grant at every operation, enforces run budgets,
  treats retrieved text as inert, and persists deterministic compact findings
  with truthful zero-result, partial, and failure outcomes. There is no
  Scheduled Work registration, model enrichment, public control, Capability
  Growth promotion, or Companion Initiative delivery yet.

- **Night Owl V1 — Slice 1 implemented:**
  `docs/NIGHT_OWL_V1_ARCHITECTURE.md` now has a default-Off, owner-private
  exact-schema persistence foundation for fixed categories, durable
  category/policy/budget-bound grants, run state, compact findings and finding
  versions, deterministic relevance and material-change suppression, and
  backup guarding. Slice 2 now supplies the separate bounded on-demand research
  path; Slice 1 itself remains the offline authority/state owner.

- **Companion Initiative V1 — complete and physically human accepted:**
  `docs/COMPANION_INITIATIVE_V1_ARCHITECTURE.md` defines a default-Off,
  application-owned local Conversation check-in boundary for optional morning,
  structured resume-work, and long-silence prompts. Initiative is permission to
  speak, not permission to act: the proposal grants no Search, execution,
  Coding Work, Planning, Project, Skill, Capability Growth, Discord, filesystem,
  or remote authority. V1 uses deterministic wording, archive application-event
  provenance, durable deduplication/cooldowns, conservative busy/presence
  suppression, and a bounded process-local evaluation loop rather than
  Scheduled Work or a persistent scheduler. Exact-schema persistence,
  signals/anchors, deterministic
  delivery/recovery, one-use reply context, Settings controls, durable
  pause/dismiss, live archive reconciliation, and multi-tab presentation are
  implemented. Desktop, restart, unfocused/background delivery, active-chat
  live update, physical-iPhone/LAN presentation, Manual Speak, exact-target
  controls, and multi-chat acceptance passed. The whole feature and every type
  remain default Off.

- **Companion Initiative V2 — complete, verified, and backed up:**
  `docs/COMPANION_INITIATIVE_V2_ARCHITECTURE.md` extends the V1 store,
  evaluator, delivery, and recovery boundary instead of creating a second
  initiative system. Read-only adapters project meaningful terminal Research,
  Delegated/Coding Work, Night Owl, and Scheduled Work state into one canonical
  attention item per source object. Deterministic relevance, material keys,
  silent/gentle/conversational delivery, durable Review/Later/Dismiss state,
  bounded meaningful Morning/return briefs, and a Workspace management card
  prevent timer-only chatter and unchanged repeats. Project association is
  contextual only, and no attention path can launch work or grant authority.

- **Voice Input V1 — complete and physically accepted on desktop:**
  `docs/VOICE_INPUT_V1_ARCHITECTURE.md` records the accepted scope. Tori provides
  desktop-local microphone capture, client-local device selection, explicit
  Off/On, hold/toggle PTT, transient partial presentation, one-time fenced final
  admission through normal Conversation, Auto voice coexistence, and manual PTT
  barge-in. PTT immediately fences current speech; only a valid nonempty final
  may cancel the exact still-active generation before admission, while empty or
  failed PTT preserves useful work. Ready retains browser-local capture only and
  sends PCM solely during PTT. Off releases capture, the owned recognition runtime,
  and GPU allocation. No production environment/models are bundled or installed
  on enable; see `deploy/voice/README.md` for separate operator preparation. Wake,
  passive activation, follow-up listening, far-field guarantees, and
  mobile/HTTPS/LAN microphone capture remain separate future scopes.

- **General polish — pending human acceptance:** Explicit normal-use
  provider/model selection now persists as one non-secret application setting
  and restores on a fresh startup that has no active archived chat. Clean
  installations retain configured defaults; unavailable saved selections stay
  visible rather than falling back or being rewritten. Historical assistant
  provenance and archived-chat model semantics remain intact. Checkpoints are
  no longer a normal Web navigation, management, or command-reference
  workspace; their dormant implementation, API, data, and terminal
  compatibility remain preserved.
- **Capability Growth / Self-Improvement V1 — complete and human accepted:** A separate owner-private exact-schema Improvement Journal consolidates deterministic capability successes, friction, failures, regressions, workarounds, and opportunities; derives known-good baselines and priority-ordered FIX / IMPROVE / EXPAND findings; and retains bounded revision-safe recommendation history with immutable candidate provenance and cooldown-based duplicate suppression. The compact inventory reads native capability, Skill lifecycle, approved MCP operation, and adapter state rather than model claims. Clear local Conversation requests and the Skills & MCP view invoke one reusable bounded review service: general review covers all three lanes and at most three areas from a fixed horizon; directed review searches one topic; either admits no more than three skills.sh candidates per search and two immutable GitHub inspections overall. Empty successful discovery completes truthfully, handled research/inspection failures are partial, and active obsolete or lower-priority duplicate evidence recommendations reconcile into history without deleting evidence. The service cannot install, enable, disable, grant, execute, add integrations, edit Tori, change Memory/identity, create agents, or acquire background authority. Verified backup/restore covers the journal under a consistency guard and excludes transient research state. Night Owl now supplies separately authorized advisory discovery and may promote only through its typed explicit path; background research outside Night Owl, broader MCP administration, and general-agent workflows remain deferred.
- **Skills V1 — complete and human accepted:** The reusable manifest, immutable identity/provenance, owner-private lifecycle registry, grants, local-origin invocation, application-owned adapters, normalized results, generic capability awareness, bounded `media.inspect`, generic Agent Skills import, exact public-GitHub acquisition, skills.sh discovery, local management UI, advisory capability-gap discovery, and reusable local-stdio MCP boundary are implemented. Verified backup now snapshots the Skills registry as SQLite and immutable packages under one lifecycle/package consistency guard while excluding transient and secret state. Restore accepts only a fully reverified payload, publishes only into an absent owner-controlled Skills destination, validates registry/package digests, and disables every formerly enabled entry for local revalidation. Exact confirmed uninstall disables first, preserves the immutable manifest and registry tombstone, and deletes only the verified digest-derived managed package; unrelated user data and package code remain outside the operation. Human acceptance passed desktop direct and hard-refreshed `/skills`, truthful `media.inspect` state and lifecycle controls, skills.sh discovery, selective GitHub inspection, production installation and separate enablement of `github/github/documentation-writer`, archive/provider health after lifecycle activity, and usable populated iPhone layout. The canonical runtime intentionally contains enabled `builtin/tori/media.inspect` v1.0.0 and enabled `github/github/documentation-writer`. The official GitHub MCP Server v1.12.0 read-only profile passed disposable live `get_me` and public README acceptance through only its approved boundary using a temporary masked credential; no write tool or credential persisted. Private repositories, durable MCP credentials, arbitrary-server administration, MCP tool approval/start/stop UI, remote HTTP MCP, GitHub writes, Agent Plugins, generic executable importing, automatic updates, background learning, autonomous Skill creation, and Remote Skill administration remain post-V1 work.
- **Maintenance UI reconciliation (historical stage):** The workspace named the reminder subsystem truthfully, retained dated reminder/Scheduled Work and meaningful Coding Work visibility, and removed unfinished right-rail placeholders. A compact read-only Host card added bounded local CPU/RAM and optional GPU/VRAM telemetry. Projects & Continuity V1 and compact Planning projection were subsequently completed. The reverted generation-profile experiment has no current source/configuration integration; its proved-orphan artifact was removed under explicit authorization. Search streaming remains optional polish, not a completion gate.

- **Targeted reliability maintenance:** RAM/memory “available” questions and explicit local civil-time reminder word orders have bounded deterministic coverage and owner-reported live passes. The bootstrap copy and stopped-worker snapshot import boundaries create strict `0600` private files without changing source executables or workspace bytes/modes. Native OpenCode 1.18.21/Git tracing confirmed template hooks, read-only objects, and source-index copying; one-use pre-launch import scopes finalize only after contained writers stop. Pending/failed finalization remains a backup/workspace-reuse barrier. Backup safety failures now retain specific application errors, with private-state validation for already-owned runtimes as well as fresh ownership. The separately authorized one-time normalization corrected the fifteen identified canonical private-state modes without changing file bytes. The Workspace card now retains a browser-observed work item through its durable terminal outcome, while a fresh/reloaded browser does not present historical work as a new notice. Hard interruption before finalization remains fail-closed recovery, not an automatic historical repair. No new feature milestone is opened.

- **Maintenance repair — capability-aware orchestration:** Existing capability inventory/state now comes from one Tori-owned registry; normal generated context receives a compact projection. Web speech-act interpretation is advisory and separate from domain validation/execution. Discussion, information, actions and missing-detail clarification have explicit paths; exact commands and existing confirmation boundaries remain authoritative. Search consent continuation, RAM paraphrases, explicit Memory creation, OpenCode audit proposals and newest-first Memory presentation are repaired. This is not a new feature milestone, autonomous action chain, or general tool executor. Model-specific conversational quality still needs owner evaluation.
- **Maintenance repair — category-aware Search relevance:** SearXNG category routing remains application-owned. Weather lookup outranks only generic Planning/Today reads when a weather noun is explicit; it separates a canonical requested location from `current`, `today`, `tonight`, or `tomorrow`, preserves both through consent, asks locally when no location is available, and treats the reply as location completion rather than authorization. It uses only location-matched current or timezone-aware structured forecast evidence, displays matching multi-engine structured evidence as one state-qualified source, and applies saved Fahrenheit presentation to isolated values, ranges, and bounded qualitative decades. Versioned IT requests can make one bounded `it` → `general` fallback when exact subject/version evidence is thin; current-news selection keeps fresh dated records ahead of stale or malformed candidates. No engine selection, model reranking, external API, or attribution-boundary change was introduced.
- **Maintenance repair — durable preference routing:** Clear natural-language fact/preference directives reuse the deterministic verified Memory path rather than relying on a provider acknowledgement. Timed `Remember to …` wording stays within authoritative reminder parsing; ambiguous requests mutate neither subsystem. A verified Fahrenheit weather preference is applied only as a deterministic presentation conversion after matching structured SearXNG weather evidence, leaving evidence/provenance unchanged. No preference database, schema change, or general units framework was added.
- **Founding phase:** Complete
- **Founding documents:** Version 1.0, Accepted
- **Current phase:** Feature-complete V1 closeout; maintenance mode
- **Closeout authority:** [Current State](FINAL_STATE.md) records the current supported product and [User Guide](USER_GUIDE.md) records end-user operation. Historical roadmap entries remain evidence, not automatically approved future scope
- **Completed and human-accepted implementation milestones:** Milestone 0 through Milestone 24
- **Historical extension checkpoint:** Main-screen UI polish at `private revision omitted` followed
  completed Night Owl V1, Delegated Work / OpenCode Orchestration V1, Research
  Worker V1, MCP V1, and Companion Initiative V2. Later accepted work is
  reflected in [Current State](FINAL_STATE.md).
- **Active program:** Documentation Gate 4 precedes the remaining final closeout gates; no new feature program is active. Capability Growth / Self-Improvement V1, Skills V1,
  Night Owl V1, Delegated Work / OpenCode Orchestration V1, Research Worker V1,
  MCP V1, and Companion Initiative V2 are complete within their separate
  accepted boundaries. MCP has one exact per-machine configured,
  production-supervised Time server with only `get_current_time` approved; no
  arbitrary server, credentialed server, remote transport, or MCP write
  authority exists. Milestone 25 remains historically frozen, incomplete, and
  not separately human accepted at its preserved schema-6 checkpoint; the
  implemented bounded Project foundation remains present without converting that
  history into acceptance.
- **Historical Deep Research experiment:** **Superseded by accepted Research Worker V1.** The older audit and contract remain historical design references and accurately record why general keyless search failed. The accepted implementation instead routes identity-sensitive discovery directly through unauthenticated GitHub and Hugging Face, retains SearXNG only for broad secondary context, and preserves the previously proven containment/provider/origin boundaries.
- **Personality / Interaction V1:** Implemented as one compact, stateless, provider-neutral Tori-core boundary with initial human conversational acceptance. Live evidence found better conversational continuity, natural follow-up and curiosity, and personality without forced humor; broader situational evaluation remains evidence-driven. It guides the same Tori across relaxed conversation, active work, and serious Project/planning contexts already visible to the selected model. It adds no classifier, persona or predefined personality mode, second model call, per-turn retrieval, persistence, schema, memory mutation, or capability authority
- **Architecture recovery:** Complete after seven committed slices and a read-only exit assessment; no Slice #8 was required. Deferred debt remains visible and future extraction is evidence-driven
- **Planning / CalDAV and Reminder Bridge:** The original adapter stage implemented `PlanningService` → `PlanningPort` → `CalDAVPlanningAdapter` → Radicale plus deterministic `PlanningReminderBridge` → derived Scheduled Work delivery. Standard VTODO/VEVENT/RRULE/VALARM values, ETag revisions, external edits, one-shot alarm reconciliation, and existing application-event delivery passed its disposable real gates. At that stage no persistent deployment, UI, or conversational authority was added; these arrived later. The current compact Planning workspace, confirmed conversational operations, and local Radicale deployment are documented in [Current State](FINAL_STATE.md) and [Planning contract](PLANNING_CALDAV_CONTRACT.md).
- **Coding Work foundation:** The original Coding Work foundation remains the
  durable domain beneath the completed Delegated Work / OpenCode Orchestration
  V1 workflow. Tori owns identity, authorization, workspace protection,
  lifecycle, receipts, and controls; exact OpenCode 1.18.31 is the replaceable
  ACP worker. Conversational status/control, related follow-up with fresh
  authorization, Workspace presentation, and physical acceptance are complete.
  Pause/resume, missing-workspace preparation, GitHub access, commit/push,
  general network, generic Jobs, and autonomous coding remain deferred.
- **Permanent architecture gate:** `docs/ARCHITECTURE_GOVERNANCE.md` applies to every future milestone and capability; `docs/TARGET_ARCHITECTURE.md` defines the implementation-independent core/adapter direction. Both are subordinate to the seven founding documents
- **Milestone 7 status:** Complete at commit `private revision omitted`
- **Milestone 8 status:** Complete at commit `private revision omitted`
- **Milestone 9 status:** Complete at commit `private revision omitted`
- **Milestone 10 status:** Complete at commit `private revision omitted`
- **Milestone 11 status:** Complete at commit `private revision omitted`
- **Milestone 12 status:** Complete
- **Milestone 13 status:** Complete at commit `private revision omitted`
- **Milestone 14 status:** Complete, including the live-use corrective commit `private revision omitted`
- **Milestone 15 status:** Complete at commit `private revision omitted`
- **Milestone 16 status:** Complete at commit `private revision omitted`
- **Milestone 17 status:** Complete at commit `private revision omitted`
- **Milestone 18 status:** Complete at commit `private revision omitted`
- **Milestone 19 status:** Complete at commit `private revision omitted`
- **Milestone 20 status:** Complete and human accepted at commit `private revision omitted`
- **Milestone 21 status:** Complete and human accepted at commit `private revision omitted`
- **Milestone 22 status:** Complete and human accepted — `Complete Tori's scheduled work and initiative foundation`; canonical schemas 3/2, browserless execution, origin-bound and originless delivery, busy-state and Edit-prefill corrections, multi-browser behavior, and physical-iPhone management acceptance are complete
- **Milestone 23 status:** Complete and human accepted — `Complete Tori's model provider and context control foundation`; canonical schemas 4/1, real legacy/OpenAI-compatible Ollama acceptance, desktop visual acceptance, iPhone portrait acceptance, and final prolonged-busy desktop+iPhone transcript reconciliation all passed. Landscape remains a human-accepted non-use limitation.
- **LM Studio profile integration:** The existing generic OpenAI-compatible boundary has a separate configuration-managed `LM Studio` loopback profile at `127.0.0.1:1234/v1`. It preserves the Ollama baseline and all Tori-owned context, personality, capability, and authority semantics. Built-in local profiles are operationally editable while retaining stable identity and deletion protection; catalog failures are isolated per profile; and an optional bearer token can be replaced or cleared from Settings, stored only in an owner-private server-side file, and resolved before the existing `LM_API_TOKEN` environment reference. No token is returned to the browser, unavailable selection has no fallback, and human acceptance verified authenticated `lm_studio/gemma-4-12b-it` streaming conversation plus token persistence across a Tori restart.
- **Finance V1:** Implemented and human accepted behind `FinanceService` → `FinanceRepository` → `WorkbookFinanceRepository`, disabled by default until the user configures and confirms an external data root. Synthetic acceptance verified the seven-sheet `.xlsx` workbook, exact Decimal calculations, manual spreadsheet coexistence, content revisions, atomic verified writes, deterministic reads, revision-bound mutations, CSV preview/review/import, persisted merchant-rule reuse, same-batch duplicate handling, debt shorthand resolution, source movement, and historical trends. XML OFX/QFX is supported; legacy non-XML OFX/QFX and arbitrary PDF layouts remain fail-closed and deferred. Finance has no Finance-domain schema or workbook data beneath canonical runtime, bank connectivity, credentials, money movement, reminders, or proactive behavior; ordinary Finance conversation events use the existing Conversation archive.
- **Current repository path:** `<tori-root>`
- **Development host:** Linux; optional GPU hardware varies by installation.
- **Initial model backend:** Ollama, behind a replaceable provider interface
- **Milestone 0 commit:** `private revision omitted` — `Initialize the Tori project`
- **Milestone 1 commit:** `private revision omitted` — `Complete Tori's first running vertical slice`
- **Milestone 2 commit:** `private revision omitted` — `Complete Tori's first conversational session`
- **Milestone 3 commit:** `private revision omitted` — `Complete Tori's explicit local continuity`
- **Milestone 4 commit:** `private revision omitted` — `Complete Tori's curated local memory foundation`
- **Milestone 5 commit:** `private revision omitted` — `Complete Tori's explicit local knowledge foundation`
- **Phase I status:** Complete and human accepted — bounded public source retrieval turns authorized SearXNG candidates or explicitly supplied URLs into temporary untrusted HTML/text/Markdown evidence behind a provider-neutral port, with SSRF-safe initial/redirect validation and canonical application-owned citation/archive provenance. The final physical-iPhone test passed after a fresh Tori start through the real streamed browser path with local SearXNG, local Ollama `gemma4:12b`, and the Oobabooga GitHub installation-research request. Search profiles, folder registration, Knowledge replacement, ingestion, crawling, permanent research storage, schemas, and migrations remain deferred.
- **Milestone 6 commit:** `private revision omitted` — `Complete Tori's minimal local web conversation interface`
- **Milestone 7 commit:** `private revision omitted` — `Complete Tori's conversation character and evaluation foundation`
- **Milestone 8 commit:** `private revision omitted` — `Complete Tori's graphical management foundation`
- **Milestone 9 commit:** `private revision omitted` — `Complete Tori's streaming conversation foundation`
- **Milestone 10 commit:** `private revision omitted` — `Complete Tori's responsive web interface foundation`
- **Milestone 21 commit:** `private revision omitted` — `Complete Tori's tasks and reminders operational foundation`

---

## Completed milestone and phase history (dated checkpoints)

The following sections preserve the language and acceptance evidence of their own stage. Read their “current” and “future” wording as relative to that stage; the current product and intentional deferrals are recorded in [Current State](FINAL_STATE.md).

## Modularization Program — Phases F1–F2: Modular Frontend and Approved UI Shell

**Status:** Complete and human accepted on desktop and physical iPhone at commit `private revision omitted` (`Complete Tori's modular frontend foundation`)

Phase F1 made Settings the first view to own its rendering root, frontend state and interactions, scoped responsive styling, and existing typed API calls behind a small internal mount/refresh/unmount contract. Phase F2 builds the approved Balanced Tori interface on that seam: desktop uses compact left navigation with persistent truthful Recent Chats and compact New chat, central Conversation, and a reusable right At a glance / Workspace utility-card host; mobile uses a compact top bar with navigation/history and utility sheets rather than squeezing three columns onto the screen. Human desktop and physical-iPhone acceptance passed, including the final desktop Conversation/Workspace geometry, responsive controls, normal chat, and TTS during chat.

Settings is now a dedicated workspace with subsection navigation for Models, Model Settings, TTS / Voice, STT, Search, MCP Servers, Capabilities, Memory, Backups / Maintenance, Appearance / UI, and Advanced. Models owns existing provider/profile management; Model Settings is a navigation bridge to the existing conversation-scoped model/context controls, not the richer standalone workspace that was planned but never completed. Only existing provider/profile, conversation-scoped model/context, speech-output, search, memory-navigation, and verified-backup behavior is actionable. Unimplemented areas are explicitly unavailable. Utility cards render only existing connection/busy presentation, selected model/context, and active Project association, plus working quick actions; they do not claim fabricated metrics, updates, progress, or terminal output.

The shared shell retains view selection, responsive placement, and module mounting; Conversation retains transcript, composer, streaming, chat selection, and Conversation-local controls; Settings owns its workspace and typed API interactions; utility cards own their rendering and accept existing application state without canonical authority. No framework, bundler, browser persistence, generic plugin system, capability registry, new Settings authority, schema, or backend capability—including new TTS, STT, Search, MCP, or Memory behavior—was introduced.

These phases do not resume or modify M25. Any next capability or product phase remains separately authorized and should use the new Settings/client seam plus the accepted adapter rules, including fresh open-source evaluation before a provider implementation decision.

---

## Product Modernization — Phase G: Settings, Chat Organization, and Useful Workspace

**Status:** Complete and human accepted on desktop and physical iPhone; completion checkpoint commit pending

Phase G organizes Settings into Models, a Model Settings bridge, Voice, Search, Capabilities, Memory, Schedule & Tasks, Maintenance, Appearance, and Advanced. Existing provider management, conversation-scoped model/context access, speech and Web Search preferences, Memory navigation, operational-workspace navigation, and verified backup remain real controls. A richer standalone Model Settings workspace was not completed. STT, MCP server management, a capability registry, and appearance preferences remain explicitly unavailable. Tori identity and personality remain core-owned; no editable system-prompt field is exposed.

Canonical schema 6 already stores one revisioned mutable chat label. A bounded deterministic policy now removes greeting/filler language, uses only visible user subject text, and may replace a provisional early label such as `Just checking in` only when the next completed turn establishes a real subject. It makes no provider call and does not use or alter M24's extraction worker. Recent Chats adds revision-safe user Rename through the existing ChatService reconciliation boundary; later automatic naming does not replace a user-owned title.

At a glance adds a bounded read-only Upcoming projection sorted by canonical UTC occurrence. It shows up to six open dated Tasks, scheduled or due Reminders, and active Scheduled Work definitions with their stored civil timezone; the modular client renders local-day groupings through that timezone. Current application busy state, speech state, supervised-command state, and active Scheduled Work remain truthful activity signals, with a compact idle state otherwise. No calendar provider, canonical store, schema, migration, external dependency, or M25 behavior was added.

Human desktop and physical-iPhone acceptance passed chat creation, ordinary chat, TTS, revision-safe Rename, Recent Chat menus, Workspace cards and utility-sheet access, navigation, and the modernized Settings workspace without a major UI regression. Phase G therefore closes product preparation on the modular client; the next planned direction is capability evaluation, not additional M25 implementation.

---

## Capability Modernization — Phase I: Search Understanding and Knowledge Direction

**Status:** Complete and human accepted on the physical iPhone

SearXNG remains the current adapter behind `SearchPort`; provider profiles are deferred until another provider is useful. A separate `SourceRetrievalPort` and Tori-owned validation service retrieve a maximum of three authorized public HTML/text/Markdown sources, or up to two explicitly supplied public URLs, under strict body/text/timeout/redirect limits and public-destination validation. Retrieved content is current-turn untrusted evidence only and is never automatically promoted into Knowledge, Memory, files, or a persistent research store.

Tori assigns stable current-result source IDs and owns the mapping to canonical title, validated final URL, and retrieved/snippet-only state. Normal local-model citation forms and benign Sources/References appendices are normalized only when they bind unambiguously to those records; operational URLs inside Markdown code remain answer content, while unknown IDs and invented or stale prose/source URLs fail closed. The final physical-iPhone acceptance used a fresh Tori process, local SearXNG, local Ollama `gemma4:12b`, and the Oobabooga GitHub installation-research request; actual retrieved evidence produced a successful streamed answer with valid visible and archived provenance.

The current `KnowledgeRegistry` and `KnowledgeRetrievalPort` remain the foundation. Registrations store metadata only and grant live bounded access to one exact user-selected `.txt` or `.md` file; original files remain authoritative and removal never modifies them. Deterministic bounded passage retrieval remains separate from Search and Memory. Folder grants, semantic/vector/RAG replacement, additional formats, derived indexes, external projects, schemas, and migrations remain deferred.

---

## Milestone 0 — Project Initialization

### Objective

Create a clean, minimal, verifiable Git repository that preserves the accepted founding documents and provides a clear starting point for implementation.

### Completion Checklist

- [x] Inspect `<tori-root>` and confirm its current contents.
- [x] Confirm the seven founding documents use canonical filenames.
- [x] Confirm all founding documents identify the project as Tori.
- [x] Confirm all founding documents are Version 1.0 and Accepted.
- [x] Confirm no unintended references to the former project name remain.
- [x] Initialize Git.
- [x] Create the minimal `docs/`, `src/`, and `tests/` structure.
- [x] Place canonical founding documents beneath `docs/`.
- [x] Add `README.md`.
- [x] Add `.gitignore`.
- [x] Add `CHANGELOG.md`.
- [x] Add `docs/IMPLEMENTATION_ROADMAP.md`.
- [x] Review `git diff --check`.
- [x] Review `git status --short` before committing.
- [x] Create and verify the initial Git commit.

### Verification Record

- Initial commit: `private revision omitted` — `Initialize the Tori project`
- Branch: `main`
- Expected 13 files tracked.
- Working tree verified clean after the commit.
- External backup created before repository initialization.

**Status:** Complete

---

## Milestone 1 — First Running Vertical Slice

### Objective

Produce the smallest sensible running version of Tori:

> Start Tori locally, submit one text request through a minimal interface, route it through an abstract model-provider interface to an Ollama model, receive one response, and shut down cleanly.

### Decision Gate

The minimum decisions required for implementation are now recorded:

1. **Initial language:** Python 3.11 or newer
2. **Initial framework:** Python standard library only
3. **Initial interface:** One-request command-line interface
4. **Initial Ollama model:** `gemma4:12b`, configurable rather than hard-wired into application logic
5. **Configuration format:** `tori.toml`, with environment variables taking precedence
6. **Logging approach:** Standard-library console logging; conversation text is not logged
7. **Test strategy:** Standard-library unit tests with a mocked Ollama HTTP response, followed by one live smoke test

### Decision Rationale

- Python provides a clear implementation path for later AI, automation, data, and service integrations without requiring those systems now.
- A CLI proves the permanent conceptual conversation path without prematurely selecting Tori's long-term visual interface.
- Standard-library-only code minimizes installation complexity and avoids an unnecessary dependency decision.
- The provider contract prevents the application path from depending directly on Ollama-specific request details.
- TOML is readable by the user and supported by Python 3.11 or newer without an external parser.
- A smaller installed conversational model provides a responsive first test while remaining replaceable through configuration.
- Unit tests verify application behavior without requiring a running model; the live smoke test verifies the actual local integration.

### Implementation Checklist

- [x] Select the initial language and minimal framework.
- [x] Select the initial interface type.
- [x] Select the initial configurable Ollama test model.
- [x] Select the configuration format and precedence.
- [x] Select the basic logging approach.
- [x] Select the minimal test strategy.
- [x] Create the project-local Python virtual environment on the primary host.
- [x] Add the Python application package beneath `src/tori/`.
- [x] Add the provider-neutral model interface.
- [x] Add the Ollama provider.
- [x] Add TOML configuration loading and validation.
- [x] Add safe startup, one-request input, response output, and shutdown handling.
- [x] Add automated tests.
- [x] Run all automated tests successfully on the primary host.
- [x] Confirm the configured Ollama model is installed.
- [x] Complete one live request through Ollama.
- [x] Verify useful behavior when Ollama is unavailable or returns an invalid response.
- [x] Review `git diff --check` and `git status`.
- [x] Update the changelog and roadmap with final verification results.
- [x] Commit and verify the completed milestone.

### Explicitly Out of Scope

- Full long-term memory
- Complex orchestration
- Multiple specialist agents
- Autonomous planning
- Broad tool or terminal access
- Complete web interface
- Voice input or text-to-speech
- Final personality and identity context system
- Multi-host service distribution
- Production packaging

### Verification Standard

Milestone 1 is complete only when:

1. The automated test suite passes on the primary host.
2. Tori starts from the documented command.
3. One request reaches Ollama through the provider abstraction.
4. A non-empty assistant response is displayed.
5. The process exits cleanly.
6. A stopped or unreachable Ollama service produces a clear failure rather than false success.
7. Documentation reflects the verified implementation state.
8. The milestone commit exists and the working tree is clean.

### Verification Record

- Milestone commit: `private revision omitted` — `Complete Tori's first running vertical slice`
- Python runtime: 3.12.3
- Automated tests: 6 passed
- Ollama version: 0.31.1
- Configured model: `gemma4:12b`, confirmed installed
- Live request: completed successfully with a non-empty response
- Interactive CLI request: completed successfully
- Unreachable provider test: clear failure message with exit code `3`
- `git diff --check`: passed with no output

**Status:** Complete

---

## Milestone 2 — First Conversational Session

### Objective

Turn the verified one-request path into the smallest conversation that begins to feel like Tori:

> Start Tori locally, hold a short multi-turn text conversation within one running session, preserve the immediate conversation context, express a recognizable runtime identity aligned with the accepted founding documents, and exit cleanly.

### Intended Scope

- A multi-turn command-line conversation loop
- Session-only message history held in memory while Tori is running
- A small runtime identity context derived from the accepted founding documents
- Clear commands or input behavior for ending the session
- Clean handling of keyboard interruption and provider failure
- Automated tests for conversation history and shutdown behavior
- One live multi-turn smoke test

### Explicitly Out of Scope

- Long-term or cross-session memory
- Automatic memory creation
- Knowledge retrieval or document indexing
- Model routing
- Specialist agents
- Tool or terminal execution
- Web interface
- Voice input or text-to-speech
- Background services
- Multi-host distribution

### Accepted Decisions

1. **Runtime identity location:** `src/tori/identity.py`, separate from provider and session logic.
2. **Conversation contract:** Continue using ordered provider-neutral `ChatMessage` sequences; no Ollama-specific history logic enters the application layer.
3. **Explicit exit commands:** `/exit` and `/quit`, matched case-insensitively after trimming whitespace.
4. **Session history limit:** Retain the last 20 completed user/assistant messages in memory. The runtime identity message is always supplied separately.
5. **Failure behavior:** A failed request is not added to history. Interactive provider failures are reported honestly while leaving the session open for retry or exit.
6. **Persistence boundary:** Session messages are never written to disk by the application or logger.
7. **One-request compatibility:** A positional prompt still performs one identity-aware request and exits, while omitting it starts the multi-turn session.

### Implementation Checklist

- [x] Add the concise runtime identity context.
- [x] Add session-only conversation state.
- [x] Add bounded history retention.
- [x] Add the multi-turn CLI loop.
- [x] Add `/exit` and `/quit` handling.
- [x] Preserve one-request CLI behavior.
- [x] Keep failed exchanges out of session history.
- [x] Add automated tests for session behavior.
- [x] Run the expanded automated tests on the primary host.
- [x] Complete a live multi-turn smoke test.
- [x] Verify immediate context retention in the live session.
- [x] Verify explicit exit and keyboard interruption.
- [x] Review `git diff --check` and `git status`.
- [x] Update final verification records.
- [x] Commit and verify Milestone 2.

### Completion Standard

Milestone 2 will be complete when:

1. Tori can exchange multiple messages in one running process.
2. Later responses receive the earlier session context.
3. Tori receives a runtime identity context aligned with the accepted founding documents.
4. No session content is persisted after shutdown.
5. The user can exit intentionally and keyboard interruption shuts down cleanly.
6. Provider failure is reported honestly without pretending the response succeeded.
7. Automated tests and one live multi-turn test pass.
8. Documentation and Git history reflect the verified milestone.

### Verification Record

- Python runtime: 3.12.3
- Automated tests: 14 passed
- Live backend and model: Ollama 0.31.1 with `gemma4:12b`
- Multi-turn conversation: completed successfully
- Immediate context: Tori correctly recalled the session test word `cobalt`
- Cross-session boundary: a fresh process did not claim to remember the prior session
- Keyboard interruption: clean shutdown with exit code `130`
- One-request compatibility: completed successfully with identity-aware response
- Generated Python cache files: present locally as expected and excluded from Git

**Status:** Complete

---

## Milestone 3 — Explicit Local Continuity

### Objective

Create the first deliberate bridge between separate Tori sessions without treating every conversation as permanent memory:

> Let the user explicitly save a local conversation checkpoint, see what checkpoints exist, resume one later, and remove one when it is no longer wanted.

### Intended Scope

- Explicit user-controlled persistence only
- A small local and human-inspectable checkpoint format
- Stable checkpoint identifiers and basic metadata
- Save the current completed conversation history on request
- List available checkpoints
- Resume one selected checkpoint in a new process
- Remove a selected checkpoint
- Validate checkpoint contents before loading them
- Keep conversation text out of application logs
- Automated tests and a live save/restart/resume smoke test

### Explicitly Out of Scope

- Automatic transcript saving
- Automatic memory creation
- Inferred personal memories
- Semantic search or embeddings
- Summarization as a substitute for the original checkpoint
- Knowledge-base ingestion
- Database services
- Cloud synchronization
- Multi-user access
- Encryption or secret-management infrastructure
- Background processes

### Resolved Decision Gate

1. **Storage:** Checkpoints use the project-local, Git-ignored `runtime/checkpoints/` directory.
2. **Format:** Each checkpoint is one human-inspectable UTF-8 JSON file using schema version `1`.
3. **Names:** Machine-safe identifiers are generated from a UTC timestamp and random suffix. An optional trimmed display name is limited to 80 characters and excludes control characters.
4. **Commands:** `/save [name]` saves completed active history; `--list-checkpoints`, `--resume CHECKPOINT_ID`, and `--remove-checkpoint CHECKPOINT_ID` manage saved checkpoints.
5. **Failure behavior:** Identifiers, document shape, version, metadata, timestamps, message order, and message count are validated. Missing or invalid checkpoints fail clearly with checkpoint exit code `5`.
6. **Content boundary:** Identifier, display name, creation time, provider, model, and message count are listing metadata. Ordered user/assistant messages are transcript content and are not printed by listings.
7. **Memory boundary:** A checkpoint restores explicit conversational context only. It does not infer, curate, or create long-term memory.

### Technical Decision Record

- Checkpoints contain ordered provider-neutral `ChatMessage` content rather than Ollama-specific request data.
- Version 1 checkpoints contain at most 20 messages, matching the existing in-memory session history bound, and only complete user/assistant exchanges beginning with a user message are accepted.
- Every save creates a new checkpoint. Existing identifiers are treated as conflicts and are never silently overwritten.
- Writes use a temporary file in the checkpoint directory, flush and synchronize its contents, then replace the destination atomically. Failed temporary writes are cleaned up without damaging valid checkpoints.
- Loading fully validates a checkpoint before the application constructs a provider or begins the resumed interactive session. `ConversationSession` independently validates restored completed history at initialization.
- Listings print validated metadata only, use a clear unnamed marker, and never print transcript excerpts.
- Removal validates and deletes only the explicitly selected checkpoint.
- Saved provider and model fields are informational metadata. Continued conversation after resume uses the current validated configuration.
- Normal sessions remain in memory and create no checkpoint unless the user explicitly enters `/save`.
- Checkpoints remain structurally and conceptually separate from Tori's future long-term memory system.

### Completion Checklist

- [x] Store checkpoints beneath the ignored `runtime/checkpoints/` root.
- [x] Define and strictly validate the version 1 JSON checkpoint schema.
- [x] Generate safe identifiers and support optional constrained display names.
- [x] Save only complete active user/assistant exchanges on explicit `/save`.
- [x] Prevent failed provider requests from entering saved history.
- [x] Create new files without silently overwriting an existing checkpoint.
- [x] Write checkpoints atomically and clean up interrupted temporary writes.
- [x] List checkpoint metadata without transcript excerpts.
- [x] Load and validate a selected checkpoint before active-session creation.
- [x] Resume validated history while using the currently configured provider and model for new requests.
- [x] Remove only the explicitly selected validated checkpoint.
- [x] Preserve one-request mode, ordinary interactive mode, explicit exit, keyboard interruption, and provider failure behavior.
- [x] Add focused automated checkpoint and application coverage.
- [x] Complete the live save, list, restart, resume, remove, and no-automatic-save workflow.
- [x] Confirm no checkpoint files remained after live verification.

### Completion Standard

Milestone 3 will be complete when:

1. No conversation is persisted unless the user explicitly requests it.
2. A completed active session can be saved locally.
3. Available checkpoints can be listed without exposing unnecessary content.
4. A new Tori process can resume a selected checkpoint with prior context intact.
5. A selected checkpoint can be removed intentionally.
6. Invalid or missing checkpoints produce clear failure messages without damaging valid data.
7. Automated tests and a live save/restart/resume test pass.
8. Documentation and Git history reflect the verified milestone.

### Verification Record

- Project date: 2026-07-26
- Python runtime: 3.12.3
- Automated tests: 42 offline tests passed; the suite did not contact Ollama
- Live backend and model: Ollama 0.31.1 with `gemma4:12b`
- Explicit save: created one version 1 checkpoint containing one completed user/assistant exchange
- Listing: displayed identifier, display name, creation time, message count, provider, and model without transcript content
- File validation: identifier matched the filename, roles were ordered user then assistant, and the saved user message contained the synthetic verification token
- Cross-process resume: a separate Tori process loaded the checkpoint and correctly recalled `copper-orchid-731`
- Removal: deleted the selected checkpoint and left no checkpoint files beneath `runtime/`
- Persistence boundary: a completed ordinary session exited without creating a checkpoint
- Existing behavior: one-request and ordinary interactive paths remained operational
- Formatting before documentation work: `git diff --check` passed with no output

**Status:** Complete

---

## Milestone 4 — Curated Local Memory Foundation

### Objective

> Allow Tori to explicitly save, review, use, correct, and verifiably forget approved ordinary memories across separate processes using a Tori-owned local canonical store, while preserving normal conversation when memory is unavailable.

### Intended Scope

- A Tori-owned SQLite canonical store at `runtime/memory/tori_memory.db`
- Stable memory identifiers and exact current canonical text
- Category, ordinary sensitivity, provenance, and UTC creation/update metadata
- Explicit `/remember`, `/memories`, `/update-memory`, and `/forget` commands
- Read-back verification for creation and updates and fresh-path absence verification for deletion
- Deterministic local token-overlap retrieval for interactive and one-request conversations
- Provider-neutral, separately labeled retrieved-memory context
- Honest, non-repeating conversation degradation when memory is unavailable
- Strict separation from conversation checkpoints

### Explicitly Out of Scope

- Automatic, inferred, or natural-language-triggered memory creation
- Sensitive-memory persistence, encryption, or secret-management infrastructure
- Mem0 integration or ownership of canonical memory decisions
- Embeddings, semantic/vector search, reranking, and knowledge-base retrieval
- Automatic conflict resolution, replacement, merging, or deduplication
- Content-bearing revision history
- Changes to checkpoint semantics
- Web/API/background services, voice, agents, orchestration, and tools

### Accepted Decisions

1. **Canonical ownership:** Tori owns the canonical SQLite database. It is not a cache or derived index.
2. **Schema:** Schema version `1` stores one current row per stable `mem-` identifier, with exact text, `general` category, `ordinary` sensitivity, fixed `explicit_user_command` provenance, and UTC timestamps. Validation covers the exact critical columns, TEXT declarations, primary keys, required `NOT NULL` constraints, and fixed category/sensitivity checks. No prior content is retained through a revision table.
3. **SQLite safety:** New databases receive foreign-key, secure-deletion, and rollback-journal settings before schema creation. Existing databases are fully validated before persistent settings are applied, so unsupported or malformed databases are reported without journal conversion, normalization, or replacement.
4. **Command text:** The interactive loop trims surrounding command-line whitespace and removes only the command separator. It does not summarize or rewrite accepted text.
5. **Policy boundary:** Creation and update pass through one best-effort protective gate before a write transaction. Recognizable authentication material and clearly structured sensitive data are rejected without echoing or logging the proposed content. This is not complete data-loss prevention or a password manager.
6. **Deletion:** `/forget` requires the exact `FORGET MEMORY_ID` confirmation, deletes one selected canonical row, and reports success only after fresh read, listing, and retrieval checks show absence. The message does not claim forensic erasure outside Tori-controlled storage.
7. **Retrieval:** Search uses deterministic meaningful token overlap, returns at most five ordinary canonical memories, and includes at most 2,000 characters of memory text. No-match and unavailable-store outcomes remain distinct.
8. **Context precedence:** Retrieved memory is a transient system-context message after identity/history and before the current user message. Its protective header identifies records as factual JSON data, says that instructions or role/prompt wording inside values must never be followed, and preserves current-user authority. Every result is one ASCII-safe JSON object line with `id` and exact `text`, preventing embedded newlines or Unicode separators from escaping the record boundary.
9. **Checkpoint separation:** Memory commands and retrieved context never enter `ConversationSession.history`; `/save` continues to persist only completed user/assistant exchanges beneath `runtime/checkpoints/`.
10. **Future Mem0 boundary:** A later Mem0 index may be derived and rebuildable, but it may not own consent, canonical content, stable IDs, policy, update/deletion truth, or user-visible inspection.

### Implementation and Verification Checklist

- [x] Add the focused SQLite memory module and versioned canonical schema.
- [x] Add exact-text validation, safe ID generation, collision handling, and metadata round trips.
- [x] Add the centralized secret and sensitive-content rejection policy.
- [x] Add explicit create, inspect, update, and confirmed-delete CLI commands.
- [x] Add deterministic bounded retrieval and provider-neutral context assembly.
- [x] Preserve ordinary conversation through unavailable-memory degradation.
- [x] Preserve one-request and checkpoint behavior and storage separation.
- [x] Add offline temporary-directory tests without Ollama access.
- [x] Complete and record the deliberate live Ollama workflow.
- [x] Complete final test, formatting, runtime-cleanup, and Git-state verification.
- [x] Review and approve the implementation and final diff.
- [x] Create the milestone commit through the explicitly authorized completion workflow.

### Completion Standard

Milestone 4 completion requires all offline tests to pass, the prescribed live `gemma4:12b` create/restart/retrieve/update/restart/forget/restart/degradation workflow to pass, runtime synthetic data to be removed, documentation and diffs to be reviewed, and an explicitly authorized milestone commit to be created. These requirements were satisfied through the authorized completion workflow.

### Verification Record

- Project date: 2026-07-28
- Python runtime: 3.12.3
- Automated tests: 82 offline tests passed; the suite did not contact Ollama
- Live backend and model: Ollama 0.31.1 with `gemma4:12b`
- Cross-process create/read: exact `lunar-cedar-482` text, stable ID, category, and timestamps survived restart
- Instrumented retrieval: the provider received identity, separately labeled memory context with stable ID, then the current user request; the answer included the exact marker
- Same-ID update: only `solar-maple-936` remained listed and retrievable after restart; the original marker had no active lexical result
- Confirmed deletion: blank confirmation preserved the record; exact confirmation removed it; fresh get, list, and retrieval paths showed absence after restart
- No automatic creation: ordinary conversation left the canonical record count at zero
- Checkpoint separation: the live checkpoint contained only completed user/assistant messages and no memory command, retrieved context, or synthetic marker; it was removed independently
- Graceful degradation: a reversible unavailable-parent substitution produced one honest warning while the ordinary Ollama request still completed
- Cleanup: the restored canonical database is valid and empty; no checkpoint, journal, WAL, or synthetic record remains
- Final review corrections: JSON-lines context encoding round-trips adversarial multiline text exactly; unsupported WAL databases remain bitwise unchanged; look-alike schemas missing critical constraints are rejected without rewrite; creation/update provenance is closed internally to `explicit_user_command`
- Focused live review-fix verification: `gemma4:12b` received identity, a separate five-line data-only memory message with one decodable JSON record, and the current user request last; it used `quartz-ember-517`, then only same-ID replacement `opal-river-842`; exact-confirmed forgetting restored a valid empty canonical database

**Status:** Complete

---

## Milestone 5 — Explicit Local Knowledge Foundation

### Objective

> Allow the user to explicitly register selected local UTF-8 text documents as approved knowledge sources, inspect and remove those registrations, and ask Tori questions using relevant passages with clear source identification—without modifying the documents, converting their contents into memory, or granting broad filesystem access.

### Intended Scope

- An interface-independent local knowledge layer in `src/tori/knowledge.py`
- Explicit registration of individual regular UTF-8 `.txt` and `.md` files up to 1 MiB
- At most 25 metadata-only, schema-version-1 JSON registrations beneath `runtime/knowledge/sources/`
- Exact resolved-path access without directory crawling, discovery, copying, or source modification
- Stable `ksrc-` identifiers and verified atomic registration/removal behavior
- Live reads from authoritative source files for every ordinary request
- Deterministic paragraph and Markdown-heading passage construction with inclusive enclosing source spans
- Local lexical retrieval bounded by passage count, per-source count, and total text
- Provider-neutral data-only JSON-lines context and successful-response source transparency
- Best-effort omission of recognizable authentication-secret passages
- Honest partial and whole-subsystem degradation
- The same retrieval behavior in interactive and one-request modes

### Explicitly Out of Scope

- Directory, glob, repository, or automatic source discovery and ingestion
- Automatic knowledge registration
- Document copying, cached chunks, persistent indexes, summaries, embeddings, or model-generated metadata
- Semantic/vector retrieval, reranking, knowledge graphs, or external knowledge services
- Document creation, editing, deletion, renaming, permission changes, or synchronization
- Natural-language source-management intent detection
- Model-generated citation parsing or citation trust
- Web interfaces, APIs, background services, agents, orchestration, tools, or voice
- Mem0 integration
- Changes to canonical memory or checkpoint semantics

Document writing remains a possible future permissioned capability rather than a permanent exclusion. A web interface remains an important near-term candidate, but no subsequent milestone is selected here.

### Accepted Decisions

1. **Registry ownership and shape:** Tori owns metadata-only schema-version-1 registration JSON. Each file contains only schema version, stable ID, normalized absolute path, filename, supported file type, and UTC registration timestamp. Document contents never enter runtime storage.
2. **Exact-file authority:** Registration grants continuing read access only to one resolved path. Tori reopens that exact regular file for every request; external edits and restoration take effect without reindexing.
3. **Validation limits:** Only regular UTF-8 `.txt` and `.md` sources up to 1 MiB are accepted, with at most 25 unique resolved paths. Directories, source symlinks, non-regular files, missing/unreadable files, invalid UTF-8, unsupported extensions, oversized sources, and duplicates are rejected.
4. **Registry-root and atomic safety:** Every registry operation normalizes the configured root to an absolute lexical path without resolving symlinks, starts from a trusted root descriptor, and opens each directory component relative to its already validated parent with directory and no-follow flags. A nonexistent component is a valid empty state for reads and may be created with restrictive permissions only by registration through the same descriptor walk; an existing symlink, non-directory, inaccessible component, or traversal path is unavailable and is not repaired, replaced, or followed. Registration publishes a synchronized same-directory temporary file atomically without replacement on collision. Invalid records are strictly reported and preserved rather than silently rewritten or removed.
5. **Passage bound:** One passage contains at most 1,500 characters. This leaves comfortable room beneath the 6,000-character aggregate budget for four maximum-sized passages while allowing a fifth shorter result; it also prevents one relevant token from sending a large document section.
6. **Passage construction:** Blank-line paragraphs are natural boundaries. Markdown ATX heading context is carried with associated passages. Long blocks split deterministically at line boundaries and then fixed character offsets while retaining source line association. A heading too large to repeat safely is emitted once as bounded standalone passage text before its bounded body, preserving every nonblank source line. `line_start` and `line_end` are the smallest inclusive source span enclosing represented lines; repeated Markdown heading context means a passage need not contain every intervening line.
7. **Retrieval:** Every safe passage with at least one meaningful query-token overlap is scored by overlap count and overlapping-token character weight, then stable source ID and line range. If any candidate has at least two overlaps, candidates with only one are excluded; otherwise one-overlap candidates remain eligible. Query length alone does not set the threshold. Results are capped at five passages, two per source, and 6,000 total passage characters.
8. **Provider ordering and data boundary:** Requests contain identity, optional curated memory, optional local knowledge, prior completed history, and the current user request last. Each supplied passage is one ASCII-safe JSON object line with source ID, filename, line range, and exact passage text beneath an explicit untrusted-data header. Absolute paths are not model-facing.
9. **Secret boundary:** The existing best-effort authentication detector is shared without weakening memory policy. Inspection occurs on complete unsplit logical blocks before bounded passage selection; every chunk derived from a matching block is omitted, its value is neither echoed nor logged, and independently safe blocks remain eligible. Complete-source PEM begin/end scanning additionally protects every line across blank paragraphs and bounded chunks, with unmatched begins protected through end-of-file. If only the complete source matches another authentication pattern, relevant passages from that source are omitted conservatively.
10. **Transparency and terminal safety:** Structured passage metadata is retained for a successful turn. The CLI reports terminal-safe filenames plus either a single source line or an inclusive enclosing source span, does not imply that every intervening Markdown line was supplied, does not claim model reliance, and emits no footer for an ungrounded or failed request. Filesystem-derived filenames, paths, registry roots, invalid-record details, and footer names preserve ordinary printable values but use unambiguous ASCII escaping whenever terminal-unsafe characters occur.
11. **Separation:** Knowledge commands, registrations, raw passages, and hidden context do not create or alter memory, enter checkpoints or history, or change checkpoint/memory deletion behavior.
12. **Graceful degradation:** Missing or unsafe sources are skipped with deduplicated warnings while independent sources remain usable. Registry failure disables local knowledge honestly without unnecessarily preventing ordinary provider-backed conversation.
13. **Mem0 boundary:** Mem0 remains separate, uncalled, and unrelated to explicit document knowledge.

### Implementation and Verification Checklist

- [x] Add the focused interface-independent knowledge registry and immutable result types.
- [x] Add strict exact-file and registration-record validation.
- [x] Add atomic metadata-only registration, fresh listing, and verified removal.
- [x] Add live source reads and current availability reporting.
- [x] Add deterministic bounded plain-text and Markdown passage construction.
- [x] Add deterministic bounded lexical retrieval.
- [x] Add authentication-secret passage omission.
- [x] Add separate provider-neutral JSON-lines knowledge context.
- [x] Add interactive commands and successful-response source transparency.
- [x] Preserve one-request, identity, memory, checkpoint, history, and provider behavior.
- [x] Add temporary-directory and fake-provider offline tests.
- [x] Pass the complete offline suite without Ollama or Internet access.
- [x] Complete focused live verification with the configured local backend.
- [x] Remove all synthetic registrations, sources, checkpoints, memories, and temporary artifacts.
- [x] Update living documentation with actual results.
- [x] Complete final user review and receive explicit commit authorization.
- [x] Create and verify the authorized milestone commit.

### Verification Record

- Project date: 2026-07-29
- Python runtime: 3.12.3
- Automated tests: 141 passed in 0.116 seconds; Ollama, Pinokio, pterm, curl, and the Internet were not contacted
- Live backend and model: Ollama 0.31.1 with `gemma4:12b`
- Registration: two synthetic sources were registered across the temporary CLI with stable IDs, exact paths, available status, and sizes without displaying contents
- Cross-process retrieval: `aurora-pine-614` was supplied from `observatory notes.md` with source span 1–3; an irrelevant ordinary request produced no source footer
- Relevance correction: candidate-relative filtering preserves a clear one-token `aurora` result for natural questions while excluding the generic one-token `marker` source whenever the intended source overlaps multiple specific terms
- Multiple sources: one fresh-process request supplied bounded passages from both sources and the model returned both exact synthetic markers
- Current-file authority: external replacement with `solar-birch-948` was reflected without reindexing, and offline inspection confirmed `aurora-pine-614` was absent
- Missing source: one warning was shown across two turns while the remaining source continued to ground successful responses; restoration at the same path returned the source to available without re-registration
- Prompt-like data: offline provider inspection confirmed one JSON structural line, successful decoding, identity first, current user last, and prompt-like prose contained only in the record value
- Removal: both registrations were verified absent while final source hashes remained unchanged
- Existing behavior: ordinary interactive and one-request Ollama conversations succeeded; no automatic memory or checkpoint was created
- Focused review-correction verification: the existing system Ollama 0.31.1 service with `gemma4:12b` received the instrumented `aurora` passage for `What does the document say about aurora?`, returned `violet-cascade-417`, and produced the source footer; the stronger `aurora calibration marker` request supplied only the stronger source and excluded the source sharing only `marker`
- Final offline correction verification: component-by-component registry-root walking rejected final, knowledge-parent, and runtime-parent symlinks without changing external bytes; PEM spans protected separated, long, multiple, and unmatched private-key blocks; terminal-hostile filesystem metadata was escaped safely; and source-line transparency used inclusive enclosing spans without changing provider JSON fields
- Final correction-pass boundary: offline verification only; Ollama, Pinokio, pterm, curl, services, and the Internet were not contacted
- Cleanup: only the valid empty `runtime/memory/tori_memory.db` remains as a runtime file; knowledge and checkpoint directories are empty and no journal, WAL, SHM, symlink, temporary record, or synthetic content remains

**Status:** Complete

---

## Milestone 6 — Minimal Local Web Conversation Interface

### Objective

> Start Tori locally, open a browser, hold a multi-turn text conversation through a minimal web interface, use the same Tori identity, provider, memory, knowledge, checkpoint, and conversation behavior as the CLI, and deliberately begin a new in-memory session without automatically persisting the prior conversation.

### Intended Scope

- A replaceable standard-library local web presentation layer over Tori's existing provider-neutral application behavior
- Fixed IPv4 loopback binding at `127.0.0.1`, with default port `8765` and an optional validated port override
- One local user, one process, one shared process-level web conversation, and one provider generation at a time
- Complete-response delivery after model generation rather than streaming
- A restrained HTML, CSS, and JavaScript interface with plain-text rendering
- Browser refresh restoration from an in-memory user-visible transcript
- Explicit New Session behavior that clears only active in-memory conversation and presentation state
- Existing `/save`, curated-memory, and local-knowledge commands through one shared local-command path
- A short-lived, unpredictable, one-use, server-validated web confirmation for `/forget`
- Structured user-visible knowledge source transparency without exposing hidden context
- Focused offline application and loopback HTTP coverage using fake providers and temporary storage

### Explicitly Out of Scope

- Remote, wildcard, LAN, automatically detected, or configurable host binding
- Accounts, passwords, multiple users, independent browser-tab sessions, or remote access
- Streaming model responses, WebSockets, server-sent events, or background generation
- Automatic transcript, checkpoint, memory, or registration persistence
- Cookies, browser local storage, or disk-backed web-session state
- Rich Markdown or assistant-generated HTML rendering
- A graphical checkpoint browser or server-shutdown endpoint
- A permanent visual identity or long-term web-application framework decision
- Third-party Python packages, JavaScript frameworks, Node.js, npm, or frontend build tooling
- Changes to provider routing, memory policy, knowledge policy, checkpoint semantics, Mem0, orchestration, tools, voice, or document permissions

### Accepted Decisions

1. **Shared application path:** Web conversation uses `ConversationSession`; it does not construct provider messages, invoke the CLI, parse terminal output, or duplicate memory and knowledge retrieval.
2. **Shared local commands:** CLI and web presentation layers use one provider-neutral local-command service for explicit checkpoints, curated memory, and knowledge registrations. Commands never reach the provider or completed conversation history.
3. **Binding and port:** The server has no host override and binds only to IPv4 `127.0.0.1`. Port `8765` is the default; an explicit port must be an integer from 1 through 65535.
4. **Process-level session:** All tabs see one active process-level conversation and user-visible transcript. Refresh redraws it; process restart loses it unless `/save` created an explicit checkpoint.
5. **Concurrency:** A process-local nonblocking operation guard permits one generation or state transition at a time and clears in every success and failure path.
6. **Browser boundary:** Exact loopback `Host`, same-origin `Origin`, and a per-process anti-CSRF header are required as applicable. JSON content type, field shape, field types, and conservative body limits are enforced.
7. **Asset and rendering boundary:** Only three known packaged assets are served. The restrictive content-security policy uses separate JavaScript and CSS. User-visible values are inserted with safe DOM text operations and never rendered as assistant HTML.
8. **Confirmation:** Web `/forget` first validates the selected memory, then requires a dedicated confirmation request containing a short-lived, one-use unpredictable token tied to that target. Confirmation revalidates the target before the existing verified deletion path runs.
9. **New Session:** Clearing a non-empty session requires browser confirmation and resets only conversation history, the presentation transcript, warning state, and pending web confirmations. Persistent subsystems and source documents are unchanged.
10. **Transparency:** The browser receives structured safe filename and single-line or inclusive-source-span metadata only for knowledge supplied to a successful response. Hidden identity, retrieved-memory messages, retrieved passages, and provider payloads remain server-side.
11. **CLI preservation:** No-argument interactive CLI, positional one-request mode, checkpoint process options, resume, commands, exits, and established exit codes remain operational. `--web --resume ID` reuses the existing validated checkpoint-loading path and current configuration.
12. **Version:** Development identifiers remain `0.7.0-dev` under the established milestone convention; the completed milestone changelog entry does not create a Git tag or change the development user agent.

### Security Boundary

- Loopback-only reachability is necessary but not treated as sufficient.
- Unexpected hosts, cross-origin state changes, missing or invalid anti-CSRF tokens, malformed JSON, oversized bodies, unexpected fields, unsupported methods, query-bearing API requests, and unknown assets fail closed.
- Responses include restrictive content security, no-sniff, frame denial, no-referrer, and no-store headers.
- Request bodies, conversation text, assistant output, tokens, provider payloads, retrieved hidden context, and protected values are excluded from web logging.
- Errors shown to the browser are concise and do not expose raw exceptions, stack traces, database internals, hidden context, or provider details.
- Existing exact-source, no-follow registry, memory-content, secret-omission, checkpoint-validation, and provider boundaries remain authoritative.

### Completion Checklist

- [x] Verify the clean completed Milestone 5 checkpoint and 141-test baseline.
- [x] Add `--web` and validated `--web-port` launch behavior without changing default CLI mode.
- [x] Support validated checkpoint resume into web mode through existing loading logic.
- [x] Add the shared local-command service and preserve CLI command behavior.
- [x] Add the loopback-only standard-library HTTP server and narrow JSON API.
- [x] Add Host, Origin, anti-CSRF, request-shape, size, method, asset, and response-header protections.
- [x] Add the minimal plain-text browser conversation interface.
- [x] Add process-level visible transcript refresh and guarded New Session behavior.
- [x] Add one-at-a-time generation and state-transition protection.
- [x] Add two-step web forgetting with expiring one-use confirmation tokens.
- [x] Preserve structured knowledge transparency without exposing hidden context.
- [x] Preserve all 141 pre-Milestone 6 tests.
- [x] Add focused fake-provider, temporary-storage, and loopback HTTP tests.
- [x] Complete offline verification without Ollama, Internet, Mem0, or external services.
- [x] Finalize living documentation with the completed live-verification record.
- [x] Complete deliberate user browser and live configured-model verification.
- [x] Review the complete Milestone 6 diff and prepare it for commit.
- [x] Create and verify an explicitly authorized Milestone 6 commit.

### Verification Standard

Milestone 6 is complete and ready for its explicitly authorized repository checkpoint only after the full offline suite passes, the loopback security and shared-behavior tests pass, runtime and founding-document boundaries remain clean, the user deliberately verifies the browser with the configured local model, and the complete diff is reviewed. The final commit remains a separate user-authorized action.

### Current Verification Record

- Starting checkpoint: `private revision omitted` — `Complete Tori's explicit local knowledge foundation`
- Python runtime: 3.12.3
- Baseline: all 141 pre-Milestone 6 offline tests passed
- Current suite: 172 offline tests passed without contacting Ollama, Pinokio, pterm, curl, the Internet, Mem0, or any external service
- Local HTTP verification: ephemeral IPv4 loopback servers with fake providers verified routing, packaged assets, security headers, Host/Origin/CSRF enforcement, bounded JSON parsing, state refresh, method/path rejection, concurrency, port conflicts, and clean shutdown
- Implementation boundary: the browser server and assets use only the Python standard library and ordinary HTML, CSS, and JavaScript; serving remains fixed to IPv4 loopback, and the existing CLI remains operational
- Live browser/model verification: the user completed the approved browser workflow with the configured Ollama backend and `gemma4:12b`; ordinary and follow-up responses preserved multi-turn context, and refresh restored the visible process-level transcript without starting a new conversation
- Curated-memory verification: an explicitly created ordinary memory was retrieved in conversation, persisted across New Session, and was removed only after the required browser `/forget` confirmation
- Explicit-knowledge verification: an explicitly registered temporary Markdown source supplied the expected fact, the browser showed its filename and source location, the registration persisted across New Session, `/knowledge` listed it, and `/remove-knowledge` removed only the registration
- New Session verification: the warning and confirmation cleared only the active in-memory conversation and visible transcript; the server continued running while curated memory, knowledge registration, and the explicitly saved checkpoint remained
- Checkpoint verification: `/save` created a checkpoint visible through `--list-checkpoints`; a fresh web process resumed it through `--resume`, restored the saved conversation, and used its context correctly
- CLI and lifecycle verification: the original CLI and exit behavior remained operational; web startup reported `http://127.0.0.1:8765/`, remained loopback-only, and stopped through terminal `Ctrl+C`
- Cleanup verification: the temporary checkpoint, knowledge registration, source document, and memory were removed; runtime contains only the empty canonical memory database and its expected directories, with no journal, WAL, SHM, symlink, or synthetic verification artifact
- User-observed result: the full approved test acted as intended, with no reported functional, security, persistence, or interface discrepancy
- Milestone 6 commit: `private revision omitted` (`private revision omitted`) — `Complete Tori's minimal local web conversation interface`
- Post-commit checkpoint: verified clean with all 172 offline tests passing, the seven founding documents unchanged, and runtime containing only the valid empty canonical memory database and expected directories; no remote, push, tag, amend, or second Milestone 6 implementation commit occurred

**Status:** Complete

---

## Milestone 7 — Conversation Character and Evaluation Foundation

### Objective

> Establish a compact, provider-neutral conversational behavior foundation derived from Tori's accepted mission, identity, principles, and personality; create repeatable automated and live-browser evaluation methods; and refine Tori's behavior without adding new capabilities or prematurely designing her permanent interface.

### Intended Scope

- A noncanonical living engineering contract that translates the accepted founding documents into reviewable conversational behavior boundaries
- A stable, repeatable browser evaluation protocol with fixed scenarios, qualitative evidence, explicit cleanup, and no claim of objective personality scoring
- Deterministic offline verification of the existing runtime identity's structure, size, provider neutrality, capability honesty, and stable semantic anchors
- Stronger verification of shared provider-neutral context construction, current-user placement, hidden-context exclusion, command locality, checkpoint boundaries, and CLI/web parity
- Concise provider-neutral CLI failure presentation that preserves existing retry behavior and exit codes without exposing raw provider diagnostics
- Two neutral browser evaluation aids: explicit client-side copying of the visible transcript and clearer visible role labels
- A baseline-first refinement cycle in which the existing runtime identity is evaluated before any identity change is proposed or applied

### Explicitly Out of Scope

- Changing the runtime identity before baseline evidence is reviewed and separately approved
- New conversational, persistence, retrieval, provider, tool, file, terminal, autonomous, agent, orchestration, search, or routing capabilities
- Automatic or inferred memory, Mem0 integration, embeddings, semantic retrieval, or new knowledge formats
- Permanent interface design, visual branding, redesign, component systems, graphical management screens, rich Markdown, streaming, voice, remote access, authentication, or multiple users
- Cookies, browser storage, automatic transcript persistence, hidden-context exposure, new web routes, or weakened Host, Origin, anti-CSRF, CSP, request-validation, rendering, logging, or loopback boundaries
- Model-specific prompt techniques or behavior overfit to `gemma4:12b`
- Changes to the seven accepted founding documents

### Stage-Based Implementation Sequence

1. **Deterministic Stage 1:** Record the engineering contract and evaluation protocol; add baseline identity and context-boundary tests; normalize CLI provider-failure presentation; add the two approved browser evaluation aids; run focused and complete offline verification.
2. **Controlled live baseline:** After separate authorization, freeze the commit, configuration, model, prompts, and runtime-identity hash; run the fixed baseline scenarios once; record privacy-reviewed qualitative evidence; clean every synthetic artifact.
3. **Evidence review:** Identify repeated material weaknesses and approve only the smallest justified runtime-identity or deterministic-boundary change.
4. **Refinement:** Apply the separately approved change, rerun offline verification, and repeat the same live scenarios once with the same setup.
5. **Comparison and cleanup:** Record paired observations, regressions, limitations, and model-dependent variation; restore the clean canonical runtime state.
6. **Finalization:** Update milestone documentation and deferred version bookkeeping, complete final verification, and obtain separate authorization before creating the milestone commit.

Only one baseline and one post-change cycle are approved by default. A second refinement cycle requires later review and explicit authorization.

### Accepted Testing-Interface Additions

1. **Copy visible transcript:** One explicit client-side control may copy only visible role labels, visible message text, and visible source references as plain text. It adds no server route, request field, storage, persistence, dependency, or hidden-context access.
2. **Clearer role labels:** Visible and copied entries use `You`, `Tori`, `Local result`, `Notice`, and `Error` without changing server-side transcript roles or semantics.
3. **Immediate submitted-message presentation:** While one generation is in progress, the browser may show the submitted user message immediately and then reconcile it with the authoritative server transcript. This is nonpersistent client presentation only and does not change provider or server transcript semantics.

Completed-turn counts, scenario markers, graphical management, redesign, branding, streaming, voice, and Markdown rendering remain deferred.

### Implementation Checklist

- [x] Approve the Milestone 7 objective and boundaries.
- [x] Complete and review deterministic Stage 1.
- [x] Verify a clean, unstaged pre-live-evaluation checkpoint.
- [x] Obtain explicit authorization for the controlled live baseline.
- [x] Record baseline behavior before changing the runtime identity.
- [x] Review baseline evidence and explicitly approve the first refinement.
- [x] Apply only the approved evidence-supported first refinement.
- [x] Repeat the fixed evaluation scenarios and compare observations.
- [x] Clean all synthetic runtime and temporary evaluation data.
- [x] Finalize living documentation and deferred version bookkeeping.
- [x] Complete final offline and authorized live verification.
- [x] Create and verify the separately authorized Milestone 7 commit.

### Verification Standard

Milestone 7 is complete only when deterministic boundaries pass offline, a separately authorized live baseline precedes any runtime-identity change, any refinement is supported by reviewed evidence, the same scenarios are repeated for comparison, model-dependent and subjective limits are recorded honestly, all synthetic data is removed, the seven founding documents remain unchanged, and the final repository checkpoint is reviewed before a separately authorized commit.

### Current Verification Record

- Starting checkpoint: `private revision omitted` — `Correct Milestone 6 completion documentation`
- Baseline suite: 172 offline tests passed before Stage 1 without contacting Ollama, the Internet, Mem0, or any external service
- Runtime baseline: only the valid empty canonical memory database and expected directories; no checkpoints, knowledge registrations, sidecar files, symlinks, or synthetic data
- Deterministic Stage 1: completed and reviewed with 182 offline tests passing before the live baseline
- Controlled baseline: completed with 8 `Observed`, 4 `Concern`, and 0 `Failure` classifications; all synthetic data and temporary transcript evidence were removed
- Post-change evaluation: completed with 9 `Observed`, 2 `Concern`, and 1 `Failure`; paired outcomes were 2 `Improved`, 9 `Unchanged`, and 1 `Regressed`
- Identity decision: the experimental revision was rejected and reverted because it did not produce meaningful overall improvement without material regression; the original compact provider-neutral identity was retained and no second tuning cycle occurred
- Known limitations: model-dependent verbosity, unnecessary questioning, inference mistakes, and occasional false persistence language remain documented and are not claimed as solved
- Living documentation: added the noncanonical conversation behavior contract and repeatable paired qualitative browser evaluation protocol
- Deterministic verification: added identity structure and neutrality tests; combined context-order and authority coverage; hidden-context exclusion; CLI/web parity; command locality; browser security and persistence boundaries
- CLI presentation: provider failures are concise and provider-neutral while retry and exit-code semantics remain intact
- Browser presentation: added visible-only transcript copying, clearer visible role labels, and immediate display of submitted user messages with authoritative reconciliation
- Browser live verification: pending-message presentation worked as intended in a real browser
- Cleanup: all synthetic memory, knowledge, source, and temporary transcript data was removed; runtime returned to only the valid empty canonical memory database and expected directories
- Final offline verification: all 183 tests passed after identity rollback and finalization
- Founding documents: unchanged from accepted commit `private revision omitted`; Mem0 remained separate and untouched
- Version bookkeeping: development package and Ollama user-agent identifiers advanced to `0.8.0-dev`
- Completion commit: `private revision omitted` (`private revision omitted`) — `Complete Tori's conversation character and evaluation foundation`; parent `private revision omitted`
- Post-commit Git checkpoint: branch `main`; clean working tree; empty staging area; nothing untracked; no remote; no tag at HEAD; exactly one Milestone 7 commit after `private revision omitted`; no push or tag occurred
- Post-commit offline verification: all 183 tests passed; the seven founding documents remained unchanged from accepted commit `private revision omitted`
- Post-commit runtime verification: only the valid empty canonical memory database remained as a file; SHA-256 `[private verification digest omitted]`; integrity `ok`; schema version `1`; journal mode `delete`; memory count `0`; no checkpoints, knowledge registrations, SQLite sidecars, or runtime symlinks
- Post-commit process and external-state verification: no temporary evaluation directory; no listener on port `8765`; Mem0 remained separate and unused

**Status:** Complete

---

## Milestone 8 — Graphical Management Foundation

### Objective

> Provide a deliberately provisional, loopback-only graphical management surface through which the user can inspect and explicitly manage conversation checkpoints, curated ordinary memories, and exact local-knowledge registrations, while reusing the existing authoritative stores and preserving Tori's current conversation, permission, explicit-persistence, security, CLI, and local-first boundaries.

### Required Scope

- A separate packaged management page at `/manage`, with modest navigation to and from the existing conversation page
- Dedicated structured JSON endpoints for checkpoint, memory, and knowledge management
- One narrow typed management service shared by existing slash-command handling and graphical-management endpoints
- Structured checkpoint metadata listing, explicit current-conversation save with an optional display name, and confirmed verified removal
- Structured memory listing, explicit ordinary-memory creation, conditional editing by stable ID and expected update time, and confirmed verified forgetting
- Structured knowledge-registration listing, typed exact-path registration, live availability, and confirmed verified registration-only removal
- Target-bound, process-local, unpredictable, expiring, one-use confirmation tokens for every graphical destructive operation
- Automatic refresh of the affected collection after successful operations and a manual full refresh
- Development package and Ollama user-agent version `0.9.0-dev`
- Focused offline service, store, web, security, concurrency, rendering, and regression tests

### Explicit Exclusions

- Graphical checkpoint resume or transcript preview
- Automatic checkpoint saving, automatic or inferred memory, natural-language memory intent, Mem0, embeddings, or semantic retrieval
- File upload, file copying, native file pickers, drag-and-drop, directory browsing, source deletion, or source modification
- Additional knowledge formats, remote or LAN access, authentication, multiple users, streaming, cancellation, voice, TTS, or rich Markdown
- Browser persistence, cookies, local storage, session storage, general filesystem or terminal access, tools, agents, orchestration, or model routing
- Runtime-identity tuning, conversation-assembly changes, personality evaluation, permanent branding, or a final visual-design system

### Technical Decisions

1. `/` remains the conversation page; `/manage` is a separate provisional packaged page.
2. The browser uses structured endpoints and never parses slash-command presentation output.
3. Existing stores remain authoritative. The shared management service contains structured orchestration and safe error conversion, not HTTP, terminal, provider, prompt, or general capability logic.
4. Checkpoint save and removal receive fresh store-level verification without changing the checkpoint format.
5. Memory editing uses one atomic conditional update bound to stable ID and `expected_updated_at`, without changing schema version 1.
6. Memory confirmation targets bind action, ID, and `updated_at`; checkpoint and knowledge targets bind action, ID, and a server-side fingerprint of the freshly validated record.
7. Knowledge registration remains typed exact-path registration. The API exposes only a server-prepared safe `display_path`, not a second raw path field.
8. Existing slash commands, CLI checkpoint process options, exact CLI forgetting phrase, and startup resume behavior remain supported.
9. Graphical checkpoint resume is not included.

### Security and Concurrency Boundaries

- Fixed IPv4 loopback binding, exact Host, same-origin Origin, anti-CSRF, CSP, request-size, exact-field, safe-error, no-store, plain-text rendering, and logging exclusions remain authoritative.
- Read-only management lists may run during model generation and report `busy: true`.
- Every management mutation, confirmation, and New Session operation uses the existing nonblocking process operation lock; overlap returns the existing safe 409 busy response.
- Management operations never enter the visible transcript, completed conversation history, provider requests, or checkpoints except when completed conversation history is explicitly saved.
- Destructive confirmation tokens are invalidated before processing and cannot be cancelled, expired, substituted, changed, or reused to affect another target.
- Source contents and checkpoint transcripts are never returned by management endpoints.

### Verification Standard

Implementation became ready for deliberate live verification only after all prior tests and focused Milestone 8 tests passed offline; the founding documents, runtime identity, conversation assembly, persistence formats, CLI behavior, web security boundary, canonical runtime data, and Mem0 separation remained unchanged; the complete diff passed `git diff --check`; and the management surface contained no browser persistence, upload, picker, drag-and-drop, directory, remote, or generalized capability expansion.

Deliberate live verification was a separate user-authorized phase. It verified the three management sections, explicit and confirmed operations, stale-target behavior, multi-tab refresh, generation concurrency, New Session isolation, source preservation, and cleanup using synthetic data only. It was not authorized during the implementation pass and was subsequently authorized and completed successfully without authorizing source, asset, test, configuration, founding-document, runtime-identity, persistence-format, staging, commit, tag, remote, or push changes.

### Runtime Cleanup Requirements

The authorized live verification required removal of every synthetic checkpoint, memory, registration, source, and temporary evaluation artifact; retention of only the valid empty canonical memory database as a runtime file; integrity `ok`; schema version `1`; journal mode `delete`; memory count `0`; no SQLite sidecars or runtime symlinks; no temporary evaluation directory; no listener on port `8765`; and an untouched separate Mem0 project. Final cleanup satisfied every requirement.

### Commit Boundary

Milestone 8 implementation, packaged assets, focused tests, and required living-document updates form one reviewable change set. Runtime data and live-verification artifacts are excluded. Staging and committing require separate authorization; no amend, tag, remote, or push is part of implementation.

### Implementation Checklist

- [x] Verify the clean `private revision omitted` starting checkpoint and 183-test offline baseline.
- [x] Record the active milestone, approved boundaries, verification standard, cleanup requirements, and `0.9.0-dev` decision before source implementation.
- [x] Add and reuse the narrow typed management service.
- [x] Add checkpoint verification and atomic conditional memory-update hardening.
- [x] Add the structured management endpoints and generic typed confirmations.
- [x] Add the provisional packaged management page and preserve the conversation page.
- [x] Add focused offline tests and preserve all existing tests.
- [x] Complete final offline verification and living-document implementation updates.
- [x] Complete separately authorized deliberate live verification and cleanup.
- [x] Finalize living documentation after live evidence.
- [x] Create and verify the separately authorized Milestone 8 completion commit.

### Current Implementation Record

- Starting checkpoint: `private revision omitted` — `Correct Milestone 7 completion documentation`
- Baseline verification: all 183 existing offline tests passed before implementation; branch, Git state, founding documents, identity hashes/blob, runtime database, Mem0 separation, and port state matched the approved checkpoint
- Shared behavior: added a narrow typed management service used by slash-command handling and structured web management without adding a general capability or orchestration layer
- Checkpoint hardening: successful saves freshly reload and validate the new checkpoint; successful removals freshly verify absence; the version 1 format and startup resume path remain unchanged
- Memory concurrency: added atomic conditional update and deletion by stable ID and expected `updated_at`, with distinct stale-target failure and unchanged schema version 1
- Web API and confirmation: added structured read and mutation routes plus action/ID/version-or-fingerprint-bound one-use confirmation targets; management operations remain transcript-, history-, provider-, and log-excluded
- Browser management: added the packaged provisional `/manage` page with manual and affected-section refresh, safe plain-text rendering, typed paths only, and no upload, picker, drag-and-drop, directory browsing, polling, browser storage, or graphical resume
- Conversation preservation: `/` retains immediate submitted-message presentation, authoritative transcript reconciliation, Copy Transcript, New Session, existing slash commands, and the current confirmation flow
- Version bookkeeping: development package and Ollama user agent advanced to `0.9.0-dev`; no Git tag was created
- Corrected offline verification: all 220 tests passed before and after the live run; both packaged JavaScript syntax checks and `git diff --check` passed; founding documents, runtime identity, persistence formats, and Mem0 separation remained unchanged
- Live verification: completed successfully with Ollama 0.31.1, configured `gemma4:12b`, and Tori bound only to IPv4 `127.0.0.1:8765`; both `/` and `/manage` served successfully without wildcard, IPv6, LAN, or remote binding
- Cleanup: all synthetic checkpoints, memories, registrations, and temporary source data were removed; Tori stopped normally; no port `8765` listener, runtime symlink, SQLite sidecar, or temporary verification directory remained; Mem0 was separate and unused
- Completion commit: `private revision omitted` (`private revision omitted`) — `Complete Tori's graphical management foundation`; parent `private revision omitted` on `main`

**Status:** Complete

### Completion Commit Record

- Branch remained `main`; exactly one commit was created after `private revision omitted`, with the expected parent and subject.
- Post-commit verification found a clean working tree, empty staging area, nothing untracked, no remote, no tag at HEAD, and no push.
- All 220 offline tests passed after the commit; both packaged JavaScript syntax checks and `git diff --check` passed.
- The seven founding documents, runtime identity, conversation assembly, and version 1 checkpoint, memory, and knowledge formats remained unchanged; package version and Ollama user agent remained `0.9.0-dev`.
- Runtime remained logically empty and clean: `runtime/memory/tori_memory.db` was the only runtime file, with SHA-256 `[private verification digest omitted]`, integrity `ok`, schema version `1`, journal mode `delete`, and memory count `0`.
- No checkpoint, knowledge registration, SQLite sidecar, runtime symlink, temporary verification directory, or port `8765` listener remained. Mem0 remained separate and unused.

### Deliberate Live Verification Record

- **Conversation regression and empty state:** Immediate submitted-message display, visible generation state, exactly one visible user entry, completed-response display, active in-session continuity, and the absence of automatic checkpoint, memory, or knowledge persistence were verified. Empty management sections, Refresh All, page navigation, the typed-path field, and the absence of graphical resume, upload, picker, drag-and-drop, and directory browsing were also verified.
- **Checkpoints:** Explicit save with an optional display name, metadata-only listing, cross-tab refresh, cancellation, confirmed removal, no transcript preview or mutation, and active-conversation preservation passed.
- **Memories:** Explicit creation, structured metadata, stable identifiers, preserved creation time, advanced update time, conditional editing, stale-tab rejection, sensitive-value rejection without retaining the rejected value, cancellation, confirmed forgetting, and cleanup passed.
- **Legacy `/forget`:** A memory changed after confirmation issuance was not removed; its updated value remained authoritative; stale confirmation and token reuse failed without appending rejection entries to the visible transcript; fresh graphical removal succeeded.
- **Knowledge:** Exact typed-path registration, safe metadata, retrieval and source attribution, cancellation, registration-only removal, and the absence of source content on `/manage` passed. The temporary source remained unchanged with SHA-256 `[private verification digest omitted]` until its separate cleanup.
- **Knowledge availability:** A temporarily absent source remained registered and became unavailable; restoring its exact path returned it to available without re-registration. Tori did not repair, replace, delete, or modify the source or registration automatically.
- **Concurrency and New Session:** Read-only management refresh remained available during generation; a mutation was rejected as busy and created no memory; generation continued without transcript or history corruption; the same mutation succeeded afterward and was cleaned up. New Session cleared active transcript and in-memory conversation while preserving checkpoint, memory, and knowledge data, and invalidated a pending confirmation before fresh cleanup.
- **Browser observations:** The user observed no broken navigation, duplicate entries, lost input, permanently disabled controls, stuck dialogs, wrong confirmation targets, unrecoverable stale lists, clipping, unreadable text, trapped focus, unsafe behavior, or incorrect success claims. The interface remains provisional and replaceable rather than a final visual design.
- **Nonblocking interruptions:** The Codex/server process was interrupted and restarted, so its prior process-bound CSRF token was correctly rejected; testing continued with the new process token. An accidental unsupported `/remove` message entered ordinary conversation, invoked no management removal, and changed no persistent data; the intended graphical workflow subsequently passed. `/remove` is not a supported slash command.
- **Final runtime:** Cleanup left `runtime/memory/tori_memory.db` as the only runtime file, with integrity `ok`, schema version `1`, journal mode `delete`, memory count `0`, and SHA-256 `[private verification digest omitted]`. The physical hash differs from the pre-live hash because supported SQLite create, update, and delete operations occurred; it does not represent leftover logical data.

---

## Milestone 9 — Streaming Conversation Foundation

### Objective

> In the provisional browser conversation interface, an ordinary model-generated response appears progressively as plain text, then reconciles to exactly one authoritative completed assistant message after successful generation.

### Intended Scope

- A narrow provider-neutral ordered text-fragment iterator while preserving the complete-response provider method
- True Ollama streaming chat with validated line-delimited JSON, safe provider errors, and deterministic resource closure
- One transactional `ConversationSession` streaming operation that reuses the established identity, memory, knowledge, history, and current-user assembly path
- One authenticated same-origin `POST /api/message/stream` route returning flushed newline-delimited `delta`, `complete`, or `error` JSON events
- One temporary browser assistant draft rendered only with safe text DOM operations and reconciled to the authoritative transcript on completion
- Existing process-level concurrency, security, privacy, explicit-persistence, CLI, management, slash-command, source-transparency, and New Session behavior
- Development package and Ollama user-agent version `0.10.0-dev`
- Focused offline provider, conversation, web application, loopback HTTP, browser-parser, security, failure, closure, and regression tests

### Explicit Exclusions

- Stop or explicit model cancellation, WebSockets, server-sent events, polling, a second server, or a framework
- Voice, speech recognition, TTS, streaming TTS, Mem0, SearXNG, web search, or any other external service
- Automatic or inferred memory, natural-language memory intent, embeddings, semantic retrieval, or persistence-format changes
- Tools, capabilities, general filesystem access, terminal execution, document writing, agents, orchestration, or model routing
- Remote or LAN access, authentication, multiple users, graphical checkpoint resume, uploads, picker, drag-and-drop, or directory browsing
- Rich Markdown, model-generated HTML, browser storage, cookies, permanent branding, final interface redesign, or founding-document/runtime-identity changes

### Technical Decisions

1. `ModelProvider.stream_chat` yields ordered provider-neutral text fragments. The existing `chat` method remains the complete-response path for the CLI and existing callers.
2. Ollama streaming uses the same `/api/chat` endpoint, validated messages, configured model, timeout, and keep-alive with `stream: true`; it does not simulate streaming from a complete response.
3. `ConversationSession.send` and `ConversationSession.stream` share one request-preparation method, preserving identity first, optional memory, optional knowledge, completed history, and current user last.
4. Streaming history commits only after provider completion and a nonempty accumulated assistant response. Failure, malformed termination, empty completion, or iterator closure commits nothing.
5. The browser stream uses UTF-8 NDJSON over one same-origin authenticated POST. `delta` contains one new text fragment; `complete` contains the safe authoritative transcript; `error` contains a concise safe failure and authoritative visible transcript state.
6. The browser draft is presentation state only. It is excluded from the authoritative transcript used by Copy Transcript, refresh, persistence, and other tabs until successful completion.
7. Existing local slash commands continue through the complete local request path. Unsupported slash-prefixed prose remains ordinary model conversation and can stream.
8. The existing operation lock covers the complete stream. Explicit closure handles success, provider failure, malformed streams, browser write failure, disconnect, abandoned iteration, and even closure before the first event.

### Security, Privacy, and Concurrency Boundaries

- Fixed IPv4 loopback, exact Host, exact same-origin Origin, per-process CSRF, restrictive CSP, frame denial, no-sniff, no-referrer, no-store, exact JSON fields, required JSON content type and Content-Length, 64 KiB request limit, query rejection, method rejection, packaged-asset allowlisting, and plain-text rendering remain unchanged.
- Conversation text, stream fragments, complete responses, request bodies, security tokens, hidden context, provider payloads, absolute source paths, and raw diagnostics remain excluded from logs and safe browser errors.
- A stream owns the existing nonblocking process operation lock. Second generation, management mutation, confirmation, and New Session operations are rejected as busy; read-only management lists remain available and report busy state.
- Ordinary streaming conversation creates no checkpoint, memory, knowledge registration, transcript file, browser storage, or other persistence automatically.

### Implementation and Offline Verification Record

- Starting checkpoint: `private revision omitted` (`private revision omitted`) — `Correct Milestone 8 completion documentation`; parent `private revision omitted` on `main`
- Starting state: clean worktree, empty staging, no untracked files, no remotes, no tags at HEAD, no port `8765` listener, logically empty canonical runtime, and all 220 existing offline tests passing
- Provider implementation: true incremental Ollama NDJSON parsing with ordered Unicode/escaped fragments, empty-fragment tolerance, explicit error/malformed-shape/premature-end rejection, normalized HTTP/transport failure, and response closure on success, error, and abandonment
- Conversation transaction: shared assembly, progressive yielding, commit after valid provider completion only, 20-message bound, hidden-context exclusion, safe source metadata, and no commit on failure, empty completion, or iterator closure
- Server and browser: flushed same-origin authenticated NDJSON, safe terminal errors, authoritative transcript reconciliation, one optimistic user entry and one temporary assistant draft, split-record and streaming UTF-8 decoding, final-buffer handling, strict event validation, source timing, and terminal cleanup
- Concurrency: second generation, mutation, and New Session rejection; read-only list availability; operation-lock release on provider failure, abandonment, disconnect/write failure, and pre-iteration closure
- Offline verification: all 240 tests passed using fake providers, temporary stores, and ephemeral IPv4 loopback fixtures without contacting Ollama, the Internet, Mem0, SearXNG, TTS, or another external service
- Static verification: both packaged JavaScript syntax checks and `git diff --check` passed
- Version bookkeeping: package version `0.10.0-dev`; Ollama user agent `Tori/0.10.0-dev`; no tag created
- Runtime and identity: the seven founding documents, runtime identity hashes/blob, version 1 persistence formats, and logically empty canonical runtime remain unchanged
- Live status: separately authorized deliberate live Ollama/browser verification and cleanup completed successfully
- Pre-completion Git status: no staging, commit, amend, tag, push, remote configuration, or history change had been authorized or performed during implementation and verification

### Deliberate Live Verification Record

- **Backend and browser:** Ollama 0.31.1 with configured `gemma4:12b`, Tori bound only to IPv4 `127.0.0.1:8765`, and headless Firefox 152.0.6 controlled through temporary loopback-only Geckodriver
- **Progressive transport:** One ordinary request returned HTTP 200 `application/x-ndjson` without `Content-Length`; eight ordered deltas began at 6.118 seconds and completed at 6.225 seconds, then reconciled to one matching authoritative assistant entry
- **Real browser behavior:** Firefox observed a temporary assistant draft while controls were disabled, 160 distinct increasing draft lengths, final reconciliation to exactly one user and one assistant entry, restored controls, `Connected locally`, and no visible error
- **Continuity and refresh:** A streamed follow-up recovered the prior `indigo` marker, produced four ordered transcript entries, and matched the authoritative session returned by refresh
- **Concurrency:** A real 642-delta generation retained the operation lock; management reads remained available with `busy: true`, competing generation and New Session returned `409 busy`, the original response completed, and no rejected prompt or memory entered state
- **Failure safety:** A separate Tori process configured to an unreachable loopback provider emitted one safe terminal error, disclosed no provider address, committed no model exchange, reconciled on refresh, and released its lock without stopping or altering Ollama
- **Source transparency:** One synthetic registered Markdown source supplied `cedar-lantern-731`; deltas contained only text, source filename and line range appeared only in authoritative completion, and no absolute path was exposed
- **Regression:** The unchanged non-streaming CLI path returned the exact requested complete response through the configured backend
- **Process note:** One accidental terminal `Ctrl+C` interrupted the live-verification process. The verification environment was reestablished, the final coherent verification run and cleanup passed, and no repository or persistent-runtime damage resulted.
- **Cleanup and final verification:** The synthetic registration and source were removed, transient conversation state was cleared or discarded on shutdown, Tori/Firefox/Geckodriver were stopped, and ports 4444/8765/8766 had no listener. All 240 offline tests passed again; JavaScript syntax and `git diff --check` passed. Runtime retained only the canonical memory database with integrity `ok`, schema version `1`, journal mode `delete`, zero memories, and original SHA-256 `[private verification digest omitted]`.
- **Boundary:** Pinokio's configured control plane was unreachable, so the installed system Firefox/Geckodriver path was used. No Internet, Mem0, SearXNG, TTS, remote service, source mutation beyond the removed synthetic file, staging, commit, tag, remote, or push was used.
- **Completion commit:** `private revision omitted` (`private revision omitted`) — `Complete Tori's streaming conversation foundation`; parent `private revision omitted`
- **Completion checkpoint:** Exactly one Milestone 9 completion commit was created. All 240 tests passed after the commit, both packaged JavaScript syntax checks passed, the founding documents and runtime identity remained unchanged, all persistence formats remained version `1`, the runtime remained logically empty, and the working tree was clean. No remote, push, tag, amend, or second implementation commit occurred.

**Status:** Complete. Implementation, offline verification, separately authorized deliberate live verification, cleanup, final evidence review, complete-diff review, completion commit, and post-commit verification passed. No Milestone 10 or later milestone is selected.

---

## Milestone 10 — Responsive Web Interface Foundation

### Objective

> Replace Tori's provisional browser presentation with a polished, responsive, modular interface foundation using charcoal and graphite foundations, gunmetal and steel surfaces, restrained metallic depth, selective dark glassmorphism, brighter blue and violet accents, and distributed ambient illumination, while preserving conversation as the central interface and retaining every established conversation, streaming, persistence, management, security, and local-first boundary.

### Intended Scope

- One packaged semantic application shell with Conversation, Checkpoints, Memories, and Knowledge as the only visible primary destinations
- Preserved direct entry at `/` for Conversation and `/manage` for Checkpoints, with management hashes and same-origin History API view navigation
- A small presentation-only `ui.js` module for routing, shared safe DOM/request helpers, status/busy presentation, and accessible dialog focus behavior
- A mobile-first design-token system, responsive navigation, safe-area and dynamic-viewport support, touch-friendly controls, long-content handling, and comfortable layouts down to approximately 320 CSS pixels
- Improved plain-text conversation, streaming-draft, status, transcript-following, and composer presentation without changing authoritative conversation behavior
- Focused responsive checkpoint, memory, and knowledge views reusing the established structured endpoints and explicit management semantics
- Semantic landmarks, visible focus, labelled forms and dialogs, deliberate live regions, reduced-motion behavior, and practical high-contrast support
- Development package and Ollama user-agent version `0.11.0-dev`
- Offline structural, responsive, accessibility, security, conversation, management, and regression coverage

### Explicit Exclusions

- LAN or remote access, authentication, HTTPS deployment, multiple users, or any weakening of loopback, Host, Origin, CSRF, CSP, request-validation, or logging boundaries
- Automatic chat saving, saved-chat browsing, graphical checkpoint resume, automatic checkpoint, memory, or knowledge persistence, or new persistence formats
- SearXNG, web search, TTS, audio, voice input, terminal execution, file writing, general filesystem access, capabilities, permission execution, or model cancellation
- Mem0, embeddings, model routing, orchestration, autonomous action, rich Markdown, arbitrary HTML, external resources, frontend dependencies, package managers, frameworks, or build steps
- Uploads, file pickers, drag-and-drop, directory browsing, source editing or deletion, browser storage, cookies, service workers, telemetry, or analytics
- Founding-document, runtime-identity, conversation-assembly, provider-contract, domain-operation, or persistence-format changes

### Technical Decisions

1. The Python standard-library backend and packaged ordinary HTML, CSS, and JavaScript architecture remain. No frontend framework, dependency, package manager, or build step is introduced.
2. `/` and `/manage` serve the same shell. `/` defaults to Conversation; `/manage` and `/manage#checkpoints` select Checkpoints; `#memories` and `#knowledge` select their corresponding implemented views.
3. Ordinary same-origin anchors remain valid. With JavaScript available, History API navigation changes the visible shell view without reconstructing the DOM, preserving unsent input during ordinary view and responsive changes; Back and Forward synchronize the selected view.
4. `ui.js` remains presentation-only. The server and existing endpoints remain authoritative for conversation, checkpoints, memory, and knowledge; no client-side state store or persistence is added.
5. `manage.html` is retired only because both direct routes now serve the tested shared shell. The explicit packaged asset allowlist expands only for `ui.js`.
6. Conversation continues to render untrusted content as plain text. One temporary assistant draft is not an assertive live region; a separate concise status region announces generation lifecycle changes.
7. Transcript following occurs only when the reader is already near the bottom, so progressive output does not forcibly displace a reader reviewing earlier content.
8. Checkpoint, memory, and knowledge operations reuse their existing endpoints, confirmation targets, operation lock, optimistic concurrency, source-preservation rules, and explicit-persistence boundaries without schema changes.

### Completion Checklist

- [x] Implement the shared responsive shell, four implemented destinations, direct-route defaults, and History API navigation.
- [x] Implement the presentation-only `ui.js` module, responsive visual system, accessible conversation presentation, and focused management views.
- [x] Preserve conversation, streaming, CLI, management, explicit-persistence, provider, endpoint, operation-lock, security, and local-first boundaries.
- [x] Pass initial offline implementation and static verification.
- [x] Complete separately authorized comprehensive live verification and cleanup.
- [x] Record and classify the long-content shell defect without broadening domain or security scope.
- [x] Complete the narrow CSS-only correction and focused responsive contract tests.
- [x] Complete user visual review, the CSS-only visual-direction correction, focused visual-contract tests, and user acceptance.
- [x] Pass final offline, static, live correction, runtime-cleanup, documentation, and complete-diff verification.
- [x] Create and verify the separately authorized Milestone 10 completion commit.

### Implementation and Verification Record

- Starting checkpoint: `private revision omitted` (`private revision omitted`) — `Correct behavior contract streaming statement`; parent `private revision omitted` on `main`
- Starting state: clean worktree, empty staging, no untracked files, remotes, or tags at HEAD; logically empty canonical runtime; no listener on ports 4444, 8765, or 8766; all 240 existing offline tests passing
- Shared shell: semantic header/navigation/main/section structure, skip link, exactly four implemented destinations, direct-route defaults, hash selection, History API synchronization, active `aria-current`, and no visible unavailable controls
- Presentation module: shared CSRF request setup, safe text-element construction, status/error/busy utilities, view visibility, accessible dialog labelling, focus placement, and focus restoration without duplicating domain authority
- Responsive system: semantic charcoal, graphite, gunmetal, steel, warm-text, blue, cyan-blue, violet, and functional-status tokens; distributed ambient illumination; restrained metallic gradients and edge depth; selective dark glassmorphism with prefixed backdrop filtering and opaque fallbacks; mobile-first density; bottom mobile navigation; restrained desktop rail; 100vh/100dvh sizing; safe-area insets; long-content wrapping; touch targets; reduced motion; and forced-colors accommodation
- Conversation presentation: one semantic non-live transcript log, concise lifecycle status, unchanged optimistic user entry and temporary assistant draft, authoritative reconciliation, proximity-aware following, responsive composer, and plain-text source display only on completion
- Management presentation: one focused checkpoint, memory, or knowledge view at a time; stacked responsive forms and records; labelled confirmations; preserved stale-memory messaging, typed exact paths, source preservation, explicit saves, and confirmed removals
- Endpoint and domain boundary: no route schema, management service, command, conversation assembly, provider contract, persistence implementation, operation-lock, or permission change
- Initial offline verification: all 247 tests passed, including the 240-test baseline, using fake providers, temporary stores, and ephemeral IPv4 loopback fixtures without contacting Ollama, Firefox, Geckodriver, the Internet, Mem0, SearXNG, TTS, or another external service
- Static verification: `app.js`, `manage.js`, and `ui.js` passed Node syntax checks; `git diff --check` passed
- Comprehensive live environment: Python 3.12.3, Ollama 0.31.1 with configured provider `ollama` and model `gemma4:12b`, Firefox 152.0.6, and Geckodriver 0.36.0 on fixed IPv4 loopback only
- Comprehensive live results: direct routes and management hashes, Back/Forward navigation, active-view semantics, unsent-input preservation, 205 progressive draft observations, UTF-8, authoritative reconciliation without duplicates, completion-only sources, visible-only copying, refresh restoration, checkpoint/memory/knowledge workflows, keyboard/dialog behavior, operation-lock concurrency, controlled provider failure and recovery, security rejection boundaries, and cleanup passed
- Initial live defect: long conversation content expanded the document rather than a bounded transcript and displaced mobile navigation below long content. The defect was presentation-only and did not affect domain behavior, persistence, endpoint meaning, conversation authority, or security.
- CSS root cause and correction: minimum viewport heights left the shell content-sized, while intermediate grid minimums prevented shrinking. A narrow stylesheet-only correction added ordered `height: 100vh` and `height: 100dvh`, shrinkable shell/workspace/view boundaries, transcript-owned vertical scrolling, management-owned scrolling, and a persistent mobile-navigation track without changing HTML or JavaScript.
- Bounded-shell verification checkpoint: 9 focused asset tests and all 249 tests passed; `app.js`, `manage.js`, and `ui.js` passed syntax checks; `git diff --check` passed
- Corrected desktop measurements: at `1440 × 900`, document/shell height remained 900 and transcript client/scroll height was 489/4,155; at `1024 × 768`, document/shell height remained 768 and transcript client/scroll height was 359/4,453. Composer and navigation remained visible with no horizontal overflow.
- Corrected compact/mobile measurements: at `844 × 390`, shell height remained 390 and transcript client/scroll height was 37/4,155; at true `500 × 568`, shell height remained 568 and transcript client/scroll height was 138/6,387. Navigation remained in the bottom shell track without composer overlap or horizontal overflow.
- Transcript-follow and management growth: across 216 progressive real-stream observations, near-bottom following tracked the draft while a reader scrolled away remained undisturbed; completion reconciled once with correct UTF-8 and no duplicate. At `500 × 568`, the management view used a 507/13,738 client/scroll-height boundary while the document and navigation remained stable.
- Environment limitation: exact true `390 × 844` and `320 × 568` widths were unavailable because the installed Firefox environment enforced a 500-CSS-pixel minimum. No scaled substitute or physical-device result is claimed; the limitation is accepted as nonblocking, and structural tests cover the approximately 320-pixel responsive foundation.
- User visual review concern: after the bounded-shell correction, the interface still appeared predominantly blue, flat, insufficiently metallic, weak in visible glass treatment, too muted in blue/violet accents, and concentrated ambient color mainly in one corner.
- Accepted visual-direction correction: a second CSS-only presentation pass changed only `styles.css` and `test_web_assets.py`, neutralizing the canvas and navigation, adding gunmetal and steel hierarchy, distributed ambient sources, layered metallic gradients, fine edge and recessed depth, selective dark glassmorphism, `backdrop-filter` and `-webkit-backdrop-filter`, opaque and `@supports not` fallbacks, and stronger selected-navigation and primary-action accents. No layout, conversation, endpoint, persistence, or security behavior changed.
- Final visual and automated verification: five structural visual-contract tests were added; all 14 focused asset tests and all 254 offline tests passed; all three JavaScript files passed syntax checks; and `git diff --check` passed. True CSS viewports `1440 × 900`, `1024 × 768`, `844 × 390`, and `500 × 568` retained the bounded shell, internal transcript and management scrolling, visible navigation and composer, no overlap or horizontal overflow, unsent-input preservation, real progressive streaming, authoritative reconciliation, New Session cleanup, and no automatic persistence.
- User visual decision: the user inspected and accepted the current visual foundation for Milestone 10. It remains evolvable rather than Tori's permanent final design; additional visual refinement is deferred unless explicitly selected in future work.
- Cleanup: all synthetic checkpoints, memories, registrations, sources, conversation state, and temporary artifacts were removed; Tori, verification Firefox, and Geckodriver were stopped; no verification listener, SQLite sidecar, or runtime symlink remained; the canonical runtime remained logically empty and valid
- Runtime and identity: the seven founding documents and runtime identity remained unchanged, memory/checkpoint/knowledge formats remained version 1, package and Ollama user-agent versions remained `0.11.0-dev`, and the canonical database retained integrity `ok`, schema `1`, journal mode `delete`, zero memories, and SHA-256 `[private verification digest omitted]`
- Completion commit: `private revision omitted` (`private revision omitted`) — `Complete Tori's responsive web interface foundation`; parent `private revision omitted`
- Post-commit Git checkpoint: branch `main`; clean tracked working tree; empty staging area; no remotes; no tag at HEAD; no push
- Post-commit verification: all 254 offline tests passed; `app.js`, `manage.js`, and `ui.js` passed JavaScript syntax checks; the seven founding documents remained unchanged
- Milestone selection: Milestone 11 remains unselected

**Status:** Complete. Implementation, offline verification, comprehensive live verification, bounded-shell correction, accepted visual-direction correction, cleanup, final documentation reconciliation, complete-diff review, completion commit, and post-commit verification are complete.

---

## Milestone 11 — LAN Web Access and Real-Device Verification Foundation

### Objective

> Make Tori's existing web interface automatically reachable from ordinary IPv4 LAN browsers, including the user's physical iPhone, while retaining loopback access, preserving one process-level shared session and existing application behavior, and deliberately verifying the Milestone 10 responsive interface on real hardware.

### Selected Decisions

- Normal `--web` startup uses one IPv4-only standard-library listener bound to `0.0.0.0`; it never presents `0.0.0.0` as a browser URL.
- Default port `8765` and the existing validated `--web-port` override remain authoritative. There is no host override, second server, IPv6 listener, background service, reverse proxy, or host-selection setting.
- Loopback remains supported. Numeric private or link-local IPv4 URLs are the only supported LAN form for this milestone; hostnames, mDNS, custom DNS, HTTPS names, and reverse proxies are out of scope.
- By explicit user decision, LAN access currently has no login or authentication and uses unencrypted HTTP. Authentication and TLS remain future decisions.
- A LAN on/off toggle remains deferred. Starting with `--web` may expose the process automatically to permitted direct IPv4 LAN clients; the later bounded Settings page does not expose LAN or security configuration.
- All connected browsers share one process-level in-memory conversation and one mutation/generation boundary. There is no multi-user, per-device, or per-tab isolation.
- Conversation, checkpoint, memory, and knowledge persistence remain explicit. No transcript is archived automatically.
- The shared responsive shell includes a fifth informational Commands destination at `/commands`. It documents supported browser slash commands and separate terminal checkpoint options without adding executable controls, guided execution, or graphical checkpoint resume.
- Unsupported command-shaped slash input is rejected deterministically as a local result. A narrow ASCII token definition excludes path-shaped and embedded slash text so normal filesystem discussion remains provider-visible.

### Retained Boundary

- Browser Host is accepted only when it contains the active port and exactly `localhost` or a syntactically valid IPv4 literal classified by `ipaddress` as private, loopback, or link-local. `0.0.0.0`, public IPv4, IPv6, arbitrary names, user-info, malformed ports, control characters, prefix/suffix tricks, and ambiguous values are rejected.
- State-changing requests require exactly one `Origin` equal to `http://` plus the already validated request Host. Missing, `null`, HTTPS, multiple, mismatched, arbitrary, malformed, or user-info Origins are rejected.
- The unpredictable per-process anti-CSRF token remains independently required.
- Because the current architecture is a direct server without proxy support, the socket peer is deterministically restricted to IPv4 loopback, private, or link-local addresses. No forwarded header is trusted. This is not claimed to prevent router forwarding, NAT exposure, VPN exposure, hostile LAN access, or every network threat.
- CSP, no-sniff, frame denial, referrer restriction, no-store responses, conservative body limits, exact JSON shapes/types, fixed routes/assets, query rejection, unsupported-method handling, safe plain-text DOM rendering, and no conversation-text logging remain unchanged.
- No cookie, local storage, session storage, service worker, external script/font/style/asset, automatic persistence, or frontend dependency is introduced.

### Startup Presentation

- Startup always shows `http://127.0.0.1:PORT/`.
- Local hostname resolution is queried through standard-library IPv4 facilities only. Unique non-loopback private or link-local candidates are displayed as numeric LAN URLs; no Internet service, shell command, unrelated system file, persistence, or dependency is used.
- If no displayable candidate is found, the listener still starts and Tori honestly asks the user to use the host's private or link-local IPv4 address without inventing one.
- Startup states that LAN access is unauthenticated and unencrypted HTTP, that Tori does not configure router/firewall/Internet exposure, and that all connected browsers share one process-level conversation.

### Explicit Exclusions

No authentication, TLS, certificate, settings page, LAN toggle, automatic conversation saving, saved-chat browser, graphical checkpoint resume, multi-user support, browser persistence, stop control, voice, search, terminal/filesystem capability, orchestration, Mem0, model routing, IPv6, hostname/mDNS support, reverse proxy, Docker, systemd, router configuration, port forwarding, UPnP, firewall change, Internet-exposure mechanism, dependency, or visual redesign is part of this milestone.

### Implementation and Verification Checklist

- [x] Bind one server to all IPv4 interfaces while retaining loopback and existing port validation.
- [x] Add filtered, honest startup address presentation and explicit LAN security/session guidance.
- [x] Replace fixed-loopback Host/Origin assumptions with strict request-specific LAN-aware validation.
- [x] Add the deterministic direct IPv4 peer boundary without proxy assumptions.
- [x] Preserve the shared conversation, streaming, management, New Session, explicit persistence, rendering, storage, and CLI behaviors.
- [x] Advance package and Ollama user-agent versions to `0.12.0-dev`.
- [x] Add focused offline tests and update living engineering documentation.
- [x] Add the static Commands destination, direct route, fifth responsive navigation item, shared registry, and deterministic unknown-command boundary after initial physical-device review.
- [x] Complete the required 269-test offline suite, JavaScript syntax checks, `git diff --check`, security review, and runtime cleanup record.
- [x] Complete reported desktop and physical-iPhone verification of numeric LAN and loopback access, portrait/landscape layout, all five destinations, the shared conversation, unsent-input preservation, and local unknown-command behavior.
- [x] Correct the reported mobile label wrapping while retaining all five full labels, the Checkpoints meaning, established touch-target height, and overflow boundaries; re-verification passed on the tested iPhone.
- [x] Review the complete implementation and reconcile the living documentation before requesting completion-commit authorization.
- [x] Obtain separate authorization, create exactly one Milestone 11 completion commit, and pass post-commit verification.

### Completion and Verification Record

- Starting checkpoint: `private revision omitted` (`private revision omitted`) — `Correct Milestone 10 completion documentation`; parent `private revision omitted` on `main`
- Implementation: one IPv4-only all-interface listener, filtered startup presentation, strict request-specific Host and Origin validation, direct-peer validation, preserved anti-CSRF and browser boundaries, informational Commands destination, deterministic unknown-command handling, path-shaped input preservation, and five-destination responsive navigation
- Live verification: the `tori-web` launcher, host loopback, and numeric IPv4 LAN access worked from an ordinary terminal and Firefox on an iPhone 13 Pro on the same network. Portrait and landscape layouts, all five destinations, shared desktop/iPhone conversation state after refresh, unsent-input preservation across Commands navigation, and deterministic local `/checkpoints` rejection passed.
- Presentation correction: initial mobile label wrapping was corrected without renaming Checkpoints or reducing the touch target; all five full labels then fit on one line on the tested phone without reported horizontal overflow or unreachable navigation.
- Completion commit: `private revision omitted` (`private revision omitted`) — `Complete Tori's LAN access and real-device verification foundation`; parent `private revision omitted`
- Post-commit verification: all 269 offline tests passed; `app.js`, `manage.js`, and `ui.js` passed JavaScript syntax checks; the seven founding documents and runtime identity remained unchanged.
- Post-commit Git checkpoint: branch `main`; clean tracked working tree; empty staging; nothing untracked; no remote; no tag at HEAD; no push.
- Runtime cleanup: only the valid empty canonical memory database remained as a regular file, with integrity `ok`, schema version `1`, journal mode `delete`, and zero memories; no checkpoint, knowledge data, SQLite sidecar, runtime symlink, Tori process, or port `8765` listener remained.
- At the Milestone 11 completion checkpoint, authentication, TLS, LAN settings, command dropdowns, guided execution, graphical checkpoint resume, multi-user isolation, and automatic conversation archiving were deferred.
- Milestone selection: no Milestone 12 has been selected.

**Status:** Complete. Implementation, offline verification, physical-device verification, corrective review, cleanup, completion commit, and post-commit verification passed.

---

## Milestone 12 — Automatic Conversation Archive and Resume Foundation

### Objective

Establish a local persistent conversation archive, separate from curated memory, explicit checkpoints, and knowledge, so ordinary conversations are archived automatically and can be listed, opened, resumed, started fresh, or explicitly deleted.

### Completed scope

- Added a schema-version-1 standard-library SQLite archive at `runtime/conversations/tori_conversations.db`, with complete validated transcript entries, safe metadata-only listings, provider/model history metadata, revisions, and one durable active-chat pointer.
- Added a provider-neutral chat service with stable safe errors, listing, full retrieval, completed-history reconstruction, create/reconcile, atomic open-and-select, new-session clearing, and revision-checked deletion.
- Integrated successful CLI one-request and interactive turns with automatic create/reconcile persistence. Added `--list-chats`, `--resume-chat`, `--remove-chat`, and `--new-chat`; saved model metadata remains informational and resumed generation uses current configuration.
- Advanced the development package and Ollama user-agent versions to `0.13.0-dev`.
- Integrated the browser lifecycle with automatic persistence, process-start active-chat restoration, metadata-only Archived Chats listing, explicit open/resume, genuinely new conversation creation, explicit deletion, safe archive errors, and unchanged operation-lock/security boundaries.
- Defined one active lifecycle: completed transcript state is persisted before transitions; `open_chat` alone records opening and selects atomically; `new_session` clears the durable pointer only after persistence; deleting the active chat clears both durable and in-memory active state. `select_chat` remains a narrow service primitive and is not sequenced separately by the web lifecycle.
- Preserved visible system/warning/error entries and structured safe knowledge-source references in browser archives. Only completed ordinary user/assistant exchanges become model history, bounded by the existing 20-message rule.

### Initialization race correction

First initialization is built under an unpredictable same-directory isolated name. A fully initialized, validated, fsynced database is published with Linux `renameat2(RENAME_NOREPLACE)`. Publication cannot overwrite or remove an entry inserted at the canonical path. If initialization or publication fails, the isolated artifact is preserved for inspection rather than risking pathname cleanup; a later safe initialization can retry normally. Existing databases and main/sidecar symlinks remain no-follow and are never repaired, overwritten, or wildcard-cleaned.

### Boundaries and non-goals

Archive contents are ordinary conversation continuity, not curated memory, a checkpoint, or local knowledge. Listing responses expose metadata and a derived label but no assistant transcript preview; full content is returned only by the explicit session/open response. No archive text enters logs or browser storage. Authentication, TLS, synchronization, multi-user accounts, transcript search, memory extraction, Mem0, model routing, external service, production dependency, or visual redesign was added.

### Verification status

- Focused store, service, CLI, application, HTTP, browser-asset, race, lifecycle, retry, failure-safety, and regression tests use temporary storage.
- The adversarial production-boundary test substitutes the canonical entry with a symlink immediately before publication and verifies the symlink, external target, and isolated owned database are preserved, the operation fails safely, and retry works after the replacement is deliberately removed.
- Python and JavaScript syntax validation, the complete offline suite, founding-document comparison, read-only runtime integrity inspection, `git diff --check`, and the canonical `./scripts/verify-milestone` command are required before handoff.
- Final offline verification passed all 338 tests, all three JavaScript syntax checks, read-only parsing of every project Python file, both diff checks, all seven HEAD-based founding-document comparisons, and canonical memory SQLite integrity/hash inspection through `./scripts/verify-milestone`.

**Status:** Implementation complete and uncommitted; ready for human review and separate commit authorization.

---

## Milestone 13 — Manual Model Selection and Model Catalog Foundation

### Objective

Give the user direct, durable control over the local provider/model used by each conversation while establishing a provider-neutral, objective model-catalog boundary for later curated metadata, evaluation, routing, and orchestration work.

### Implemented scope

- Added provider-neutral `ModelIdentity`, `ModelDescriptor`, catalog result/error, identifier validation, deterministic ordering, and cached explicit-refresh behavior. Descriptors support provider/native identifier, display name, availability, family, parameter size, quantization, storage size, modification time, and bounded provider-supplied objective metadata.
- Extended Ollama with read-only `/api/tags` normalization and request-specific exact-model chat/stream invocation while retaining the established timeout, keep-alive, headers, streaming validation, and IPv4-loopback boundary. Malformed, duplicate, unavailable, or mismatched-model responses fail safely; no model mutation endpoint exists.
- Advanced the development package and Ollama user-agent versions to `0.14.0-dev`.
- Added CLI `--list-models` and `--model`, plus interactive `/models`, `/model`, and `/model MODEL` behavior. Catalog failure remains safe; known-unavailable selections block generation without fallback.
- Added browser active-model presentation, an accessible selector, one initial bounded catalog load, explicit refresh, same-origin model APIs, pending-change exclusion, open/reload synchronization, safe errors, and per-assistant provider/model labels using text-only DOM construction.
- Made the selected model a request-specific conversation property. The actual provider/model stays attached to each completed assistant archive entry, so mid-conversation changes preserve cross-model history without rewriting transcript content.

### Archive compatibility decision

Milestone 13 deliberately keeps the Milestone 12 archive schema at version 1. Its existing validated `latest_provider` and `latest_model` conversation metadata now serve as the durable current selection, while immutable per-assistant `provider` and `model` fields remain the actual-generation history. Changing selection uses the existing revision-checked metadata-only reconciliation transaction: transcript entries are asserted unchanged, the conversation revision/timestamp advances atomically, and the selected identity is freshly verified. Therefore every valid Milestone 12 archive opens without a destructive migration; its last recorded provider/model becomes its initial durable selection. Unsupported future schema versions and malformed records continue failing closed without replacement.

With no active archived chat, a fresh process uses the configured default. A selection made for a new in-process conversation is used when its first completed turn creates the archive. Opening/resuming replaces the process selection with the archived selection. New Session and active deletion clear only active-chat/transcript state and keep the current process selection coherent for the next chat; a later fresh process with no active chat returns to configuration. Failed selection leaves both durable and in-memory state unchanged.

### Boundaries and non-goals

The catalog reports objective provider facts only. It does not infer capability, quality, personality fit, coding ability, reasoning ability, or tool support from names. Tori's accepted identity and runtime identity remain authoritative even though underlying models may express them with different quality. The visibility and cross-model history support deliberate human comparison only.

No automatic routing, orchestration engine, recommendations, personality scoring, benchmarking, response judging, hidden secondary model, answer rewriting, model download/pull/copy/delete, conversation branching, second production provider, dependency, polling loop, public-network operation, or visual redesign is included.

### Verification status

Focused catalog, Ollama adapter, configuration, archive/service, application/CLI, browser application/HTTP, and asset tests use fakes, temporary stores, and loopback-only ephemeral HTTP. The final gate passes all 358 offline tests, read-only Python parsing, all three JavaScript syntax checks, founding-document comparison, read-only canonical runtime inspection, and both diff checks through `./scripts/verify-milestone` plus the explicit final `git diff --check`.

**Status:** Implementation and offline verification complete and uncommitted; ready for human review and separate commit authorization.

---

## Accepted Technical Decisions

The following decisions are inherited from the accepted founding documents and implementation kickoff:

- Tori is local-first and user-controlled.
- Conversation is the permanent conceptual interface.
- Tori's identity is independent of any model.
- Models and model backends must be replaceable.
- Ollama is the first backend, not a permanent architectural dependency.
- The user remains the final authority for meaningful actions.
- Capabilities should operate with least privilege.
- Execution must be verified before success is claimed.
- Memory and knowledge are separate responsibilities.
- The repository is the durable source of implementation state.
- The project should advance through small, usable milestones.
- The primary host is sufficient for the first implementation milestone.
- Docker is not required for the initial implementation.
- New infrastructure and directories require a current, concrete purpose.

### Milestone 1 Decisions

- Python 3.11 or newer is the initial implementation language.
- Milestone 1 uses no third-party Python runtime dependencies.
- The first interface is a one-request CLI, not the permanent user interface.
- `tori.toml` is the initial configuration file.
- Environment variables override corresponding TOML values.
- `gemma4:12b` is the initial configured test model and is replaceable.
- Conversation text is not written to logs.
- Ollama-specific HTTP behavior remains inside the Ollama provider.

### Milestone 2 Decisions

- Runtime identity lives in `src/tori/identity.py`, separate from provider and session state.
- Ordered provider-neutral chat messages remain the conversation contract.
- `/exit` and `/quit` intentionally end an interactive session.
- Session history retains the last 20 completed user/assistant messages.
- Failed requests never enter conversation history.
- Session messages are not written to disk or application logs.
- Omitting a positional prompt starts an interactive session; supplying one preserves one-request behavior.

### Milestone 3 Decisions

- Saved conversations require an explicit `/save`; normal sessions are never persisted automatically.
- Versioned, human-inspectable JSON checkpoints live beneath the ignored `runtime/checkpoints/` directory.
- Checkpoint loading is strictly validated before a resumed active session is created.
- Listings expose metadata rather than transcript excerpts, and removal targets one selected checkpoint.
- Saved provider and model fields are informational; resumed continuation uses the current configuration.
- Conversation checkpoints restore context but remain separate from future long-term memory.

### Milestone 4 Decisions

- SQLite is the accepted Tori-owned canonical memory store; future Mem0 indexing, if approved, must remain derived and rebuildable.
- Only explicit, ordinary, general-category memories are accepted in this milestone.
- Creation and update provenance is fixed internally to `explicit_user_command`; callers cannot supply arbitrary provenance.
- Memory content is limited to 2,000 characters and protected by centralized best-effort secret and sensitive-data rejection.
- Retrieval is local, lexical, deterministic, limited to five records and 2,000 characters, and subordinate to the current user statement. Model-facing records use one ASCII-safe JSON object line each under an explicit data-only header.
- Existing databases are validated completely before persistent PRAGMAs are applied; version 1 requires the exact critical types, keys, nullability, and category/sensitivity checks.
- Conversation continues without retrieved memory when the store is unavailable, with one concise warning per session.
- Canonical memory and saved conversation checkpoints remain separate storage systems with independent deletion.

### Milestone 5 Decisions

- Local knowledge registration is explicit, exact-file scoped, metadata-only, and separate from curated memory and checkpoints.
- Source documents remain authoritative and read-only; Tori creates no copied document store or persistent retrieval index.
- Plain-text and Markdown passages are constructed locally with a 1,500-character per-passage bound and source line association.
- Lexical retrieval is deterministic and capped at five passages, two per source, and 6,000 total passage characters.
- Model-facing passages use a separate ASCII-safe JSON-lines data message; the current user remains authoritative and absolute paths are excluded.
- Recognizable authentication-secret passages are omitted through the shared protective predicate without weakening memory persistence policy.
- Source transparency comes from structured application metadata, not model-generated citation claims.
- The CLI is a temporary surface; knowledge registration, status, retrieval, and context construction remain interface-independent.

---

## Milestone 14 — Explicit Local Web Search and Source Attribution Foundation

### Implemented decision

Tori now has one small provider-neutral capability boundary and one production adapter: bounded structured JSON search through the administrator-configured local SearXNG endpoint. Every execution requires either an explicit `/search QUERY` or conservatively recognized natural-language request, or a current conversation's unexpired proposal followed by a bounded affirmative response. Pending proposals are intentionally process-local and are cleared by restart or conversation lifecycle changes.

Search results are normalized as untrusted source data and supplied only to the active selected model for one answer. The application validates citation numbers and constructs the visible `Web findings` and `Sources` framing from actual normalized records. Schema-version-1 archives use an additive validated envelope in the existing optional source-metadata column, read legacy source arrays unchanged, preserve query/status/title/URL attribution, and never rerun a search on resume.

The post-milestone corrective pass retains this architecture while accepting a bounded set of semantically equivalent source-ID presentations from selected models. Every accepted marker is canonicalized against the normalized result set; missing, unknown, malformed, model-authored source-list, and model-authored URL output still fails before an assistant commit, and the application remains the sole source of visible titles and URLs. The same pass extends the existing proposal classifier only for explicit freshness language covering volatile prices, availability/in-stock state, releases/versions, rosters/personnel, office holders, schedules, and news/developments. It creates the established structured consent proposal when available, reports disabled/unavailable search truthfully, never treats model output as authority, and executes a confirmed exact query once.

Ordinary questions remain on the existing single selected-model generation path. An exact, whole-response, application-recognized external-knowledge advisory may replace an inadequate model answer with the existing structured proposal, but the advisory is hidden control data, carries no query or execution authority, and is rejected when mixed, malformed, echoed from the current user request, or returned after search context has already been supplied. The application binds any valid proposal to the original request and existing conversation/expiry rules. Search transport, service, configuration, and response failures now share a safe capability-level presentation, commit no assistant findings, perform no stale model fallback or retry loop, and leave later ordinary conversation and later explicit search usable.

### Explicit boundaries

- The only approved initial endpoint is the administrator-configured private-LAN SearXNG instance; chat cannot select an endpoint.
- No result webpage is opened, rendered, downloaded, executed, crawled, or recursively searched.
- No search result is automatically promoted to curated memory or registered knowledge.
- No silence, broad sentiment, model-generated proposal, or website snippet authorizes execution.
- No autonomous research, tool routing, chaining, orchestration, settings UI, API credential, benchmarking, purchasing, or background work is implemented.
- Tests inject transports and temporary stores; live SearXNG verification is deliberately not required.

**Status:** Complete, including the live-use corrective commit `private revision omitted`.

---

## Milestone 15 — Local Streaming Text-to-Speech Output Foundation

### Implemented decision

Tori now owns a provider-neutral transient text-to-speech presentation boundary. The first adapter targets the administrator-configured local Qwen/faster-qwen3-tts service at the single approved endpoint and voice. The backend validates and queues only speech-safe text that has crossed the same user-visible normalization boundary as browser deltas; browsers receive ordered base64 PCM records from Tori's authenticated same-origin API and never contact or learn the upstream URL.

Automatic speech begins at the first useful natural boundary while later model text continues to stream. Sentence punctuation is preferred, with paragraph and bounded strong-clause/whitespace fallbacks for long prose and a final unterminated flush. One upstream generation runs at a time per active session. The browser schedules 24 kHz mono signed-16-bit PCM with Web Audio so already-generated audio can play while later speech is produced. Completed assistant transcript entries can be replayed, and Stop Speaking clears browser audio, queued text, and the active upstream stream without cancelling model generation or changing the transcript.

Text remains canonical. Generated PCM, speech queues, and session identifiers are process/browser-transient and are never stored in conversation archives, checkpoints, memory, knowledge, or `runtime/`. Loading or resuming history never auto-speaks it. TTS timeout, connection, HTTP, malformed-audio, cancellation, and per-segment failures terminate speech with concise secondary feedback while the model stream, completed assistant response, and archive remain valid.

### Explicit boundaries

- Qwen is the first replaceable provider; no automatic provider routing or arbitrary URL selection exists.
- Speech consumes approved visible answer prose, not raw provider tokens, hidden reasoning, tool output, advisory markers, system context, status records, or application-owned source URLs.
- Search synthesis remains whole-response validated before speech because source attribution is an authoritative response transform.
- Automatic speech is an in-memory browser preference, not the project's future settings system.
- No STT, microphone, wake word, VAD, saved audio, speech history, voice-profile manager, emotion inference, or TTS-host modification is implemented.
- Automated tests use injected providers and temporary stores; the canonical runtime remains read-only.

Audible human acceptance confirmed incremental speech timing, speed, quality, ordered playback, Automatic Speech, replay, Stop Speaking, and the overall TTS interaction. A focused acceptance correction decouples composer editability from the existing busy-turn submission boundary: model and speech activity no longer disable or erase the textarea, an edit revision preserves even an intentionally emptied busy-time draft during transport-error recovery, and Send remains disabled and guarded until the active turn completes. No TTS architecture, persistence, navigation, settings, or concurrent-turn behavior changed.

**Status:** Complete at commit `private revision omitted` (`Complete Tori's local streaming text-to-speech foundation`), including audible human acceptance and the focused composer correction.

---

## Milestone 16 — Local Settings and Capability Control Foundation

### Implemented decision

Tori now provides a small application-owned Settings destination for the durable Web Search, Speech Output, and Operator Activity Log preferences. A typed schema-versioned SQLite store at `runtime/settings/tori_settings.db` is separate from conversation archives, checkpoints, curated memory, knowledge, model selection, and infrastructure configuration. An absent database or absent override preserves the accepted behavior, with Operator Activity Log defaulting on; read-only access or application startup does not create or migrate the store. The schema-1 settings record is accepted read-only and migrates transactionally to schema 2 only on an explicit protected setting mutation.

Administrator TOML/environment configuration remains authoritative. Effective availability is the conjunction of administrator permission and the user's preference: the user may disable an allowed capability or re-enable one they previously disabled, but cannot enable a capability the administrator has disabled or not configured. Provider endpoints, implementations, voices, timeouts, credentials, LAN/security configuration, filesystem paths, and arbitrary keys remain outside ordinary Settings. The browser cannot rewrite `tori.toml`.

The Settings page and typed same-origin API expose administrator permission, user preference, and effective state for exactly the two current controls. State-changing requests retain the existing Host, exact-Origin, anti-CSRF, content-type, size, and request-shape protections. Unknown fields, wrong types, malformed data, and unsupported operations fail deterministically. A failed write does not update the presented authoritative state. A malformed or unreadable existing store fails optional controlled capabilities closed with application-owned presentation while ordinary text conversation remains usable; Tori never repairs, replaces, or deletes such a store automatically.

Web Search disablement gates explicit `/search`, explicit natural-language search, freshness proposals, confirmation of existing proposals, and model-insufficiency advisories before any SearXNG request. Re-enabling restores the existing consent, validation, attribution, and status behavior without restart when administrator configuration permits it. Speech Output disablement gates manual replay and Automatic Speech before any upstream synthesis, leaves text streaming intact, and stops current browser speech after successful persistence. The browser-local Automatic Speech preference is neither persisted in the settings database nor erased by global Speech Output changes.

### Explicit boundaries

- Settings contain exactly the two typed non-secret preferences; there is no arbitrary key/value editor, capability registry, plugin framework, or general permissions system.
- Settings do not contain endpoints, providers, secrets, credentials, voices, model selection, conversation state, or Automatic Speech.
- No backups, restore, Open Terminal, generic execution, STT, microphone, wake word, VAD, routing, orchestration, page retrieval, deep research, or additional provider was added.
- Existing search consent/source integrity and transient TTS ordering, same-origin streaming, Web Audio activation, iPhone playback-session behavior, cancellation, and no-audio-persistence boundaries remain intact.
- Automated persistence and capability tests use isolated temporary paths; the canonical runtime is not created or mutated by implementation verification.

**Status:** Complete at commit `private revision omitted` (`Complete Tori's settings and capability control foundation`).

---

## Milestone 17 — Verified Tori Backup Capability

### Implemented decision

Tori now owns one narrow disaster-recovery action under Settings → Maintenance. `Back Up Now` always snapshots the physical `<tori-root>` project into the fixed external `<backup-root>` root; neither the browser, chat, environment, nor the durable Settings store can choose a source, destination, filename, command, exclusion, or backup option. Production startup and read-only latest-backup inspection do not create the destination. The explicit button may create only that bounded root when absent.

Each attempt receives a timestamp plus collision-resistant identifier and builds beneath a clearly non-final `.Tori_...incomplete` directory. The payload lives in `project/`; application-owned proof lives in a versioned `manifest.json`. Complete source and staged inventories cover ordinary hidden files, empty directories, `.git`, `.venv`, runtime content, file and directory modes, and symlinks as link-target strings. Directory-descriptor and no-follow traversal prevents source symlinks or swapped parent directories from becoming traversal roots. Defined transient rollback journals are subsumed by the self-contained online database snapshot rather than copied as independent files. An unexpected WAL/SHM sidecar or a journal with an unsafe object type fails before database access rather than risking source mutation or inventing unsupported handling. Other special filesystem objects, known-database symlinks, unsafe roots, collisions, source inventory/type changes, ordinary-file mutation, copy/write errors, manifest errors, and any verification mismatch fail without publication. Failed staging evidence remains non-final and no older backup is changed or removed.

Defined memory, conversation, and settings SQLite stores are captured through Python's online backup API into their logical project-relative destinations. The sources are opened read-only without VACUUM, journal-mode changes, checkpoints, migration, repair, replacement, or cleanup. Each destination database must pass `PRAGMA integrity_check` before overall success. Ordinary files are opened without following symlinks, checked by stable source identity/size/time/mode before and after capture, hashed during capture, and compared by destination SHA-256 and size. A second complete source inventory must remain stable; live changes to defined SQLite database files are intentionally exempt from ordinary-file metadata stability because the online API supplies the consistent snapshot.

Before publication, Tori verifies exact payload membership, object types, modes, file sizes and hashes, symlink targets, SQLite integrity, counts, total regular bytes, manifest correspondence, and the two-entry staging structure. Only then does one same-filesystem rename publish `Tori_YYYYMMDD_HHMMSS_<unique-id>/`. The manifest records schema/version, timestamps, fixed source and final paths, development version, safely available Git HEAD, complete relative inventory, modes, sizes, hashes, targets, SQLite results, counts, byte total, and verified status. Git tree identity is recorded as unavailable rather than inferred when it cannot be obtained without extra complexity.

The parameterless protected HTTP action retains Host, exact same-origin Origin, anti-CSRF, content-type, body-size, and exact empty-object shape enforcement. One backup-specific nonblocking process lock rejects a concurrent second request without starting another copy while leaving ordinary conversation boundaries independent. Settings shows fixed destination, in-progress presentation, concise safe failure, and latest verified completion time, directory, approximate size, and verification state. Restart discovery is read-only, bounded to the fixed root, ignores malformed/unrelated content, validates manifest structure and counts, and never creates, rewrites, or deletes anything.

### Explicit boundaries

- Backups are separate from settings preferences, conversation archives, checkpoints, curated memory, knowledge, model selection, Web Search, TTS, and model/provider execution.
- The milestone adds no restore, deletion, retention, pruning, schedule, automation, compression, encryption, remote transfer, arbitrary path, CLI backup command, conversational dispatch, terminal access, generic filesystem capability, job framework, action registry, or permission framework.
- Automated tests inject temporary project, backup, runtime, and SQLite paths. They do not touch canonical runtime or `<backup-root>`.
- The implementation is append-only and intentionally leaves failed non-final attempts and all older completed backups untouched.

**Status:** Complete at commit `private revision omitted` (`private revision omitted`) — `Complete Tori's verified backup capability`. No production backup was created during implementation verification.

---

## Milestone 18 — Safe Action Execution Contract Foundation

### Implemented decision

Tori now owns one small provider-independent action contract for the fixed `tori.backup` action. Its application-owned definition supplies the stable ID, human-readable purpose, Interactive permission class, empty-argument validator, fixed `BackupService.create_backup` executor, and deterministic structured outcome. The dispatcher has no registration API and accepts no caller-selected action IDs beyond its fixed definition, paths, commands, executors, callables, environment changes, or backend functions.

An explicit Settings click or recognized current-user conversation imperative causes application code to validate an empty argument object and issue one opaque, single-use authorization bound to the exact action, validated arguments, and invocation source. Dispatch consumes that exact grant before execution. Missing, replayed, altered, cross-action, unknown-action, invalid-source, and invalid-argument invocations fail closed. No blanket or durable authorization is stored.

Settings → `Back Up Now` now reaches the existing Milestone 17 backup service only through this dispatcher. The browser conversation paths recognize exactly the supported explicit forms `Tori, run a backup.`, `Run a Tori backup.`, `Back up Tori.`, and `Please back up Tori.` with case, whitespace, and final period/exclamation normalization. Both complete and streaming conversation paths execute the same `tori.backup` definition before any provider request. Application-authored presentation records the resulting verified identifier/location only after structured success and reports failure without completed wording when the executor fails.

Advisory questions, tentative discussion, unsupported execution requests, ordinary model prose, JSON or fenced tool-shaped output, provider tool channels, model-created IDs, and executable strings provide no authorization. Existing provider-response containment remains in place, and the action system never asks a provider to select, validate, dispatch, execute, verify, or determine the outcome of an action.

### Explicit boundaries

- Only the bounded Interactive `tori.backup` action is implemented; the Informational, Advisory, Interactive, and Persistent concepts are named, but no generalized Persistent storage or permission manager exists.
- There is no shell, terminal, arbitrary filesystem/path/command execution, user/model action registration, plugin system, chaining, planning loop, agent/orchestration system, background/scheduled action, retry, cancellation, rollback, restore, backup deletion/pruning, or durable generalized audit history.
- Focused tests use temporary project and backup roots and cover fixed registration, fail-closed arguments/actions, exact single-use authorization, cross-action isolation, success/failure outcomes, shared Settings/conversation execution, explicit recognition, ambiguity, unsupported requests, and model-generated tool-shaped containment.

**Status:** Complete at commit `private revision omitted` (`private revision omitted`) — `Complete Tori's safe action execution contract foundation`.

---

## Milestone 19 — Native Supervised Command Execution Foundation

### Implemented decision

Tori now recognizes only the exact leading `/run COMMAND` path as a command-execution request. Natural-language suggestions to run, check, or execute something remain ordinary model conversation. Valid `/run` input creates an application-owned proposal; it never starts a process. The proposal exposes the exact command, fixed authorized workspace, native-isolation availability, sanitized environment, 30-second timeout, and independent 64-KiB stdout/stderr bounds. Browser and interactive CLI paths require a separate explicit Execute choice for every invocation.

The fixed Safe Action catalog now also contains `tori.command.execute`. Its strict arguments are exactly `command` and the application-selected workspace. Authorization remains invocation-, action-, arguments-, and source-specific, opaque, single-use, and fail-closed under alteration, replay, wrong source, missing grants, or unknown actions. Confirmation cancellation consumes the grant without execution. The browser has no generic command API; the narrow Stop route requires the observed invocation identifier and can signal only that currently active Tori-owned process group.

`CommandExecutionService` owns subprocess creation, sanitized environment, one-active-command enforcement, separate bounded stream draining, timeout, stop, exit-code truth, and deterministic process-group cleanup including background children. Results distinguish succeeded, nonzero failed, timed out, stopped, and executor-rejected outcomes. Command output remains plain-text untrusted application output and is never provider input, automatic continuation authority, memory, knowledge, or a new command trigger. Confirmation returns as the application-owned worker starts; invocation-specific browser observation keeps the compact activity mounted through starting/running and terminal states. Its always-visible header shows command and status with Stop while active, while expandable details retain workspace/isolation, exit/termination evidence, and separate bounded stdout/stderr after generic operation status clears.

The production backend is native Bubblewrap, not Docker. Its proposed boundary uses the real selected workspace at `/workspace`, a private root, read-only host toolchain, private PID/IPC/UTS/cgroup/network namespaces, transient `/tmp`, no unrelated `<project-parent>` paths, no backup root or Docker socket, and an empty transient overlay at `/workspace/runtime` so canonical Tori runtime is not exposed. The supervisor creates the owned host process session/group, and Bubblewrap contains all descendants within it. It executes the exact confirmed text through `/bin/sh -c` only inside that boundary; no command denylist is treated as security.

Host inspection found Bubblewrap 0.9.0, systemd 255, util-linux `unshare` 2.39.3, enabled unprivileged-user-namespace sysctls, and `kernel.apparmor_restrict_unprivileged_userns=1`; nsjail, firejail, and a Landlock helper are absent. Bubblewrap and direct unshare probes fail only inside the nested Codex execution environment. Subsequent real-host human acceptance launched Tori normally and confirmed Bubblewrap isolation is available and production execution works without AppArmor, namespace, kernel, Docker, package, or host-configuration changes. The implementation still fails closed whenever its startup isolation probe is unavailable and has no unrestricted host fallback. Automated supervision tests use an injected backend rooted in disposable temporary workspaces; real-host Bubblewrap behavior remains a human acceptance check outside Codex.

### Explicit boundaries

- No Docker, Open Terminal, unrestricted host shell, command parser/denylist security claim, arbitrary browser command endpoint, model-selected command, provider tool execution, output-to-model continuation, queue, retry, schedule, recurring task, detached task, remote/SSH execution, sudo, privilege escalation, plugin registration, or autonomous coding loop.
- The current application-selected workspace is the Tori repository. Future project selection and separately authorized file-editing capabilities remain separate design work.
- Network remains absent in the Bubblewrap design. Package installation and network-enabled coding workflows require future explicit permission semantics.
- Tests use temporary stores and workspaces only. Canonical runtime and `<backup-root>` are not test inputs and are never mutated.

**Status:** Complete at commit `private revision omitted` (`private revision omitted`) — `Complete Tori's native supervised command execution foundation`. Real-host human acceptance confirmed the production Bubblewrap isolation path; namespace failure inside nested Codex remains an evaluation-environment limitation, not a host prerequisite. The accepted compact browser command-activity UI should not be reopened solely for cosmetic work.

---

## Milestone 20 — Intelligent Curated Memory Foundation

### Accepted implementation

Tori retains application-owned SQLite as canonical memory authority. After an ordinary assistant turn has completed and the authoritative conversation archive commit succeeds, a separate hidden invocation of the selected provider/model may return one strict bounded candidate document grounded by exact evidence in the current user statement. Candidate extraction is advisory: the model cannot choose canonical IDs, CRUD operations, database targets, deletion, confirmation, or authority.

Deterministic policy accepts only direct, ordinary, durable, evidence-anchored preferences, projects, goals, routines, constraints, or general continuity that are neither temporary nor operational scheduler data. Exact and safely normalized duplicates are suppressed. Strong repeated or long-duration behavioral patterns are inferred rather than direct and always require an expiring process-local one-use confirmation. Weak one-off behavior produces no candidate. Candidate, classifier, provider, legacy-schema, and store failures remain nonfatal to the already successful conversation and archive.

Lexical relatedness only preselects up to three bounded existing memories for advisory comparison. `independent` records may coexist; `duplicate` records express the same durable proposition; `update` and `contradiction` require the same underlying memory dimension; and `uncertain` does not establish replacement authority. Only a valid same-dimension update or contradiction with an application-allowlisted opaque target may create a revision-bound replacement proposal, and explicit confirmation is still required. Invalid, uncertain, independent, or non-allowlisted classifier output cannot target an existing record and instead fails non-destructively.

New memory stores use schema version 2 with the current canonical record plus minimal source chat/user-sequence, advisory provider/model, and confirmation provenance. Pending/rejected candidates and old content revisions are not persisted. Schema-1 stores remain safely usable for explicit memory and lexical retrieval and are never automatically migrated. A separate explicit transactional migration preserves every existing ID, exact text, and timestamp and assigns truthful legacy explicit provenance.

The memory filesystem boundary now uses descriptor-relative no-follow opening and atomic no-replacement publication patterned after the conversation archive. Newly created stores use owner-only directory/file modes. The canonical production database was explicitly migrated through the controlled schema-1-to-2 mechanism, verified against the exact schema-2 runtime contract, and corrected to mode `0600`; normal application startup still never migrates a legacy store automatically. Retrieval remains bounded lexical retrieval; Mem0, embeddings, vectors, sensitive memory, a scheduler/calendar/task database, background extraction, archive sweeping, and autonomous retries remain absent.

Ollama hidden extraction and relationship calls request provider-native structured output, while the application still requires the exact bounded shape and rejects arbitrary prose or fenced output. Browser complete and streaming paths carry only verified application-owned `Remembered:` status and confirmation data. Trusted provider-neutral runtime guidance distinguishes retrieved pre-request canonical memory from current-turn post-response persistence: the current user statement has immediate conversational priority, but the model may not claim that the current turn already changed persistent memory.

Deliberate live acceptance passed direct automatic persistence, duplicate suppression, contradiction/update cancellation, scheduler and sensitive rejection, archive-resume replay protection, inferred additive confirmation, and temporary-state rejection. A physical-iPhone correction test confirmed same-dimension replacement updates the bound record only after confirmation. Live-discovered extraction-format, streaming-event, current-turn truthfulness, direct-versus-inferred, and independent-versus-update defects were corrected and receive offline regressions. Final production state contains exactly the two genuine accepted preferences and no disposable correction-test memory.

**Status:** Complete and human accepted at commit `private revision omitted` (`private revision omitted`) — `Complete Tori's intelligent curated memory foundation`. The production store is exact schema 2 at mode `0600`; 566 offline tests and the complete milestone verifier pass.

---

## Phase H — Modular speech capability

Phase H.1 through H.5 implement Tori's provider-neutral TTS port, conforming Qwen
and Kokoro adapters, canonical revision-safe profiles and active selection, the
modular Settings management surface, and the complete selection-to-speech runtime
lifecycle. First Web startup seeds an absent profile store atomically from the
already validated legacy configuration; later starts use only existing canonical
selection and never re-project or silently fall back. Each speech session snapshots
one profile, while successful selection or an effective active-profile edit cancels
old speech before future sessions use the new provider/model/voice. Human acceptance
passed the Settings Voice workflow, Qwen3 TTS, Kokoro, and immediate profile/provider
switching. Changing a Kokoro voice may require one Settings refresh before its new
voice metadata is reflected; switching remains immediate, so this is an accepted
minor presentation note rather than a capability defect. Discovery, connection-test
UI, credentials, public/cloud providers, STT, and future schema migrations remain
separate work.

The ordinary Phase H profile contract is now OpenAI-compatible local TTS rather
than a vendor selector. New profiles use a bounded numeric local endpoint root,
optionally `/v1`, and the standard `POST /audio/speech` request with optional
model, input, voice, and WAV response format. Existing Qwen/Kokoro profiles are
preserved as legacy adapter records because their raw-PCM/streaming details are
not silently equivalent to the standard WAV contract. No discovery, credential,
public endpoint, or fallback authority was added.

---

## Unresolved Decisions

These decisions remain intentionally open until an active milestone requires them:

- Long-term application framework
- Long-term interface: lightweight web interface, Open WebUI integration, or another option
- Model routing and model residency strategy
- Long-term configuration layering and secret management
- Logging retention and structured logging
- Long-term knowledge expansion beyond explicitly registered local `.txt` and `.md` files
- Capability protocol
- Event or messaging architecture
- Speech-to-text and microphone-input systems
- TTS discovery, credentials, external providers, and optional portable controls
- Distribution across different supported Linux host configurations
- Packaging and deployment strategy
- Public or private repository status
- Project license

---

## Known Risks

### Scope Expansion

The long-term vision is broad. Attempting memory, orchestration, tools, voice, interface design, and multi-host services too early could prevent a stable first implementation.

**Mitigation:** Enforce milestone boundaries and defer features that do not serve the active objective.

### Identity Coupled to One Model

A large personality prompt alone could make Tori's behavior depend too heavily on a particular model's quirks.

**Mitigation:** Milestone 1 intentionally does not implement the final personality system. Identity, configuration, context assembly, and provider behavior remain conceptually separate.

### False Success From Tooling

Models and automation tools may report that files or actions changed when they did not.

**Mitigation:** Treat execution and verification as separate steps. Verify files, exit codes, responses, and persistent state.

### Premature Abstraction

Designing every future service boundary before a working vertical slice could create unnecessary complexity.

**Mitigation:** Milestone 1 introduces only one abstraction with an immediate purpose: separating the application from Ollama-specific behavior.

### Hardware Coupling

The first implementation could accidentally depend on the exact current GPU, host, or model.

**Mitigation:** Keep the server URL and model selection in configuration and preserve clear failure messages.

### Saved Conversations Mistaken for Memory

A persisted transcript could be treated as if it were a curated, verified long-term memory.

**Mitigation:** Keep explicit conversation checkpoints conceptually and structurally separate from canonical memory. Resuming a checkpoint restores conversational context; it does not convert any statement into memory, and current canonical retrieval is applied only to new requests.

### Secret or Sensitive Content Stored as Ordinary Memory

Pattern matching can miss novel secret formats or ambiguous sensitive information.

**Mitigation:** Permit ordinary, non-sensitive curated memory only through application-owned persistence policy: direct durable user statements may be accepted automatically, while inferred durable memory requires user confirmation. Reject representative structured secrets and sensitive identifiers at a centralized pre-write boundary, keep models non-authoritative over persistence, describe the gate honestly as best-effort, and defer sensitive persistence and encryption.

### Sensitive Local Conversation Data

Automatically archived conversations and explicitly saved checkpoints may contain private or sensitive information.

**Mitigation:** Keep archives local in a clear dedicated store, expose metadata-only listings, require explicit target selection for transcript opening and deletion, avoid logging content, keep checkpoints separately inspectable/removable, and defer synchronization or broader access features.

### Documentation Drift

Implementation decisions may slowly conflict with the accepted vision or become scattered across conversations.

**Mitigation:** Review relevant founding documents at milestone boundaries and keep the roadmap, changelog, code, and Git history current.

### Registered Source Drift and Unsafe Content

An explicitly registered file may later be removed, replaced with an unsafe type, become oversized or invalid UTF-8, or gain recognizable authentication material.

**Mitigation:** Revalidate and reopen only the exact path for every request, retain no persistent document copy, skip unsafe sources or passages honestly, and preserve registration metadata for later recovery.

---

## Milestone 21 — Tasks and Reminders Operational Foundation

**Status:** Complete and human accepted at commit `private revision omitted` (`Complete Tori's tasks and reminders operational foundation`); controlled canonical archive migration and desktop/physical-iPhone acceptance are complete

**Objective:** Let Tori durably track work and scheduled attention while preserving local ownership, deterministic application authority, truthful failure, responsive conversation, and a narrow path toward later scheduled work without implementing a general scheduler.

**Implemented scope:**

- A separate exact schema-1 SQLite operational store at `runtime/tasks/tori_tasks.db` owns tasks, standalone or task-linked reminders, a global revision, and crash-safe delivery state. Lifecycle rows are retained by default. Explicit confirmed History deletion is revision-bound: resolved reminders and their delivery rows are deleted atomically without changing chat history or linked tasks, while a historical task is refused until all referencing reminder rows are explicitly deleted first.
- A validated IANA `TimeContext` captures one authoritative instant per turn. Configuration precedence is `[time] timezone`, then `TORI_TIMEZONE`, then validated host discovery. Civil-time gaps and unresolved overlaps require clarification; elapsed durations use the captured instant. Narrow standalone elapsed reminders accept both duration-first and action-first word order without model interpretation. Narrow standalone `today`/`tomorrow` windows with explicit 12-hour bounds also bypass model interpretation, preserve both canonical UTC bounds, reject same-day end-before-start, and become due at the start.
- One application-owned reminder thread performs earliest-due waiting, explicit mutation wakes, bounded wall-clock rechecks, atomic due transitions, startup overdue catch-up, and clean shutdown. It never invokes a model or writes a streaming transcript.
- Strict provider-native structured interpretation may classify or propose bounded user-visible content and application-supplied targets. The application owns IDs, revisions, UTC conversion, transitions, persistence, verification, and all success/failure claims.
- The browser presents one canonical reminder in normal chat when an active conversation is appropriate and one persistent attention card derived from the same reminder. Polling revisions synchronize all browsers; one active card plus a bounded queue count prevents uncontrolled stacking.
- The responsive management surface supports task/reminder inspection, revision-bound editing, completion, dismissal, delay, cancellation, Details, Discuss, and confirmed permanent deletion of eligible History records only. It provides no reopen, bulk clear, or automatic retention controls. Text remains plain and safely rendered, browser storage is not introduced, and draft input survives attention refreshes.
- Conversation archive schema 2 adds nullable, globally unique application-event identity on transcript entries. Application reminders remain visible but do not enter model history, completed-model counts, or curated-memory extraction. The explicit migration utility accepts an exact supplied path and never defaults to canonical runtime.
- Verified backup recognition and runtime-safety inspection include the operational database when it exists. Automated tests inject temporary roots and do not construct or mutate the canonical operational store.

**Acceptance result:** The documented desktop and physical-iPhone plan passed. Accepted coverage includes task creation/management/editing; standalone elapsed reminders in both word orders; exact civil reminders and full time windows firing at their start; task linkage and duplicate-target clarification; Delay, Dismiss, Done, refiring, and linked-task atomic completion; response-before-reminder delivery ordering; cross-browser attention/action convergence; separate active/History UX and safe permanent deletion; truthful no-browser and restart overdue recovery; and touch-friendly iPhone attention behavior.

**Corrective-cycle result:** Live findings in standalone elapsed interpretation, active-vs-History management, explicit existing-task linking, reminder editing, permanent History deletion, civil-time windows, and action-first elapsed wording are corrected. The final routing remains deliberately narrow: deterministic standalone windows, explicit existing-task elapsed links, and deterministic standalone elapsed forms precede broader strict structured interpretation without becoming a general natural-language scheduler.

**Exclusions:** Recurrence and recurring schedules, Night Owl, calendar integration, Signal/Discord, OS/mobile push, remote notification services, authentication/TLS, wake word, STT, proactive inactivity check-ins, broader initiative policy, general jobs, research jobs, general orchestration, Mem0/vector memory, autonomous work, and Milestone 22 Scheduled Work / Initiative infrastructure remain future scope.

---

## Milestone 22 — Scheduled Work / Initiative Foundation

### Objective

Provide durable application-owned execution of explicitly authorized, bounded future work without granting general initiative.

### Implemented scope

- Scheduled Work exact schema 2 at `runtime/scheduled_work/tori_scheduled_work.db` separates definition lifecycle, immutable Persistent authorization snapshots, occurrence-unique execution runs, bounded terminal evidence, global revision, and result-delivery outbox. Definitions and terminal notification snapshots carry an immutable nullable `origin_chat_id`. Human-authorized migration and later live acceptance created valuable canonical evidence; automated coverage injects disposable paths and never mutates canonical runtime.
- Conversation archive exact schema 3 separates selected-model state from actual execution attribution and permits `completed_turn_count = 0` only with null first/latest provider/model metadata. Ordinary archive creation still requires a genuine completed model exchange. One dedicated service path establishes or reconciles a zero-model-turn origin only after a recognized conversational Scheduled Work request, an application proposal, and explicit Persistent confirmation.
- Strict one-shot, daily, and weekly schedule types use the existing IANA time foundation. Recurrence preserves local civil time, skips spring-forward gaps truthfully, and selects the first fall-back occurrence. `run_when_available` and `skip_if_missed` are authorization-bound; recurring recovery coalesces long downtime, paused time never catches up, and interrupted external work never replays automatically.
- A domain-neutral deadline/wake loop is shared with the unchanged reminder state machine. Scheduled work has its own coordinator, transactional occurrence claims, and one non-daemon execution worker. Definitions, reminder attention, and browser timers remain semantically separate.
- The process operation mutex still serializes conversation and mutation safety, but only deliberately visible operations set the application working signal. A future definition, coordinator/deadline infrastructure, sleeping worker, and quiet result reconciliation do not produce global working state; normal interactive backup and supervised-command busy behavior remains unchanged.
- M18 capability definitions now carry contract versions, strict result validation, availability, and deny-by-default Interactive/one-shot/recurring eligibility. Interactive dispatch remains separate and process-local. `tori.backup` allows one-shot scheduling only; `tori.command.execute` allows neither scheduled mode. Tests inject `test.scheduled.record`; it is absent from the production catalog.
- Creation and material edits require a separate expiring application confirmation before atomic persistence. Pause/resume/cancel and edits are revision-bound; old authority is superseded or revoked, queued work is cancelled before start, and running history retains its original binding.
- Separate Scheduled Work APIs and responsive management expose Active, Paused, resolved History, recent runs, safe Details, Edit, Pause/Resume, Cancel, and individually confirmed dependency-safe History deletion. Multiple browsers converge through the scheduled-work global revision and bounded polling.
- Confirmation is deliberately ordered across stores: establish and select the archive origin first, then atomically create definition plus Persistent authorization with that origin, then append one deterministic creation-success application event. Archive-anchor failure creates no work; Scheduled Work failure retains a truthful origin; post-commit archive presentation failure retains valid work and reports partial success without action replay or rollback.
- Terminal runs retain canonical results even without a browser. A notification with an origin appends one stable `scheduled_work_result` event directly to that exact chat, whether or not it is active, and is marked archived only after exact append/idempotent verification. It never falls back to an unrelated chat. A deleted origin remains pending without a replacement; originless management-created work preserves the active-chat/pending policy.
- Both stores have separate explicit controlled migrations: conversation 2→3 and Scheduled Work 1→2. Normal startup rejects those legacy exact schemas with a migration-required error, and rejects malformed lookalikes without repair. The human separately performed both canonical migrations; current canonical versions are conversation 3 and Scheduled Work 2.
- Verified backup recognition and runtime-safety inspection recognize the new canonical SQLite path when present.

### Explicit limits

Scheduling exists only while the Tori application process exists and cannot wake a stopped or sleeping host. M22 adds no initiative policy, Night Owl behavior, arbitrary prompt/shell execution, scheduled command action, recurring backup, automatic retry, Run Now/Again, retention/pruning, research, maintenance/update, coding, self-improvement, orchestration, OS service, or multi-host worker.

### Acceptance status

All 701 offline tests pass. Automated verification covers exact migrations, provider-free origin continuity, the later-real-model transition, origin-first cross-store failure boundaries, immutable definition provenance, notification snapshots, inactive-origin delivery, missing origins, concurrent/idempotent drains, restart, memory/provider-history exclusion, waiting-work non-busy state, deterministic terminal cleanup, refresh/multi-browser convergence, retained interactive-action busy behavior, and one-shot Edit prefill across UTC/local date boundaries, midnight, and non-hour offsets. The human separately migrated both canonical stores. Live acceptance verified structured Persistent authority, local scheduling grammar, a real browserless one-shot backup, a zero-model-turn durable conversational origin, exact origin-bound result delivery, originless management delivery after revision-bound edit and replacement authorization, and stale-revision/origin-immutability boundaries. Human retests also passed the operation-mutex/working-signal correction before and after real execution and the persisted-timezone Edit prefill correction for a future one-shot definition. The temporary future definition was cancelled and deleted by the human. Final physical-iPhone acceptance passed in portrait and landscape: Scheduled Work navigation, Active/Paused/History, stable Details, correct Edit prefill and cancellation, touch controls, orientation changes, horizontal overflow, and false-working-banner behavior were all accepted. Milestone 22 is complete and human accepted.

---

## Milestone 23 — Model Provider & Context Control Foundation

**Status:** Complete and human accepted; canonical schema-4 migration, human-created schema-1 provider storage, bounded real legacy/OpenAI-compatible Ollama acceptance, visual/device review, and final multi-browser reconciliation passed

**Core implementation:**

- Durable provider identity is now the administrator-configured profile ID, separate from implementation type. The unchanged flat `[model]` and `TORI_MODEL_*` form still synthesizes one Ollama profile; explicit `[[model.profiles]]` supports multiple Ollama/OpenAI-compatible LOCAL/LAN profiles and rejects ambiguous legacy mixtures.
- Endpoint configuration is limited to explicit-port HTTP/HTTPS numeric IPv4 in `127/8`, `10/8`, `172.16/12`, and `192.168/16`. Hostnames, IPv6, public/link-local/CGNAT addresses, URL credentials, query/fragment input, redirects, and environment proxies are excluded. Authentication is `none`, an application-owned non-secret dummy bearer, or the one configuration-managed LM Studio loopback exception that references exact process environment `LM_API_TOKEN`; optional local bearer overrides are stored owner-private on the server and are never exposed through the browser.
- The focused OpenAI-compatible adapter implements bounded `GET /v1/models` and `POST /v1/chat/completions`, strict complete/SSE normalization, selected-model matching, recognized string reasoning-field containment, unsupported tool/multimodal rejection, malformed reasoning rejection, visible-content requirements, bounded responses/fragments, distinct safe connection/timeout/malformed/unsupported errors, optional usage telemetry, and the existing hidden structured memory/task calls without fallback-format retry.
- Provider complete and streaming contracts carry optional normalized terminal model/usage metadata. Ollama reports existing prompt/evaluation counts and receives a provider-neutral effective budget as `num_ctx`; OpenAI-compatible generation limits supplied input without claiming to alter a fixed backend window.
- Catalog identities are profile/model pairs. Administrator-known models supplement failed or absent discovery and may declare verified context capacity; discovery never silently replaces an archived selection. Missing profiles/models remain selected but unavailable, with no automatic routing or fallback.
- `lexical-v1` is a deterministic standard-library estimator that treats prose, code, JSON, long numeric/identifier segments, punctuation, and non-Latin text differently. A context budget includes estimated input, `min(8192, max(2048, ceil(B × 0.125)))` reply reserve, and a separate `max(512, ceil(B × 0.10))` uncertainty/template reserve. Estimated and provider-reported actual usage remain separate.
- The old destructive 20-message session/archive reconstruction default is removed. All eligible completed archived exchanges remain available, while the planner protects identity/current request/required supplemental context, trims oldest whole ordinary exchanges first, and only then may omit lower-ranked optional knowledge/memory. Required-material overflow and fixed budget above known capacity fail before provider contact.
- Exact archive schema 4 adds `chats.selected_context_policy` and nullable `transcript_entries.context_json`. Telemetry is bounded, non-authoritative, and contains only policy/budget/estimator/count/usage fields. The explicit schema-3 → schema-4 migration code defaults chats to `auto`, historical telemetry to `NULL`, and preserves chat/entry values, ordering, IDs, attribution, sources, application events, revisions, timestamps, and active pointer in temporary tests.
- Mission B reviewed and tightened the OpenAI URL contract: administrator configuration accepts a numeric LOCAL/LAN origin or its `/v1` form and normalizes exactly once; the adapter requires that canonical API root and appends only the two supported relative resources. Ambiguous paths are rejected.
- The compact browser bar presents `Profile · Model` plus approximate context pressure. One touch-friendly bounded dialog changes only configured profile/model and `auto` or bounded fixed planning policy. The combined durable change is one revision-checked archive transaction; unavailable historical identities remain visible without placeholder/fallback providers.
- Browser catalog documents expose only safe profile identity/display/availability and model identity/display/status/verified capacity. Endpoint, auth, implementation, dummy bearer, provider metadata, diagnostics, and native payloads remain server-side.
- Mission D adds a separate exact-schema-1 user-managed provider-profile store rather than overloading capability Settings. It requires explicit initialization, validates regular/no-follow storage and exact schema, bounds typed values, uses immutable generated IDs and optimistic revisions, and stores only OpenAI-compatible LOCAL/LAN profiles with `none` or dummy compatibility auth. Built-in/configuration profiles retain stable identity and deletion protection while allowing operational overrides through a separate owner-private local settings file; source-ID collisions fail instead of receiving priority. Catalog failure and status remain isolated per profile.
- Settings → Model Providers supports human create/edit/enable/disable/confirmed-delete/refresh operations through narrow Host/Origin/CSRF/content-type/request-shape protected APIs. The general model catalog remains limited to safe identity/status fields, while the protected management surface exposes only the operational fields needed for local editing. User endpoint edits affect only future connections; disabling/deleting never rewrites archive selection or attribution and never substitutes another backend. The responsive form stacks and remains viewport-bounded on narrow layouts.
- The human-created canonical store is `runtime/model_providers/tori_model_providers.db` at exact schema 1. This corrective mission read the existing `Secondary Ollama` profile without creating, editing, enabling, disabling, or deleting profile state. Normal startup remains non-creating and fail-closed for malformed existing storage.
- Context details distinguish estimated input from nullable provider-reported prompt/completion/total usage, show included/omitted exchange counts, and identify verified versus unknown backend capacity. Reply reserve remains planner headroom, not a cross-provider requested output maximum or hard total-token promise.

**Migration and acceptance evidence:** Normal startup never migrates. The separately authorized canonical schema-3 → schema-4 migration ran exactly once after a verified backup and preserved all 28 chats, 172 entries, IDs, ordering, revisions, timestamps, attribution, sources/events, and active pointer; all migrated policies are `auto` and historical telemetry is `NULL`. A stage-sequence regression proves each migration hook fires once and an already-schema-4 store is rejected unchanged.

Bounded real Ollama acceptance passed with the unchanged legacy `ollama` profile and configured `gemma4:12b`: normal catalog startup discovered 14 models, complete and progressive application streaming retained terminal model/usage metadata, and isolated 4K versus 16K planning restored older whole exchanges without conflating `lexical-v1` estimates with Ollama counts. Corrective live acceptance also passed through the existing human-managed `Secondary Ollama` OpenAI-compatible profile at a private-LAN endpoint: discovery found `gemma4:12b`; complete and application streaming returned nonempty visible text with exact attribution and validated usage; one streamed turn committed exactly one temporary assistant entry; the next request contained the prior visible user/assistant exchange; and JSON-object auxiliary mode returned a validated object. Ordinary complete and stream payloads carried no `response_format`; only streaming carried `stream_options.include_usage`, while the bounded auxiliary call alone carried `response_format: {"type":"json_object"}`. Recognized reasoning strings were not emitted or archived, and a native-provider sentinel proved no complete or streaming substitute was invoked. All corrective application/archive acceptance state was temporary; no canonical acceptance conversation was created.

Human desktop visual and physical-iPhone portrait acceptance passed. The human accepts iPhone landscape as a known limitation because conversation is not practically visible there and landscape is not an intended mode. A later physical cross-browser test exposed one stale client-state defect: a desktop that observed an iPhone-started turn as busy could remain disabled after the server became idle because attention polling refused to reload session state while the browser-local `busy` flag was true. Authoritative busy state corrected idle/control recovery. Subsequent physical testing passed native Ollama automatic transcript convergence but initially showed that Secondary Ollama still required refresh after its prolonged post-archive busy interval. The archive revision advances before synchronous intelligent-memory work releases busy; Secondary Ollama's roughly 24-second interval therefore produces many `busy=true` polls carrying the already-advanced revision, whereas native Ollama often reaches idle before that race is exposed. Attention and session documents include active-chat identity and transcript revision. The browser separately retains the revision actually rendered and explicitly latches a newer same-chat revision observed while busy; repeated observations cannot advance rendered state, and terminal idle performs one revision- and identity-checked session reload. A different chat cannot be injected by this path. Local initiating requests retain their own terminal lifecycle, and unchanged polling does not rerender transcripts, close dialogs, rewrite drafts, or disturb selection/scroll. Automated coverage holds the rendered revision at N across 24 consecutive `busy=true, revision=N+1` polls, then proves one idle reload advances it to N+1; it also covers one busy poll, direct idle discovery, provider failure, initiating-client disconnect, background/foreground recovery, different-chat isolation, dialog stability, and draft preservation. Final physical same-chat testing through the existing `Secondary Ollama` profile passed: the iPhone initiated a turn, the desktop showed working state, returned to idle, re-enabled controls, and automatically rendered the new user and assistant entries without refresh.

Measured Secondary Ollama sequencing with temporary schema-2 memory and TTS disabled showed provider stream terminal/visible text at 20.825 seconds, automatic post-archive memory extraction from 20.849 through 44.916 seconds, and the browser terminal event at 44.919 seconds. This is the existing synchronous intelligent-memory candidate lifecycle, not TTS preparation; replay controls appear only after the authoritative assistant entry and terminal event. Decoupling candidate extraction from visible completion while preserving M20 safety semantics is an accepted high-priority post-M23 performance/UX candidate, not part of M23.

All 758 offline tests pass. Coverage includes exact schemas and explicit migrations, provider-profile lifecycle/collision boundaries, LOCAL/LAN endpoint validation, complete and SSE response normalization, reasoning containment, structured-call isolation, provider/model attribution and no-fallback behavior, context planning and telemetry, responsive provider controls, and deterministic same-chat reconciliation through repeated advanced-revision busy polls.

---

## Milestone 24 — Asynchronous Intelligent Memory Completion Foundation

### Objective

Remove hidden intelligent-memory extraction from foreground response completion while preserving M20 policy authority, durable recovery, exact source-turn binding, and exactly-once effective application outcomes.

### Implemented Foundation

- Exact conversation archive schema 5 adds only `memory_extractions` plus its FIFO index. An eligible ordinary assistant append and one opaque extraction record commit in the same SQLite transaction. The record binds chat ID, user/assistant sequences, resulting archive revision, provider/profile ID, model, and a non-secret provider-definition fingerprint. Application events, Scheduled Work results, proposed/declined capability turns, and provider-free entries do not enqueue.
- Exact memory schema 3 adds only permanent `memory_extraction_effects` receipts. Automatic create or confirmed create/update and the corresponding logical-effect receipt commit in one `BEGIN IMMEDIATE` transaction. A receipt remains after later user edit/deletion, so recovery cannot recreate an already-effective outcome.
- Intelligent-memory evaluation now returns a strictly validated bounded plan without mutation; effect application remains application-owned. Existing M20 evidence anchoring, sensitive/task/scheduler rejection, duplicate suppression, related-memory comparison, exact target revision, confirmation, and nonfatal extraction failure remain unchanged.
- One managed FIFO coordinator uses an opaque process-incarnation owner rather than time leases. `pending` work is claimable; an older incarnation's `running` or `planned` work is crash-recoverable; the current incarnation's claim is not stolen. Validated plans persist before effects. `awaiting_confirmation` is durable and source-chat-bound; `completed`, `failed`, and `cancelled` are terminal. Ordinary provider/validation failure is terminal and nonfatal; only crash-ambiguous durable states recover automatically.
- The coordinator resolves only the captured provider/profile and model and verifies its captured definition fingerprint. Disabled, deleted, changed, or unavailable providers fail safely without fallback. Source entries are revalidated immediately before effects, and chat deletion is serialized with that boundary so a returning in-flight result cannot mutate memory.
- Complete and streaming web responses become authoritative after the archive+outbox commit. The worker does not acquire the foreground operation mutex, set browser `busy`, revise the transcript, or delay Speak/replay. Deferred proposals use separate attention state, remain isolated to the active source chat, and their decisions do not rerender transcript content or disturb the composer, scroll/selection, or unrelated dialogs. M23 transcript revision reconciliation is unchanged.
- Foreground request admission and authoritative attention busy state now transition through one condition-guarded gate. Foreground idle publication is atomic with admission release, non-busy quiet delivery reconciliation cannot cause a misleading foreground 409, and a genuinely active foreground operation still rejects duplicate admission.
- Interactive CLI returns to its prompt after durable enqueue and presents any deferred proposal only at a later safe prompt boundary. One-shot CLI prints/returns the answer and exits without waiting; the next startup recovers its pending extraction.
- Dedicated explicit migrations implement exact conversation 4→5 and memory 2→3 transitions with descriptor-bound no-follow checks, exact-source/lookalike rejection, transactional rollback, post-commit verification, and already-migrated refusal. Normal startup does not migrate.

### Gate Status

Milestone 24 is complete and human accepted. The separately authorized stopped-application migrations completed once; canonical conversation archive schema 5 and canonical memory schema 3 are production state and must not be migrated again. The asynchronous-memory architecture passed live acceptance. Secondary Ollama structured auxiliary extraction can exceed its configured 30-second provider timeout; failure remains durable, nonfatal, exact-source-bound, does not delay foreground completion, and cannot trigger fallback. The human-supplied final physical desktop+iPhone multi-browser retest passed: the corrected same-chat Secondary Ollama workflow converged without refresh, returned the desktop to idle, and re-enabled its controls.

---

## Milestone 25 — Project Context & Continuity Foundation

**Status:** Frozen and incomplete at the pre-architecture-recovery checkpoint; canonical schema 6 migration complete; live acceptance incomplete; not human accepted

### High-Level Objective

Establish a bounded foundation for useful project context and continuity while preserving Tori's accepted local-first, privacy, human-authority, and capability boundaries.

### Implemented Foundation

- A Project is a small durable user-owned context for an ongoing objective: immutable application-generated ID, bounded title and objective, active/paused/completed lifecycle, bounded four-section continuity brief, revision, and timestamps. It answers what the user and Tori are working toward and where they left it, without granting authority to act.
- Exact conversation archive schema 6 owns Project records and one nullable association per chat. One Project may support many conversations; each conversation has zero or one Project; shared Project state is not duplicated into transcripts; association changes preserve every transcript entry.
- Associated Project title, status, objective, and continuity brief enter the existing M23 planner as clearly labeled required data before the current request. Older ordinary history trims first, current user input remains last, and required overflow fails before provider contact. Project context is neither memory nor knowledge.
- Ordinary conversation never changes canonical Project state automatically. Project discussion is not creation authority: explicit discussion remains ordinary Conversation, and ambiguous potential-Project intent receives a concise create-or-discuss clarification in chat before only a clear create answer may enter the existing proposal flow. Narrow provider-neutral semantic interpretation recognizes varied create, update, associate, detach, pause, resume, and complete wording, but application code selects canonical targets and revisions. Conversational operations remain visible, inert, source-chat-bound, revision-bound, one-use proposals until confirmation; clarification and unconfirmed proposal state are intentionally process-local.
- Creation from an unassociated conversation proposes atomic create-plus-associate. Continuity updates use canonical Project state, recent current-chat material, and the explicit request to build a bounded four-section proposal. Stale revisions refuse overwrite. Talking about another Project does not switch association.
- Explicit lifecycle supports active→paused, paused→active, active/paused→completed, and completed→active. Confirmed deletion atomically removes only Project-owned state and detaches all chats; it does not delete or alter transcripts, curated memory, tasks, reminders, Scheduled Work, knowledge, files, backups, or capability state.
- The compact responsive Projects surface lists and inspects state, creates and edits Projects, manages lifecycle and association, deletes with explicit confirmation, polls authoritative state for multi-browser convergence, and shows a small current-conversation Project indicator. Conversation remains primary. CLI Project management remains deliberately minimal while shared context assembly remains interface-invariant.
- The dedicated explicit schema-5→schema-6 migration requires exact schema 5, preserves every schema-5 value, creates no Projects, leaves every historical chat unassociated, rejects lookalikes and schema 6, rolls back on injected pre-commit failure, and is never called by normal startup.

### Boundary and Gate Status

The recoverable offline implementation and automated verification are preserved, and the separately authorized canonical 5→6 migration completed. M25 is frozen and incomplete: live acceptance stopped after material UI and continuity-proposal defects, subsequent narrow corrections were verified offline, and the milestone has not been human accepted. Project-to-associated-conversations UX is still missing. Architecture recovery subsequently extracted canonical Project use cases behind `ProjectApplicationService`, but substantial Web and custom-UI orchestration remains intentionally deferred. At least one disposable Project continuity brief was reported as structurally contaminated and must not be silently repaired or cleaned without an authorized supported workflow.

**Architecture recovery result:** The repository-wide audit verdict **MAJOR IN-PLACE REFACTOR** was addressed through seven incremental, reviewed recovery slices rather than a rewrite. `docs/ARCHITECTURE_GOVERNANCE.md` remains the permanent implementation gate. A read-only exit assessment found no remaining MUST-FIX-BEFORE-M25 cluster, so M25 may resume only through a separately authorized mission under the recovered boundaries.

The completed slices are:

1. `ProjectApplicationService` — `be6524eb332df4e9d7acd20c4aab82f32c1b56c3`, `Establish Tori's first application-core boundary`.
2. `ManagementRemovalWorkflow` — `e5b65e8cd83c4d956af306835aa8b5f2b6d6db05`, `Extract Tori's management removal workflow`.
3. `SearchApplicationPolicy` — `6c2ebd1ce7f1ffe826967f5d15a749217dcc8d5f`, `Extract Tori's search application policy`.
4. `TaskReminderApplicationService` — `dad95b28d84d3a18517f75e0818e33716cff1037`, `Extract Tori's task and reminder application service`.
5. `ScheduledWorkApplicationService` — `6404bf26b8c38d98eff2054f74e00541541b5915`, `Extract Tori's scheduled work application service`.
6. `SearchPort` — `21c1617e2e7a3717963558ec4e8b9f1942dfcad8`, `Introduce Tori's search execution port`.
7. `KnowledgeRetrievalPort` — `7f2ecfe27192815b580085661ea52f3d177a531f`, `Introduce Tori's knowledge retrieval port`.

No Slice #8 was required. Remaining deferred debt includes model/context synchronization across mutable runtime services; active-session/browser coordination in Web; process-local supervised-command worker and presentation coordination; completed-turn persistence duplication across Web, interactive CLI, and one-shot modes; compatibility and composition fallbacks; concrete canonical-store and curated-memory dependencies where future replacement evidence may justify ports; and Project-to-associated-conversations UX. `WebApplication` remains substantial rather than fully thin, and class size alone is not an architecture failure.

LAN authentication and TLS remain deferred under the accepted user-controlled LAN start/stop model and are not part of M25. STT and microphone input also remain deferred; physical-iPhone STT would require the separately deferred HTTPS/certificate work. M25 must not become autonomous project management, orchestration, agent infrastructure, or a generic job framework.

---

## Coding Work / OpenCode Foundation

**Status:** The committed foundation, application lifecycle, Web Conversation authorization, and compact Workspace presentation slices are complete. The first real human-authorized production acceptance reached proposal, one-use confirmation, durable creation/authorization, native OpenCode session confirmation, and canonical Workspace status against a dedicated `/tmp` workspace, but it did not pass: OpenCode ACP closed after the local provider returned HTTP 200 and before modifying the file. Revision-bound cancellation collected the terminal observation and durably recorded `failed` / `transport_eof`, zero changed paths, and bounded evidence. Its exact process-exit cause cannot be reconstructed because the old path did not retain it. Recovery commit `private revision omitted` added bounded sanitized exit evidence, passive idempotent terminal collection, and correct schema/global-revision safety; recognizer commit `private revision omitted` then added the proven bounded `change` and filename-subject cases. Two later full-Web operations reached native OpenCode sessions and then died at `-9` / SIGKILL before workspace modification; the first was accidentally confirmed and the second was a deliberate failed human acceptance. Privileged system-wide lifecycle and signal tracing established their shared cause without finding an explicit signal syscall: the transient `ThreadingHTTPServer` confirmation thread launched outer Bubblewrap with `--die-with-parent`, then exited immediately before the kernel generated SIGKILL for that Bubblewrap process. Commit `private revision omitted` moved process creation synchronously to one durable, non-daemon, application-owned supervisor thread. The request thread can return without killing the worker, while `--die-with-parent`, explicit cancellation, bounded termination evidence, provider ownership, passive reconciliation, and deterministic application shutdown remain intact. The first deliberate canonical retry after that fix survived confirmation and reached stable `waiting`, but OpenCode attempted the authorized host `/tmp` workspace path from inside Bubblewrap instead of its `/workspace` mount; the unchanged `external_directory` policy correctly denied the operation and no file changed. Commit `private revision omitted` translates the exact authorized host root to `/workspace` only in OpenCode-facing objectives, acceptance criteria, and follow-up instructions. The real host path remains authoritative in proposals, immutable authorization, canonical records, UI status, workspace identity, and host-side changed-path verification. A disposable full-Web production run kept its proposal and authorization bound to `/tmp/tori-coding-work-path-mediation`, completed through Bubblewrap, OpenCode 1.18.21 ACP, the approved local relay, and `qwen3.8:latest`, changed only `synthetic.txt` from `before\n` to `after\n`, reported `synthetic.txt`, reached stable truthful waiting state, and remained revision-idempotent without any external-directory grant or Cancel. A fifth canonical operation then correctly failed `workspace_busy` because the restored fourth work still owned the same workspace. The first human Cancel attempt created no request, directive, or event: the browser control depended on an unacknowledged custom-event relay and could return silently. Commit `private revision omitted` replaced that relay with an explicit handler bound to the latest projected work ID/revision and visible bounded errors. The user explicitly cancelled the restored fourth operation; it reached `cancelled`, its session stopped, and ownership of `/tmp/tori-coding-work-acceptance-retry` was released. The sixth independent canonical operation then completed the first successful deliberate human-authorized Coding Work acceptance through Conversation, the durable supervisor, Bubblewrap, OpenCode 1.18.21 ACP, the approved relay, and `qwen3.8:latest`. It changed only `acceptance.txt` from `before\n` to `after\n` through `/workspace`, reported the relative path, and settled at stable truthful `waiting` without Cancel, reload, retry, erroneous external-directory denial, or parent-death failure. Canonical readiness remains available/ready and all six operations remain preserved. Primary desktop presentation passed; second-browser and physical-iPhone checks were not performed.

The concrete `CodingWork` domain owns objective, optional acceptance criteria, one exact workspace, weak optional Project/origin identifiers, user-facing lifecycle, immutable authorization references, run history, bounded meaningful progress, evidence, and continuation. Exact schema-1 storage separates global revision, work aggregates, immutable authorization snapshots, adapter/session runs, durable instruction/cancellation directives, and bounded semantic events. Initialization remains explicit; application startup never creates, migrates, repairs, or bootstraps a missing runtime.

One application-owned `CodingWorkRuntime` now composes optional production settings, the existing kernel owner, readiness evaluator, exact store, OpenCode adapter/supervisor, application service, bounded status projection, controls, and shutdown. It is not a generic Jobs or service-container abstraction. Startup exposes no mutable facade until all durable nonterminal records have been marked reconciling and resolved through the existing adapter contract. A previously observed quiescent session may reload as waiting; an interrupted active turn is never replayed or promoted to waiting. Follow-up, cancellation, terminal continuation, refresh, and Project filtering stay presentation-neutral. Pause/resume is not represented because schema 1 has no paused lifecycle state, and an absent requested workspace still fails rather than gaining implicit filesystem authority; a future narrow workspace-preparation operation is the recommended seam.

The corrected first authority envelope is deliberately fixed to `tori.coding.work`, one exact workspace with read/modify decisions, and sandboxed-tool execution. It records only enforceable resource facts: existing authoritative repository Git control state is read-only if present; host HOME, credentials, and caches are unavailable; the host/system package environment is read-only; general network and external filesystem access are denied. Project-local `.venv`, `node_modules`, vendor, manifest, lockfile, and unpacked-package files are normal reportable workspace modifications whenever workspace modification is granted. The envelope no longer claims that a mount namespace can classify arbitrary workspace writes as commits or dependency installation. Future local commit or mediated dependency capabilities remain separately authorized work; copy-on-write promotion is only a possible future stronger mode. Project and origin-chat identifiers remain weak provenance and introduce no Project or conversation-archive coupling.

Maintenance correction: for the bounded OpenCode contract, ACP `end_turn` is now the authoritative end of that authorized turn rather than an indefinite conversational pause. The supervisor contains the owned process and finishes strict private-state import before emitting `completed`. Only explicit authority-required continuation remains Waiting; terminal continuation uses the existing fresh authorization/new-run path. Restart reconciliation upgrades only the exact historical `model_turn_complete` plus `workspace_snapshot_observed` evidence shape, retaining fail-closed handling for every other waiting state.

A narrow presentation-neutral application service coordinates one replaceable worker port. The deterministic in-memory fake proves domain semantics. Slice 2 adds a production process supervisor that records durable run intent before adapter launch, owns one process group, drains bounded stdout/stderr, delivers retry-safe directives, escalates cancellation from `SIGTERM` to `SIGKILL`, removes descendant processes, normalizes crash/exit outcomes, and admits only one active worker per resolved workspace. Process creation is serialized through one durable application-owned supervisor thread so Bubblewrap parent-death containment follows the Coding Work/application lifecycle rather than a transient Web caller. Launch rejection becomes a durable failed run rather than an ambiguous starting claim. A fresh supervisor recognizes no prior raw process or PID; after restart, nonterminal work reconciles and missing supervisor ownership fails honestly without silent restart.

The Bubblewrap plan derives entirely from the immutable authority: one resolved workspace is mounted read-only or read/write, existing root `.git` is overmounted read-only, canonical `<tori-root>/runtime` is hidden behind an empty read-only mount when Tori is the workspace, `/usr` is read-only, HOME/tmp are private, environment is fixed and proxy/credential/socket variables are absent, broad `<project-parent>` workspaces are rejected, and all namespaces including general networking are unshared. Unsafe Git/runtime symlink mountpoints fail closed. Structural security-plan tests and real unsandboxed fixture-process supervision pass. The conditional automated Bubblewrap fixture skips honestly inside nested Codex, while normal-host Bubblewrap transport acceptance and the full temporary-state production application/store/OpenCode acceptance have physically passed with the fixed local model, exact-session restart, durable follow-up, and security probes.

The first OpenCode 1.18.21 adapter keeps ACP and harness-private mechanics outside the domain. Durable OpenCode data is rooted per CodingWork; a stable private-instance identity allows only ownership-proven stale relay sockets to recover; active-turn restart fails honestly without replay while a previously observed waiting session may reload to waiting; and authority changes require the old run to stop before a new authorization/run can take effect. Explicit policies retain at most 500 durable semantic events per work, 512 current supervisor observations and directive receipts, 500 changed paths, 20,000 filesystem entries, 8 MiB hashed per file, and 64 MiB hashed per snapshot. Omitted history, paths, oversized files, and partial snapshots remain visible as bounded evidence rather than being silently claimed complete. Exact-store reopen validates work/authorization/run/directive/event ownership and refuses inconsistent state without repair.

The shared Workspace/side area now shows compact canonical CodingWork status when work exists: exact workspace, objective, truthful lifecycle/approval meaning, latest meaningful activity and update time, bounded changed-file/result/activity summaries, collapsed details, and a revision-safe Cancel control. The card is absent when no work exists and remains driven by canonical CodingWork state rather than browser-local state. A restored waiting item binds Cancel directly to the latest projected work ID/revision; request failures remain visibly bounded on that same item rather than disappearing during polling. Continue is intentionally withheld because it requires fresh authority; pause/resume has no truthful schema-1 meaning.

The canonical-readiness gate and atomic initializer are implemented. The separately authorized initializer published `runtime/coding_work` as one schema-1 generation containing `tori_coding_work.db`, `supervisor.lock`, and the owner-only `opencode` instance/works/ipc/bootstrap-cache skeleton. Reopen refuses unsafe ownership, modes, types, links, or schema rather than repairing them. One nonblocking `flock` owner gates every production Coding Work operation; ordinary shutdown stops admissions, preserves durable directives, contains owned workers, releases provider transport, and releases the kernel lock last. Backup recognizes the database as SQLite and requires an ownership-held maintenance guard; active states, live waiting writers, or any provider socket make backup busy rather than cancelling work or raw-copying live harness state. Closed per-work session state and the database are one restore generation. Regenerable bootstrap cache is safely included for now because selective exclusion would broaden the backup implementation; sockets are never copied. The store now retains all three failed runtime-reaching operations, their immutable authorizations and runs, the first operation's cancellation directive, per-work OpenCode state, and bounded event histories as canonical evidence.

Production worker settings are an explicit optional `[coding_work]` boundary separate from Tori's conversation model: exact canonical root, absolute OpenCode and Bubblewrap executables, required OpenCode version, one loopback provider `/v1` upstream, one model, and bounded control/model-turn timeouts. Readiness is unavailable until the canonical layout exists, kernel ownership is held, exact executables/provider/model pass, and an explicit offline-bootstrap receipt matches the bounded no-follow digest of prepared cache material. Startup performs no package acquisition; each CodingWork receives an owner-only copy of that regenerable cache while durable session/data and directive receipts stay isolated, and normal-user OpenCode state is never used. The Workspace presentation consumes only the application status projection and has no browser-local authority.

Deferred scope remains conversational Coding Work status/control routing, pause/resume lifecycle design, missing-workspace preparation, Pi, remote-provider/broker expansion, GitHub cloning/fetching, Git commit authority/broker, mediated dependency installation, optional copy-on-write promotion, generation-setting profiles, calendar integration, generic Jobs, and M25 resumption.

---

## Planning / CalDAV Foundation

**Status:** Foundation, Reminder Bridge, conversational operations, compact Workspace, persistent local deployment, and live acceptance implemented and verified.

The approved foundation adds Tori-owned Task and Event values, a presentation-neutral `PlanningService`, a replaceable `PlanningPort`, and the first CalDAV adapter. Radicale is an implementation choice behind that port, not a Tori domain dependency. Standard VTODO, VEVENT, RRULE, VALARM, UID, and ETag semantics preserve portable planning data and revision visibility without adding a new SQLite planning store.

The real isolated Radicale gate starts a native 3.7.8 server on an ephemeral numeric IPv4 loopback port with disposable `/tmp` storage. It proves task create/read/update/complete/read/delete; event create/read/update/delete; weekly and daily recurrence; relative 30-minute DISPLAY alarms; changed-ETag rejection after an external-client edit; and complete cleanup. Production Tori is enabled against the persistent native `systemd --user` service `tori-radicale.service` at `127.0.0.1:5232`, with `Tori Tasks` and `Tori Calendar` collections stored under `%h/.local/share/tori/radicale/collections`; persistent Radicale data remains outside `<tori-root>/runtime` and the current verified backup scope.

`PlanningConversationService` now intercepts only bounded, clear Planning requests before generic model chat. Read-only Today, upcoming/date-range, task, and calendar queries fetch current `PlanningService` truth directly and need no confirmation. Creates, reminder changes, rescheduling, recurrence changes, completion, and deletion produce a Tori-owned review proposal; the process-local token is one-use, expires after five minutes, belongs to the originating chat/revision, and binds existing objects to their opaque Planning revision. Confirmation rereads canonical state, rejects external ETag changes, calls `PlanningService`, and then asks `PlanningReminderBridge` to reconcile. The model has no Planning mutation tool or direct CalDAV/Scheduled Work authority.

The conversational grammar deliberately covers common local civil times, daily/weekly/every-N-day/every-N-week/named-weekday recurrence with count or exact-until bounds, title/recent-object reference resolution, and relative DISPLAY reminders. Ambiguous matches, vague mutation dayparts, absolute alarms, recurrence exceptions, and unsupported time forms fail boundedly rather than being approximated. Radicale owns portable planning objects; Tori retains authority, presentation, and attention. `PlanningReminderBridge` reconciles canonical VALARM intent into deterministic one-shot Scheduled Work delivery without making Scheduled Work a second task/event source of truth or accepting direct Conversation writes. Persistent Radicale storage remains outside current Tori backup scope and requires a separate consistent-backup design.

The compact Planning module now lives inside the existing Workspace rail and mobile utility sheet. `/api/planning` returns one bounded projection for Today, seven-day Upcoming, task filters, and a fourteen-day nearby Calendar agenda. Recurrence expansion, overdue evaluation, local-time conversion, collection names, and human reminder/recurrence summaries are server-owned. Browser view/filter/day state is ephemeral, and every action submits through the established proposal/confirmation flow; no direct Planning mutation endpoint exists.

Live acceptance verified task create/complete, event create/reschedule/cancel, real VALARM delivery through the Reminder Bridge and Scheduled Work, restart persistence, desktop Workspace behavior, and physical iPhone portrait behavior. The live `make cookies` issue was a proposal-only request rather than a projection defect: no VTODO or legacy task existed until the request was explicitly confirmed. The acceptance fix queues a fresh server projection read after an in-flight refresh, and the legacy management view is labeled as legacy. Calendar navigation now shows the selected date independently of the Today action. Deferred work is richer recurrence/alarm support, continuous startup/periodic bridge orchestration, background ETag/sync-token reconciliation, full month/week grids, attendee/invitation workflows, and provider-specific integrations. M25 remains frozen and unchanged.

## Conversational System Capabilities

The Web Conversation boundary now handles a deliberately small first-class System surface before generic model chat: native disk usage, local/LAN IPv4 address reporting, RAM, CPU, GPU/VRAM, uptime, allowlisted Ollama and Radicale/Planning status, compact Tori health, and bounded desktop opening for Brave, Dolphin, a terminal, LM Studio, and existing directories. RAM reads normalized `MemTotal`/`MemAvailable` values from Linux; CPU reports the model, logical CPU count, a short `/proc/stat` utilization sample, and load average as a distinct metric; uptime reads `/proc/uptime`; NVIDIA status uses an exact trusted executable, fixed `nvidia-smi --query-gpu=... --format=csv,noheader,nounits` arguments, `shell=False`, a two-second timeout, bounded CSV parsing, and truthful unavailable failure. Desktop targets are resolved only from fixed trusted paths/names, and folder opening requires an existing resolved directory before launching Dolphin. Multiple GPUs are presented independently when present.

Status requests and desktop opens require no confirmation, contact no Internet service, and retain no telemetry or persistent capability state. Ollama is checked only through its fixed local loopback API; Radicale uses Tori's existing `PlanningService.status()` when Planning is configured, otherwise the fixed `127.0.0.1:5232` local endpoint. Confirmed service actions are limited to the actual `ollama.service` system unit and `tori-radicale.service` user unit, with only start/stop/restart allowed. Radicale retains its fixed unprivileged `systemctl --user` vector. Root-owned Ollama runs only through the root-owned, non-user-writable `/usr/local/libexec/tori-ollama-service` helper sourced from `deploy/system/tori-ollama-service`; the exact `deploy/system/tori-ollama-service.sudoers` policy permits only that helper with exactly one of the three allowlisted actions. Tori invokes it through fixed `sudo -n` argv with `shell=False`, and the helper invokes fixed absolute `timeout` and `systemctl` paths for the permanent `ollama.service` target. Proposals are exact, one-use, five-minute, and bound to the active conversation revision; arbitrary service names, process names, systemd units, model-generated arguments, arbitrary app paths, executable files, URLs, and privileged commands are not accepted. Tori health projects existing application state for Tori, Conversation, Planning, Coding Work when configured, and Scheduled Work when configured. A degraded subsystem is reported without claiming total failure. Requests outside this surface continue through the existing supervised `/run` proposal and execution path; Tori self-restart, other host service mutations, and background monitoring remain deferred.

Focused tests cover realistic recognition and false positives, bounded desktop resolution/folder validation, fixed launch and service vectors, one-use conversation-bound confirmation, post-action verification, RAM/CPU/uptime formatting, GPU parsing and multiple GPUs, unavailable paths, the known-service allowlist, internal health projection, existing disk/IP/Brave behavior, and supervised general-command fallback. Live acceptance passed the requested desktop opens and confirmed Radicale restart on the production host; Planning remained reachable and its data remained intact. The root-owned Ollama helper plus exact-action sudo policy closed the previous authorization gap: Tori proposed and confirmed `restart Ollama`, invoked only the fixed helper, reported endpoint recovery, and then returned `Ollama is running.` The unit was independently active with its post-restart PID and the fixed loopback endpoint returned HTTP 200. No arbitrary service or application action was tested. Additional host mutations, Tori self-restart, and broader monitoring remain deferred.

## Personality / Interaction Engine V1

**Status:** Minimal application-owned foundation implemented and initially accepted through live casual conversation; broader controlled situational evaluation remains ongoing and evidence-driven.

`src/tori/interaction.py` owns one immutable, compact V1 guide derived from the accepted identity and personality direction. `ConversationSession` places it immediately after the stable runtime identity in the protected context prefix. The guide does not assign a mode: it asks the already-selected model to read the current request, completed conversation, and any separately supplied Project context, then express the same Tori naturally. Relaxed conversation leaves room for warmth, curiosity, reactions, and occasional humor; active work protects momentum; serious Project, planning, troubleshooting, and tradeoff work prioritizes concrete reasoning, respectful challenge, and clear distinctions among facts, uncertainty, recommendations, and decisions.

The boundary is provider-neutral and contains no model transport logic. It is stateless and adds no classifier, second inference, network operation, per-turn retrieval, memory search, persistent personality state, database, schema, or migration. Existing curated memory and Project context remain separate and are used only when the existing context planner already supplies them. User authority, one-use confirmations, verified action reporting, memory authority, and every capability boundary remain deterministic application responsibilities that personality guidance cannot grant or bypass.

Automated tests cover bounded deterministic guidance, provider neutrality, stable identity ordering, exactly one existing generation call, separate Project data, current-request-last ordering, and unchanged context planning. Private human evaluation used lightweight repeatable live scenarios. Initial human evaluation found meaningful improvement in casual continuity, natural follow-up, curiosity, and personality without forced humor; it does not claim exhaustive coverage or permanent perfection. V1 should be tuned only from controlled human conversational evidence, and should not grow into persona selection, mood/emotion simulation, scoring, new retrieval, or autonomous personality change.

## Remote Chat V1 — Discord implementation complete and human accepted

**Status:** Transport-neutral core plus the Hikari 2.6.0 Discord adapter are complete and physically human accepted. Real acceptance passed exact-owner ordinary conversation and dedicated context; consent-approved Exampleville structured-weather retrieval, original-question synthesis, attribution, and Discord delivery; reminder reads; prohibited-mutation refusal; restart continuity; self-termination/no-reconnect/local re-enable; loopback Settings lifecycle with LAN read-only status; and privacy-safe activity logging. The earlier bounded timeout and affirmative-as-question defects were corrected and passed retest.

The accepted `docs/REMOTE_CHAT_V1_CONTRACT.md` now has its first source foundation. Immutable `RequestOrigin` values distinguish current local Web/CLI application paths from a future verified `discord_remote` envelope without placing origin metadata in prompt text. `OriginAuthority` uses typed operation identifiers: local behavior retains its existing authority, while the remote origin has exactly six read/conversation operations plus one authority-reducing `remote_chat.terminate_self` operation and denies all others independently of wording. The seventh operation recognizes only the exact published owner-DM command, revalidates the durable DM/configuration generation, disables owner enablement, and stops the connector without exposing generic administration or a model-callable tool.

Web supplies its application-owned origin and authoritative active chat/revision to a presentation-neutral `ConversationTurnService`. The service binds sessions by origin kind and conversation ID, owns real ordinary complete/stream `ConversationSession` execution, origin-bounded Memory/Knowledge retrieval, conservative typed-operation resolution before provider dispatch, and foreground admission. A non-Web caller can therefore run an allowed real Tori turn without importing Web or supplying a callback, while a Web chat rebind cannot replace a future dedicated Remote session. Web retains HTTP/NDJSON, browser state, speech, archive presentation, and the existing local-only capability-handler choreography; those handlers now enter the same typed authority gate before dispatch. The former Web-private operation gate is an application-level `OperationCoordinator`, composed above Web in production, preserving foreground busy publication and quiet reminder/Scheduled Work reconciliation.

Slice 2 adds an SDK-free `RemoteChannelPort`, normalized immutable envelopes/results, and a fake adapter with separate send initiation/outcome semantics. A default-off, one-owner `RemoteChatService` verifies exact connector/application/bot/install/actor/DM identity before retention, processes a durable owner-private SQLite ledger in local FIFO order, and creates or reconciles one reserved `Remote Chat` archive ID plus archive-side reservation provenance without changing browser active-chat state. One logical reply is bounded at 4,000 application characters and prepared before commit as durable ordered physical chunks beneath the adapter's advertised limit. Each chunk records pending, sending, acknowledged, ambiguous, failed, or suppressed state, so restart never resends an acknowledged prefix or mistakes an interrupted send for pending.

The shared Conversation boundary now owns the approved Remote Search and upcoming-reminder dispatch seams. Search reuses current Search authority, evidence, and attribution while consent is additionally bound to the dedicated chat, exact immediately following durable admission sequence, remote origin, connector, actor, DM, originating event, decision event, query/weather state, and expiry. An intervening ordinary message invalidates consent even when an application-authored proposal did not advance provider history, while a bounded location reply continues a pending weather clarification. Reminder access is a bounded read projection only. Typed origin policy blocks local confirmation, mutation, execution, Finance, Knowledge, Project, host-sensitive, and other non-allowlisted operations before provider or domain-handler execution.

Credential, identity, and administrator-ceiling administration remains CLI-only through `scripts/tori-remote-chat`. Saved configuration is durable, but every Tori process begins Remote Chat Off; a fresh direct-IPv4-loopback Settings action enables only the current session. A post-start local CLI enable revision may likewise activate the running session, while a pre-start CLI enable never auto-connects a new process. LAN browsers are read-only. Connector identities and a synthetic/future token are stored outside Git, runtime, model/archive/Memory, browser, logs, and backup using kernel-locked compare-and-swap publication, monotonic revisions/generations, atomic owner-private replacement, and no-follow path validation; token entry uses no echo and has no read-back or command-line form. Disable, revoke, kill, rotation, and clear durably fence the prior generation even across stopped-process re-enable. The core serializes admission mutation, archive-plus-outbound publication, and the final application-owned physical-send authorization against that authority fence; already-started uncertain sends become ambiguous. Verified backup announces pause before contending for the same application fence, drains active generation/delivery or fails boundedly, and snapshots the non-secret ledger coherently with the dedicated chat. No canonical runtime was initialized by this slice.

Lifecycle correction leaves adapter preparation outside the application fence. At the final pre-invocation linearization point, the adapter calls a narrow Tori-owned authorizer that atomically checks closing/configuration generation and performs the durable `pending`-to-`sending` claim under the fence. If kill/disable wins, authorization fails and no send call occurs; if authorization wins, later unacknowledged interruption remains ambiguous. The fake exposes explicit preparation, authorized-entry, and pre-completion barriers, and deterministic tests prove both orderings. Shutdown stops admission and transport, joins the non-daemon worker, clears process-local Search/weather continuation both before and after the drain, reconciles interrupted generation/send state, and verifies that no current-generation `processing`, `reconciliation_required`, or `sending` row remains before success. Failed terminalization, cleanup, durable inspection, or worker containment stays Error and cannot be reported idle.

Slice 3 completed the current Hikari-versus-discord.py SDK/license/security review and selected pinned MIT-licensed `hikari==2.6.0`. The production adapter stays behind `RemoteChannelPort`, opens only an outbound Gateway connection, requests only the standard Direct Messages intent, disables cache/member chunking, accepts only exact owner-authored one-to-one DM create events, and rejects guild/group/bot/webhook/system/unsupported messages before core admission. Startup verifies the configured application ID, bot user ID, exactly one private installation guild, and optional or durably bound DM channel. The normal Web application now composes the Remote service over the same Conversation turn coordinator while isolating connector startup failure from local Web availability.

Discord's 2,000-character physical message bound feeds the existing 4,000-character logical reply/chunk ledger. Every send suppresses mentions, uses a deterministic bounded nonce, and acknowledges only a verified returned Discord message ID plus matching nonce. The application-owned authorizer still performs the durable send claim immediately before REST send entry; pre-entry disable/revoke/kill suppresses, while post-entry uncertainty stays ambiguous. Non-daemon Gateway and worker shutdown are joined and verified. `scripts/tori-remote-chat status` combines redacted configuration with a private lock-backed live state: disabled, configured/disconnected, connecting, connected/ready, authentication/configuration error, runtime error, or stopping. It never reads back the token.

Offline tests cover the real adapter projection, exact identity/admission, duplicate and changed replay behavior, ordered Discord-sized chunks, reconnect/authentication failure, send fencing and ambiguity, token-generation fencing, shutdown, Search consent, reminder reads, deny-by-default authority, backup coordination, and secret redaction. The live Search diagnosis added exact weather → proposal → immediate affirmative → original-request synthesis coverage, ordinary Search, bounded Search failure publication, repeated/ambiguous/intervening invalidation, and privacy-safe retrieval/synthesis operator events. Normal informational operator events use a durable default-on Settings preference; Off never suppresses sanitized errors, and neither mode emits conversational or secret content. Settings tests cover sanitized status, direct-loopback mutation, LAN denial, live stop/restart reuse, and truthful restart/error states. Adversarial tests cover exact owner-DM self-termination, wrong-user/guild/approximate/model denial, persistent disablement, no reconnect, and local re-enable. Physical acceptance completed the human checklist. There is no checked-in credential, public listener, guild conversation, group DM, attachment, voice, general Remote Chat administration, or further Remote Chat V1 work.

## Capability Growth / Self-Improvement V1

This separately authorized post-closeout extension is complete and human
accepted. Tori core owns an exact-schema Improvement Journal and compact
capability inventory. Verified normalized outcomes consolidate by immutable
operation/component identity; failures after successes create regression
evidence without destroying the known-good baseline. Lifecycle and
recommendation changes are revision-safe, records are hard bounded, and only
old terminal history may be retired for capacity.

Manual Skills Review preserves
`OBSERVE -> EVIDENCE -> PATTERN -> RESEARCH -> RECOMMEND -> USER DECIDES`.
A clear local request provides one-use research authority; no standing research
permission is created. General review covers journal FIX and IMPROVE patterns
plus missing EXPAND areas from a ten-area horizon. Directed review searches one
bounded topic. Research reuses skills.sh normalization and the public-GitHub
immutable quarantine/inspection boundary with fixed search/candidate/inspection
caps. Recommendations distinguish current authority, Skill lifecycle or
permission work, application adapters, MCP/external integration, unsupported
execution, duplicates, and rejected candidates. Acceptance remains advisory and
does not invoke any lifecycle action.

The responsive Skills & MCP surface displays the inventory, open findings,
known-good baselines, recommendations, provenance, authority requirements,
history, and recent review summaries. Verified Backup snapshots the canonical
journal under its maintenance guard; Verified Restore copies and checks it with
the rest of Tori-owned runtime. The journal never stores raw Conversation,
chain-of-thought, catalog prose, model self-grades, secrets, or sensitive traits.
The older Self-learning V1 capability-gap candidate selection remains ephemeral
and retains its separate consent and lifecycle boundaries.

Night Owl, background research, automatic install/enable/update, autonomous
Skill creation, general execution, MCP administration expansion, agents, image
generation, Discord integration, personality/identity modification, and Deep
Research are explicitly outside this milestone. Architecture details are in
`docs/CAPABILITY_GROWTH_V1_ARCHITECTURE.md`.

## Delegated Work / OpenCode Orchestration V1

**Status:** Implemented; final verification and physical acceptance are
recorded in the mission handoff

The existing concrete `CodingWork` aggregate remains Tori's durable delegated
coding domain, `CodingWorkerAdapter` remains the replaceable port, and OpenCode
1.18.21 ACP remains its first production adapter. No generic Job framework,
second database, schema migration, dependency, transport replacement, or
founding-document change was required.

Conversation now supports bounded provider-free status/result/verification
queries and explicit stop. Related follow-up uses a new proposal, immutable
authorization, work record, and run, with the prior work identity retained in
the new item's durable creation event. This preserves relationship without
reusing old authority or falsely claiming that a terminal ACP session resumed.
The public projection and responsive Workspace card show active,
attention-needed, and recent terminal work plus bounded changed-file,
verification, artifact, acceptance, and relationship receipts after reconnect.

Existing exact-workspace identity, Bubblewrap, no-network/no-credential,
read-only Git control state, restart reconciliation, shutdown, backup guard,
restore integrity, and proactive-system non-authority rules remain unchanged.
Architecture and non-goals are recorded in
`docs/DELEGATED_WORK_V1_ARCHITECTURE.md`.

## Supervised Terminal V1 — complete after Slice 5 closeout

Fresh-chat Gemma reproduction and correction: `start-tori.sh` sets the
checkout's `src` as PYTHONPATH; an unqualified venv import has no installed
`tori` package, while that exact launcher path imports the worktree modules.
There was no live Tori listener to inspect directly during this engineering
pass. The actual `tori.toml` Ollama/Gemma route with isolated stores reproduced
the first-turn error: Gemma streamed a valid exact proposal, but a brand-new
conversation had no archived ID, so the handler could not bind the action and
normalization raised `ProviderResponseError` for an unauthorized proposal.
Earlier disposable acceptance had first sent an ordinary turn, which created
the missing chat. A directly requested first-turn proposal is retained only
in process memory while a provider-free terminal origin creates a verified
archived chat. Its fixed application event is never visible assistant prose,
model history, or a completed model turn. After that commit, the local
authority, policy, approval, and grant route resolves it. Before commit it
cannot issue a grant, launch a process or expose a usable approval token. A
whitelist launches only after chat verification; an archive failure launches
nothing. Safe structural
events distinguish an unbound proposal, validation, normalization and launch
failure without logging command text, tokens or terminal output. A real local
Gemma run using `tori.toml` with temporary stores now completed from a fresh
chat, required DEFAULT_ASK approval, executed `echo hello` once, discussed
the result and completed `Yes, please.` without a model error. The later
physical-browser Gemma retest passed after restart.

First-turn result-continuation repair: returning a pending JSON string from
the action handler caused `ConversationSession` to commit that internal control
object as a completed assistant response. Approval subsequently launched the
PTY but never invoked synthesis. A trusted deferred-action signal now prevents
that premature model turn; the provider-free origin is verified before policy
or grant. On short exit after approval, the existing browser owner and origin
bind a single foreground result continuation. Only the broker's bounded,
sanitized output is supplied as labeled untrusted evidence, with the terminal
action handler disabled. Its actual model reply completes the original user
turn in both archive and browser transcript. Locked Private Input output is
not synthesized; a long-running or failed synthesis remains eligible for a
later explicit user turn. Disposable `ollama/gemma4:12b` using `tori.toml` and
the normal working directory reached DEFAULT_ASK, executed `echo hello` once,
then displayed a natural response about `hello` without pending JSON. Physical
browser acceptance after restart passed: no Generation Failed or raw pending
object; one `echo hello` launch and a natural response about `hello`.

Post-closeout conversational model correction: explicit fresh user command
requests are evaluated without unrelated pending PTY evidence, which stays
available for a later question; evidence-backed turns still cannot propose
another command from untrusted output in the same response. The local model
gets an application-owned default cwd and an explicit reminder that policy UI
owns approval. Split Ollama stream content can carry validated leading
reasoning, which is removed before the unchanged exact-envelope parser runs.
Disposable actual Gemma 4 12B turns proposed `echo hello`, required policy
approval, executed once, discussed `hello`, and handled `Yes, please.` without
generation failure. A separately authorized `nvidia-smi` model turn produced
a successful HOST_USER terminal result in the disposable host process.

The earlier reported NVIDIA-SMI failure did not reproduce in HOST_USER tests:
on this host the ordinary shell, an empty allowlisted environment, a direct
HOST_USER broker, a real loopback HTTP request/approval, and the disposable
Gemma-originated HOST_USER run all returned driver data with exit 0. UID,
supplementary groups, mount namespace, and visible NVIDIA device match the
parent in the broker probe. No driver-environment or device-access exception
was introduced.
Read-only canonical receipt digests match the two `nvidia-smi` exit-9 sessions
to PROJECT_SANDBOX at the default cwd; the HOST_USER receipts are successful
`ls` and `pwd`, with no matching HOST_USER `nvidia-smi` receipt at the checked
cwd values. The drawer now labels the selected exited session's actual scope
beside its exit code, and the scope input specifies that it applies to the
next command. The user subsequently physically verified a fresh HOST_USER
`nvidia-smi` session: exit 0 with a supported GPU visible.

Post-closeout fresh-start manual launch repair: when a local browser has no
active archived chat (including after restart), manual terminal requests bind
to a process-local browser-owner scope instead. The same loopback, cookie,
CSRF, policy, approval, grant, and broker checks remain mandatory. Model turns
and model-result reads still require a real originating chat; a no-chat manual
session never becomes model context and cannot be adopted by another browser
or later chat. Disposable HTTP launch tests run `ls` and `pwd` successfully
across two fresh Web application lifetimes and both scopes (project isolation
plan injected for the namespace-limited test environment).

Post-closeout completed-session UI repair: a closed WebSocket for an exited
session no longer starts an attach-ticket/reconnect cycle. Discovery and
automatic reconnect target only running sessions; an explicit selection of a
completed session can inspect one bounded snapshot without automatic retries.
Unchanged polls avoid selector/viewport rerenders, and completion respects a
minimized drawer. The frontend regression exercises successful exit, polling,
historical inspection, and launching a new command without duplicate execution.

Slice 4 binds conversation terminal launches to the active local
browser conversation and a fresh turn ID, adds read-only same-conversation
results with a separate 64 KiB sanitized model capture, retains a server-side
Private Input blackout across disconnect, and adds exact-rule Settings
management. The browser `/run` path now uses the four policy outcomes and
one-use broker grants; CLI `/run` no longer executes. The local conversation
now accepts one exact structured assistant command proposal only through a
trusted browser turn. Short results return as bounded untrusted evidence in
that turn, while running commands return a typed pending result. The old
in-process general-command action and runner reject direct execution. First
Private Input activation locks model capture for the lifetime of that process,
including after the keyboard state ends and across reconnect. Slice 5 audited
policy, grants, origin, WebSocket, Private Input, process lifecycle, and
browser acceptance. It closed an untrusted-output follow-up proposal path,
fixed streamed model-proposal completion parsing, and made reconnect prefer
the newest running owned session. Native sandbox PTY acceptance passed.

The architecture in `docs/SUPERVISED_TERMINAL_V1_ARCHITECTURE.md` fixes the
Tori-originated command authority chain and separates browser-session-bound
human PTY input from Tori execution policy. Slice 1 adds an exact-match,
versioned SQLite rule/grant store, four outcomes with mandatory precedence,
conservative application Always Ask classification, owner/cwd/scope/environment
binding, expiry, and atomic one-use consumption. Read-only policy evaluation
does not create runtime state; mutations and approved grant issuance create
the store only when invoked. Backup treats the database as SQLite. The browser
`/run` path uses this policy and the PTY broker; CLI `/run` and the old
in-process general runner are retired. Fixed system
capabilities and Delegated Work retain their narrower established authority
contracts; the model has only a structured execution proposal, never raw shell
or PTY input.

Slice 2 adds an internal process-centric Linux PTY broker that consumes the
Slice 1 grant before spawning, executes structured argv directly, reuses the
Delegated Work Bubblewrap plan for project scope, and keeps host child
environment variables on an explicit allowlist. The existing Tori HTTP server
now also serves a versioned WebSocket with strict Origin/browser-session owner
checks and 30-second one-use attach tickets. Browser disconnect preserves the
command but revokes keyboard control. A bounded in-memory output buffer
supports same-owner reconnect. A second verified-backup SQLite store retains
only lifecycle metadata, not output or keystrokes. Orderly shutdown kills and
reaps process groups; hard-crash cleanup is best effort through terminal
hangup, parent-death signaling, and Bubblewrap where applicable. Tori has no
account login, so the new cookie is a browser-session binding within the
existing LAN access boundary, not user authentication. No extra listener or
model stdin route was added. A true WHITELIST match is prompt-free only for an
authorized local browser interaction.

Slice 3 adds a direct-loopback local-browser execution origin, request/approval
adapter, and xterm.js drawer. The peer check gates proposal, approval, session
discovery, ticket issuance, and WebSocket upgrade; Host, Origin, and proxy
headers never prove locality. A whitelist match still requires an authorized
local origin. The UI handles multiple owned sessions, reconnect with bounded
scrollback, observation-only default, explicit takeover/release, resize, and
distinct interrupt/terminate/force-kill controls. The broker now forks from a
long-lived spawn worker because Linux parent-death signals follow the creating
thread; request-thread exit cannot kill an active command. The browser owner
cookie uses a new name and root path so reload retains ownership without
colliding with Slice 2's narrower cookie. Native Bubblewrap PTY/job-control
acceptance passed on a namespace-capable host context. Slice 3 added no model
input or output integration; later completed behavior is summarized above and
detailed in the architecture record.

## Next Concrete Action

Companion Initiative V1 is complete and physically human accepted. Companion
Initiative V2 Attention & Relevance is complete, verified, and backed up after
its controlled disposable physical acceptance. Its architecture is in
`docs/COMPANION_INITIATIVE_V2_ARCHITECTURE.md`. It preserves and extends the
accepted V1 architecture in `docs/COMPANION_INITIATIVE_V1_ARCHITECTURE.md`.
V1 Slices 1–4 implement the
default-Off exact-schema policy/store foundation,
deterministic candidate identities, revision-fenced claims and leases,
fail-closed recovery, guarded Verified Backup coverage, content-free
meaningful-interaction signals, and narrow source-owned resume-anchor
projections. Slice 3 adds deterministic eligibility orchestration, exactly-once
local application-event delivery/recovery, bounded one-use reply context, and
the opt-in local Web experience. A bounded process-local evaluator now gives
policy one opportunity every 30 seconds while Tori runs, regardless of browser
focus, visibility, or connection. It reuses the domain-neutral deadline-loop
lifecycle but creates no durable schedule and performs no stopped-process
catch-up. Settings expose only approved V1 controls; attention/session polling
reconciles the cached active transcript from authoritative archive revisions,
and exact dismiss plus durable one-day or one-week pause preserve the existing
lifecycle fences. Manual Speak is presentation-only and cannot acknowledge the
initiative, consume reply context, or remove its controls. Meaningful activity is
separate from acknowledgement: navigation, unrelated controls, and turns in
other chats may advance silence-policy activity without resolving the delivered
candidate. Only its exact Dismiss, its event-bound Pause, or a reply-context
claim in its target chat resolves it; switching back restores the target-only
controls.

V2 adds canonical attention projections for Research, Delegated/Coding Work,
Night Owl, and exceptional Scheduled Work; deterministic relevance and material
change; durable Review/Later/Dismiss state; a Workspace card; and bounded
meaningful Morning/return briefs. It suppresses empty briefs and timer-only V2
Long Silence delivery. A new scheduler, model-authored eligibility, automatic
TTS, and Discord initiative delivery remain out of scope.

Remote Chat V1 and Capability Growth / Self-Improvement V1 remain closed out.
Night Owl V1 is complete and human accepted. Broader research, MCP
administration expansion, agents, remote initiative delivery, and all
autonomous lifecycle behavior remain deferred.
Historical milestone plans and deferred contracts are not standing authority.

## Security Center V1 — complete and accepted

From clean accepted baseline `private revision omitted`, Security Center reuses Night Owl's
versioned finding/run/store/authorization and the existing Home attention
surface. The Security category uses three code-owned SearXNG discovery angles
and at most three bounded primary CISA/Ubuntu/NVIDIA/Mozilla advisory fetches
per run. Environment Watch is static research relevance metadata, never a scan
or verified package inventory. Review/Dismiss share Night Owl revision-bound
actions; selected-finding Discuss passes one short untrusted packet into the
next conversation turn with terminal model proposals disabled. Future local
security alerts remain separate, unconnected domain events with no inbound API
or autonomous response. See `docs/SECURITY_CENTER_V1.md` for limitations and
evidence discipline.
