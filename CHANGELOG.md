# Changelog

## v0.9.0 — Stable Private Testing Checkpoint (private)

- Gate 8E candidate: failed backup maintenance emits a bounded, privacy-safe `tori.operator` console diagnostic identifying the guard entry/exit or backup-body stage, exception class, and an allowlisted message label. Existing backup admission, publication, generic HTTP error, and retention boundaries are unchanged; no production backup or tag is part of this change.
- Restore staging now recovers only the fully verified `models/voice/` asset tree alongside trusted Git source and Tori runtime. Unsafe links, permissions, digest drift and trusted-source collisions fail before activation. Voice's separate `.venv` remains excluded and needs operator preparation after restore; no packages or models are downloaded by Restore.
- Gate 6B accepted an actual private GitHub fresh clone of core Tori. Gate 7 whole-product production smoke passed with no known closeout defect; Research Worker was available under normal owner launch. Automatic Research Worker and Voice Input installer provisioning remain deferred. The stable tag identifies the source paired with the final verified production backup and disposable restore. Public Release Readiness is separate future work.

### Gate 6 — core installer committed (Stage A accepted)

- Removed interactive external provider/server onboarding, upstream installer execution, automatic endpoint toggles and optional privileged host-helper installation from the fresh installer. Core now checks dependency integrity and clears inherited Python import paths; separate clone launches no longer use the production backup destination. Interactive prompts are limited to missing core Python prerequisites. Isolated Stage A and fresh-GitHub-clone Stage B acceptance passed. Research Worker and Voice Input automatic provisioning are explicitly deferred pending reviewed provenance, licensing, hash-checked reproducibility and runtime readiness.

### Gate 4 — documentation reconciliation

- Consolidated the current product/deployment/deferral checkpoint in `docs/FINAL_STATE.md`, shortened the root README to an entry point, and made `docs/README.md` a documentation map. Corrected the User Guide for current Planning, Supervised Terminal, Remote Chat lifecycle, Commands, and Research Worker dependency; contextualized superseded Deep Research, Projects, and milestone-era claims. No application, installer, founding-document, or runtime behavior changed.

### Security Center V1 — accepted

- Live isolated acceptance found CISA alerts' dated URLs and NVIDIA's vendor
  `nvidia.custhelp.com` security-bulletin answer paths; those exact primary forms
  are now admitted while generic indexes remain rejected. Security's three
  fetch slots are offered across the three fixed discovery angles before a
  repeated publisher can consume another slot. Direct `/security` browser
  navigation now mounts and loads its view module without a manual refresh.

- Added a compact Security workspace with Environment Watch, source-attributed
  external threat intelligence, Night Owl review lifecycle and bounded Discuss
  with Tori context. No connected alert sources or local security claims.
- Added an explicitly enabled Night Owl Security category with fixed discovery
  queries and a primary-advisory-only, bounded evidence lane. Existing Night Owl
  storage, grants, runs, retention and scheduling remain authoritative; no
  schema migration or automatic security action is introduced.
- Home uses one existing attention row for new KEV-listed findings matching an
  Environment Watch family; generic Security Watch findings do not trigger a
  Companion Night Owl check-in. Source content cannot grant terminal authority.

### Supervised Terminal — Gemma conversational proposal correction

- Fixed a first-turn failure in a fresh chat: Gemma could return a valid exact
  proposal before an archived chat existed, so the action handler could not
  bind it and normalization rejected it as unauthorized. The first turn now
  archives a provider-free terminal origin, then resolves policy against that
  verified chat; even an exact whitelist cannot launch before archive commit.
  Its fixed internal event is hidden from the transcript and model history,
  never a completed model answer. Short completed sessions receive one
  action-disabled, bounded untrusted-result synthesis; the natural reply
  completes the originating turn. Archive failure leaves no grant or process,
  and post-archive launch failure never claims execution.
- Gave local model turns an application-provided default cwd and explicit
  policy-owned approval guidance, so Gemma can propose a directly requested
  command without asking for a second conversational confirmation.
- Passed only validated visible assistant content (excluding well-formed
  leading reasoning) to the unchanged exact terminal proposal parser.
  Explicit new user command requests defer earlier untrusted PTY evidence for
  a later question instead of disabling the proposal handler on that turn.
- Disposable real `ollama/gemma4:12b` streaming acceptance reached the normal
  policy approval for `echo hello`, executed once, discussed the bounded
  result, and completed a `Yes, please.` turn. A separate real model turn
  whitelisted `nvidia-smi` through HOST_USER with a successful driver result.
- Physical-browser Gemma acceptance passed: first-turn `Run echo hello for me.`
  launched once, printed `hello`, and produced a natural response without
  Generation Failed or a visible internal pending object.

### Supervised Terminal — selected-session scope clarity

- An exited terminal session now displays its actual recorded scope alongside
  its exit code. The scope picker explicitly applies to the next command, so
  changing it cannot be mistaken for changing a prior sandboxed session.
- A subsequent physical HOST_USER `nvidia-smi` run passed with exit 0 and the
  GPU visible. No NVIDIA device, sandbox or child-environment change was
  needed.

### Supervised Terminal — fresh-start manual launch repair

- Restored manual `ls`/`pwd` launch with no active archived conversation. Local
  browser sessions receive a distinct owner-bound no-chat terminal scope; the
  existing policy, approval, grant, and PTY broker gates still apply. These
  sessions cannot be read as model results or adopted by another chat/owner.
- Covered first start and clean restart through real loopback HTTP, fresh
  browser cookies, host-user execution, and an injected disposable project
  sandbox plan; confirmed the pre-fix HTTP 409 occurred before policy evaluation.

### Supervised Terminal — completed-session UI repair

- Stopped the exited-session attach-ticket/WebSocket retry cycle after a
  successful or failed command. Polling leaves unchanged completed sessions
  stable; explicit selection can still inspect their bounded output snapshot.
- Preserved a minimized drawer across delayed launch discovery and process
  completion, disabled controls after exit, and covered the browser request,
  socket, render, and drawer transitions in a regression test.

### Backup/Restore Catalog Performance V1 — accepted

- Maintenance lists structurally valid backup publications and source
  compatibility without rehashing every payload. Listed backup contents are
  explicitly **not rechecked**; eligible means a restore may be proposed, not
  that the backup is currently verified.
- A new backup remains fully verified before publication. Confirmed restore
  still creates a verified safety backup, fully reverifies the selected backup
  before staging, and reverifies again before handoff. Malformed publications
  and untrusted source history remain ineligible for automatic restore.

### Load Performance Repair V1 — accepted

- Recent Chats uses a narrow read-only Project ID/title projection from the
  canonical archive, avoiding full Project Home assembly when drawing badges;
  the Projects workspace continues to use its complete projection.
- Global New Chat navigates to Chat and focuses the composer after a successful
  new conversation from Home, Settings, or another view. Cancellation and
  failure do not navigate.

### Visual Refresh V1.1 — mobile Home correction (accepted)

- Prevented narrow Home grid rows from shrinking beneath their contents and
  overlapping the hero/session area. Mobile Home now uses a non-shrinking flow.
- Reduced the hero and integrated model/context controls without another panel;
  arranged CPU/RAM/GPU/VRAM into two compact metric rows with existing live,
  stale, and unavailable presentation intact.
- Flattened nested Attention cards into compact rows, retained full titles and
  Review/Later/Dismiss with 44px hit areas, and tightened work/schedule spacing.
  Tablet review actions sit beside their item text when space permits.
- All overrides are scoped to Home at widths up to 1023px; shared rendering,
  data, action handlers, and desktop presentation are unchanged.

### Visual Refresh V1 — accepted

- Reworked Home into a stronger hero/session area and ongoing-work column,
  balanced by a supporting System Monitor, attention, and schedule column.
  Existing live cards move between layouts without cloning controls or data.
- Moved Speak into the message metadata row with a lighter chip treatment;
  ordinary replies no longer need a separate action footer. Message text stays
  at 15px, mobile touch targets remain comfortable, and initiative actions retain
  their existing footer and behavior.
- Tightened only Chat's secondary rail text and delegated-work rows, keeping
  long lists scrollable and all detail accessible. Settings, Skills & MCP, and
  the Remote Chat prerequisite repair remain as previously implemented.

- Added Home at `/#home`, using the existing live status, System Monitor,
  attention, schedule, Research, and Delegated Work cards. Home and Chat reuse
  the same DOM controls and projections; no duplicate Quick Actions, mock
  metrics, new provider calls, or additional data stores.
- Refined the graphite visual system, original local SVG branding, colored
  feature icons, active navigation, panel edges, conversation/composer styling,
  and shared desktop/mobile sizing, including Settings.
- Kept actual model/context usage and detailed context controls; marked host
  values stale after 15 seconds without a fresh response.
- Fixed the Remote Chat prerequisite: inert construction of a complete,
  administrator-permitted Discord adapter now works while disabled, allowing
  the existing coordinated backup guard to register. Live enablement and
  generation authority remain with the application. Real-adapter composition,
  coordinated backup, and continued fail-closed fallback have regression tests.
- Human acceptance was completed privately; the private evidence record is not
  part of the public release candidate.

### Supervised Terminal V1 — Slice 5 closeout

- Audited exact policy precedence, one-use grants, local origin, WebSocket
  ownership/tickets, Private Input, process lifecycle, and durable data
  boundaries. Native Bubblewrap PTY/job-control acceptance passed on the host.
- Prevented a completed untrusted terminal result from enabling another model
  command proposal in the same turn. Expanded adversarial shell-form and
  delayed transformed-secret regression tests.
- Fixed strict browser parsing of streamed terminal proposal completions and
  made reconnect select the newest running owned session. Browser acceptance
  used disposable stores and verified prompt behavior, takeover, privacy,
  reconnect, and interrupt without touching canonical runtime.

### Supervised Terminal V1 — Slice 4 implementation

- Bound PTY sessions and metadata receipts to the originating conversation and
  turn, added a separate bounded sanitized model-result capture, and added
  server-acknowledged Private Input that survives disconnect.
- Added loopback-only exact-rule policy management, four-state browser `/run`
  admission, and retired command-line `/run` execution.
- Added an exact structured assistant proposal for trusted local conversation
  turns. Completed commands return bounded untrusted evidence in the same turn;
  longer commands return a typed pending result. Approval tokens stay with the
  browser, and remote/background turns cannot mint terminal authority.
- Retired the internal general-command action and subprocess runner. Private
  Input now permanently locks model capture for the process after its first
  activation, including delayed output after the keyboard state ends.

### Supervised Terminal V1 — Slice 3 local interface

- Restricted terminal launch, approval, discovery, tickets, and WebSocket
  controls to direct loopback browser peers. A whitelist no longer implies
  permission for a remote channel to start a terminal command.
- Added exact local browser command proposals and one-use approval through the
  existing policy/grant chain; added locally bundled MIT xterm.js 6.0.0 and
  addon-fit 0.11.0 drawer with session selection, takeover, reconnect,
  resize, interrupt, terminate, and confirmed force kill.
- Fixed broker child SIGHUP after a short-lived HTTP request thread exited,
  and fixed browser owner-cookie scope across reload. Native Bubblewrap PTY
  validation passed in a disposable host workspace. No model terminal input,
  transcripts, extra listener, or Private Input was added.

### Supervised Terminal V1 — Slice 2 PTY broker

- Added an internal grant-gated Linux PTY broker with process-group lifecycle,
  scoped Bubblewrap plans, sanitized child environment, bounded reconnect
  scrollback, and metadata-only durable receipts covered by verified backup.
- Added same-server, browser-session-bound WebSocket attachment with one-use
  expiring tickets, observation-first human control, and no model input route.
  No xterm.js UI, extra listener, or backend-restart session persistence was
  added.

### Supervised Terminal V1 — Slice 1 foundation

- Documented the user-to-policy-to-grant-to-broker authority chain, host and
  sandbox scopes, future PTY takeover and Private Input, sanitized environment,
  reconnect, receipt, and untrusted-output rules. No terminal UI or general
  model command tool was added.
- Added exact durable command rules with BLACKLIST, ALWAYS_ASK, WHITELIST, and
  DEFAULT_ASK precedence; high-risk forms remain each-time approval. Added
  expiring single-use request/owner-bound grants. Existing confirmed `/run`
  now checks policy and consumes a grant before its sandboxed runner. Verified
  backup recognizes the new SQLite store.

### Research Worker claim/evidence ledger

- New Research reports persist bounded ordered claims and retained source
  excerpts in the existing Research database. A terminal gate checks support
  states, report locations, same-job source ownership, excerpt bounds, and
  claim links before atomically accepting completion. The schema upgrade also
  rolls back atomically on failure. New user-visible Findings are derived only
  from structured claims, with deterministic support labels; free worker prose
  is retained separately as unverified narrative. Malformed terminal results
  durably fail. Qualified partial, conflicted, or unsupported claims complete
  with visible limitations.
- Historical reports remain readable with their original completion state and
  are labeled as legacy evidence-unverified records. Typed application
  readback resolves a claim to retained evidence and its source. The current
  external research wrapper and authority/network boundary were unchanged.
  Source fingerprints are consistency metadata, not independent verification
  of remote content or semantic support.

### OpenCode worker version contract

- Pinned the configured OpenCode CLI, adapter, runtime readiness, installer
  detection, and bootstrap tooling to exact version 1.18.31. The installed
  executable and separately refreshed trusted offline-bootstrap material now
  pass readiness verification. Earlier 1.18.21 material remains invalid for
  this contract; no Coding Work job was created during Slice 5 acceptance.

### Projects & Continuity V1

- Completed and manually live-accepted Projects & Continuity V1 across its six
  slices: schema-7 structured continuity, Project Home and associated chats,
  deterministic Where We Are, bounded Project context with exact receipts,
  source-owned Related Work, and explicit source-verified links. Project
  association and context remain organization, never capability authority.
- Implemented Slice 6's explicit Project Home link-management UI for existing
  Night Owl findings, Scheduled Work definitions, and Knowledge sources. The
  human-readable Source and Item selectors resolve source-owned stable IDs;
  the source owner re-verifies each exact ID before a revision-fenced link is
  saved. Removal deletes only the Project-owned relationship. Related Work
  labels source ownership, safe metadata, source navigation,
  missing/unavailable records, and current-record activity. An active link
  form survives in-flight Project polling; the narrow Attention & review rail
  shows concise source/state metadata instead of long finding bodies.
- Corrected recurring Scheduled Work authority checks: operational definition
  revision advances no longer invalidate an unchanged immutable Persistent
  authorization, while future/impossible authorization revisions and material
  authority mismatches still fail closed. Deadline-loop failures now retain the
  generic operator message plus bounded class/code diagnostics, and the UI
  labels the stable scheduled identifier **Definition ID**.
- Corrected an acceptance-discovered special-origin archive incident. SQLite
  remained healthy, but an origin-less Scheduled Work result was routed into
  an active Project proposal chat, creating an invalid event sequence. Only
  disposable malformed test-chat data was removed through reviewed recovery.
  Background-result routing now skips incompatible special-origin chats, and
  archive appends validate the resulting event sequence before commit.
- Implemented Slice 5's bounded source-owned Related Work projection for native
  Research, Coding Work, and Companion Attention Project IDs plus explicitly
  linked Night Owl findings, Scheduled Work definitions, and Knowledge sources.
  Current-record activity uses authoritative UTC timestamps and identifies
  unavailable sources instead of fabricating a complete timeline. Explicit
  Project links are verified by their source owners before revision-fenced
  creation; unlinking affects only Project-owned references.
- Fresh Coding Work proposals from Project-associated chats now carry the
  Project ID and human-reviewable organization-only title; related follow-up
  work retains that ID and rejects a conflicting current-chat Project. Project
  membership does not change Coding Work authorization or execution scope.
- Coding Work proposal parsing now keeps explicit no-modification and read-only
  requests read-only, refuses contradictory broad authority wording, and still
  permits a specific requested change with a no-other-changes restriction.
- Implemented Slice 4's presentation-neutral `ProjectContextService` with
  deterministic Stable, Working, and conservative Historical whole-record
  selection. It uses the existing context estimator, provider capacity, reply
  reserve, and uncertainty reserve; Historical is discarded before Stable or
  Working, omissions carry closed reasons without omitted text, and the minimum
  Project identity fails before provider contact if it cannot fit.
- Replaced browser and CLI legacy Project prompt assembly with the structured
  service. Each completed provider turn that receives Project context now
  atomically stores one exact bounded receipt with the assistant archive entry.
  Conversation disclosure reads that persisted receipt, including exact rendered
  context and digest, rather than reconstructing current Project state. Receipts
  never become model context and retain the existing Project/chat deletion
  cascades.
- Implemented Slice 3's presentation-neutral `ProjectHome` and deterministic
  Where We Are projections, metadata-only Project conversation listing, and
  revision-checked New Project Chat workflow. The compact responsive Project
  dashboard now shows structured state, plan, questions, decisions, associated
  conversations, and legacy continuity as separate compatibility data. Viewing
  Project Home is read-only; opening a conversation loads its transcript only
  through the existing archive path, and a fresh Project chat creates no archive
  row until its first completed ordinary turn is persisted.
- Implemented Slice 2's presentation-neutral structured Project mutation and
  query layer over the existing schema-7 tables: explicit workspace state,
  immutable linear decisions and supersession, terminal question lifecycle,
  ordered flat plan items, and narrowly typed verified links. Every owned
  mutation checks the parent and relevant child revisions, advances the Project
  aggregate revision in the same transaction, and verifies the committed result.
- Retired normal legacy `continuity_brief` writes and the former recent-chat to
  Key-decisions synthesis path while preserving existing briefs read-only.
  Structured Project operations grant no capability authority. Broad structured
  editing remains outside V1.

### Main Conversation UI polish

- Reduced the New Chat control's footprint without changing its placement,
  label, color, or behavior.
- Matched the loaded model label to the adjacent Context status typography.
- Matched Send to the compact voice-control sizing while preserving composer and
  voice behavior. Accepted message body typography remains `15px`.

### Companion Initiative V2 — Attention & Relevance

- Extended the existing owner-private Companion store with canonical attention
  items, source/material identities, durable Review/Later/Dismiss state,
  surfaced-material history, revision-safe controls, and restart reconciliation.
- Added read-only projections for terminal Research, Delegated/Coding Work,
  current Night Owl findings, and failed/interrupted/missed Scheduled Work.
  Exact active-Project association adds context but no authority; routine
  successful scheduled runs are intentionally omitted.
- Added deterministic needs-attention / worth-reviewing relevance and silent /
  gentle / conversational delivery. Timer-only presence is no longer a reason
  for V2 initiative; quiet hours, activity suppression, cooldowns, rolling
  caps, readiness, and existing opt-in settings still govern delivery.
- Added a bounded Workspace Attention card, source routing, concise meaningful
  Morning/return briefs, and exact conversational reads such as “What needs my
  attention?” No path launches Research, Coding Work, MCP, commands, Night Owl,
  or Scheduled Work, mutates Projects, or bypasses normal authorization.
- Automated source, material-change, anti-nagging, delivery, migration, backup,
  and safety coverage is in place. A controlled disposable real-browser run
  passed desktop and narrow Workspace presentation, priority ordering,
  Review/Later/Dismiss persistence, concise Morning/return behavior, no-repeat
  behavior, and the unchanged explicit Research authorization gate. Repository
  closeout, push, and verified production backup completed.

### MCP V1

- Completed the existing MCP foundation instead of replacing it: production
  startup now owns configuration, exact identity validation, discovery,
  Capability Registry state, ordinary Conversation routing, live management
  status, and shutdown for one reviewed local stdio server.
- Integrated official `mcp-server-time==2026.8.18` (`mcp==1.30.0`). Tori
  discovers `get_current_time` and `convert_time` but permits only the exact
  schema-approved `get_current_time` read. Newly advertised or changed tools do
  not gain authority.
- Added per-server Bubblewrap isolation with no network, no writable host
  filesystem, a temporary working directory, minimal explicit environment, and
  no inherited provider/cloud/proxy/SSH credentials. Executable, sandbox,
  package, implementation, protocol, and schema drift fail closed.
- Added bounded argument/result validation, hostile-output treatment as data,
  timeout/crash truth, and live Skills & MCP readiness/error/count projection.
  Real browser/server acceptance passed successful Conversation invocation,
  denied unapproved invocation, crash visibility, restart authority stability,
  and orphan-free shutdown.

### Research Worker V1

- Replaced the unreliable DDGS experiment with bounded unauthenticated GitHub and
  Hugging Face primary-source discovery plus SearXNG secondary discovery. Provider
  identity checks, exact provenance, conservative quota handling, and fail-closed
  degradation are retained without account credentials or paid APIs.

- Added a separate Tori-owned durable Research Job domain with revision-bound
  public-web authorization, resource limits, progress/source events, exact URL
  provenance, validation summaries, full reports, cancellation, and truthful
  restart interruption.
- Added the replaceable supervised NDJSON `ResearchWorkerPort` and first hardened
  GPT Researcher adapter boundary. Completion fails closed unless the worker
  proves claim validation governed finalization and no unsupported claim remains
  presented as established fact.
- Added a Bubblewrap private-network boundary with a per-job Unix-socket egress
  broker. Public DNS answers are validated in full and the broker connects the
  validated numeric address; local inference is restricted to one exact Ollama
  relay. The worker inherits no ambient provider credentials or proxy settings.
- Added conversational proposal/status/stop handling, a Research Workspace card
  with visible limits and provider provenance, verified-backup coverage,
  capability awareness, and focused domain/security/UI tests.
- Corrected the traced Web-launch parent-death defect without weakening
  Bubblewrap. Research launch records now pass to one durable Tori-owned
  supervision thread, which alone calls `Popen`; transient HTTP request threads
  may exit while `--die-with-parent` remains bound to the runtime-lifetime owner.
  Queued cancellation prevents process creation, duplicate attempts remain
  rejected, and shutdown interrupts active work for truthful startup
  reconciliation before joining the owner.
- Completed production Piper and broad TTS smokes, a source-backed browser report,
  five-claim citation audit, Workspace cancellation, active-job restart,
  network-boundary regression, and complete offline milestone verification.

### Delegated Work / OpenCode Orchestration V1

- Extended the existing Tori-owned Coding Work domain into a conversational
  Delegated Work workflow without adding a second store, schema migration, or
  generic Job framework.
- Added deterministic provider-free status/result/verification questions and
  explicit conversational stop for chat-bound work.
- Added fresh-confirmation related follow-up proposals. A follow-up creates a
  new immutable work/authorization/run and records its prior work ID in durable
  event history; prior authority is never silently inherited.
- Expanded the bounded public receipt with acceptance assessment, terminal
  time, related work, structured verification, and artifacts while keeping ACP,
  process, provider, socket, stderr, reasoning, and token details private.
- Updated the responsive Workspace card to list Active, Needs attention, and
  Recent terminal work after reconnect, with revision-safe stop and detailed
  durable receipts.
- Preserved OpenCode 1.18.21 ACP, Bubblewrap, exact-workspace authority,
  read-only Git control state, no-network/no-credential policy, deterministic
  restart reconciliation, and coordinated backup/restore behavior.

- Completed and human-accepted Night Owl V1. Physical acceptance covered the
  default-Off master/category grant, all-six-category on-demand and nightly
  runs, persisted schedule/next-run state, Workspace activity, fair category
  coverage, real approved GitHub and skills.sh research paths, strict relevance,
  advisory retained findings, summaries, dismissal, stored-finding Conversation
  review/detail routing, provider-free application events, and the closed
  configured `Run Night Owl` control. No run installed, executed, configured,
  promoted automatically, spoke through TTS, or sent Discord content. Current
  SearXNG/Bing discovery can still favor GitHub-hosted pages that do not reduce
  to canonical repositories for some categories; durable funnel diagnostics
  expose that truthfully, and source/search-quality tuning remains separate
  future work rather than a V1 completion blocker.

- Corrected Night Owl stored-finding refresh and Conversation detail routing
  without changing research scope. A successful unchanged rediscovery can now
  refresh bounded source-derived presentation metadata without manufacturing a
  material finding version; legacy fingerprint-style descriptions receive a
  truthful limited display fallback until source metadata is available again.
  A previously retained finding is withdrawn from active review only when that
  same source is successfully reassessed and fails the current deterministic
  relevance policy; its history is preserved and it is not represented as a
  user dismissal. Numbered, punctuated, and natural named-finding detail
  requests now resolve from stored Night Owl data before generic Search. The
  search backend also preserves the entity after a “Tell me more about …”
  conversational lead instead of querying a generic word such as “more.”

- Improved Night Owl finding usability without expanding research authority.
  Findings now retain a safe source-derived plain-English summary instead of
  material-identity shorthand; Settings presents it as **What it is**, keeps
  attribution visible, and reads richer already-stored facts only after an
  explicit Details action. Conversation can summarize or disambiguate stored
  findings and explicitly start the same configured bounded review with `Run
  Night Owl`; added topic, URL, or query text is refused rather than silently
  becoming research scope. Harmless fenced JSON enrichment is normalized, while
  prose-wrapped, malformed, or action-seeking output remains unavailable.
  GitHub inspection now distinguishes rate limiting, not-found, forbidden,
  server, and generic HTTP failures through safe bounded codes.

- Corrected Night Owl's result-fairness and Settings funnel presentation without
  changing its research authority. SearXNG consideration is now independently
  capped at 12 results for each enabled category; Skills catalog candidates use
  their separate six-item budget and cannot consume another category's search
  quota. A normal fully processed 72-result plan completes rather than being
  labeled partial solely for reaching its authorized ceiling. Last Run Details
  now distinguishes GitHub-hosted results, canonical repository leads, queued
  repositories, and completed corroborations, while separately reporting Skills
  catalog requests, failures, and candidate count in a compact responsive grid.

- Refined Night Owl's approved-source failure truth without changing its source
  policy: public GitHub and exact-host skills.sh transports now distinguish DNS
  resolution, connection, TLS, HTTP, response, and policy failures through
  bounded codes. Physical diagnostics found the local execution environment's
  `/etc/resolv.conf` link targets an absent resolver stub, so direct approved
  outbound names fail before HTTPS while the configured private-LAN SearXNG
  service remains reachable. No global DNS, firewall, proxy, or source policy
  was changed.

- Aligned Night Owl's fixed SearXNG discovery templates with its public-GitHub
  corroboration boundary. The configured deployment's Bing upstream returned no
  GitHub leads for `site:github.com` syntax, while the fixed literal
  `github.com` query form returned GitHub-host entries but, on the observed
  Bing results, those were GitHub root/profile forms rather than canonical
  projects; all three application-owned angles in every category now use that
  bounded form while retaining this diagnostic evidence. Search
  leads now reduce only approved public repository, release/tag, commit,
  tree, or blob paths to a canonical repository subject before the existing
  unauthenticated GitHub inspection. Profiles, issues, pull requests,
  discussions, gists, assets, redirects, and non-GitHub URLs remain rejected.
  The bounded discovery adapter also prioritizes already-approved GitHub lead
  shapes within its fixed SearXNG result window while preserving source order
  inside each policy class. Last Run Details now also distinguishes considered,
  GitHub-eligible, and canonical queued leads per category. The exact-host skills.sh failure is now
  reported as its truthful network/response class; the observed acceptance
  failure was DNS resolution (`Name or service not known`), not a parser,
  policy, or installation failure.

- Tuned Night Owl V1 research depth through an explicit `night_owl_budgets_v2_depth`
  grant/schedule policy revision. Each enabled category now receives three
  distinct fixed discovery angles, with category-scaled ceilings of 3 searches,
  12 considered results, and 4 GitHub fetches per category (18/72/24 maximum),
  six Skills inspections only when that category is enabled, six model calls,
  32,000/8,000 model-token ceilings, and 192,000 retrieved characters. The
  strict Tori-fit/relevance and source boundaries are unchanged. Terminal runs
  now retain sanitized aggregate and per-category coverage diagnostics, which
  Settings presents as Last Run Details without exposing queries, URLs,
  snippets, grant material, or untrusted content. Existing grants and recurring
  schedules are revision-fenced and must be explicitly reauthorized for this
  expanded bounded authority. The authorized six-category acceptance run used
  all 18 discovery searches and considered 72 results in 16.5 seconds; all
  leads were rejected outside the GitHub corroboration allowlist and skills.sh
  was unavailable, so it truthfully retained no finding and made no GitHub or
  model call.

- Corrected the first Night Owl Slice 5 physical-acceptance defects without
  widening research authority. Active manual or scheduled research now appears
  as bounded background activity in the existing Workspace surface; dismissed
  findings leave the reviewable list immediately and cannot retain review or
  promotion actions; and stored-findings Conversation replies use durable,
  provider-free application-event provenance while remaining valid Web
  completions. Settings now places Run Now between scheduling and findings and
  aligns category controls responsively. The research runner discovers across
  all enabled categories before a deterministic cross-category corroboration
  pass, deduplicates repository candidates, retains the eight-GitHub-fetch
  ceiling, and emits content-free outcome counters for empty/unusable discovery,
  policy rejection, budget skip, relevance rejection, and corroboration
  failure. Category match plus local/self-hosted status alone no longer admits a
  finding; an evidenced Tori subsystem/protocol/capability fit is also required.
  A second real all-category acceptance run remains deliberately pending.

- Implemented Night Owl V1 Slice 5's user-facing local Web surface. Settings
  now exposes the default-Off master grant, six fixed research categories,
  on-demand/nightly/weekly modes, status, explicit Run Now, compact attributed
  findings, separate model-analysis presentation, review/dismiss, and explicit
  EXPAND or eligible linked-IMPROVE promotion. A bounded Conversation request
  reads stored findings without starting research, and the separately
  default-Off Companion Initiative Night Owl type is configurable alongside
  its existing master, Quiet Hours, cooldown, caps, and pause controls. The
  canonical Improvement Journal was explicitly safety-copied, migrated from
  schema 1 to schema 2, integrity-checked, and content-verified before the
  production promotion path was enabled. Night Owl remains advisory: the UI
  has no arbitrary query/URL/prompt or install, clone, execute, enable, MCP,
  configuration, TTS, or Discord action. Final Night Owl milestone closeout is
  still separate from this slice. Physical local-Web acceptance verified the
  default-Off surface, explicit three-category grant, truthful partial source
  failure, restart persistence, and two later completed bounded runs. The live
  sources produced zero relevant corroborated findings, which was preserved as
  a successful zero-findings result rather than inflated into a recommendation.

- Implemented Night Owl V1 Slice 4's bounded advisory integrations. Optional
  provider-neutral enrichment receives only one already-admitted structured
  finding, uses fixed prompts with no tools or retrieval authority, and enforces
  the three-call / 16,000-input-token / 4,000-output-token run ceilings.
  Deterministic findings survive provider, timeout, malformed-output, injection,
  and budget failures; model analysis is stored separately with provider/model,
  prompt-version, and input-digest provenance. Night Owl can explicitly submit
  an attributed external-research proposal through Capability Growth's typed
  ingestion seam: EXPAND is normal, IMPROVE requires an existing open
  operational-friction link, FIX is impossible, the same material is
  idempotent, and each research run is limited to three promotions. External
  research never becomes `CapabilityEvidence` and recommendation acceptance
  remains advisory. A metadata-only attention provider now supplies count,
  cohort digest, and oldest/newest timestamps to the separately default-Off
  `night_owl_findings` Companion Initiative type; all existing master/type Off,
  Quiet Hours, recent-activity, cooldown/cap, snooze, unresolved-message,
  active-chat, readiness, claim, archive, and recovery policy still applies.
  Explicit Night Owl and Improvement Journal schema migrations preserve prior
  state without startup migration. No final Night Owl Settings/review UI,
  Conversation review command, automatic action, TTS, Discord delivery,
  installation, execution, configuration, or source-policy expansion was added.

- Implemented Night Owl V1 Slice 3's backend Scheduled Work integration. The
  recurring-only `tori.night_owl.research` capability accepts one closed,
  immutable Night Owl grant snapshot and supports explicitly created nightly
  or weekly local-civil schedules with `skip_if_missed`. Execution revalidates
  the current Night Owl grant before research, records a bounded linked result,
  suppresses scheduled overlap as `skipped / already_running`, and uses the
  existing scheduler's DST, missed-run, authorization-revision, occurrence,
  and interruption truth. Startup performs no catch-up research. No schedule
  is created by default, and no model, Capability Growth promotion, Companion
  Initiative delivery, TTS, notification, or final Settings/review UI was added.

- Implemented Night Owl V1 Slice 2's explicit on-demand research seam. Fixed
  application-owned category queries may use configured SearXNG for discovery,
  exact-host skills.sh catalog discovery, and a no-credential public GitHub
  metadata/release inspector for corroboration. The deterministic runner
  revalidates its durable grant before each operation, accounts hard run/source
  budgets, rejects unsupported leads, retains only compact attributed findings,
  deduplicates unchanged material, and records completed/partial/failed truth.
  Retrieved instructions remain inert data. No model, Scheduled Work,
  Capability Growth promotion, Companion Initiative delivery, or public UI/API
  was added.

- Implemented Night Owl V1 Slice 1's offline, default-Off foundation: an
  owner-private exact-schema store for category-limited durable research grants,
  bounded run lifecycle/accounting, compact attributed finding/version history,
  deterministic source identity, relevance, and material-change suppression.
  Verified Backup recognizes the authoritative store behind a dedicated guard.
  This slice has no Search, GitHub, skills.sh, model, Scheduled Work,
  Capability Growth promotion, Companion Initiative delivery, or user-facing
  control path.

- Completed and physically accepted Companion Initiative V1's opt-in local Web
  experience. A bounded process-local evaluator
  now invokes the existing deterministic policy every 30 seconds while Tori is
  running, independent of browser focus, visibility, or connection and without
  Scheduled Work or durable scheduling. Normal attention/session reads now
  reconcile the cached active-chat revision from the authoritative archive, so
  a newly appended check-in appears in an already-open Conversation without a
  chat switch or reload and later polls cannot duplicate it.
  Settings now expose the master/type switches, morning and quiet-hour windows,
  read-only timezone, and durable one-day/one-week pause controls. Truthful
  local Conversation check-ins reconcile through the existing archive across
  tabs, retain manual Speak but never auto-play TTS, and provide exact,
  revision-safe dismiss controls without fabricating a user turn. Companion
  Initiative manual Speak is now strictly presentation-only: the successful
  replay POST no longer enters meaningful-activity recording, so it cannot
  acknowledge the candidate, consume reply context, or remove Dismiss/Pause
  controls on the next poll. Meaningful activity and initiative acknowledgement
  are now separate lifecycle operations: chat navigation, new-session controls,
  unrelated mutations, and turns in other chats may update silence-policy
  activity without resolving the target-chat check-in. Exact Dismiss,
  event-bound Pause, and a same-chat reply-context claim remain the only V1
  acknowledgement paths. Desktop, restart, unfocused/background, live-update,
  multi-chat, physical-iPhone/LAN, manual-Speak, Dismiss/Pause, persistence,
  and authority-boundary acceptance passed. The temporary acceptance-reset
  seam was removed after testing; the production 24-hour cooldown is unchanged.
  Companion Initiative remains default Off.

- Implemented Companion Initiative V1 Slice 3's backend eligibility and local
  Conversation lifecycle. The application now deterministically combines
  settings, activity, structured resume anchors, civil-time windows,
  cooldowns/caps, snooze, quiet-operation readiness, and an explicit future
  presentation-readiness input; revision-fenced candidates append one
  idempotent, unattributed `companion_initiative` application event. Expired
  leases reconcile through exact event lookup, and the next local same-chat
  turn can consume one bounded, non-authorizing supplemental reply reference.
  No browser-presence route, Settings UI, Search, TTS, Discord delivery,
  scheduler, or model-authored initiative wording was added.

- Implemented Companion Initiative V1 Slice 2's content-free activity signals
  and structured resume-anchor projections. Accepted local typed/finalized Voice
  turns and verified Discord owner admissions now update a replay-safe activity
  revision without storing message text or raw external identifiers; successful
  explicit local controls use the same failure-isolated boundary. Resume policy
  can inspect only waiting Coding Work identity/state metadata or active Project
  title plus latest ordinary exchange metadata. The feature remains default Off
  and produces no proactive Conversation, TTS, scheduler, Search, or Discord
  delivery behavior.

- Implemented Companion Initiative V1 Slice 1's default-Off, application-owned
  policy and persistence foundation. The new owner-private exact-schema store
  durably fences settings, meaningful-interaction revisions, snooze state,
  deterministic candidates, cooldown/cap history, claims, leases, and
  recovery outcomes. Verified Backup now snapshots the authoritative store
  under its maintenance guard. No proactive Conversation message, browser
  presence, scheduler, model call, TTS, Discord outreach, or capability
  authority is enabled by this slice.

- Normal verified production backups now exclude any rebuildable Python virtual
  environment directory named `.venv`, including `deploy/voice/.venv`, while
  retaining adjacent deployment files and Voice models under `models/voice/`.

- Completed and physically accepted desktop Voice Input V1 on the main host:
  explicit Off/On, client-local microphone selection, hold/toggle PTT, transient
  partials, fenced final admission through normal Conversation, Auto voice
  coexistence, and manual PTT barge-in. PTT stops speech immediately but cancels
  only the exact active generation after a valid nonempty final; empty or failed
  PTT preserves useful work. Ready forwards no PCM, raw audio is not persisted,
  and Off releases capture, the separately prepared runtime, and GPU resources.
  Wake phrase, passive activation, and mobile/LAN microphone capture remain
  deferred; enabling Voice Input never installs or downloads prerequisites.

- Built Voice Input V1 Slice 1's backend foundation: engine-neutral recognition
  port, explicit state/controller/segment fences, bounded local Tori transport,
  private RealtimeSTT recorder adapter, and supervised start/stop lifecycle using
  separately prepared offline assets. Audio and recognition text remain transient;
  no install/download occurs on enable. Product microphone/PTT controls, Settings,
  Conversation admission, interruption, and physical acceptance remain later work.

- Reconciled living README, User Guide, and roadmap status text with accepted
  post-closeout Capability Growth, Discord Remote Chat, and OpenAI-compatible
  TTS work. This changes documentation only and grants no new capability or authority.

- Made normal TTS profiles protocol-oriented: new Voice profiles use Tori's
  bounded OpenAI-compatible local speech contract without a Qwen/Kokoro vendor
  selector. Approved numeric loopback/private-LAN roots may include `/v1`; Tori
  sends the standard `/audio/speech` request with optional model and validated
  WAV playback. Existing Qwen/Kokoro raw-PCM profiles remain readable through
  their legacy adapters without destructive migration or implicit reinterpretation.
  Physical acceptance passed with a real private-LAN OpenAI-compatible backend;
  backend reference voices and runtime configuration remain outside this repository.

- Retained one non-secret application-level last-used provider/model preference
  alongside existing user settings. An explicit normal-use selection now
  survives a fresh start without an active archived chat; clean installations
  still use configured defaults, and an unavailable saved identity remains
  visible without fallback or rewrite. Historical assistant provenance and
  archived-chat selection remain unchanged. Removed Checkpoints from normal
  Web navigation, management, and command-reference surfaces while preserving
  its dormant backend, API, data, and terminal compatibility options.

- Changed accepted Discord Remote Chat startup authority to session-explicit.
  Identity, token, installation, owner, administrator permission, and saved
  local enablement remain intact, but every new Tori process starts Discord Off
  without opening a Gateway connection. A fresh loopback Settings action, or a
  post-start local CLI enable revision, activates only the running session; LAN
  and Discord remain unable to enable it.

- Completed Remote Chat V1 after full physical human acceptance with the real
  official Discord bot. Acceptance proved exact-owner one-to-one DM admission,
  normal provider/personality conversation and durable Remote Chat context,
  consent-approved Exampleville structured-weather retrieval and synthesis,
  source attribution/delivery, upcoming-reminder reading, deny-by-default
  mutation refusal, restart/reconnect continuity, exact owner self-termination
  and durable local re-enable, loopback-only Settings control with LAN
  read-only status, and privacy-preserving Operator Activity Log behavior.
  The accepted Remote ceiling has seven operations; the seventh,
  `remote_chat.terminate_self`, only reduces authority.

- Corrected the live Discord Remote Search synthesis continuation. Durable
  evidence proved that retrieval used the original Exampleville weather request,
  but the Remote proposal had not entered provider history and synthesis then
  used only `Yes, please.` as its effective request. A consent reply remains
  authorization-only; Remote synthesis now uses the validated original query
  with the normal Search evidence, while preserving exact-next-turn, one-use,
  topic-change, ambiguity, origin, and replay fences. Added separate
  retrieval/synthesis activity events without content. Settings now also shows
  sanitized Discord Remote Chat status to accepted browsers and permits On/Off
  owner enablement only from a direct IPv4-loopback client. Off uses the
  existing durable kill/generation fence; On reuses an existing connector when
  available or truthfully requests restart when the process was composed
  without one. Token, identities, and administrator permission remain CLI-only.

- Added the persistent Settings **Operator Activity Log** preference, default-on.
  Turning it off suppresses only normal privacy-safe informational lifecycle
  events; sanitized failures and serious runtime errors remain visible, and no
  conversational or secret-bearing debug stream was added. Remote Chat's typed
  ceiling now has exactly one additional authority-reducing operation,
  `remote_chat.terminate_self`. Only the exact verified owner in the durable
  one-to-one Discord DM can invoke the exact command `Terminate Discord
  connection now`; it disables owner enablement, advances the existing
  generation fence, stops Discord, survives restart, and can be reversed only
  through local administration. It grants no general Remote Chat administration
  or model-callable tool.

- Diagnosed the first live Remote Search acceptance failure from the canonical
  ledger without changing it. The immediate owner confirmation was admitted in
  the correct durable sequence and reached Search dispatch, but the configured
  eight-second Search request timed out; the generic Remote worker failure path
  then produced no reply. Remote Search now consumes the one-use consent as
  before and converts bounded `SearchError` failures into the existing safe
  Search-unavailable reply. Added the exact weather → consent → confirmation →
  result regression, timeout/failure publication, intervening-topic and
  ambiguous-confirmation coverage, plus privacy-preserving console events for
  Web/Remote lifecycle, turns, provider calls, Search consent/execution,
  delivery outcomes, reminders, and Scheduled Work. Events contain no prompts,
  replies, queries, Discord IDs, tokens, credentials, or durable transcripts.

- Implemented Remote Chat V1's production Discord slice and verified it
  offline before the later physical acceptance. The pinned MIT-licensed
  `hikari==2.6.0` adapter stays behind
  the existing `RemoteChannelPort`, opens an outbound-only Gateway connection,
  requests only Direct Messages, and admits only the exact configured owner in
  a verified one-to-one bot DM. Application, bot, sole private installation
  guild, owner, and DM identities are checked before durable admission; guild,
  group, bot, webhook, system, unsupported, malformed, oversized, duplicate,
  and changed-replay inputs fail within existing boundaries. Discord's 2,000
  character limit now drives the existing ordered durable chunk state beneath
  Tori's 4,000-character logical reply limit. Mention suppression, nonce/message
  acknowledgement, ambiguous post-entry outcomes, pre-entry generation fences,
  bounded reconnect/failure state, non-daemon shutdown, production Web
  composition, coherent backup participation, and secret-free live CLI status
  are covered by focused tests. The official bot token remains write-only in
  the existing owner-private XDG configuration and is absent from Git, normal
  runtime, Web responses, archives, Memory, logs, and backups. No public
  listener, guild conversation, group DM, second user, command, media, voice,
  administration, execution, mutation, MCP, or agent authority was added.

- Implemented Capability Growth / Self-Improvement V1 as an advisory-only
  extension of Skills V1. A separate owner-private exact-schema Improvement
  Journal consolidates deterministic success, friction, failure, regression,
  workaround, and opportunity evidence; preserves known-good baselines; and
  maintains bounded revision-safe FIX / IMPROVE / EXPAND findings and
  recommendations with cooldown-based duplicate suppression. A compact
  application-owned inventory reports native, Skill, and approved MCP state
  without model self-reporting. Clear local Conversation requests and the
  responsive Skills & MCP surface can run a one-use bounded Skills Review using
  the existing skills.sh and immutable public-GitHub quarantine/inspection
  pipeline. Reviews never install, enable, grant, execute, add MCP authority, or
  modify Tori. Verified backup/restore includes the journal under a consistency
  guard while excluding transient research state. Night Owl, background
  research, agents, MCP administration expansion, automatic Skill lifecycle,
  image generation, Discord integration, personality changes, and Deep
  Research remain deferred. Human acceptance passed desktop and physical iPhone
  presentation, refresh behavior, general and directed image/Excel/Discord
  reviews, truthful inspection and partial-review reporting, baseline and
  reconciliation semantics, and unchanged Skills authority. Success-only
  recommendations now reconcile to obsolete history, while a higher-priority
  regression recommendation supersedes the matching duplicate failure
  recommendation without erasing failure evidence. Live normal-use acceptance
  used `lm_studio/gemma-4-26b-a4b-it@q4_k_m`; that selected profile is not an
  architectural dependency.

- Added Verified Restore V1 to Settings → Maintenance. Only a fully reverified
  backup whose recorded commit is available in the fixed sanitized Tori origin
  can be selected; legacy-history-only, invalid, and incomplete backups fail
  closed. A one-use confirmation creates and verifies a fresh safety backup,
  stages exact trusted source plus restored Tori-owned runtime in a same-filesystem
  sibling, preserves the current machine `tori.toml`, reapplies the existing
  Skills disable/revalidation rules, and hands an immutable bounded plan to a
  copied external helper. The helper waits for Tori to exit, swaps by rename,
  performs a provider-free local health check, and makes one rollback attempt on
  failure while preserving evidence. Backup `.git`, backup configuration and
  `.venv`, Finance, Radicale, and Knowledge source data are never restore inputs.
  Maintenance cards and the one-use confirmation keep long backup identifiers
  and source identities readable on narrow screens.

- Prepared source distribution for per-machine configuration: root `tori.toml`
  is now ignored for the future sanitized baseline, `install.sh` validates and
  atomically creates a missing local copy from `deploy/portable/tori.toml`
  without overwriting existing or raced-in state, and the clean portable ZIP
  publishes that same generic template whether source tracks a root config or
  not. Runtime/user state and machine-specific settings remain local. The
  sanitized private GitHub repository is now the trusted source-history boundary.

- Repaired bounded Conversation routing for direct current-weekday questions.
  Phrasings such as “What day of the week is it today?” now answer from
  Tori's captured application clock and timezone without a model call, while
  genuine Today schedule requests continue through Planning. Calendar and
  Planning reads share the existing validated provider-free archive continuity
  path, so repeated identical reads remain distinct, monotonic turns.

- Completed and human-accepted the initial Skills V1 milestone. Desktop acceptance
  passed direct and hard-refreshed `/skills`, truthful `media.inspect`
  permissions/health and disable/enable confirmation, skills.sh discovery,
  selective GitHub inspection, production installation and separate enablement of
  `github/github/documentation-writer`, and archive/provider health after Skill
  lifecycle activity. iPhone acceptance passed readable populated details, usable
  confirmation controls, and no problematic horizontal overflow. The canonical
  Skills runtime intentionally retains enabled `builtin/tori/media.inspect` and
  enabled `github/github/documentation-writer`. Agent Plugins, durable MCP
  credentials, MCP writes/additional transports, automatic updates, background
  self-learning, autonomous Skill creation, and Remote administration remain
  deferred.

- Fixed a Conversation archive verification race found during Skills V1 human
  acceptance. A successful reconciliation is now verified as an exact immutable
  archive prefix and may return a later valid revision when another writer has
  already appended a distinct application event; missing, reordered, or altered
  committed entries still fail closed. Web adopts that newer verified archive
  state before the next turn, preventing a successfully returned provider answer
  from being mislabeled as a generation failure. Disposable coverage exercises
  ordinary provider turns, a GitHub Skill installation result, disabled and
  explicitly enabled instruction-Skill behavior, unique application events, and
  a subsequent provider turn.

- Corrected three concrete Skills V1 human-acceptance defects. Direct `/skills`
  loads now mount a deferred view module after the shell has selected the
  deep-linked route, preserving normal history navigation. Production Web
  composition now registers the reviewed bounded `media.inspect` adapter and
  Conversation bridge; compatibility comes from Tori-owned registered adapter
  support while health separately revalidates the immutable FFprobe identity
  and required containment helpers. Enable proposals therefore no longer apply
  Agent-Skills importer findings to a supported built-in Skill. Public GitHub
  acquisition now resolves the commit and walks only the selected Git tree
  subtree, fetching bounded verified blobs by immutable identity instead of
  downloading a whole repository archive. Live inspection of
  `github/awesome-copilot/skills/documentation-writer` succeeded at commit
  `87ba8b1780d0e2655fc19fa3f8d4fc7879881744` and digest
  `sha256:c39766ddcc7ee7881196dd148239bf332e462f7f51d3e673a8285ba3b3bec3ec`;
  it remained uninstalled and no package code executed.

- Completed the implementation side of the initial Skills V1 closeout. Verified
  backup now treats `runtime/skills/registry.sqlite3` as SQLite, takes the shared
  Skill lifecycle/package consistency guard, includes immutable managed packages,
  provenance, grants, retained tombstones, and other non-secret durable evidence,
  and excludes fixed transient/quarantine/discovery/secret subtrees. A fully
  reverified backup payload can restore an absent Skills generation atomically;
  every restored enabled entry becomes disabled with a new lifecycle revision,
  and package/registry digest inconsistency fails closed. Restore never overwrites
  existing Skills state. Local UI uninstall is an exact revision-bound one-use
  confirmation: enabled Skills are disabled first, the registry retains an
  `uninstalled` provenance tombstone, and only the verified digest-derived managed
  Agent Skill package is removed. No package code runs and unrelated user data is
  untouched. Skills V1 is ready for the concise desktop/iPhone human acceptance
  checklist; post-V1 Agent Plugins, durable MCP credentials, MCP writes/transports,
  background learning, autonomous Skill writing, automatic updates, and Remote
  administration remain deferred.

- Added Self-learning V1 as a bounded, advisory local Conversation flow. A
  closed application-owned detector recognizes a small set of explicit file-
  transformation capability gaps only after existing native/domain routes have
  declined and suppresses suggestions when a matching enabled Skill or approved
  MCP operation already exists. Security/policy denials, informational questions,
  Search requests, Remote Chat, and general uncertainty are not capability gaps.
  Tori first asks whether to make an active skills.sh request; only explicit
  current-Conversation consent performs a bounded three-result search. Candidate
  identity ranking is deterministic, catalog prose remains visibly untrusted,
  compatibility/scripts/permissions remain unknown until inspection, and exact
  selection is ephemeral and conversation-bound. Selecting a candidate invokes
  only the existing immutable GitHub quarantine/inspection path and creates no
  install proposal. No background discovery, durable behavioral profile,
  installation, enablement, update, permission grant, execution, Skill writing,
  Memory change, identity change, or self-modification was added.
  Disposable live acceptance recognized a PDF-manipulation gap, waited for
  explicit search consent, returned three uninspected skills.sh candidates,
  accepted an explicit narrower `pdf` re-search, and inspected
  `anthropics/skills/skills/pdf` at commit
  `41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f` and digest
  `sha256:dbc5f8574b7b57c040d612d181d84851bede97413e0736de7dbc6515f41dcdc5`.
  Inspection truthfully reported partial compatibility and eight inert scripts;
  no installation proposal, registry, or execution was created.

- Added a dedicated responsive local **Skills & MCP** management view backed by
  application-owned projections rather than browser-owned policy. It lists
  immutable Skill identity, source, version, compatibility, lifecycle, requested
  and granted permissions, components, inert-script status, health, network/file/
  process/secret authority, provenance, and compact privacy facts. Local users can
  search the existing skills.sh discovery service, inspect a public GitHub Skill
  through the existing immutable quarantine path, and separately confirm install,
  enable, and disable operations. MCP records show local transport, executable and
  configuration identity, exact network destinations, safe credential status,
  read-only classification, approved versus merely discovered tools, input-schema
  summaries, drift, and availability. Skill and MCP lifecycle proposals bind exact
  revisions or approved schema state before existing local confirmation applies
  them. External descriptions remain visibly untrusted and secret values never
  enter browser responses. MCP tool approval/start/stop, uninstall package removal,
  durable MCP credentials, write tools, and remote administration remain
  unavailable.

- Added the first reusable local-stdio MCP interoperability boundary. Tori now
  owns exact executable/configuration identity, fixed arguments, local-only
  administration and invocation, explicit individual-tool approval, exact
  requested/granted permissions, bounded `tools/list` snapshots, schema-drift
  admission, provider-neutral JSON Schema projections, result normalization,
  timeouts/cancellation, process-death handling, and deterministic shutdown.
  Server descriptions, annotations, schemas, and results remain untrusted;
  discovery exposes nothing automatically. A disposable fake server proves the
  complete handshake/list/approval/call/drift/failure path. The reviewed
  official GitHub MCP Server profile is native stdio, read-only, and limited to
  `get_me`, `get_file_contents`, `issue_read`, and `pull_request_read`, with no
  write, dynamic, or experimental tools. Disposable acceptance verified the
  official v1.12.0 Linux binary and its exact four-tool catalog without
  approving any tool. A later disposable live acceptance used a masked,
  non-persisted fine-grained PAT to call only approved `get_me` and
  `get_file_contents` operations against the public `github/github-mcp-server`
  README; no write tool was projected and cleanup preserved canonical runtime.
  No
  arbitrary-server UI, remote HTTP MCP, automatic download, Remote Chat MCP,
  write-capable GitHub integration, MCP chaining, or Agent Plugins were added.

- Added a lightweight, local-only skills.sh discovery service. It uses the
  verified bounded public `https://skills.sh/api/search` catalog endpoint,
  normalizes only syntactically valid GitHub candidate records, limits query,
  result count, timeout, response size, redirects, and host scope, and keeps
  catalog names, descriptions, popularity, links, and metadata explicitly
  untrusted. Discovery records are ephemeral and expose no install, enable,
  invocation, grant, or executable authority. A local Conversation shortlist
  and `skill_admin_cli search` return application-owned summaries; choosing a
  stored candidate passes its unverified conventional source mapping only into
  the existing GitHub commit-pinning, quarantine, inspection, one-use
  install-disabled proposal, and separate enablement flow. Remote origins are
  denied before network use. The public local-client response currently has no
  pinned commit or authoritative package directory, so a `skills/<skillId>`
  convention is marked unverified and GitHub inspection fails closed if it is
  wrong. No marketplace installation, automatic update, Agent Plugins, MCP,
  self-learning, or downloaded-code execution was added. Isolated live
  acceptance searched `pdf`, selected `anthropics/skills/pdf`, resolved commit
  `41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f`, inspected
  `skills/pdf` at tree digest
  `sha256:dbc5f8574b7b57c040d612d181d84851bede97413e0736de7dbc6515f41dcdc5`,
  installed disabled, separately enabled, and invoked generic guidance. Its
  eight bundled scripts remained inert; no third-party code executed.

- Added a standard-library, public-GitHub-only acquisition path for reusable instruction Agent Skills. A local user can supply a common `github.com/OWNER/REPO/tree/REV/path` URL; Tori resolves the revision through GitHub to an exact 40-character commit, downloads a bounded archive only from approved GitHub API/codeload endpoints without ambient proxies or credentials, and extracts only the selected package into owner-private disposable quarantine. The existing importer then rejects links, special files, escapes, malformed or oversized packages and hashes every selected byte without executing repository or Skill content. Application-owned inspection summaries expose exact provenance, digest, compatibility, package components, declared license, requested permissions and risk notes. One-use, origin-bound installation proposals bind those inspected bytes and current registry revision; approval publishes only that package as `installed_disabled`, while a second exact proposal and approval is required to enable it. Clear local Conversation requests and the local Skills CLI share the service; Remote Chat is denied before network access. Real isolated acceptance acquired `obra/superpowers` `skills/verification-before-completion` at commit `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`, produced tree digest `sha256:a7ba9c47acd79ec2a77265c5285128f74b6e812837b6eb71420a3bdbd37a80ba`, installed disabled, separately enabled, and invoked it through the generic instruction adapter; its package contained only `SKILL.md`, and no downloaded code executed. The package does not declare a license field; the pinned upstream repository carries an MIT `LICENSE`. Private repositories, tokens, marketplaces/skills.sh, automatic updates, generic executable loading, Agent Plugins, MCP and self-learning remain deferred.
- Added a standard-library Agent Skills importer for explicitly selected local directories and already-staged Git snapshots bound to an exact repository, commit, and package subdirectory. It validates portable `SKILL.md` frontmatter, canonical name/source identity, bounded UTF-8 guidance, every regular package file, per-file and whole-tree SHA-256 evidence, and rejects symlinks, special files, path escapes, malformed packages, unsafe collisions, and oversized content. Installation atomically publishes owner-private immutable package bytes but remains disabled until a separate local enable action. Enabled instruction Skills use one generic application-owned adapter and metadata-based selector; only the selected `SKILL.md` body is loaded into a prominently untrusted bounded Conversation context, while references/assets are never injected and all bundled scripts or executable-looking files remain inert. A local JSON CLI provides inspect, install, list/show, enable, and disable operations; Web loads an existing canonical registry read-only at startup but never creates or auto-enables one. Acceptance used pinned upstream Anthropic `doc-coauthoring` and NousResearch Hermes `grounded-citations` snapshots; the latter is honestly partial because its references and citation-ledger scripts are preserved but not activated. No third-party code executed. Agent Plugins, Git fetching/downloading, MCP, marketplace/discovery, executable importing, automatic updates, backup integration, UI administration, secrets, and self-learning remain deferred, so Skills V1 is still incomplete.
- Implemented `media.inspect` as the first bounded real Skill on the generic Skills V1 lifecycle and permission boundary. Its built-in immutable manifest requests only one opaque selected-file read and the exact `/usr/bin/ffprobe` adapter; install remains disabled until explicit enablement with both grants. Tori opens one normalized absolute regular file through component-by-component no-follow checks, retains its descriptor identity across replacement, and exposes only that descriptor read-only inside a fresh Bubblewrap namespace. The adapter uses fixed argv without a shell, a minimal environment, no network/secrets/writes, wall/CPU/address-space/process-family/output bounds, system-image ownership and mode checks, FFprobe version plus SHA-256 drift admission, bounded UTF-8/JSON validation, and a closed normalized result. Local Web can route an explicit media-inspection request with an exact path through the generic Skill service without provider path authority; disabled, under-granted, changed, malformed, unsupported, over-limit, unavailable-isolation, and Remote-origin cases fail closed. Tests and administration use disposable storage; no canonical Skill registry is initialized. External Agent Skills/Plugins import, MCP, acquisition, marketplace behavior, secrets, updates, and self-learning remain deferred, so Skills V1 is not complete.
- Added the Skills V1 Core Foundation behind Tori-owned authority. A closed normalized manifest records canonical identity, immutable version/digest, provenance, component/operation schemas, requested permissions, requirements, and inspection evidence; external descriptions and instructions remain untrusted data. An owner-private, no-follow, exact-schema SQLite registry separates immutable manifests from revisioned lifecycle/grant state, installs disabled, enables only an exact version/digest, supports disablement and tombstoned uninstall, and survives restart without touching canonical runtime in tests. The closed six-kind permission vocabulary distinguishes requests from grants and is enforced again at invocation. Local-only typed origin operations, an application-registered component adapter contract, normalized `CapabilityResult` validation, and generic enabled-operation awareness prove that compatible Skills do not need Skill-specific authority code in Tori core. That foundation slice added no production Skill, executable loader, external Agent Skills/Agent Plugins importer, MCP, network access, secret broker, marketplace, automatic update, self-learning, or Remote Chat Skill authority.
- Implemented and adversarially corrected Remote Chat infrastructure Slice 2 without a Discord SDK, connection, credential, or public listener. The transport-neutral `RemoteChannelPort` and fake adapter exercise an authorized synthetic `discord_remote` envelope through the shared `ConversationTurnService`, normal Tori identity/provider/curated-Memory path, and one dedicated browser-independent `Remote Chat` archive proven by a reservation-specific archive marker. Exact identity checks precede retention; immutable replays converge while changed replays fail closed; interrupted generation uses exact admitted-turn archive correlation rather than regeneration. Remote Search consent is limited to the exact immediate continuation turn and preserves bounded weather-location clarification. Upcoming reminders remain a bounded read projection, and all other operations remain denied by typed origin authority before their handlers.
- Added kernel-locked compare-and-swap private configuration, monotonic durable connector generations, and one application fence spanning admission mutation, archive-plus-outbound publication, and final adapter send-entry authorization. Disable, administrator revoke, kill, token rotation, and token clear fence older work across restart and later re-enable. The ledger separates a 4,000-character transport-neutral logical reply bound from durable ordered physical chunks under the adapter-advertised limit; acknowledged chunks are never resent, interrupted sends become ambiguous, and unsent tails are suppressed. Clean shutdown now drains the worker, reconciles current-generation `processing` and `sending`, verifies no in-flight durable state remains, and clears ephemeral Search/weather continuations before it may report success. Unprovable delivery terminalization or cleanup enters observable Error and still stops transport. Adapter preparation occurs outside the application fence; immediately before irreversible entry, the adapter invokes a narrow Tori-owned authorizer that atomically checks the fence and performs the durable `pending`-to-`sending` claim. The fake exposes deterministic preparation, authorized-entry, and completion barriers proving both kill-before-entry suppression and kill-after-entry ambiguity. Verified backup covers the full admission window; unsafe existing SQLite sidecars fail closed; disabled/incomplete configuration does not initialize Remote runtime. The CLI retains no-argv/no-readback token handling and owner-private no-follow storage. Real Discord transport/dependency review, private bot setup, and live Discord acceptance remain Slice 3 work; Remote Chat V1 is not complete and no current Tori runtime is enabled.
- Added the first infrastructure slice for the accepted Remote Chat architecture without adding Discord behavior or dependencies. A presentation-neutral `ConversationTurnService` now owns real ordinary complete/stream model turns, bounded context retrieval by origin, conservative typed-operation dispatch, and process-wide admission; Web delegates its provider-facing turn instead of owning a second generation path. Immutable application-owned origin carries explicit chat/revision inputs, the initial six-operation future `discord_remote` ceiling was deny-by-default independently of wording, and local proposals are bound to their creating origin. The accepted final ceiling is seven operations because `remote_chat.terminate_self` was later added as an authority-reducing operation. The former Web-private foreground/quiet gate is now an application-level coordinator composed above Web in production. Remote Search/upcoming-reminder handlers, durable Remote Chat state, and transport were unimplemented at this historical slice.
- Polished the bounded weather presentation and consent path without changing SearXNG configuration or Search authority. A missing location is now a short-lived, conversation-bound clarification rather than consent: a natural-language location reply restores the original weather period and asks the normal Search approval question before transport, while an explicit `/search` request remains directly authorized. Fahrenheit presentation converts isolated Celsius values, numeric ranges, and bounded qualitative Celsius decades without mixed-unit output. Multiple matching structured weather engines now contribute bounded provenance under one state-qualified visible SearXNG source record rather than duplicate indistinguishable entries.
- Repaired bounded temporal weather handling without changing Search provenance or provider fallback. Explicit weather requests now outrank the generic Planning/Today reader; Tori separates a canonical requested location from `current`, `today`, `tonight`, or `tomorrow`, retains both through Search consent, and selects bounded forecast entries in the validated source timezone. Forecast providers with a shortened city name are accepted only beside a nearby exact state-qualified structured record; wrong locations and malformed timezone/data remain rejected. Locationless weather receives the local, non-mutating clarification “What location should I check?”. The existing Fahrenheit Memory presentation applies consistently to forecast answers. The Host card now renders CPU, RAM, GPU, and optional VRAM as compact label/value rows without changing telemetry or refresh behavior.
- Repaired initial weather-query handling without changing Search provenance or provider fallback. Tori extracts a requested location from ordinary weather phrasing before calling SearXNG's specialized weather category. At a glance also has a compact read-only Host card: CPU and RAM are local kernel measurements, while a fixed, timeout-bounded `nvidia-smi` probe adds per-GPU utilization and VRAM only when safely available. Its dedicated endpoint is server-cached for five seconds, so unavailable telemetry cannot affect Conversation or fast attention polling.
- Polished the current workspace without adding a capability: primary navigation now calls the current reminder workspace **Reminders**, retains existing legacy task records under **Reminders & legacy tasks**, and no longer invites creation of new legacy task records. At a glance keeps compact local connection state, useful Upcoming schedule, and meaningful active Coding Work/activity, while removing duplicate model/context, empty Project, unfinished Planning, and duplicate Quick Actions cards. Projects and Planning code/data remain preserved but deferred rather than advertised as completed workspaces. A provider-emitted leading `Web findings` heading is now removed before Tori adds its single authoritative heading; Search routing, provenance, and synthesis are unchanged. The reverted generation-profile experiment's unreferenced runtime artifact was removed only after proving that current code/configuration has no reader or writer for it.
- Repaired two bounded conversational follow-ups without changing provider fallback. A weather information question such as “What's the weather in Exampleville Illinois?” is now treated as inherently current, enters the existing Search-consent flow, and strips that exact conversational lead before strict structured-location matching. An incomplete “Remember to … at TIME” request now keeps a conversation-bound, one-reply reminder draft so `today`, `tonight`, or `tomorrow` resolves deterministically without model interpretation; unrelated replies discard the draft without mutation. Fahrenheit Memory presentation, Search provenance, date/time validation, and provider failure handling remain unchanged.
- Repaired Coding Work provider quiescence after bounded terminal turns. The shared, owner-token-bound provider relay now closes after the last owned worker finishes, waits for listener/read activity to stop, verifies parent/marker/socket identity, and removes only its exact private Unix socket before publishing `completed`; failure, cancellation, launch failure, and startup recovery use the same fail-closed ownership boundary. Verified backup still rejects every live, foreign, replaced, or otherwise unsafe socket. Also corrected the fast `/api/attention` retry loop exposed when a due Reminder followed a zero-turn Coding Work result: that explicitly valid mixed application event now reopens and delivers idempotently, and unexpected local GET failures log only the route and exception class for safe diagnosis.
- Corrected OpenCode bounded-turn terminalization. ACP `end_turn` now initiates orderly worker containment and publishes `completed` only after the strict private snapshot import succeeds; a failed import remains failed and blocks backup. Explicit authority-required pauses remain actionable `waiting` states, while further work after a terminal turn uses the existing fresh-authorization continuation path. Restart reconciliation recognizes only the exact historical `model_turn_complete` plus `workspace_snapshot_observed` evidence pair, so previously stranded legitimate turns converge without treating arbitrary waiting records as successful. Disposable real OpenCode 1.18.21 acceptance completed a read-only, tool-using Git inspection with no workspace or canonical-runtime change.
- Surfaced durable Coding Work terminal outcomes in the Workspace card. A browser already observing active work now retains that same card when its canonical state becomes `completed`, `failed`, or `cancelled`, with concise authoritative wording and bounded Details. Historical terminal rows remain inspectable through the existing status projection but do not become new notices after a browser reload; repeated polling and concurrent browsers remain read-only and idempotent. No chat/archive notification, worker lifecycle, backup guard, or private-state policy changed.
- Completed the Coding Work snapshot-output lifecycle repair: a private, inode-pinned snapshot scope is armed before each owned launch; after process-group and reader cleanup, a bounded import validates all incoming objects before normalizing only regular-file permissions to `0600`. Git sample hooks, read-only objects, and an index copied with source permissions no longer strand later startup/backup after orderly finalization. Existing unsafe trees cannot arm this scope; symlinks, hardlinks, ownership/type/mode violations, and root replacement fail closed. Source bytes, workspace permissions, executable bootstrap sources, and the strict runtime validator are unchanged. Shutdown waits for finalization, and pending/failed imports block backup and workspace reuse. A forced host/application death before finalization can still require explicitly authorized recovery; startup never sweeps historical runtime.
- Fixed verified-backup error translation: Coding Work layout validation may fail before ownership acquisition or while an existing owner enters maintenance. It now produces a safe `backup_unsafe` outcome rather than escaping as a generic HTTP `internal_error`. An owned guard revalidates private state before copying; active writers, incomplete imports, unsafe state, and failed verification never bypass publication gates. Disposable native OpenCode 1.18.21 acceptance and copied-runtime backups verified the lifecycle without producing a production backup or changing canonical state. Exact version pinning and the validated-update requirement remain intentional.

- Extended bounded RAM/free-memory recognition with “available” formulations, without colliding with curated Memory requests. Added deterministic local civil-time reminder word orders for “Set a reminder to … at TIME today” / “… today at TIME” and “Remind me to … at TIME today”, preserving timezone/DST validation and existing Planning confirmation behavior. Flexible interpretation failures now log only a safe provider-versus-invalid-interpretation category, never prompts or provider output.
- Corrected offline bootstrap copying so newly created per-work private files are `0600`, while immutable bootstrap-source executable modes remain unchanged. Added Git-shaped copy/security tests and a disposable real-Git reproduction. **Partial Coding Work repair only:** Git snapshot creation itself still conflicts with exact private-file modes (sample hooks `0700`, objects `0400` under umask `077`; indexes can become `0664` under umask `002`). The configured OpenCode executable was unavailable for tracing the precise historical invocation. No validator relaxation, runtime normalization, live configuration change, dependency change, or packaging was performed.

- Repaired Web Search attribution after provider synthesis: Tori retains strict rejection of invented, unknown, and malformed source references, but no longer rejects a useful answer solely because a local model omitted its fragile inline citation syntax. The application now appends a clear provenance disclosure and rebuilds the visible source list from the exact retrieved records it owns. Backend-unavailable, malformed-result, synthesis, invalid-citation, and attribution-format failures are reported as distinct safe outcomes. Conversational question leads are removed only from the SearXNG backend query; the original request remains the consent, archive, and synthesis record.
- Improved SearXNG retrieval with application-owned category routing: ordinary searches use `general`; clear weather/forecast, explicit news, and verified deployed computing searches use the bounded `weather`, `news`, and `it` categories. Tori continues to reject model-selected categories, engines, and bangs. It now safely represents deployed structured weather evidence as SearXNG-service provenance without inventing a webpage URL, and can normalize payload-backed infobox records while retaining current attribution validation.
- Repaired category-specific SearXNG relevance: weather now sends the requested location rather than conversational framing and accepts structured weather only when the returned location matches it; versioned technical searches make at most one deterministic `it` → `general` retry when the specialized category returns too little exact subject/version evidence; and current-news selection skips malformed candidates, excludes clearly stale dated records, and ranks fresh dated evidence. No engine/bang selection, model reranking, or attribution relaxation was added.
- Repaired durable-preference routing: explicit natural-language Memory directives now receive the existing verified Memory receipt rather than falling through to a provider promise. Timed `Remember to …` requests remain reminders, while ambiguous requests clarify without mutating either subsystem. A saved Fahrenheit weather preference deterministically converts explicit Celsius measurements only in validated structured-weather presentation; source evidence and attribution remain unchanged.
- Repaired capability-aware conversation routing (2026-09-02). One provider-neutral registry now projects existing application capabilities/current configuration into compact model context and truthful capability-status replies. Advisory speech-act classification separates discussion from operational handling without supplying executable arguments or mutation authority. Casual work talk and reminder questions no longer enter task mutation; local task writes independently require the requested operation family. Explicit natural Memory creation uses the existing policy, RAM paraphrases use deterministic host reads, and OpenCode audit requests retain bounded proposals/confirmation. Finance and CalDAV awareness describe their actual supported scope. Memory management lists newest first without rewriting storage.
- Corrected Search permission continuation when time/Project context is present: a valid external-information advisory can create the existing one-use proposal, and “Yes please” retains the original query in evidence context. Empty retrieval is an application-owned no-results notice without model synthesis; provider synthesis failure after retrieved sources is reported separately with no silent fallback. No dependency, runtime schema, live configuration, packaging, or capability authority was added.
- Restored completed Finance V1 on the live installation by reattaching its preserved, externally stored workbook root; portable Finance remains disabled and contains no owner path or data. Production verified backups now use Coding Work's existing exclusive coordination boundary, including safe snapshots of dormant post-restart `reconciling` records while live workers, active mutations, and provider sockets still fail closed. Restart reconciliation now processes records already left in `reconciling` and truthfully terminalizes a run whose authorized workspace has disappeared instead of stranding all Coding Work readiness. Recovery tests prove that Project creation/association accepts legitimate retired Deep Research metadata without rewriting transcript rows, and Project field-validation errors are no longer mislabeled as invalid chat data.
- Restored the tracked live-machine `tori.toml` after closeout accidentally substituted clean-install defaults: LM Studio, Coding Work, Search, TTS, and Planning again use their last known-working configuration. Qwen and SearXNG now retain loopback defaults but accept bounded numeric RFC1918 endpoints; public, link-local/metadata, credential-bearing, and malformed roots still fail closed. Portable packaging now replaces `tori.toml` only inside disposable `/tmp` staging with the reviewed `deploy/portable/tori.toml` template and regression-tests live-config/runtime preservation, sanitizer failure, and cleanup.
- Restored bounded read compatibility for the four explicitly enumerated application-event types written by Tori's retired uncommitted Deep Research experiment. Historical `deep_research_started` and `deep_research_result` rows now pass their original provider-free sequence rules without a schema migration or row rewrite; arbitrary types, malformed ID/type pairing, invalid sequences, and attempts to write new retired events still fail closed. Added `start-tori.sh` as a root-relative, signal-preserving convenience launcher and made it the portable installer's primary startup instruction.
- Closed Tori V1 as feature-complete and placed the project in maintenance mode on 2026-08-31 without changing the seven founding documents or manufacturing acceptance for the historically frozen Milestone 25.
- Added `docs/USER_GUIDE.md`, a practical code-grounded guide covering installation, startup, Conversation, providers, memory, Knowledge, Search, Finance/Budgeting, Planning, Scheduled Work, Projects, system/service controls, Coding Work, backups, Settings, LAN/mobile use, privacy, troubleshooting, and limitations.
- Added `docs/FINAL_STATE.md` to distinguish final implemented capability, safety/data locations, operational dependencies, maintenance policy, and intentionally deferred ideas from historical plans.
- Closeout initially replaced tracked host-specific configuration with a portable localhost-first `tori.toml`; the resulting live-machine regression is corrected by the entry above. The accompanying generalized OpenCode verification paths, sandbox home-boundary checking, Radicale documentation, and Ollama sudoers installation template remain valid portability improvements.
- Added `scripts/create-clean-portable-archive` and focused tests. The tool requires a clean committed source, exports the exact committed tree into disposable `/tmp` staging, rejects runtime, virtual environments, secrets/caches/databases/sidecars and symlinks, checks current-machine identity text, creates the ZIP outside the source, intentionally omits Git history containing retired machine identifiers, and cleans staging on success or failure.
- Deferred Deep Research V1. The committed technology audit and design contract remain available for a future reconsideration, while the experimental uncommitted application, canonical Research runtime, owner-local configuration, and external worker environments were removed. Free/no-account discovery reliability was not sufficient for live product acceptance: the remote SearXNG defaults produced zero candidates, direct DuckDuckGo and Mojeek paths were unreliable, 4get required CAPTCHA cookie state, and Local Deep Research also failed the free-search gate. Normal SearXNG-backed Web Search is unchanged.
- Implemented Finance V1 as a local-first, disabled-by-default budgeting notebook behind `FinanceService` → `FinanceRepository` → `WorkbookFinanceRepository`. The user selects an external data root and explicitly confirms initialization; the human-readable `.xlsx` workbook has the seven contracted sheets, exact decimal financial semantics, opaque content revisions, atomic replacement, and post-write verification without any Finance-domain schema or workbook data beneath canonical runtime. Ordinary Finance conversation events continue to use the existing Conversation archive.
- Added deterministic spending, category/merchant trend, upcoming-bill, debt/APR, affordability, payoff, and goal calculations plus stale/missing-data warnings. Bounded Finance conversation reads bypass the model provider, while all durable initialization/import/record changes remain one-use, conversation- and workbook-revision-bound confirmations using the existing Web authority envelope.
- Added preview-only CSV and XML OFX/QFX imports through one normalized candidate pipeline with deterministic merchant rules, count-aware committed and same-batch source-ID duplicate detection, bounded unresolved-item review, source/candidate digests, and source movement only after verified commit. Finance slash commands are registered through the existing local command boundary; reviewed reusable rules and exact candidate corrections remain transient until the final import confirmation. Legacy non-XML OFX/QFX and arbitrary PDF statement parsing remain truthfully deferred behind fail-closed adapter boundaries.
- Human acceptance verified confirmed external-root initialization, ordinary seven-sheet workbook readability, safe rejection of an incorrectly mapped CSV, a 22-row reviewed import with one repeated-source-ID duplicate excluded and two durable merchant rules, verified movement to `processed`, manual spreadsheet coexistence, reuse of persisted rules on a historical import, and deterministic spending, bill, debt, affordability, payoff, and three-month trend results. A unique case-insensitive debt shorthand now resolves an active debt while ambiguity fails closed. The live synthetic acceptance conversation was correctly archived; a read-only audit confirmed it was not automated-test contamination, and the focused Web test now injects a disposable conversation archive.
- The Finance V1 completion gate ran 1,226 offline tests with 1,222 passes and four honest skips (the namespace-dependent Bubblewrap probe and three opt-in real-Radicale gates), parsed every project Python file, validated all seven packaged JavaScript files, preserved the founding-document blobs, and confirmed the complete canonical runtime tree was unchanged.
- Added Personality / Interaction V1 as a compact, deterministic, provider-neutral Tori-core boundary. One bounded mandatory system message follows the stable runtime identity and guides the same Tori to leave more room for warmth and natural humor in relaxed conversation, prioritize progress during ordinary work, and lock in for serious Project, planning, troubleshooting, and tradeoff work. It adds no persona or predefined personality mode, classifier, second model call, per-turn retrieval, persistent personality state, memory mutation, capability authority, or confirmation bypass.
- Added focused structural and conversation-path tests plus a lightweight human-evaluation checklist covering casual, working, and Project/planning situations. Automated checks prove message placement, boundedness, provider neutrality, single-call behavior, context separation, and unchanged authority boundaries. Initial human conversational acceptance found better continuity, natural follow-up and curiosity, and personality without forced humor; broader situational evaluation remains evidence-driven.
- Corrected conversational Project entry so discussion is not treated as creation authority. Explicit discussion remains ordinary conversation; ambiguous potential-Project intent receives a concise create-or-discuss clarification in chat, and only a clear create answer advances to the existing formal proposal and confirmation boundary. The pending choice is conversation-scoped and process-local, adds no model call or schema, and creates no Project or durable authorization. Live acceptance confirmed that cancelling the formal confirmation leaves no Project created.
- Corrected bounded host-information recognition so clear conversationally wrapped RAM and disk-space requests remain deterministic and bypass provider generation, while non-request mentions remain ordinary conversation.
- Made the Conversation provider/model/context status strip more compact while retaining its model selection control on narrow screens. Transcript messages now show a subdued browser-local timestamp only when their existing authoritative archive timestamp is available; no timestamp is invented for unpersisted or legacy entries. The final responsive spacing cleanup keeps a small intentional gap between the compact strip and transcript.
- Added a configuration-managed `LM Studio` profile through the existing generic OpenAI-compatible provider boundary at the local loopback `/v1` API. It remains separate from the selected Ollama baseline, receives the same Tori-owned context and authority behavior, and never falls back silently. Built-in local profiles are now operationally editable but retain stable identity and deletion protection; per-profile catalog failures are isolated; optional bearer tokens can be replaced or cleared from Settings and are stored only in an owner-private server-side file (with the existing `LM_API_TOKEN` environment reference as fallback), never returned to the browser. Human acceptance entered a local LM Studio token through Settings, verified authenticated streaming conversation with `lm_studio/gemma-4-12b-it`, and verified token usability after a Tori restart; Local Ollama remained independently healthy.

- Added a bounded conversational System capability surface for native disk-usage and local/LAN IPv4 address inspection plus allowlisted Brave launching. Disk and network reads do not require confirmation or contact an Internet service; Brave uses only an exact trusted executable and argument-vector process launch. Requests outside this surface continue through the existing supervised `/run` command path, with no model-owned shell authority or persistent system-capability state.
- Added focused recognition, native capability, failure-boundary, allowlist, no-shell, and Web integration coverage for realistic System requests and general-command fallback. Live streamed acceptance after a fresh Tori restart returned truthful disk usage, local LAN addresses, and the bounded Brave launch response; no browser or host package changes were performed by the capability.
- Extended the same bounded System surface with read-only RAM, CPU, GPU/VRAM, uptime, allowlisted Ollama and Radicale/Planning status, and Tori health answers. RAM/CPU/uptime use native Linux/Python sources; GPU status uses a fixed trusted `nvidia-smi` query with `shell=False`; local status reads do not contact the Internet and need no confirmation.
- Added deterministic coverage for status parsing, multiple GPUs, bounded unavailable behavior, known-service allowlisting, truthful internal health projection, false-positive recognition, and supervised general-command regression. Live Web acceptance passed the seven requested status prompts against the production host: RAM/CPU/uptime were reported, `NVIDIA GeForce RTX 3090` was detected with plausible VRAM/utilization/temperature, Ollama and Radicale/Planning were reachable, and Tori truthfully reported Coding Work reconciliation as degraded.
- Extended the same System boundary with allowlisted Brave, Dolphin, terminal, LM Studio, and existing-directory opening, plus confirmed start/stop/restart actions for the actual `ollama.service` system unit and `tori-radicale.service` user unit. Desktop actions use fixed trusted executable vectors without confirmation; service actions use exact one-use conversation-bound confirmation, fixed `systemctl` vectors with `shell=False`, bounded failure handling, and post-action local verification. Arbitrary apps, folders, services, units, and Tori self-restart remain unavailable.
- Added the narrow root-owned `/usr/local/libexec/tori-ollama-service` deployment helper and exact-action sudo policy source for Ollama only. Tori invokes it with fixed `sudo -n` argv after its existing confirmation; the helper accepts only start/stop/restart and permanently targets `ollama.service`. Radicale remains unprivileged `systemctl --user` control, and no general sudo or systemctl authority is added.

- Deployed and live-accepted the Planning capability with native Radicale 3.7.8 as the persistent `systemd --user` service `tori-radicale.service`, bound only to `127.0.0.1:5232`. Production Tori now enables Planning against persistent `Tori Tasks` and `Tori Calendar` collections under `%h/.local/share/tori/radicale/collections`; Radicale data remains outside the canonical runtime and current backup scope. Desktop and physical iPhone portrait acceptance passed, including restart persistence and real VALARM → Reminder Bridge → Scheduled Work → Tori attention delivery.
- Corrected the live `make cookies` acceptance defect: the request had reached a Planning proposal but had not been confirmed, so it had created neither a CalDAV VTODO nor a legacy task. Confirmed Planning tasks now appear once in Open Tasks and Upcoming after projection refresh, and the legacy Tasks & reminders surface is labeled explicitly as legacy rather than presenting a competing ordinary todo path. Calendar navigation now presents the selected date separately from the Today jump action. Acceptance objects were cleaned up through normal Planning confirmation flows; full month/week grids, provider integrations, and other deferred scope remain unchanged.
- The final source-change verifier completed 1,118 offline test cases with 1,114 non-skipped passes and four honest skips (the namespace-dependent Bubblewrap probe and the three opt-in real-Radicale gates), parsed project Python, validated packaged JavaScript, preserved founding-document blobs, and confirmed canonical runtime integrity.
- Added one compact Planning Workspace module to the existing desktop utility rail and mobile utility sheet. Today combines timed/all-day events, due tasks, and overdue tasks; Upcoming groups a bounded seven-day agenda; Tasks filters Open, Due, Overdue, and Completed; Calendar provides a fourteen-day server-expanded agenda window with nearby-day navigation. Empty, loading, and unavailable states are explicit.
- Added a read-only `/api/planning` projection that queries fresh `PlanningService` truth, expands recurrence server-side, formats local civil times and human reminder/recurrence summaries, bounds payloads, and omits UIDs, ETags, CalDAV URLs, raw iCalendar, and Scheduled Work identities. The established modest polling cadence refreshes external edits without browser persistence or blocking Conversation.
- Planning Workspace Add Task/Event/Reminder, Done, Edit/Reschedule, and Delete/Cancel controls feed the existing conversational Planning proposal and confirmation path. No direct Planning mutation endpoint, CalDAV JavaScript, browser recurrence engine, or browser-owned authority was added. Responsive DOM/CSS/Node tests cover the shared desktop/mobile module; subsequent live desktop and physical iPhone portrait acceptance passed.
- Added normal Conversation access to Planning through a bounded Tori-owned `PlanningConversationService`. Read-only Today, upcoming/date-range, open/due/overdue/completed-task, and calendar queries fetch current `PlanningService` truth directly without model contact or confirmation and return compact local-time results without UIDs, ETags, URLs, or raw iCalendar data.
- Added one-use, five-minute, originating-chat-and-revision-bound Planning proposals for creating tasks, standalone VTODO reminders, and events; rescheduling or changing due time, recurrence, and event reminders; completing tasks; and deleting/cancelling items. Existing-object proposals capture an opaque `PlanningRevision`, confirmation rereads canonical state, and an external CalDAV edit rejects the stale proposal without overwrite. Ambiguous references and unresolved times never mutate.
- Added common civil-time and recurrence interpretation for today/tomorrow/weekdays, explicit clock times and ranges, all-day events, daily/weekly/every-N-day/every-N-week/named-weekday RRULEs, finite counts, and exact until dates. At-due reminders use a zero-offset relative DISPLAY `VALARM`; absolute alarms, vague dayparts for mutations, recurrence exceptions, and broad natural-language interpretation remain intentionally unsupported.
- Successful confirmed mutations use only `PlanningService` and then reconcile through `PlanningReminderBridge`; Conversation never writes CalDAV or derived Scheduled Work directly, and model output has zero Planning authority. Planning-unavailable reads/proposals/confirmations fail truthfully without a shadow record or offline queue.
- Extended the native disposable Radicale gate through full Conversation behavior: confirmed task create/read/complete/delete, event-plus-reminder create/upcoming-read/reschedule/cancel, derived Scheduled Work movement/cancellation, external CalDAV edit visibility, stale-proposal rejection, and cleanup using temporary Planning, Scheduled Work, and archive state.
- Added `PlanningReminderBridge` and a non-interactive system-derived Scheduled Work capability. Canonical CalDAV VTODO/VEVENT alarms now reconcile into one-shot delivery entries with deterministic object/alarm/occurrence identities, idempotent no-op behavior, revision-safe rescheduling, removal/deletion/completion cancellation, bounded recurrence expansion, external-edit reconciliation, and preservation of derived state when either backend is unavailable. Existing Scheduled Work execution and application-event delivery remain the only delivery path; no bridge ledger, second scheduler, model authority, or planning-store duplication was added.
- Added focused bridge tests and extended the opt-in real Radicale gate to prove create/no-op, external event-time movement, one derived execution, next recurrence materialization, VALARM removal cancellation, delivery plumbing, and disposable cleanup.
- Added Tori-owned Task, Event, recurrence, reminder, collection, revision, `PlanningPort`, and presentation-neutral `PlanningService` contracts. No model tool or conversational mutation path was added.
- Added the first replaceable CalDAV adapter using pinned `caldav` 2.2.6 and standard VTODO, VEVENT, RRULE, VALARM, UID, and ETag mapping. Expected revisions are checked and sent with `If-Match`; a changed external ETag fails as a bounded conflict instead of overwriting.
- Added optional `[planning]` configuration and `PlanningRuntime` composition. Disabled, reachable, and unavailable states are truthful; missing credentials or an unreachable backend do not stop ordinary Tori startup and no local shadow write claims success.
- Added a native real-Radicale 3.7.8 integration gate using an ephemeral IPv4-loopback port and disposable `/tmp` collection storage. It proves task create/read/update/complete/delete, event create/read/update/delete, weekly/daily recurrence, 30-minute DISPLAY alarms, external-edit conflict/reload, and complete cleanup without canonical runtime mutation.
- Documented CalDAV as the replaceable boundary, Radicale as the first backend, Scheduled Work as derived reminder delivery, deterministic bridge reconciliation, future external-client synchronization, user-service deployment direction, and out-of-scope backup storage. No founding document, M25 behavior, Planning UI, conversational mutation authority, SQLite planning store, migration, Docker deployment, or host service was added.
- The single broad verifier completed 1,117 offline test cases with 1,113 non-skipped passes and four honest skips (the namespace-dependent Bubblewrap probe and the three opt-in real-Radicale gates), parsed every project Python file, validated all seven packaged JavaScript files, preserved all founding-document blobs, and confirmed the complete canonical runtime tree was unchanged.

- Completed Tori's first successful deliberate human-authorized canonical Coding Work acceptance. After commit `a79da3f` repaired restored-waiting Cancel dispatch, the user explicitly cancelled `coding-work-bd188c60352789f61b96a0696568a9bb`; canonical cancellation reached `cancelled`, stopped the restored session, and released `/tmp/tori-coding-work-acceptance-retry`. The user then submitted and deliberately confirmed the exact bounded replacement request through Conversation. Independent work `coding-work-153f4939714abef1da4cff7de40548b3` completed through the durable supervisor, Bubblewrap, OpenCode 1.18.21 ACP, the approved local relay, and `qwen3.8:latest`; `/workspace/acceptance.txt` changed from `before\n` to `after\n`, only `acceptance.txt` was reported, and canonical state settled at stable `waiting` without Cancel, reload, retry, erroneous `external_directory`, or parent-death SIGKILL. The primary desktop Workspace UI showed the real host workspace, truthful activity, changed-file evidence, and final state. Second-browser and physical-iPhone presentation checks were not performed.

- Corrected the restored-waiting Coding Work Cancel control after canonical evidence showed that a deliberate browser click created no cancellation directive or event and left the workspace owned. The Workspace utility now registers an explicit cancellation handler instead of relying on an unacknowledged document-level custom-event relay, takes the exact work ID and current work revision from each canonical status projection, posts through the existing `/api/coding-work/cancel` boundary, and keeps bounded request errors visible on the same work card across ordinary polling. The canonical cancellation path, revision checks, directive delivery, process containment, and workspace concurrency guard are unchanged. Deterministic disposable coverage now restores a persisted waiting OpenCode fixture session after application restart, cancels it to terminal state, and immediately admits independent replacement work on the same workspace. Final deliberate canonical acceptance remains pending.

- Corrected the Coding Work host-to-sandbox workspace-path mediation defect exposed by the first deliberate canonical retry after the durable Web process-ownership fix. Tori continues to retain and display the exact authorized host workspace in proposals, immutable authorization, canonical records, status, and host-side changed-file evidence, while OpenCode-facing objectives, acceptance criteria, and follow-up instructions now translate only that authorized root to the sandbox execution root `/workspace`. The worker prompt states that all workspace operations belong beneath `/workspace` and that the original host path is inaccessible identity metadata; OpenCode's `external_directory` denial remains enabled and no host mount, filesystem authority, network policy, provider, timeout, retry, persistence, or parent-death behavior changed. Focused Conversation/OpenCode/integration/supervisor verification passed, and one disposable full-Web production run kept its proposal and authorization bound to `/tmp/tori-coding-work-path-mediation` while OpenCode used its sandbox workspace, changed only `synthetic.txt` from `before\n` to `after\n`, reported `synthetic.txt`, reached stable `waiting`, and required no Cancel. The fourth canonical operation and all earlier evidence remain intact; another deliberate canonical acceptance is still pending.

- Corrected the Web-triggered Coding Work parent-death defect proven by privileged process and signal tracing. `ThreadingHTTPServer` confirmation previously reached `subprocess.Popen()` on its transient request-handler thread, so Bubblewrap's retained `--die-with-parent` protection delivered SIGKILL when that thread exited. Process creation is now synchronously handed to one durable, non-daemon, application-owned supervisor thread; request handlers may return while the sandbox continues, and normal cancellation, bounded Tori-issued termination evidence, passive reconciliation, and deterministic application shutdown remain intact. A focused real HTTP regression enables Linux parent-death signaling in its worker fixture and proves the handler can disappear while the process survives; a separate supervisor regression proves the durable thread owns the child and shutdown leaves none behind. One disposable full-Web production run then completed through Bubblewrap, OpenCode 1.18.21 ACP, the approved local relay, and `qwen3.8:latest`, changing only `synthetic.txt` from `before\n` to `after\n` and reaching stable `waiting` state after the confirmation response completed. The original historical ACP EOF remains irrecoverable; the later two full-Web SIGKILL failures are explained by the traced parent-death mechanism. No canonical CodingWork was created, and deliberate successful human acceptance remains pending.

- Restored the tracked production `[coding_work]` configuration with the existing canonical runtime, OpenCode 1.18.21, Bubblewrap, fixed loopback provider, `qwen3.8:latest`, and established bounded timeouts. Normal Web startup now reports Coding Work `ready` while Conversation remains on its configured model; this configuration-only check created no CodingWork or other canonical record, invoked no coding task, and leaves first deliberate human acceptance pending.

- Investigated the second runtime-reaching Coding Work acceptance failure without changing canonical state. That operation used the corrected bounded filename/change proposal but was accidentally confirmed, so it is not deliberate human acceptance; the supervised Bubblewrap/OpenCode process was observed exiting at `-9` / signal 9 before any workspace change, ACP reported `transport_eof`, and passive polling reconciled one durable failure idempotently. The issuer of SIGKILL remains unknown: the live timeline places Tori's clean shutdown more than two minutes after the process death, no cancellation directive or pre-existing terminal event existed, Web request completion does not own the worker, every relevant Tori TERM-to-KILL path was audited, and available journal/cgroup evidence showed no OOM event. A syscall-traced disposable Conversation-service/runtime production run and a final patched run both completed normally through Bubblewrap, OpenCode 1.18.21 ACP, the approved local relay, and `qwen3.8:latest`; the latter changed only `synthetic.txt` from `before\n` to `after\n`, reached truthful waiting state in about 28 seconds, remained revision-idempotent, and cleaned up. Process evidence now always records an exit termination classification, labels externally observed signals with unknown origin, and separately records a bounded Tori reason plus actual TERM/forced-KILL issuance when Tori controls containment. Both failed canonical operations remain intact, and first deliberate successful human acceptance remains pending.

- Ran the first real human-authorized Coding Work acceptance through Tori's production Web Conversation, one-use confirmation, canonical `CodingWorkRuntime`, Bubblewrap, and OpenCode path against a dedicated `/tmp` workspace. Tori produced the correct bounded proposal and durable authorization, created one CodingWork and native session, and exposed canonical Workspace status. OpenCode ACP then closed unexpectedly before changing the file; the supported revision-bound Cancel path collected the terminal observation as durable `failed` / `transport_eof`, zero changed paths, and bounded evidence. The retained provider journal proves the local model request completed with HTTP 200, while OpenCode's captured state contains an unfinished assistant turn and no tool use; the exact process-exit cause is not recoverable because the old failure path did not retain exit status or bounded stderr. The recovery now preserves bounded sanitized process-exit evidence, makes passive status reads idempotently collect departed-worker terminal events, and accepts legitimate schema-1 global revisions greater than one without relaxing exact schema checks. One disposable production-path Bubblewrap/OpenCode/local-model run subsequently completed the intended `before\n` to `after\n` edit and reached truthful waiting state. The failed canonical record remains intact; a successful human-authorized acceptance retry remains pending.

- Added a compact Coding Work card to the shared Workspace utility module. A bounded same-origin projection renders Tori-owned objective, exact workspace, canonical lifecycle meaning, latest meaningful activity, update time, changed paths, recent activity, and result summary without exposing OpenCode/ACP/process/provider internals. Details stay collapsed by default, empty state adds no permanent card, desktop and mobile reuse the same module, and periodic reads make browsers converge on canonical application state without browser persistence. Cancellation is revision-bound through `CodingWorkRuntime`; Continue is not exposed because it requires fresh authority, while pause/resume remains unsupported. First real user-authorized acceptance remains deferred.

- Added the first product-facing Coding Work conversation flow without exposing OpenCode or granting model-owned authority. Clear requests with one explicit existing workspace now produce a bounded Tori-owned proposal containing objective, optional acceptance criteria, exact workspace, capability, enforceable authority summary, and limitations. A provider-free archive event durably establishes originating-chat provenance; one-use process-local confirmation is revision- and expiry-bound, while cancellation, changed conversations/workspaces, missing workspaces, and unavailable runtime fail without execution. Explicit confirmation alone creates, authorizes, and starts work through `CodingWorkRuntime`; failures are reported from durable Coding Work state. Ambiguous requests remain ordinary conversation. Workspace preparation, GitHub, Git authority, pause/resume, autonomous coding, and periodic conversational status/control questions remain deferred.

- Integrated the committed Coding Work/OpenCode foundation into Tori's application lifecycle behind one explicit optional runtime facade. Configured startup now acquires canonical ownership, evaluates fail-closed readiness, opens exact schema 1, constructs the OpenCode/supervisor boundary, reconciles every nonterminal item before admitting new work, and deliberately releases contained resources and the kernel lock at shutdown. Unconfigured, uninitialized, unsafe, unready, or already-owned Coding Work does not break ordinary Conversation. A bounded Tori-owned status projection reports objectives, exact workspaces, lifecycle/worker meaning, authorization need, meaningful activity, changed paths, result summaries, and valid controls without ACP/process/provider internals; follow-up, cancellation, terminal continuation, and refresh use existing application/domain semantics. Pause/resume remains explicitly unsupported because schema 1 has no durable paused state, and missing workspaces remain refused pending a future narrow workspace-preparation authority. The completion gate passed all 1,048 offline tests with the one honest namespace-dependent skip and preserved canonical runtime. Conversation dispatch and the compact Workspace card remain separate next slices.

- Added a separately invokable, explicit OpenCode offline-bootstrap operation. It isolates HOME/XDG/config/workspace/tmp, fixes umask `0077`, validates OpenCode 1.18.21, invokes only `debug config --pure`, captures only regenerable data/cache/state roots, produces an owner-only bounded digest receipt with timestamp and provenance, and publishes prepared material plus receipt without replacement or merge. Default production execution refuses unless network-bearing provisioning is explicitly authorized; fixture tests prove staging, failure preservation, isolation, empty-domain behavior, per-work cache copying, and readiness rejection for missing, changed, substituted, oversized, symlinked, wrong-mode, wrong-version, wrong-package, or stale-digest material. Real disposable and canonical normal-host runs completed through Bubblewrap and the fixed `models.opencode.ai:443` relay without a model turn or session creation. Published OpenCode SQLite state is now inspected only through an owner-only disposable copy, including WAL/SHM/journal sidecars; the canonical tree digest remains unchanged across session inspection and readiness evaluation. Canonical bootstrap readiness passes while Coding Work remains empty and has no user-facing invocation.

- The final completion-gate verifier passed all 1,035 offline tests with one honest namespace-dependent Bubblewrap skip, parsed every tracked and untracked Python file, validated all seven packaged JavaScript files, preserved the founding documents, and confirmed the complete canonical runtime tree was unchanged. Previously accepted real OpenCode, provider-transport, restart/session, and Bubblewrap proofs were not repeated.

- Implemented the remaining temporary-state production gates for canonical Coding Work initialization without startup/UI wiring. A whole-layout initializer builds schema 1, the supervisor lock, stable private instance identity, and owner-only OpenCode skeleton in an unpredictable sibling, validates and fsyncs it, publishes with atomic no-replace semantics, and refuses existing, abandoned, symlinked, wrong-owner, wrong-mode, or unsupported layouts without repair. Runtime-wide nonblocking kernel ownership gates production mutations and coordinated shutdown releases workers and provider transport before the lock. Backups recognize the Coding Work database as SQLite and require a maintenance guard that refuses active/live harness writers or provider sockets before capturing the database and closed per-work durable OpenCode state as one generation. Separate explicit Coding Work configuration and readiness report uninitialized, unsafe/unowned, missing or wrong executables, unavailable exact provider/model, missing offline bootstrap, reconciling, or available states without fallback or network bootstrap. All initialization and backup tests use temporary roots; the separately authorized canonical schema-1 layout now exists and remains empty.

- Corrected the review-pending Coding Work/OpenCode foundation without initializing canonical state. OpenCode session/config/data state is now isolated per CodingWork; owned stale provider sockets recover through durable private-instance provenance while hostile, wrong-owner, and active paths fail closed; restart preserves the prior Tori observation and never turns an interrupted active model/tool turn into false waiting; and authorization cannot be replaced or narrowed beneath a live run. Durable events, supervisor observations, directive receipts, changed paths, and workspace hashing now have explicit retention and byte budgets with honest truncation/oversize evidence. Expected adapter setup failures after durable launch intent normalize to durable failure, SQLite reopen validates cross-record ownership, stale missing-run terminalization is refused, ACP handler failures wake pending calls and reject Boolean IDs, and provider responses are buffered before success with bounded concurrency. Deterministic temporary-state coverage was expanded; the already completed real Bubblewrap/transport/end-to-end acceptance was not repeated.
- Completed the disposable normal-host end-to-end acceptance for the production OpenCode Coding Work path using only temporary workspace, SQLite, and harness-private state. The real `qwen3.8:latest` flow created and authorized CodingWork through the application service, edited one synthetic file, persisted one stable OpenCode `ses_...` identity, stopped the first process, reconciled the same CodingWorkRun through a new adapter/supervisor, delivered one durable follow-up exactly once, produced the required final bytes, filtered internal ACP noise, and ended through process-contained cancellation. Integration corrections keep ACP `end_turn` as evidence-backed `waiting` rather than accepting harness self-report as terminal completion, preserve adapter event sequence ordering across process restart, precreate OpenCode's required private config metadata before its read-only mount, and retain safe bounded startup diagnostics for the opt-in security probe. The relay admitted only fixed-model chat-completions requests, rejected its administrative probe, and the sandbox could not reach an unrelated host service. Canonical runtime remained unchanged.
- Added the review-pending first production Coding Work harness adapter for OpenCode 1.18.21 without initializing canonical state or exposing the capability in Conversation/Web. The adapter composes the accepted process supervisor and Bubblewrap plan with ACP over inherited stdin/stdout, monotonic per-operation deadlines, bounded protocol and stderr handling, stable `ses_...` persistence/reload, restrictive authority-derived private configuration, the fixed-model Unix-socket provider relay, durable directive receipts, SIGTERM-to-SIGKILL cancellation, direct workspace evidence, and semantic event filtering that discards thought, token, usage, and catalog noise. Restart reconciliation now receives Tori-owned workspace authority explicitly and persists a confirmed native session ID without falsely promoting still-starting work to running. Tests use only temporary state and an OpenCode-shaped ACP fixture; no canonical database, adapter-private production state, provider credentials, general network, UI, Pi, Git operations, or generic Jobs framework was added.

All meaningful completed changes to Tori will be recorded in this file.

This project is in early implementation. Versioning and release conventions may be refined before the first public release.

## [Unreleased]

### Added

- Implemented the review-pending first two internal slices of Tori's concrete Coding Work foundation without creating a generic Jobs framework. Slice 1 adds the Tori-owned revisioned aggregate, immutable authorization snapshots, durable runs/directives, bounded semantic evidence, presentation-neutral application service, and narrow worker contract proven by a deterministic fake. Slice 2 corrects the authority document to kernel-enforceable resource facts and adds presentation-neutral real-process supervision, bounded diagnostics, process-group cancellation/escalation and child cleanup, workspace concurrency, crash/exit normalization, PID-free restart refusal, a deterministic JSONL fixture, and a fail-closed Bubblewrap plan. The plan binds exactly one workspace read-only or read/write, overmounts existing authoritative `.git` read-only, masks canonical Tori runtime with an empty read-only mount, exposes no sibling projects, host HOME/config/credentials/caches or host sockets, inherits only a synthetic environment, and unshares general networking. Project-local `.venv`, `node_modules`, vendor, manifest, lockfile, or unpacked-package changes are correctly treated as reportable workspace modifications rather than falsely claimed semantic sandbox denials; copy-on-write promotion remains only a possible future stronger mode. Exact persistence initialization and every executed fixture use temporary paths. The conditional real Bubblewrap test skips honestly inside nested Codex, while the separately executed normal-host Bubblewrap transport and production adapter acceptances passed physically. Pi, Web/mobile presentation, canonical runtime initialization, commit authority/broker, and generic Jobs remain deferred, and Coding Work is not yet a user-available completed capability.
- Completed and human-accepted Phase I Search understanding while retaining the existing exact-file Knowledge foundation: authorized SearXNG results now flow through a separate provider-neutral, Tori-owned bounded source-retrieval service that reads up to three public HTML/text/Markdown sources, extracts temporary untrusted evidence, preserves final-URL provenance in the existing citation/archive presentation, and identifies failed retrievals as snippet-only rather than claiming pages were read. Explicit requests to read up to two supplied public HTTP/HTTPS URLs bypass SearXNG rediscovery for that request only. Initial and redirect destinations fail closed against credentials, unsafe schemes, loopback, private, link-local, multicast, unspecified, reserved, and ambiguous DNS results; transport is pinned to a validated public address without ambient proxies, cookies, conversation history, Memory, or Knowledge. Application-assigned current-result source IDs remain stable across redirects; redundant local-model Sources/References appendices and exact supplied prose URLs are validated, reduced to those IDs, and rebuilt from authoritative records. Operational URL literals inside closed Markdown code remain answer content rather than attribution metadata, while unknown IDs, stale or invented prose/source URLs, and unbound answers still fail closed. Final physical-iPhone acceptance passed after a fresh Tori start through the real streamed browser path using local SearXNG, local Ollama `gemma4:12b`, actual retrieved source evidence, and the Oobabooga GitHub installation-research request. No Search profiles, crawler, folder registration, semantic/vector/RAG replacement, ingestion, permanent research storage, schema, migration, automatic Knowledge/Memory promotion, or M25 work was introduced.
- Completed and human-accepted Phase H.5 TTS profile lifecycle integration: an absent canonical profile store is atomically seeded once from the validated legacy TTS configuration without rewriting it, existing stores are never re-projected, and normal Web speech snapshots the explicit canonical selection through a provider-neutral runtime source. Qwen/Kokoro selection and effective active-profile edits cancel old queued/in-flight speech, future sessions use the newly selected provider/model/voice, operational availability is shown truthfully in Settings, and missing/invalid/unavailable selections never trigger legacy or cross-provider fallback. Human acceptance verified Qwen3 TTS, Kokoro, profile switching, and the Settings Voice workflow. Provider switching is immediate; after changing a Kokoro voice, Settings may require one refresh before the new voice metadata is reflected, which is an accepted minor presentation note rather than a capability defect. Automated implementation work uses isolated temporary stores.
- Completed and human-accepted Phase G of the product-modernization program: Settings separates Models, a Model Settings navigation bridge, Voice, Search, Capabilities, Memory, Schedule & Tasks, Maintenance, Appearance, and Advanced. The Model Settings section opens the implemented conversation-scoped model/context controls; a richer standalone Model Settings workspace was not completed and remains deferred. Recent Chats use deterministic subject titles with bounded early greeting refinement plus revision-safe manual Rename and contextual actions; and At a glance adds compact status/activity, a bounded Upcoming projection from canonical Tasks, Reminders, and Scheduled Work, and working quick actions. Desktop and physical-iPhone acceptance passed chat creation, ordinary chat, TTS, Rename, Recent Chat menus, Workspace, navigation, and Settings without a major UI regression. Existing schema-6 chat labels provide title persistence, so no schema or canonical migration was added. Tori identity remains core-owned rather than an editable system prompt, and no external capability, M23/M24 semantic change, or M25 work was introduced.
- Implemented and human-accepted Phase F2 of the modular frontend program on the F1 foundation: the Tori Web client now has a compact three-region desktop shell, persistent truthful Recent Chats, an integrated compact New chat control, a central Conversation workspace, a visible modular right At a glance / Workspace rail driven only by existing application/session state, a dedicated subsectioned Settings workspace, and mobile navigation/utility sheets. Desktop and physical-iPhone acceptance passed, including normal chat, Workspace cards, responsive controls, and TTS during chat. The Balanced Tori blue/chrome dark treatment preserves familiar Conversation rendering and all existing application authority; unavailable STT, MCP, registry, and appearance controls are labeled honestly rather than simulated. No schema, backend capability, dependency, framework, canonical runtime mutation, or M25 work was introduced.
- Established Phase F1 of the modular architecture program: Settings is now the first independently mounted frontend view, owning its rendering, local view state, interactions, existing typed API calls, and scoped responsive styling behind a small internal view-module lifecycle. The shared shell retains navigation and Conversation remains unchanged; no frontend framework, capability registry, new Settings authority, or M25 work was introduced.
- Completed the deliberate architecture-recovery cycle after seven reviewed slices and a read-only exit assessment found no remaining pre-M25 blocker. The cycle established `ProjectApplicationService`, `ManagementRemovalWorkflow`, `SearchApplicationPolicy`, `TaskReminderApplicationService`, `ScheduledWorkApplicationService`, `SearchPort`, and `KnowledgeRetrievalPort`; no Slice #8 was required.
- Recorded that substantial Web/session orchestration, model/context synchronization, supervised-command coordination, completed-turn duplication, compatibility fallbacks, possible future evidence-driven storage ports, and Project-to-associated-conversations UX remain deferred rather than resolved. M25 is ready to resume under the recovered architecture but remains incomplete, frozen, and not human accepted.
- Separated the architecture-review research draft into non-contractual reference notes and added a concise `docs/TARGET_ARCHITECTURE.md` defining Tori core ownership, replaceable adapter boundaries, open-source-first evaluation, and modular completion direction without selecting implementations.
- Established `docs/ARCHITECTURE_GOVERNANCE.md` as accepted engineering governance subordinate to the seven founding documents. It makes core ownership, tool-without-authority boundaries, open-source-first evaluation, replaceability, architecture and product-workflow gates, contract evidence, external-system safety, and interface independence mandatory for future milestones.
- Preserved Milestone 25 as a frozen, incomplete schema-6 recovery checkpoint after the architecture audit verdict **MAJOR IN-PLACE REFACTOR**. The canonical 5→6 migration is complete and architecture recovery has since completed, but M25 remains unaccepted and requires a separately authorized resumption mission.

- Completed the approved offline implementation scope for Milestone 25 — Project Context & Continuity Foundation. Exact conversation archive schema 6 adds bounded application-owned Project records and one nullable Project association per conversation; one Project may support many chats, association changes never rewrite transcripts, and confirmed deletion atomically detaches chats without deleting any other domain data.
- Added revision-safe Project CRUD and active/paused/completed lifecycle, including completed-to-active resumption; compact responsive browser management; an associated-Project indicator; authoritative polling; explicit association/detachment; and confirmed permanent deletion. Projects remain conversation continuity data and grant no command, file, search, task, reminder, Scheduled Work, backup, or other capability authority.
- Integrated clearly labeled Project data into M23 required context planning for web and CLI. Associated title, status, objective, and bounded four-section continuity brief survive ordinary-history trimming, the current user request remains last, and required-material overflow fails before provider contact. Project context never becomes curated memory or knowledge.
- Added narrow provider-neutral natural-language Project intent for varied create, update, association, detachment, pause, resume, and complete phrasing. Conversational changes remain inert, source-chat-bound, target/revision-bound, one-use proposals until explicit confirmation; cancellation, restart loss, ambiguity, stale revisions, and discussion about a Project cause no canonical mutation.
- Added a dedicated explicit exact-schema archive 5→6 migration with descriptor-bound no-follow preflight, malformed/lookalike and already-migrated refusal, rollback verification, exact schema-5 value preservation, no inferred historical Projects, and all legacy chats unassociated. The separately authorized canonical migration completed exactly once; normal startup remains non-migrating.
- Advanced the development package and local provider/search/speech user-agent identifiers to `0.25.0-dev`; no Git tag was created.

- Completed and human-accepted Milestone 24. Exact conversation archive schema 5 adds a narrow durable `memory_extractions` outbox, and exact memory schema 3 adds permanent extraction-effect receipts. New ordinary assistant turns and exact source-bound extraction obligations commit in one archive transaction; automatic memory create/update effects and their receipts commit in one memory transaction.
- Split intelligent-memory evaluation/planning from application-owned effect application without changing M20 evidence, sensitivity, task/scheduler exclusion, duplicate, relationship, target-revision, confirmation, or failure semantics. One managed FIFO worker uses process-incarnation claims, recovers older-incarnation `running`/`planned` work, persists validated plans before effects, refuses changed/unavailable providers without fallback, and does not participate in foreground busy or transcript revision.
- Decoupled complete, streaming, interactive CLI, and one-shot CLI response completion from hidden extraction. Browser terminal state, controls, transcript reconciliation, and Speak/replay now follow the durably archived assistant response; deferred source-chat-bound confirmations use separate attention state and do not rerender transcripts or disturb drafts, scroll/selection, busy state, or unrelated dialogs.
- Added explicit exact-schema conversation 4→5 and memory 2→3 migration implementations with no-follow preflight, lookalike/already-migrated refusal, transaction rollback tests, and no normal-startup migration. The separately authorized canonical migrations completed once; canonical conversation archive schema 5 and memory schema 3 are now production state and must not be migrated again.
- Corrected a post-completion attention/admission race: foreground cleanup previously cleared the published working event immediately before releasing the operation mutex, so attention could authoritatively report `busy=false` during a narrow interval in which the next foreground request still received HTTP 409. One condition-guarded operation gate now makes foreground idle publication and admission release atomic, retains legitimate foreground serialization, and lets foreground admission wait through non-busy quiet delivery reconciliation.
- Added crash/restart, atomicity, idempotency, provider-change, deletion-race, FIFO, one-shot recovery, blocked-extractor foreground-completion, multi-browser, durable-confirmation, complete/stream idle-admission, repeated-request, failure/timeout, and safe interactive-prompt regression coverage using temporary stores only.
- Recorded the human-supplied final physical desktop+iPhone multi-browser PASS for corrected same-chat Secondary Ollama convergence. Structured auxiliary extraction through that provider may exceed its configured 30-second timeout; this accepted provider-performance limitation is durable, nonfatal, source-bound, outside foreground completion, and never triggers provider fallback.
- Advanced the development package and local provider/search/speech user-agent identifiers to `0.24.0-dev`; no Git tag was created.

- Completed and human-accepted Milestone 23 Model Provider & Context Control Foundation: durable administrator model-provider profiles, backward-compatible legacy Ollama configuration, focused LOCAL/LAN OpenAI-compatible Chat Completions support, profile-namespaced catalogs, safe known-model supplementation, strict no-fallback routing, and optional provider-reported usage metadata.
- Added exact numeric IPv4 loopback/RFC1918 endpoint validation with explicit HTTP/HTTPS ports, redirect/proxy rejection, and only `none` or application-owned non-secret dummy-bearer authentication. Cloud/public providers, real credential storage, browser endpoint editing, routing, retry fallback, and model management remain excluded.
- Replaced the destructive default 20-message provider-history limit with full eligible archived-history access plus a versioned deterministic context estimator/planner. Per-request planning protects required current-turn material, trims oldest whole exchanges, reserves reply and tokenizer/template uncertainty capacity, fails before contact on required overflow, and keeps estimated versus actual usage distinct.
- Implemented exact conversation archive schema 4 with per-chat context policy and nullable bounded assistant-turn context telemetry, plus explicit transactional schema-3 → schema-4 migration code and temporary-fixture preservation tests. The separately authorized canonical migration completed once with exact historical preservation, `auto` policy for all migrated chats, and `NULL` historical telemetry.
- Implemented Milestone 23 Mission B browser controls: the compact conversation model bar now presents profile/model plus estimated context pressure and opens one bounded provider/model/context dialog. Safe browser APIs expose no endpoints, authentication data, provider-native payloads, or raw diagnostics; combined selection persists atomically under the existing revision/operation boundary.
- Tightened Mission A review findings: OpenAI-compatible configuration now normalizes only an origin or `/v1` form to one canonical API root; the adapter refuses to guess other paths. Archived profile restoration now rebinds conversation, intelligent-memory, and task-interpretation paths to the exact provider or explicit unavailability, and fixed context choices above verified capacity fail before persistence/provider contact.
- Clarified that reply capacity is planner headroom rather than a provider-neutral maximum-output request. Browser telemetry keeps approximate input, actual prompt/completion/total usage, omitted exchange counts, and verified/unknown backend capacity distinct.
- Corrected the reported migration-hook residue finding: the source had one `committed` notification; overlapping inspection ranges had displayed the same boundary line twice. Added regression coverage proving the exact five migration stages fire once and that schema 4 is rejected without modification.
- Completed bounded real Ollama acceptance with the unchanged legacy profile and configured `gemma4:12b`: schema-4 startup and a 14-model catalog passed, complete and progressive streaming responses retained exact model identity and usage, and isolated 4K/16K planning tests showed older whole exchanges omitted then restored while estimated and provider-reported tokens remained separate.
- Confirmed no OpenAI-compatible profile is administrator-configured. Temporary schema-4 browser HTTP lifecycle acceptance passed safe catalog shape, context change/refresh, archive reopen, New Session, idle state, and telemetry separation. Later human desktop visual and physical-iPhone portrait acceptance passed; the human accepts landscape conversation visibility as a known limitation and does not intend to use that orientation.
- Implemented Mission D human-managed OpenAI-compatible LOCAL/LAN profiles in a dedicated exact-schema-1 SQLite store: explicit initialization, no-follow/exact-schema validation, immutable generated identity, bounded typed records, optimistic revisions, enable/disable, confirmed deletion, and deterministic collision rejection with read-only configuration profiles. A human later initialized the canonical store and created the `Secondary Ollama` profile; final reconciliation preserved it unchanged.
- Added narrow Settings management APIs and a responsive Model Providers interface for create/edit/enable/disable/delete/refresh. Configuration endpoints stay hidden, dummy bearer material is never exposed, existing archived selections remain unavailable without remapping when a profile is disabled/deleted, and the verified backup inventory recognizes the future provider-profile database when present.
- Corrected the live OpenAI-compatible adapter for Ollama responses that populate string-valued `reasoning` before visible `content`: recognized reasoning is contained, malformed reasoning types still fail, tool/multimodal structures remain unsupported, and reasoning-only responses cannot complete successfully. Timeout, connection, malformed-response, and unsupported-response failures now retain distinct safe application classifications.
- Completed explicitly authorized live acceptance against the existing human-managed `Secondary Ollama` profile at a private-LAN endpoint. Discovery found `gemma4:12b`; complete generation, progressive application streaming, validated usage, exact profile/model attribution, visible multi-turn history, and one bounded JSON-object auxiliary call passed. Ordinary chat carried no structured-output fields, reasoning was not surfaced or persisted, exactly one assistant entry was committed for the isolated streamed turn, and no native complete/streaming fallback occurred. All acceptance conversation/archive state was temporary; canonical profile and conversation data were not changed.
- Corrected a physical multi-browser stale-working defect: the existing attention poll now carries authoritative process busy state, so non-initiating browsers observe active work and reconcile terminal idle—including after background/foreground transitions—without refresh. Attention and session state carry active-chat identity plus revision; the browser explicitly latches an advanced same-chat busy-time revision without changing the actually-rendered revision, then performs one identity-checked terminal session reload. Deterministic coverage proves the rendered revision remains unchanged through 24 consecutive busy polls, one-poll and direct-idle variants, failure/disconnect, background/foreground, unchanged revision, and different-chat isolation while preserving dialogs, drafts, selection/scroll, and no-flicker rendering. Final physical Secondary Ollama desktop+iPhone retesting passed: the desktop returned to idle, re-enabled controls, and rendered both remotely created messages without refresh.
- Measured Secondary Ollama's post-visible delay with TTS disabled: provider terminal/visible text occurred at 20.825 seconds, synchronous post-archive intelligent-memory extraction ended at 44.916 seconds, and the browser terminal event followed at 44.919 seconds. TTS does not cause the delay; replay controls intentionally appear only with the authoritative completed assistant entry. Decoupling candidate extraction from visible completion while preserving M20 safety semantics is a high-priority post-M23 performance/UX candidate.
- Expanded the fully offline suite from 701 to 758 tests with provider-profile persistence and collision boundaries, OpenAI-compatible request/response/SSE normalization, reasoning containment, context planning and telemetry, archive schema-4 migration, exact provider/model selection, responsive management controls, and prolonged-busy multi-browser transcript reconciliation coverage.

- Completed and human-accepted the Milestone 22 Scheduled Work / Initiative Foundation: a separate exact-schema SQLite store for revisioned definitions, immutable Persistent authorization snapshots, occurrence-unique runs, bounded results, notification delivery, and one global synchronization revision.
- Added strict one-shot/daily/weekly schedules, IANA civil recurrence with deterministic DST gap/overlap policy, authorization-bound missed-run policy, bounded/coalesced startup recovery, interrupted-run truth, transactional claims, and one background execution worker without automatic retry.
- Generalized the bounded Safe Action definition metadata with deny-by-default dispatch eligibility, contract/result validation, and availability checks while retaining separate Interactive and Scheduled dispatch. `tori.backup` explicitly permits only one-shot scheduling; `tori.command.execute` permits no scheduling; deterministic recurrence tests inject a non-production recorder capability.
- Added explicit scheduled-backup proposal and confirmation, revision-bound Edit/Pause/Resume/Cancel, dependency-safe individually confirmed History deletion, a separate synchronized responsive Scheduled Work destination, and stable application-authored result events excluded from provider history and curated memory.
- Added verified-backup and runtime-safety recognition for the future canonical `runtime/scheduled_work/tori_scheduled_work.db` path. Automated tests use temporary injected stores and do not create or mutate the canonical store.
- Evolved the conversation archive implementation from exact schema 2 to exact schema 3. A dedicated Scheduled Work origin path may persist one confirmed provider-free application conversation with zero completed model turns and null first/latest execution attribution; ordinary zero-turn or local-command archive creation remains rejected, selected-model state remains separate, and the first later real model turn supplies truthful attribution.
- Evolved Scheduled Work from exact schema 1 to exact schema 2 with immutable nullable conversational origins on definitions and terminal-notification snapshots. Conversational results append directly and idempotently to the exact origin even when it is not active; management-created originless work retains existing active-chat delivery, and a missing origin remains pending without retargeting.
- Added explicit descriptor-bound, no-follow conversation 2→3 and Scheduled Work 1→2 migration commands with exact source/target validation, rollback-before-commit behavior, post-commit inspection semantics, and historical logical-value preservation. Normal startup refuses either legacy schema without surprise mutation.
- Added origin-first cross-store confirmation ordering, stable creation/failure application events, and crash/failure-injection coverage. No executable work can precede its conversational anchor; a failed work commit leaves a truthful anchor, and a failed success append does not roll back valid work or duplicate authority.
- Recorded the separately human-authorized canonical migrations to conversation schema 3 and Scheduled Work schema 2; normal startup remains non-migrating.
- Corrected the live-acceptance busy-state defect by separating the existing operation mutex from its user-visible working signal. A future definition, scheduler/coordinator infrastructure, and quiet result reconciliation no longer report Tori as globally working, while conversation, management, immediate-backup, and supervised-command operations retain their existing visible busy lifecycle and exclusion boundary.
- Corrected Scheduled Work Edit prefill so a one-shot definition's canonical UTC occurrence is presented immediately as local civil date/time in its persisted IANA timezone. Opening or cancelling remains presentation-only, and the revision-bound edit proposal now interprets those civil values in the same persisted timezone even if current application configuration differs.
- Completed human acceptance for structured Persistent-authority review, local scheduling grammar, real browserless execution, exact conversational-origin delivery, originless management delivery, corrected waiting/terminal busy state, corrected timezone-aware Edit prefill, multi-browser convergence, and the physical-iPhone Scheduled Work management surface in portrait and landscape. Navigation, Active/Paused/History, Details, Edit prefill/cancellation, touch controls, orientation changes, overflow, and false-working-banner behavior passed.
- Expanded the fully offline suite from 672 to 701 tests with migration, zero-model-turn transition, cross-store functional, failure-injection, immutable-origin, concurrent delivery, browser-input, provider-history, memory-exclusion, waiting-work, terminal-cleanup, refresh, multi-browser, Edit-prefill, and interactive-action regression coverage.

- Completed the Milestone 21 Tasks and Reminders Operational Foundation at commit `4cf54b3`: exact-schema application-owned task/reminder persistence, revision-bound lifecycle mutations, linked-task atomic completion, crash-safe reminder delivery state, and verified-backup/runtime-safety coverage.
- Added deterministic IANA time context, DST gap/overlap detection, relative/civil-time resolution, and one reminder-specific scheduler thread with mutation wakes, bounded rechecks, startup overdue catch-up, and clean shutdown.
- Added provider-neutral strict task-intent interpretation with application-owned target allowlisting, time conversion, persistence, verification, and success/failure wording; operational turns remain separate from curated-memory extraction.
- Added canonical multi-browser attention polling, one-card queue presentation, Details, Discuss, Done, Dismiss, delay presets/custom scheduling, and bounded responsive task/reminder management without browser storage or unsafe rendering.
- Added explicitly confirmed, revision-bound permanent deletion for resolved History records only. Reminder deletion atomically removes its delivery state without changing linked tasks or archived chat messages; task deletion refuses remaining reminder references. No reopen, bulk clear, or automatic expiration behavior was added.
- Added conversation archive schema 2 application-event support and a controlled explicit schema-1 migration command. The separately authorized canonical migration completed and exact schema 2 is now production state; normal startup still refuses a legacy schema-1 archive without modifying it.
- Corrected clear standalone civil-time window reminders with a narrow application-owned `today`/`tomorrow` path that preserves both bounds, converts them through the authoritative IANA timezone, fires at the start, rejects invalid or ambiguous wall times without mutation, and reserves save-failure wording for attempted persistence failures.
- Corrected natural action-first elapsed reminder wording such as `Remind me to ACTION in 2 minutes` by routing it through the same anchored application-owned path as `Remind me in 2 minutes to ACTION`, including bounded minute/one-hour syntax and elapsed-specific clarification for malformed forms.
- Completed human desktop and physical-iPhone acceptance for task/reminder creation and management, both elapsed-reminder word orders, exact civil and full-window scheduling, linked-task semantics, synchronized attention and actions, delay/refiring, response-before-reminder delivery ordering, separate History and safe deletion, truthful no-browser/restart overdue recovery, and mobile attention layout. M21 implementation, migration, acceptance, and completion commit `4cf54b3` are complete.
- Reconciled the corrective cycles into one routing policy: narrow standalone windows, explicit existing-task elapsed links, and both narrow standalone elapsed word orders take application-owned precedence before broader strict structured interpretation. Active-vs-History management, reminder editing, permanent History deletion safeguards, and application-authored delivery remain aligned with that policy.

- Completed and human-accepted Milestone 20's intelligent curated-memory foundation: a separate hidden provider-neutral extraction request may propose at most three strict candidates grounded by exact evidence in the current user statement, while deterministic application policy alone validates, deduplicates, excludes sensitive/temporary/scheduler content, and authorizes canonical SQLite mutations.
- Added conservative automatic acceptance for direct ordinary durable candidates, process-local one-use confirmation for inferred candidates and same-dimension updates or contradictions, canonical source/model provenance, verified `Remembered:` presentation, and nonfatal post-archive failure isolation. Models cannot choose IDs, CRUD operations, targets outside an application-bounded relationship, deletion, SQL, paths, tokens, or authority.
- Added schema version 2 plus an explicit transactional schema-1 migration mechanism preserving IDs, text, and timestamps. Added descriptor-bound no-follow storage opens, private new-store creation, symlink/ancestor rejection, normalized duplicate suppression, and revision-bound CLI forgetting. The canonical production store was explicitly migrated, strictly verified as exact schema 2, and corrected to mode `0600`; normal startup still never surprise-migrates a legacy store.
- Corrected live extraction and streaming integration by using Ollama provider-native structured output while retaining strict application parsing, and by carrying validated application-owned memory status and confirmation through the browser terminal event.
- Corrected current-turn persistence truthfulness, direct-versus-inferred origin classification, and relationship safety. Retrieved memory is pre-request canonical context; repeated durable behavior is inferred and confirmation-bound; lexical relatedness is comparison preselection only; and invalid, uncertain, independent, or non-allowlisted relationship output cannot acquire a destructive replacement target.
- Added focused temporary-store coverage for storage hardening, migration, candidate validation and attack-shaped fields, evidence anchoring, ordinary automatic saves, inferred confirmation, same-dimension updates, independent and uncertain relationships, scheduler/sensitive rejection, duplicates, nonfatal extraction, browser presentation, and the CLI forget race.
- Completed deliberate desktop/browser and physical-iPhone acceptance covering direct save, duplicate suppression, contradiction cancellation, scheduler/sensitive/temporary rejection, archive replay protection, inferred additive confirmation, and revision-bound correction. The final canonical production store contains only the two accepted genuine preferences; disposable correction-test data was removed through supported user workflows.

- Implemented Milestone 19's explicit `/run COMMAND` proposal path and fixed `tori.command.execute` Safe Action with exact command/workspace arguments, invocation/source-bound single-use confirmation, and cancellation without execution.
- Added application-owned command supervision with one active invocation, sanitized environment, fixed timeout, independently bounded stdout/stderr, truthful exit/timeout/stop outcomes, and deterministic process-group cleanup including background children.
- Added a native Bubblewrap backend design with private filesystem/process/network namespaces, real authorized workspace access, hidden canonical runtime, and no unrelated host project, backup, Docker-socket, or secret-environment exposure.
- Added compact browser proposal/activity/output presentation and a narrow Stop-current-command control, plus interactive CLI confirmation; command output remains untrusted application output and never reaches the model or triggers continuation.
- Corrected the human-acceptance browser lifecycle so confirmation returns at command start, invocation-specific polling retains running and completed activity after generic status cleanup, Stop remains visible and is bound to the observed invocation, and exit code, termination reason, empty output, stdout, and stderr remain accessible through compact user-expanded details. Named layout regions keep the transcript—not an absent activity or intrinsic composer—in the flexible row, while terminal activity can be dismissed locally without altering its recorded outcome.
- Recorded real-host acceptance evidence that Bubblewrap is available to Tori's normal runtime; namespace denial inside the nested Codex environment is not a production host-policy prerequisite.
- Added focused temporary-workspace tests for recognition, proposal-only behavior, exact authorization, cancellation, alteration/replay/source failure, success/nonzero/stderr truth, timeout, stop, output bounds, environment sanitization, one-active enforcement, background cleanup, API shape, UI rendering, and model/tool/output containment.

- Implemented Milestone 18's fixed application-owned Safe Action Execution Contract with the stable `tori.backup` definition, empty-argument validation, Interactive permission classification, invocation-specific single-use authorization, fixed executor, and structured application-determined outcomes.
- Routed Settings → `Back Up Now` and narrowly recognized explicit browser conversation imperatives through the same action dispatcher and existing verified backup service, with success/failure presentation derived only from the structured outcome.
- Added fail-closed coverage for unknown actions, invalid or executable-shaped arguments, missing/replayed/cross-action authorization, ambiguous and advisory backup language, unsupported execution requests, executor failure, and model-generated action/tool-shaped content with zero execution authority.

- Added Milestone 17's narrow Settings → Maintenance `Back Up Now` action and parameterless same-origin API for one complete verified disaster-recovery snapshot of `<tori-root>` beneath the fixed external `<backup-root>` root.
- Added transactional per-attempt `.incomplete` staging, collision-resistant final names, complete physical-tree inventory, no-follow symlink handling, ordinary-file stability/hash verification, unsupported-object rejection, versioned manifests, and atomic same-filesystem publication only after verification.
- Added online SQLite snapshots for the defined memory, conversation, and settings stores with integrity checks against each backup copy while leaving source databases read-only, plus read-only bounded discovery of the latest valid verified manifest after restart.
- Added deterministic temporary-root coverage for complete trees, hidden and empty content, `.git`/`.venv`-like data, modes, symlinks, SQLite integrity and writer activity, root/type/collision/source-change/verification failures, retained non-final attempts, concurrency, protected request shape, provider isolation, and responsive safe UI rendering.

- Added Milestone 16's schema-versioned application-owned SQLite settings store for the two typed non-secret preferences Web Search and Speech Output, separate from administrator configuration, archives, checkpoints, curated memory, knowledge, model selection, and browser-local Automatic Speech.
- Added a protected typed Settings HTTP boundary and a sixth Settings destination in the existing desktop navigation and compact mobile menu. The page distinguishes administrator permission, user preference, and effective capability state without claiming provider health or exposing endpoints, secrets, providers, voices, or arbitrary configuration.
- Added fail-closed capability gates across every authorized Web Search path and manual/automatic speech generation, immediate stopping of active browser speech after Speech Output is disabled, and safe ordinary text conversation when stored settings cannot be trusted.
- Added deterministic persistence, malformed-store, administrator-ceiling, request-security, search-bypass, speech-bypass, UI, archive-isolation, and absent-store coverage using temporary databases only.

- Added Milestone 15's provider-neutral transient speech service, bounded Qwen/faster-qwen3-tts adapter, administrator-controlled fixed local endpoint and voice configuration, ordered one-request-at-a-time speech sessions, and same-origin authenticated PCM streaming without exposing the upstream service to browsers.
- Added incremental safe-visible sentence and long-clause segmentation so automatic speech can begin before model completion, while final partial prose flushes once, ordering remains exact, and Markdown/source-list machinery is omitted from the faithful speakable representation.
- Added browser Automatic Speech, per-message Speak replay, Stop Speaking, transient status, stale-session cancellation, and native Web Audio scheduling. Historical rendering never auto-plays, stopping speech does not stop text generation, and generated audio is never persisted.
- Added deterministic offline coverage for configuration, request construction, segmentation, current-turn incremental timing, ordered queues, replay, cancellation, malformed/upstream failure, same-origin APIs, browser structure, and text/archive survival.

- Added Milestone 14's small provider-neutral capability/result/source contracts and a standard-library SearXNG adapter restricted to the configured approved local endpoint, with bounded queries, results, response size, timeouts, strict JSON and URL validation, exact-URL deduplication, deterministic ordering, rejected redirects, and safe errors.
- Added explicit `/search QUERY` and conservative natural-language search authorization, process-local conversation-bound expiring proposals, bounded affirmative/negative confirmation, and visible browser search/review status without a persistent panel or silent search.
- Added search-assisted untrusted-source context, validated source markers, application-built `Web findings` and `Sources` presentation, and backward-compatible schema-version-1 archive attribution that resumes without rerunning searches.
- Added offline adapter, configuration, consent, attribution, archive, CLI, browser, security, sizing, and failure coverage using injected transports and temporary runtime stores only.

- Added Milestone 13's provider-neutral model identity, objective descriptor, catalog service, deterministic ordering, validation, safe unavailable/unresolved representation, and cached explicit-refresh foundation.
- Added read-only Ollama installed-model normalization plus exact request-specific model invocation without any model pull, copy, download, deletion, or mutation behavior.
- Added CLI `--list-models`/`--model` and interactive `/models`/`/model` controls, plus accessible browser active-model, selector, and manual-refresh controls backed by same-origin APIs.
- Added focused offline catalog, provider, identifier, durable-selection, cross-model history, unavailable/no-fallback, CLI, web API, security-shape, synchronization, and asset coverage using fakes and temporary archives only.
- Added Milestone 12's schema-versioned SQLite conversation archive, provider-neutral chat service, complete visible transcript records, metadata-only listings, revision checks, and durable active-chat pointer, separate from checkpoints, curated memory, and knowledge.
- Added automatic successful-turn persistence for one-request CLI, interactive CLI, and browser conversation paths; terminal archive listing/resume/deletion/new-chat options; and browser Archived Chats listing, open/resume, New Session, and explicit deletion controls.
- Added atomic first-database publication with Linux `renameat2(RENAME_NOREPLACE)`, isolated failure-artifact preservation, and an adversarial canonical-substitution test covering replacement symlink/target preservation and safe retry.
- Added focused archive store/service, CLI, web lifecycle, HTTP API, browser asset, failure-safety, and canonical-runtime-isolation coverage.
- Added Milestone 11's single standard-library IPv4 listener on `0.0.0.0`, retaining loopback while making the same process available through supported numeric private or link-local LAN IPv4 URLs.
- Added filtered local IPv4 startup discovery and concise loopback/LAN guidance that never presents `0.0.0.0`, public, invalid, duplicate, or loopback candidates as LAN URLs and degrades honestly when no LAN address can be identified.
- Added strict LAN-aware Host parsing, request-specific exact plain-HTTP Origin enforcement, and a direct socket-peer IPv4 boundary while preserving independent per-process anti-CSRF protection.
- Added focused offline tests for binding, IPv4-only behavior, default and overridden ports, candidate discovery/presentation, Host and Origin attack cases, independent CSRF enforcement, direct-peer classification, cleanup, and preserved application behavior.
- Added a fifth implemented Commands destination at `/commands` within the existing shared shell, with an informational reference for browser slash commands, terminal-only checkpoint options, graphical equivalents, confirmation behavior, and explicit persistence distinctions.
- Added one shared supported-command registry and narrow command-shaped token helper. Unsupported leading slash commands are now handled locally without provider, history, retrieval, checkpoint, memory, or knowledge effects, while path-shaped text remains ordinary conversation.
- Added focused Commands route, content, History API, active-navigation, narrow mobile-navigation, registry, no-control, unknown-command, path-preservation, and no-persistence tests.
- Added a responsive semantic application shell with exactly four implemented destinations—Conversation, Checkpoints, Memories, and Knowledge—while preserving `/` and `/manage` as direct entry points.
- Added a small packaged `ui.js` presentation module for same-origin History API navigation, active-view semantics, shared safe request and element helpers, busy/status presentation, and accessible dialog focus restoration.
- Added a mobile-first charcoal, graphite, gunmetal, and steel visual system with semantic design tokens, brighter but selective blue, cyan-blue, and violet accents, safe-area support, dynamic viewport sizing, long-content wrapping, touch-sized controls, reduced-motion handling, and forced-colors accommodation.
- Added focused standard-library asset-contract tests for shared-shell structure, implemented-only navigation, safe rendering, responsive foundations, accessibility semantics, History API behavior, and the absence of browser persistence.
- Added a narrow provider-neutral ordered-fragment streaming contract while preserving the complete-response provider method used by the CLI and existing callers.
- Added true Ollama streaming chat with validated incremental NDJSON, safe premature/error handling, configured model/URL/timeout/keep-alive behavior, and deterministic response closure.
- Added one transactional streaming operation to the existing conversation session path; it reuses established context assembly and commits a nonempty completed exchange only after provider success.
- Added the same-origin authenticated `POST /api/message/stream` endpoint with flushed minimal `delta`, `complete`, and `error` events and authoritative safe transcript reconciliation.
- Added one temporary plain-text browser assistant draft with streaming UTF-8/NDJSON parsing across split records and network reads, strict terminal validation, and success/failure cleanup.
- Added focused provider, conversation, web application, loopback HTTP, browser-parser, security, concurrency, disconnect, resource-closure, and regression tests.
- Added the provisional packaged `/manage` page with separate checkpoint, memory, and knowledge sections while preserving `/` as the conversation page.
- Added structured loopback-only JSON management endpoints, a narrow typed shared management service, and safe structured record responses that are reused without parsing slash-command text.
- Added verified checkpoint save/removal, conditional memory editing by stable ID and expected update time, and typed exact-path knowledge registration management.
- Added expiring, unpredictable, one-use graphical confirmation targets bound to action, identifier, and memory version or server-side checkpoint/registration fingerprint.
- Added focused store, shared-service, web API, security, concurrency, rendering, source-preservation, and regression tests.

### Changed

- Advanced the development package and local-service user agents to `0.20.0-dev`; no Git tag was created. Milestone 20 is accepted and complete in the current uncommitted working set, with 566 offline tests and the full milestone verifier passing.

- Advanced the development package and local-service user agents to `0.19.0-dev`; no Git tag was created.
- Reconciled Milestone 19's living-document status with its accepted completion commit `a2b210d5de355e5650b0a476b53f22a1f16ddbe7` (`a2b210d`) — `Complete Tori's native supervised command execution foundation`; Milestones 0 through 19 are complete.
- Reconciled Milestone 18's living-document status with its accepted completion commit `bc053a09231bb2380a5f9e4814f5a71620f35fe8` (`bc053a0`) — `Complete Tori's safe action execution contract foundation`; Milestones 0 through 18 are complete.
- Confirmed through normal real-host Tori acceptance that the installed Bubblewrap boundary can create the required namespaces and production command execution is available; namespace creation remains unavailable only inside the nested Codex environment. Isolation unavailability still fails closed with no unrestricted-host fallback.

- Advanced the development package and local-service user agents to `0.18.0-dev`; no Git tag was created.
- Reconciled Milestone 17's living-document status with its accepted completion commit `e561bf39ed50ff790debf9e6470e2154dae4dce2` (`e561bf3`) — `Complete Tori's verified backup capability`; Milestones 0 through 17 are complete, and no active implementation milestone is selected.

- Advanced the development package and local-service user agents to `0.17.0-dev`; no Git tag was created.
- Changed optional search and speech availability to combine administrator configuration with the user's durable preference. Missing settings preserve the accepted pre-Milestone-16 behavior, and reads or startup do not create the production settings store.

- Corrected the Milestone 15 browser composer regression: drafts can now be typed and edited throughout active model streaming and speech activity, remain intact through completion and Stop Speaking, and become sendable when generation ends without allowing overlapping turns.
- Advanced the development package and local-service user agents to `0.16.0-dev`; no Git tag was created.
- Changed ordinary browser response normalization to release only already-approved natural text boundaries incrementally. Reasoning, pseudo-tool, advisory, and response-transform candidates retain their stricter buffering, so raw provider tokens never become speech input and search attribution remains final-response validated.

- Added a bounded whole-response external-knowledge advisory for ordinary model-first questions. Useful ordinary answers remain unchanged; only the exact hidden advisory can ask the application to create the existing consent-bound search proposal. A single whole-response Markdown code wrapper is normalized as harmless provider presentation, while mixed/malformed advisories, user echo attempts, casual uncertainty, and pseudo-tool output grant no authority and expose no control data.
- Corrected the search-only synthesis contract so the selected provider model is told that Tori's application just completed this authorized search for the current request and that the supplied untrusted records are its current-turn output. Search-assisted answers must not invent earlier timing or search-history retrieval, deny Tori's completed capability execution, or send the user to repeat it, while limited or insufficient result coverage remains an honest supported outcome; ordinary generation receives no search-completed context.
- Replaced rigid search-confirmation sentence matching with a bounded proposal-only affirmative grammar covering ordinary yes/please/go-ahead/search/run variants while retaining one-use, expiry, conversation, decline, ambiguity, and pseudo-tool boundaries. Queryless explicit search requests now receive a stateless application-owned request for the missing topic; when a proposal is already pending, the same wording may confirm only its stored query.
- Known non-blocking recognition limitation: natural-language wording such as “Please search for the GitHub project X and what it does” may follow the model-first insufficiency-and-consent path instead of immediate explicit-search dispatch. Clearly explicit forms such as “Search the web for X,” “Do a web search for X,” and `/search X` remain deterministic immediate-search requests.
- Unified disabled, unreachable, timed-out, failed, and malformed local-search service presentation behind one safe capability-level message. Search failures terminate the browser stream cleanly without model fallback, fabricated findings, source output, or assistant commit; ordinary conversation remains usable and later explicit search can succeed without automatic retry.
- Corrected pending freshness-search confirmation dispatch by recognizing the bounded affirmative `Yes, please search` family after punctuation normalization. A valid conversation-bound proposal now resolves to its stored query, executes the configured search exactly once before model synthesis, and cannot fall through to an ordinary stale-knowledge response; absent, expired, declined, replaced, topic-invalidated, other-conversation, and disabled-search boundaries remain unchanged.
- Made search attribution tolerant of a bounded set of unambiguous provider formatting differences—including labelled, Unicode-bracketed, footnote, grouped, and parenthetical source IDs—while canonicalizing every accepted marker to an actual normalized result. Unknown or malformed IDs, missing attribution, model-authored source lists, and model-authored URLs still fail without a completed assistant entry; Tori alone builds the visible source titles and URLs.
- Extended the existing conservative search-proposal policy to explicit freshness wording for prices, availability/in-stock state, releases/versions, rosters/personnel, office holders, schedules, and news/developments. These requests now create the existing conversation-bound one-use proposal when search is available; disabled or unavailable search is reported deterministically, and no search runs before affirmative consent.
- Corrected search-assisted browser generation so ordered search/review status records use the validated NDJSON event contract; explicit `/search` and clearly explicit natural-language requests remain deterministic application-authorized dispatches that execute the configured SearXNG adapter exactly once before selected-model synthesis.
- Added one provider/conversation output-normalization boundary before browser, CLI, validation, transcript, and archive use. Dedicated Ollama thinking/reasoning fields and validated leading reasoning sections are withheld, while malformed reasoning and empty normalized output fail without committing a partial assistant response.
- Contained whole-response model pseudo-tool JSON and provider tool-call channels as untrusted output: they execute nothing, create no consent, trigger no retry, and are neither displayed nor persisted as successful assistant answers; ordinary JSON remains supported.
- Added proposal-only confirmation wording such as “Please run the tool search”; without a current conversation-bound structured proposal, that wording authorizes no search.
- Refined the compact runtime behavior contract so ordinary greetings continue an established relationship without forced self-introduction or invented shared history, personal facts, memories, or prior events.
- Corrected the desktop Archived Conversations dialog with viewport-bounded sizing, shrink-safe card/list children, wrapping metadata, left-aligned wrapping actions, list-only vertical scrolling, and defensive horizontal-position reset while preserving the compact mobile rules.

- Advanced the development package, Ollama user-agent, and search user-agent versions to `0.15.0-dev`; no Git tag was created.
- Configured web search as enabled by default at the then-approved private-LAN SearXNG endpoint, while keeping enablement, result count, and timeout administrator-controlled and prohibiting chat-selected endpoints.

- Refined the narrow-screen conversation layout so the transcript receives more of the mobile viewport, while compacting the header, model controls, composer, internally scrolling archive dialog, and bottom navigation without reducing touch targets, redesigning desktop, or changing archive, model-selection, rendering, or security behavior. Shrink-safe grid tracks now keep long model names, the selector arrow, composer content, and panel edges fully inside the mobile viewport without relying on browser zoom or hidden overflow as the sizing fix.
- Hardened repository operations so every existing `runtime/` entry is presumed user data, ambiguous provenance is preserved, mutations require exact separate authorization, and tests inject temporary stores instead of assuming canonical presence or absence.
- Added no-follow before/after runtime-tree snapshots and read-only database reporting to milestone verification. Any path, type, mode, symlink-target, inventory, or content change now fails with evidence and no automatic cleanup or restoration.
- Made the existing archive `latest_provider`/`latest_model` metadata the backward-compatible durable conversation selection while preserving immutable per-assistant actual-model history; valid Milestone 12 schema-version-1 archives require no destructive migration.
- Changed generation to pass the active conversation's exact selected model per request. Opening/resuming restores it, selection changes persist before another message, and known-unavailable models fail clearly without silent fallback.
- Restricted configured Ollama access to plain HTTP on numeric IPv4 loopback `127.0.0.1` with an explicit valid port.
- Advanced the development package and Ollama user-agent versions to `0.14.0-dev`; no Git tag was created.
- Made the archive store the source of truth for active-chat selection: completed state persists before transitions, open selects atomically, New Session clears the durable pointer after persistence, and active deletion clears both durable and in-memory state.
- Changed ordinary conversation from process-only continuity to automatic local archive continuity while preserving the existing 20-message model-history bound and current configured provider/model for resumed generation.
- Advanced the development package and Ollama user-agent versions to `0.13.0-dev`; no Git tag was created.
- Kept archive content out of logs and metadata-only listing responses; full transcript content appears only in the active session or explicit open response and is never treated as curated memory.
- Selected and activated Milestone 11 — LAN Web Access and Real-Device Verification Foundation.
- Advanced the development package and Ollama user-agent versions to `0.12.0-dev`; no Git tag was created.
- Changed normal `--web` startup from fixed IPv4 loopback binding to one IPv4-only all-interface binding. Default port `8765`, validated `--web-port`, direct `/` and `/manage` routes, management hashes, one shared process-level conversation, and one active mutation/generation boundary remain unchanged.
- Documented the explicit temporary decision that LAN access has no authentication and uses unencrypted HTTP. Authentication, TLS, a settings page, a LAN toggle, and multi-user isolation remain deferred; no router, firewall, UPnP, port-forwarding, reverse-proxy, account, password, certificate, automatic transcript saving, or browser persistence was added.
- Kept the Commands destination informational and compatible with future controls without adding command dropdowns, guided execution, automatic form filling, graphical checkpoint resume, automatic chat archiving, a second document, a framework, or an external asset.
- Advanced the development package and Ollama user-agent versions to `0.11.0-dev`; no Git tag was created.
- Unified the former separate conversation and management documents into one packaged shell; `/manage` now opens the Checkpoints view, management hashes select their focused views, and `manage.html` has been retired.
- Improved conversation presentation with proximity-aware transcript following, a single non-live temporary streaming draft, concise lifecycle status announcements, responsive composition, and unchanged authoritative reconciliation.
- Integrated existing checkpoint, memory, and knowledge workflows into focused responsive views without changing endpoint schemas, domain operations, explicit-persistence semantics, source preservation, or concurrency behavior.
- Preserved ordinary same-origin anchors while using History API navigation when JavaScript is available so view changes do not discard DOM-only unsent input; no view or draft state is stored in the browser or runtime.
- Corrected the presentation-only long-content sizing defect by bounding the application shell to the visual viewport, allowing intermediate grid containers to shrink, and keeping transcript, management, composer, and mobile-navigation regions in their intended shell tracks; no HTML, JavaScript, endpoint, conversation, persistence, or security behavior changed.
- Completed a second CSS-only presentation correction after user review: neutralized the predominantly blue foundation, added distributed ambient illumination, layered gunmetal metallic gradients, fine edge and recessed depth treatment, selective dark glassmorphism, prefixed backdrop filtering with opaque and `@supports not` fallbacks, a stronger blue/violet accent hierarchy, and more dimensional selected navigation and primary actions. The user accepted this visual foundation for Milestone 10; the interface remains evolvable and is not declared Tori's permanent final design.
- Advanced the development package and Ollama user-agent versions to `0.10.0-dev`; no Git tag was created.
- Changed ordinary browser model conversation from complete-response presentation to progressive plain-text presentation followed by one authoritative completed transcript, without changing CLI complete-response behavior.
- Preserved the 20-message completed-history bound, memory/knowledge/source behavior, local slash commands, Copy Transcript, New Session, refresh restoration, multi-tab shared-session semantics, and explicit-persistence boundaries.
- Kept streaming within the existing operation lock and loopback HTTP security boundary; no cancellation control, browser storage, framework, WebSocket, server-sent event, polling, second server, remote service, tool, agent, orchestration, voice, search, or automatic persistence was added.
- Advanced the development package and Ollama user-agent versions to `0.9.0-dev`; no Git tag was created.
- Preserved existing CLI and slash-command behavior while routing slash-command persistence operations through the typed management service.
- Kept management explicit and transcript-free; no upload, picker, drag-and-drop, directory browsing, browser persistence, automatic persistence, graphical checkpoint resume, or source-document mutation was added.
- Corrected checkpoint management error safety, completed fixed-field memory read-back verification, and kept rejected or stale confirmations out of the visible transcript while preserving target-bound one-use behavior.
- Reconciled the living Milestone 10 documentation with its completed and post-commit-verified checkpoint.
- Corrected the living documentation to reflect the completed Milestone 8 commit and verified clean post-milestone checkpoint.
- Corrected the Milestone 7 completion documentation to reflect commit `83ec5d7` and the verified clean post-milestone checkpoint.
- Corrected the Milestone 6 roadmap completion record to reflect commit `0da3494` and the verified clean post-milestone checkpoint.

### Verified

- Passed all 432 offline tests, read-only parsing of every project Python file, JavaScript syntax validation for all packaged scripts, both diff checks, founding-document blob comparison, and before/after complete canonical-runtime comparison. The correction suite used mocked provider streams, injected search transports, loopback fixtures, and temporary stores; it made no live SearXNG or Ollama request, retrieved no result page, and wrote no search result, hidden reasoning, or rejected pseudo-tool output to canonical runtime data.

- Passed all 358 offline tests, read-only Python parsing, all three packaged JavaScript syntax checks, both diff checks, HEAD-based comparison of all seven founding documents, and read-only canonical SQLite/archive inspection through the Milestone 13 final gate. No test contacted Ollama or performed model mutation, package installation, or public-network access.
- Verified the initialization race correction, no-follow database/sidecar behavior, non-overwrite of existing/corrupt/zero-byte entries, preservation of unrelated replacements and sidecars, complete transcript round trips, active lifecycle transitions, safe errors, and retry behavior using temporary storage only.
- Verified automatic CLI/web persistence, list/open/resume/new/delete behavior, current-model continuation, metadata-only lists, same-origin API boundaries, browser text-only rendering, and absence of canonical conversation data after tests.
- Passed all 338 offline tests, read-only Python parsing, syntax checks for all three packaged JavaScript files, both diff checks, HEAD-based integrity comparison for all seven founding documents, and read-only canonical SQLite inspection through `./scripts/verify-milestone`.
- Passed all 269 offline tests, including the previous 265-test Milestone 11 checkpoint and the Commands correction coverage, using fake providers, temporary stores, injected local-address results, local ephemeral fixtures, and IPv4 loopback HTTP requests only. All three packaged JavaScript files pass syntax checks and `git diff --check` passes.
- Completed required desktop and physical-iPhone verification using the `tori-web` launcher, host loopback, and numeric IPv4 LAN access from Firefox on an iPhone 13 Pro. Portrait and landscape layouts, all five destinations, one shared process-level conversation, unsent-input preservation, and deterministic local `/checkpoints` rejection passed. The initially wrapped mobile labels were corrected without renaming Checkpoints, reducing the touch target, or introducing horizontal overflow; all five full labels then fit on one line on the tested phone. Tori stopped cleanly, no port `8765` listener remained, and no automatic checkpoint, memory, knowledge registration/source copy, or transcript archive remained.
- Created and verified Milestone 11 completion commit `95abb0ba6189595d4a32e053f257c23a51a4175c` (`95abb0b`) — `Complete Tori's LAN access and real-device verification foundation`; parent `70cb95175c610ba1cd43afd8620e0c36f0369b08` (`70cb951`) on `main`. Post-commit verification passed all 269 offline tests and syntax checks for `app.js`, `manage.js`, and `ui.js`, with a clean tracked working tree, empty staging, no remote, no tag at HEAD, and no push. No Milestone 12 has been selected.
- Created and verified Milestone 10 completion commit `d111e687dbe73f1a252eede209f11b85b7ccdb85` (`d111e68`) — `Complete Tori's responsive web interface foundation`; parent `c033d0c2758e312adcb2fad27043e95c66e5b9d3` on `main`. Post-commit verification passed all 254 offline tests and syntax checks for `app.js`, `manage.js`, and `ui.js`, with a clean tracked working tree, empty staging, no remote, no tag at HEAD, and no push. No Milestone 11 or later milestone was selected.
- Passed all 254 offline tests after the accepted visual-direction correction, including the historical 240-test pre-Milestone 10 baseline, 247-test initial implementation checkpoint, and 249-test post-bounded-shell checkpoint, without contacting Ollama, Firefox, Geckodriver, the Internet, Mem0, SearXNG, TTS, or another external service.
- Verified all three packaged JavaScript files parse successfully and `git diff --check` passes.
- Completed comprehensive deliberate live verification using Python 3.12.3, Ollama 0.31.1 with configured `gemma4:12b`, Firefox 152.0.6, and Geckodriver 0.36.0 on fixed IPv4 loopback only. Direct routes and hashes, Back/Forward navigation, active-view semantics, unsent-input preservation, responsive structure, keyboard/dialog behavior, structured management, concurrency, controlled provider failure and recovery, and Host/Origin/CSRF/route/request/rendering/storage/external-resource boundaries passed.
- Verified real progressive streaming across 205 increasing draft observations in the comprehensive pass, with correct UTF-8, one temporary draft, authoritative reconciliation without duplicates, completion-only source metadata, visible-only transcript copying, refresh restoration, and complete-response CLI behavior preserved.
- Recorded the initial live finding that long conversation content expanded the document and displaced mobile navigation. The presentation-only cause was the shell's content-driven minimum sizing; a narrow CSS correction established ordered `100vh`/`100dvh` bounds, shrinkable grid tracks, transcript-owned scrolling, management-owned scrolling, and persistent mobile navigation.
- Verified the correction with 9 focused asset tests, all 249 offline tests, and live viewports `1440 × 900`, `1024 × 768`, `844 × 390`, and a true `500 × 568`. The document remained viewport-bounded, transcript and management content gained internal scroll ranges, navigation and composer remained visible without overlap or horizontal overflow, and proximity-aware transcript following worked both near and away from the bottom across 216 real progressive observations.
- Added five structural visual-contract tests for neutral semantic surfaces, distinct accent roles, layered primary actions, distributed ambient sources, metallic depth, selective glass treatment and fallbacks, and the absence of external visual dependencies. All 14 focused asset tests and the complete 254-test suite passed after the accepted visual correction.
- Verified the accepted visual direction at true CSS viewports `1440 × 900`, `1024 × 768`, `844 × 390`, and `500 × 568`: the shell remained bounded without horizontal overflow; transcript and management scrolling stayed internal; navigation and composer remained visible; unsent input, real progressive streaming, authoritative reconciliation, and New Session cleanup remained intact; and no automatic persistence occurred.
- Exact true `390 × 844` and `320 × 568` live viewports were unavailable because the installed Firefox environment enforced a 500-CSS-pixel minimum; no scaled substitute or physical-iPhone verification is claimed, and structural tests retain the approximately 320-pixel responsive contracts.
- Removed all synthetic checkpoints, memories, registrations, sources, conversations, and temporary verification artifacts; stopped Tori, Firefox, and Geckodriver; retained no listener or SQLite sidecar; and verified the canonical runtime remained logically empty and valid.
- Preserved the seven founding documents, runtime identity, version 1 persistence formats, logically empty canonical runtime, loopback-only security boundary, existing endpoint semantics, and plain-text rendering policy.
- Passed all 240 offline tests, including the 220-test pre-Milestone 9 baseline, using fake providers, temporary stores, and ephemeral IPv4 loopback fixtures without contacting Ollama, the Internet, Mem0, SearXNG, TTS, or another external service.
- Verified ordered and Unicode/escaped fragments, empty-fragment tolerance, malformed and premature stream rejection, HTTP/transport normalization, provider-resource closure, transactional history, hidden-context exclusion, safe source timing, strict NDJSON response shape, progressive flush, failure reconciliation, lock cleanup, and preserved busy/read-only behavior.
- Verified both packaged JavaScript syntax checks and `git diff --check`; preserved the seven founding documents, runtime identity, version 1 persistence formats, and logically empty canonical runtime.
- Completed separately authorized live verification with Ollama 0.31.1, configured `gemma4:12b`, and Firefox 152.0.6 on IPv4 loopback only. Real NDJSON arrived progressively, browser draft text grew across 160 observed lengths, and the final DOM reconciled to exactly one user and one assistant entry with controls restored and no visible error.
- Verified context continuity and refresh, safe source attribution only at authoritative completion, a 642-fragment generation holding the existing operation lock while reads remained available and competing generation/New Session were rejected, safe unreachable-provider reconciliation, and the unchanged complete-response CLI path.
- Removed the synthetic knowledge registration and source, cleared transient conversation state, stopped Tori, Firefox, and Geckodriver, and verified no verification listener, process, checkpoint, knowledge registration, SQLite sidecar, runtime symlink, or temporary source remained. The canonical memory database retained integrity `ok`, schema version `1`, journal mode `delete`, zero memories, and its original SHA-256.
- Re-ran all 240 offline tests after live cleanup; both packaged JavaScript syntax checks and `git diff --check` passed. Final evidence and complete-diff review passed, and Milestone 9 implementation is complete.
- Created and verified Milestone 9 completion commit `efe8b4c3a3d299be3c0009e769cdf5aec253082a` (`efe8b4c`) — `Complete Tori's streaming conversation foundation`; no remote was configured, no push occurred, no Git tag was created, and no Milestone 10 or later milestone was selected.
- Passed all 220 offline tests, including the 183-test pre-Milestone 8 baseline, without contacting Ollama, the Internet, or Mem0.
- Passed syntax checks for both packaged JavaScript files and passed `git diff --check`.
- Preserved runtime identity, conversation assembly, checkpoint/memory/knowledge formats, source bytes, fixed loopback serving, Host/Origin/CSRF/CSP/request/logging boundaries, and explicit-persistence semantics.
- Completed deliberate live browser verification with Ollama 0.31.1 and `gemma4:12b` on IPv4 `127.0.0.1:8765`, covering conversation regression, empty states, checkpoint/memory/knowledge workflows, stale-target and token-reuse rejection, missing/restored knowledge, generation concurrency, New Session isolation, cross-tab refresh, and source preservation.
- Removed all synthetic checkpoints, memories, registrations, and temporary source data; stopped Tori; verified no listener, sidecar, or runtime symlink remained; and retained only the valid logically empty canonical memory database. Mem0 remained separate and untouched.
- Created and verified Milestone 8 completion commit `c79d5fb63d53d49f6f41f8d2441252c2ae8bc179` (`c79d5fb`) — `Complete Tori's graphical management foundation`; no remote was configured, no push occurred, and no Git tag was created.

## [0.8.0] - 2026-07-30

### Added

- Added a living, noncanonical conversation behavior contract subordinate to the seven accepted founding documents.
- Added a repeatable qualitative browser evaluation protocol with fixed paired scenarios, privacy-reviewed evidence, explicit cleanup, and no claim of objective personality scoring.
- Added structural runtime-identity tests for message shape, size, provider and interface neutrality, capability honesty, and retained baseline semantic anchors.
- Added deterministic context-order, current-user-authority, hidden-context, command-locality, and CLI/web parity verification.
- Added explicit client-side copying of only the visible transcript.
- Added clearer visible `You`, `Tori`, `Local result`, `Notice`, and `Error` role labels.
- Added immediate display of submitted user messages during generation.

### Changed

- Made CLI provider failures concise and provider-neutral while preserving retry and exit-code behavior.
- Reconciled optimistic browser presentation with authoritative transcript state without adding persistence or changing server/provider semantics.
- Advanced the development package and Ollama user-agent versions to `0.8.0-dev`; no Git tag was created.

### Evaluation

- Completed baseline and post-change paired qualitative evaluations with the configured `gemma4:12b` model.
- Recorded baseline totals of 8 `Observed`, 4 `Concern`, and 0 `Failure`; post-change totals were 9 `Observed`, 2 `Concern`, and 1 `Failure`, with 2 paired improvements, 9 unchanged outcomes, and 1 material regression.
- Rejected and reverted the experimental runtime-identity revision because it did not produce meaningful overall improvement without material regression.
- Retained the original compact provider-neutral runtime identity.
- Documented model-dependent verbosity, unnecessary questioning, inference mistakes, and occasional false persistence language rather than claiming those limitations were solved.
- Made no claim that subjective conversational quality was deterministically proven, and performed no second identity-tuning cycle.

### Verified

- Passed all 183 offline tests after identity rollback and finalization.
- Verified immediate pending-message presentation, working-state visibility, authoritative reconciliation, and visible-only transcript copying successfully in a real browser.
- Preserved existing memory, knowledge, checkpoint, CLI, web, security, command-locality, and explicit-persistence behavior.
- Removed all synthetic runtime and temporary evaluation data; runtime contains only the valid empty canonical memory database as a file.
- Confirmed the seven founding documents remained unchanged and Mem0 remained separate and untouched.
- Created and verified Milestone 7 completion commit `83ec5d71e87addeee2dfaf6ea605e7699212de78` (`83ec5d7`) — `Complete Tori's conversation character and evaluation foundation`; no remote, push, or Git tag was created.

## [0.7.0] - 2026-07-29

### Added

- Added the Milestone 6 minimal local web conversation interface using only Python standard-library HTTP facilities and packaged ordinary HTML, CSS, and JavaScript.
- Added explicit `--web` launch mode on fixed IPv4 loopback `127.0.0.1`, default port `8765`, and a validated `--web-port` override that cannot change the host boundary.
- Added one process-level in-memory browser conversation and user-visible transcript with refresh restoration, guarded New Session behavior, complete-response delivery, working state, and plain-text rendering.
- Added structured browser source transparency using safe filenames and single-line or inclusive-source-span metadata.
- Added short-lived, unpredictable, one-use, target-bound confirmation tokens for two-step web `/forget` operations.
- Added 31 focused offline web application, parser, command, concurrency, persistence, security, and loopback HTTP tests using fake providers and temporary storage.

### Changed

- Added a shared local-command service used by both CLI and web presentation layers for explicit checkpoint saving, curated-memory commands, and knowledge-registration commands.
- Preserved `ConversationSession` as the only identity, memory, knowledge, history, current-user, and provider conversation-assembly path.
- Added `--web --resume CHECKPOINT_ID` through the existing validated checkpoint-loading and current-configuration rules.
- Advanced the development package and Ollama user-agent versions to `0.7.0-dev`, following the established milestone convention; no Git tag was created.
- Kept the existing no-argument interactive CLI, positional one-request mode, checkpoint process options, slash commands, and exit-code behavior operational.

### Security

- Restricted web serving to fixed IPv4 loopback with exact Host validation and no host override.
- Required the exact same-origin `Origin` and a per-process in-memory anti-CSRF header for state-changing JSON requests.
- Added conservative body limits, strict JSON object fields and types, known-route and known-asset allowlists, query rejection, unsupported-method handling, and safe user-facing errors.
- Added restrictive content-security, no-sniff, frame-denial, no-referrer, and no-store response headers.
- Kept browser rendering on DOM `textContent`; assistant output, user input, paths, filenames, command results, and errors are never inserted as HTML.
- Kept conversation text, request bodies, CSRF and confirmation tokens, provider payloads, hidden identity/memory/knowledge context, and protected values out of web logs.

### Verified

- Preserved all 141 pre-Milestone 6 offline tests.
- Passed all 172 offline tests using fake providers, temporary storage, and ephemeral IPv4 loopback ports without contacting Ollama, Pinokio, pterm, curl, the Internet, Mem0, or any external service.
- Verified identity-first, optional-memory, optional-knowledge, completed-history, current-user-last ordering through the shared provider-neutral path while browser transcript responses exclude hidden context.
- Verified successful bounded history, failed-exchange exclusion, one-generation-at-a-time behavior, busy-state cleanup, refresh state, New Session isolation, and no automatic transcript, checkpoint, memory, or registration persistence.
- Verified local slash commands never reach the provider or completed history; explicit saves create only checkpoints, memory commands affect only canonical memory, and knowledge commands never change source bytes.
- Verified web forgetting rejects invalid, altered, reused, and expired confirmation tokens, cancellation preserves the target, and confirmation revalidates and deletes only the selected memory.
- Verified fixed loopback binding, port conflicts, known assets, path and query rejection, unsupported methods, Host/Origin/CSRF enforcement, JSON content and shape validation, body limits, security headers, and concise errors.
- Completed deliberate live browser verification with the configured Ollama backend and `gemma4:12b`: ordinary and follow-up conversation preserved context, refresh restored the visible process-level transcript, and startup, fixed loopback serving, terminal shutdown, original CLI behavior, and existing exits acted as intended.
- Verified explicit curated-memory creation and retrieval, persistence across New Session, required browser confirmation for `/forget`, and successful removal.
- Verified explicit Markdown knowledge registration and retrieval with browser filename and source-location transparency, persistence across New Session, listing through `/knowledge`, and registration-only removal.
- Verified New Session warned before clearing only the active in-memory conversation and visible transcript while leaving the server, curated memory, knowledge registrations, and an explicitly saved checkpoint intact.
- Verified explicit checkpoint save, checkpoint listing, and cross-process web resume restored and reused the saved conversation context.
- Removed all synthetic live-verification data after testing. Runtime contains only the empty canonical SQLite memory database and expected directories, with no checkpoint or knowledge JSON, temporary source, journal, WAL, SHM, symlink, or synthetic record.
- Recorded no user-observed functional, security, persistence, or interface discrepancy; the user reported that the full approved test acted as intended.

## [0.6.0] - 2026-07-29

### Added

- Added a metadata-only, schema-version-1 local knowledge registry beneath `runtime/knowledge/sources/`, with one atomic human-inspectable JSON record per explicitly selected source.
- Added `/add-knowledge`, `/knowledge`, and `/remove-knowledge` interactive commands without sending commands, paths, or identifiers to the model or conversation history.
- Added exact-path registration for regular UTF-8 `.txt` and `.md` files, limited to 1 MiB per file and 25 registrations.
- Added live source reads, paragraph and Markdown-heading passage construction, deterministic bounded lexical retrieval, and structured source metadata.
- Added provider-neutral ASCII-safe JSON-lines knowledge context with explicit untrusted-data, current-user-authority, and incomplete-source boundaries.
- Added successful-response source footers showing terminal-safe filenames and honest single-line or inclusive enclosing source-span metadata.
- Added best-effort omission of passages containing recognizable authentication material while preserving independently safe passages.
- Added 59 focused offline knowledge and application tests using temporary files and fake providers.

### Changed

- Updated conversation assembly order to identity, optional curated memory, optional local knowledge, prior completed history, and the current user request last.
- Updated the runtime identity to acknowledge separately supplied local knowledge without treating it as identity or instructions.
- Factored the existing authentication-secret predicate so memory rejection remains unchanged while knowledge retrieval can omit protected passages.
- Advanced the development package and Ollama user-agent versions to `0.6.0-dev`, following the existing milestone convention.
- Applied one component-by-component no-follow registry-root boundary to registration, fresh verification, get, listing, retrieval, removal, and fresh removal verification; every ancestor is opened relative to its validated parent, while unsafe existing components are unavailable and are never traversed or repaired.
- Corrected knowledge relevance to score all safe candidates with at least one meaningful overlap, exclude one-overlap candidates only when a candidate with two or more overlaps exists, and otherwise retain valid one-overlap results.
- Moved authentication inspection to complete unsplit logical blocks so every bounded chunk derived from a recognized block is omitted, with conservative source-level handling for matches that cross block boundaries.
- Added complete-source PEM private-key line-span protection so blank lines, logical-block boundaries, bounded chunks, and missing end markers cannot expose a key body.
- Preserved oversized Markdown headings as deterministic bounded standalone passages before their bounded body rather than dropping the heading when it cannot safely serve as a repeated prefix.
- Added one terminal-safe display boundary for filesystem-derived knowledge filenames, paths, registry roots, invalid-record details, and source footers.
- Clarified `line_start` and `line_end` as an inclusive enclosing source span and changed CLI transparency to `source line` or `source span` wording without changing provider JSON fields.

### Verified

- Preserved all 82 pre-Milestone 5 offline tests.
- Passed all 141 offline tests in 0.116 seconds without contacting Ollama, Pinokio, pterm, curl, or the Internet.
- Verified registration persistence, strict validation, collision and duplicate rejection, the 25-source limit, atomic failure cleanup, invalid-record preservation, live availability states, registration-only removal, and consistent rejection of symlinked or non-directory registry roots without changing external targets.
- Verified deterministic 1,500-character passage construction, normal Markdown heading context, oversized-heading preservation, accurate line ranges, five-passage/two-per-source/6,000-character retrieval limits, current-file authority, and no persistent copied document text.
- Verified natural questions with one clear `aurora` overlap remain eligible, while a stronger multi-term passage excludes a generic one-token `marker` candidate.
- Verified password, API-key, access-token, JWT-like, private-key, and recovery-code logical blocks are omitted without echoing or logging protected values; assignments split at a passage boundary and long private-key-like blocks supply none of their derived chunks, while safe independent prose remains eligible.
- Verified private-key spans remain wholly protected across paragraphs and bounded chunks, multiple and unterminated blocks are handled, safe text outside closed spans remains eligible, and protected values do not enter provider requests, warnings, CLI output, checkpoints, memory, or logs.
- Verified newline, ESC, bidi-control, and POSIX surrogateescaped registry filenames render without terminal control execution or crashes, while ordinary spaced filenames and absolute paths remain readable.
- Verified plain, Markdown-heading, later-paragraph, and single-line source metadata uses deterministic inclusive-span terminology while provider-facing `line_start` and `line_end` fields remain unchanged.
- Verified separate memory and knowledge messages, ASCII-safe one-record-per-line JSON, identity-first/current-user-last ordering, hidden-context exclusion from history and checkpoints, source transparency, and graceful degradation.
- Live verification with Ollama 0.31.1 and `gemma4:12b` registered two synthetic sources, retrieved one and then both across fresh processes, excluded an irrelevant generic match after correction, reflected an external source edit without reindexing, degraded honestly for one missing source, restored it without re-registration, and removed both registrations without changing either source.
- Focused live review-correction verification through the existing system Ollama 0.31.1 service confirmed that `What does the document say about aurora?` supplied the instrumented `aurora` passage, returned `violet-cascade-417`, and printed its source footer; a stronger `aurora calibration marker` request supplied only that source and excluded the source sharing only `marker`.
- Offline request inspection verified prompt-like source prose remained inside one JSON record value under the data-only header and did not replace identity or the final current-user request.
- Restored a clean runtime data state with only the valid empty canonical memory database; no knowledge registrations, checkpoints, synthetic memories, temporary records, journals, WAL files, SHM files, or runtime symlinks remain.
- This final correction pass used offline tests only; no live model or service verification was invoked.

## [0.5.0] - 2026-07-28

### Added

- Added Tori-owned schema-versioned SQLite canonical storage for explicit ordinary memories.
- Added `/remember`, `/memories`, `/update-memory`, and deliberately confirmed `/forget` commands with read-back or absence verification.
- Added stable memory IDs, exact current text, category, sensitivity, provenance, and UTC creation/update metadata.
- Added centralized best-effort rejection for recognizable authentication material and structured sensitive information.
- Added deterministic local token-overlap retrieval limited to five records and 2,000 characters of memory text.
- Added provider-neutral retrieved-memory context that is labeled as context, includes stable IDs, and makes current-user precedence explicit.
- Added ASCII-safe JSON-lines encoding for model-facing memory records, with a data-only header that rejects instructions or role/prompt wording inside record values.
- Added offline memory-store and application coverage using temporary directories and synthetic values.

### Changed

- Updated conversation request assembly to add relevant memory transiently before the current user message without adding it to session history.
- Updated interactive startup guidance for local memory commands and graceful memory degradation.
- Updated the runtime identity text to acknowledge separately supplied approved memory without claiming unavailable capabilities.
- Advanced the development package and Ollama user-agent versions to `0.5.0-dev`, following prior milestone versioning practice.
- Clarified that checkpoints and canonical memory are independent storage systems with independent deletion.
- Changed existing-database initialization to validate schema and version before applying persistent SQLite PRAGMAs.
- Strengthened schema version 1 validation to require the exact critical TEXT columns, primary keys, nullability, and fixed category/sensitivity checks.
- Closed creation and update provenance to the internally assigned `explicit_user_command` value.

### Verified

- Preserved all 42 pre-Milestone 4 offline tests.
- Passed the expanded offline suite without contacting Ollama.
- Verified new database initialization, supported and unsupported schemas, corruption preservation, secure deletion, rollback-journal mode, exact-text reopen, stable metadata, update replacement, confirmed deletion, and unavailable storage behavior.
- Verified secret/sensitive rejection occurs before insertion and rejected content is not sent to the provider, stored, logged, or echoed.
- Verified relevant/irrelevant retrieval, result and character bounds, deterministic ordering, current-user precedence, and no history/checkpoint contamination.
- Passed all 82 offline tests without contacting Ollama.
- Completed the prescribed live create, restart, inspect, retrieve, same-ID update, replacement-only retrieve, cancel, exact-confirm deletion, restart, no-automatic-create, checkpoint-separation, and cleanup workflow with Ollama 0.31.1 and `gemma4:12b`.
- Inspected the live provider request and confirmed that labeled memory context with its stable ID appeared before the final current-user message.
- Verified ordinary Ollama conversation continued with one honest warning while the canonical store was safely and reversibly unavailable.
- Restored a valid empty canonical database and removed the live checkpoint; no synthetic record, journal, or WAL artifact remained.
- Verified JSON decoding recovers exact multiline/instruction-like text while every encoded record remains one structural line.
- Verified an unsupported version 99 database in WAL mode retains its version, journal mode, main-file SHA-256, and directory entries after rejection.
- Verified version 1 look-alike schemas missing primary keys, required `NOT NULL`, category checks, or sensitivity checks are rejected without rewrite.
- Focused live re-verification with Ollama 0.31.1 and `gemma4:12b` confirmed identity plus separate JSON memory context, exact ID/text decoding, current-user-last ordering, same-ID replacement-only retrieval, exact-confirmed forgetting, and final empty-database integrity.

## [0.4.0] - 2026-07-26

### Added

- Added explicit `/save` conversation checkpoints with optional constrained display names.
- Added a version 1, UTF-8 JSON checkpoint schema with safe generated identifiers and one file per checkpoint.
- Added atomic same-directory temporary writes and replacement, with clear failure handling and no silent overwrite.
- Added metadata-only checkpoint listing through `--list-checkpoints`.
- Added validated checkpoint resume and explicit removal through `--resume CHECKPOINT_ID` and `--remove-checkpoint CHECKPOINT_ID`.
- Added validated restored-history support using ordered provider-neutral messages.
- Added checkpoint-specific failure handling with exit code `5`.
- Added automated checkpoint-store and application tests covering explicit persistence, validation, listing, resume, removal, and failure boundaries.

### Changed

- Updated interactive startup guidance to mention `/save [name]`.
- Updated `ConversationSession` so it can be initialized with validated completed user/assistant history.
- Advanced the package development version to `0.4.0-dev`.
- Updated project documentation to distinguish explicit saved conversations from Tori's future curated long-term memory.

### Verified

- Passed all 42 offline automated tests.
- Used Ollama 0.31.1 with `gemma4:12b` for the complete live checkpoint workflow.
- Explicitly saved one checkpoint containing one completed user/assistant exchange.
- Confirmed that checkpoint listing displayed metadata without transcript content.
- Started a separate process, resumed the checkpoint, and recalled the synthetic verification token `copper-orchid-731`.
- Removed the checkpoint successfully and confirmed that no checkpoint files remained.
- Completed and exited an ordinary unsaved session without creating a checkpoint.
- Confirmed that `git diff --check` was clean before documentation work.
- Confirmed that existing one-request and ordinary interactive behavior remained operational.

## [0.3.0] - 2026-07-23

### Added

- Added a session-only multi-turn command-line conversation loop.
- Added Tori's first concise runtime identity context derived from the accepted founding documents.
- Added bounded in-memory history retaining the last 20 completed user/assistant messages.
- Added `/exit` and `/quit` commands.
- Added automated tests for identity injection, conversation history, history limits, provider failure, retry behavior, explicit exit, and keyboard interruption.

### Changed

- Updated the one-request path to include Tori's runtime identity context.
- Updated interactive provider failures to keep the session open for retry or intentional exit.
- Updated the Ollama user agent and package development version for Milestone 2.

### Verified

- Passed all 14 automated tests on Python 3.12.3.
- Completed a live multi-turn conversation through Ollama using `gemma4:12b`.
- Confirmed that Tori retained the test word `cobalt` within the active session.
- Confirmed that a new process did not claim to remember the previous session.
- Confirmed that `Ctrl+C` stopped Tori cleanly with exit code `130`.
- Confirmed that the identity-aware one-request command remained operational.
- Confirmed that generated `__pycache__` files remained outside Git tracking.


## [0.2.0] - 2026-07-23

### Added

- Added the initial Python application package for Milestone 1.
- Added a one-request command-line interface.
- Added a provider-neutral model contract and initial Ollama provider.
- Added TOML configuration with environment-variable overrides.
- Added minimal console logging that does not record conversation text.
- Added automated tests for configuration, request routing, and Ollama request construction.

### Changed

- Expanded `.gitignore` for the project-local Python environment and generated Python files.
- Marked Milestone 1 complete and Milestone 2 active in project documentation.

### Verified

- Created the project-local virtual environment with Python 3.12.3.
- Passed all 6 automated tests.
- Confirmed Ollama 0.31.1 was available locally.
- Confirmed the configured `gemma4:12b` model was installed.
- Completed a live request through Tori and received a non-empty Ollama response.
- Completed an interactive one-request CLI run.
- Verified that an unreachable Ollama endpoint produced a clear failure message and exit code `3`.
- Verified that `git diff --check` reported no formatting errors.

## [0.1.0] - 2026-07-23

### Added

- Imported the seven accepted Tori founding documents as canonical project documentation.
- Established the initial minimal repository structure.
- Added the project README as the repository's front door.
- Added the living implementation roadmap.
- Added the initial `.gitignore`.
- Added tracked placeholders for the future `src/` and `tests/` directories.

### Project State

- Founding phase complete.
- Implementation phase started.
- Completed Milestone 0 — Project Initialization.
- Planned Milestone 1 — First Running Vertical Slice.
