# Companion Initiative V1 Architecture

**Status:** Complete and physically human accepted

**Authority:** Subordinate to the seven accepted founding documents,
`docs/ARCHITECTURE_GOVERNANCE.md`, and existing capability-specific authority
contracts.

## 1. Decision and purpose

Companion Initiative gives Tori a small, explicitly enabled ability to place an
occasional application-authorized check-in into the local Conversation.

> **Initiative is permission to speak, not permission to act.**

The Tori application, never a model, owns eligibility, timing, reason,
suppression, wording class, persistence, and delivery. An initiative creates no
Search, execution, Coding Work, Planning, Project, Skill, Capability Growth,
Discord, filesystem, or remote authority. A user's reply enters the existing
Conversation and authorization paths exactly as if the user had started it.

This aligns with companion-first conversation, user control, curiosity without
intrusion, honest failure, local-first ownership, and conversation before
automation. It does not assume attention, friendship, distress, loneliness, or
an obligation to respond.

## 2. V1 scope and non-goals

V1 supports three local-Web types:

- an optional morning check-in inside a configured local-time window;
- a resume-work offer based only on narrow, structured recent-work state; and
- a restrained long-silence check-in.

The whole feature and every type default to **Off**. V1 has no CLI initiation,
Discord outreach, operating-system notification, email/SMS/push delivery, wake
phrase, passive microphone, background model call, transcript mining, file
scan, Web Search, automatic Planning read, autonomous work, or learned timing.
It does not create a general notification platform, relationship score,
emotion model, presence-surveillance system, or new model/tool authority.

## 3. Recommended user-facing behavior

An initiative appears as one ordinary-looking Tori message with a subtle
`Check-in` marker and actions to **Dismiss** or **Pause check-ins** for one day
or one week. It is preserved in the active Conversation, is visible to every
tab through normal transcript reconciliation, and never changes the active
chat or creates a chat on its own.

Recommended deterministic wording is short and non-demanding:

- **Morning:** “Good morning. Want to ease into the day, review what’s ahead,
  or just talk?”
- **Resume work:** “Want to pick up where we left off on _Project title_, or
  leave it for later?” If no safe title exists: “Want to pick up the work we
  left waiting, or leave it for later?”
- **Long silence:** “Hey—just checking in. No need to respond; I’m here if you
  feel like talking or working through something.”

The wording offers possibilities only. “Review what’s ahead” does not read
Planning, and a weather offer does not Search. A reply is a new user request
and receives the normal deterministic interpretation, consent, confirmation,
and capability checks.

Only one delivered initiative may await a user response. Ignoring it produces
no follow-up. Meaningful activity affects future eligibility but does not by
itself acknowledge a delivered initiative. Only a same-chat Conversation reply
that claims its one-use context, Dismiss on that exact event, or Pause invoked
from that event acknowledges it. Turning the feature or its type Off prevents
new delivery but does not rewrite transcript history.

## 4. Architecture and reused components

Add a presentation-neutral `CompanionInitiativeService` in Tori core with four
narrow inputs:

1. an aware UTC clock plus the existing configured application timezone;
2. a read-only `InitiativeContext` projection of allowed structured state;
3. the existing `OperationCoordinator` readiness boundary; and
4. `ChatService` for revision-safe, idempotent application-event delivery.

One process-local `CompanionInitiativeEvaluator` gives the service a bounded
evaluation opportunity every 30 seconds while Tori's Web process is running.
It reuses the existing `DeadlineLoop` lifecycle but owns no durable schedule,
eligibility state, or delivery authority. Browser focus, visibility, presence,
or connection state is not an input. No browser storage, device fingerprint,
navigation history, keystroke capture, or durable presence log is needed.

Reuse these existing components:

- `ConversationArchiveStore` / `ChatService.append_application_event()` for an
  unattributed assistant application event and globally unique event ID;
- archive revisions and the Web attention/session polling path for multi-tab
  reconciliation;
- `OperationCoordinator` for conservative exclusion from foreground or quiet
  work;
- current configured timezone and civil-time helpers;
- read-only Project, Coding Work, chat metadata, and origin links for resume
  anchors; and
- existing owner-private exact-schema SQLite, no-follow, revision, backup, and
  startup/shutdown patterns.

Do not put policy in JavaScript, the model prompt, Scheduled Work definitions,
curated Memory, Projects, the Conversation archive schema, or Remote Chat.

## 5. Authority model

The application evaluates a fixed predicate. Every term must be true:

```text
master enabled
AND type enabled
AND type-specific eligibility
AND inside any type window
AND outside quiet hours
AND global and type cooldowns/caps pass
AND no unresolved delivered initiative
AND no durable snooze
AND no recent meaningful user interaction
AND an existing active local chat exists
AND Tori is ready and not busy
AND candidate can be claimed durably
```

Failure or uncertainty in any term suppresses delivery. Neither a model nor a
client may override the predicate. Initiative authority permits exactly one
bounded `companion_initiative` Conversation application event. It cannot invoke
any `ConversationOperation`, capability, confirmation, or mutation on the
user's behalf.

## 6. Meaningful interaction and readiness

A **meaningful user interaction** is a verified user-origin event that shows
actual engagement with Tori, not passive connectivity:

- admission of a nonempty local typed or finalized voice turn, even if the
  provider later fails;
- an accepted verified-owner Remote Chat message (suppression signal only;
  Remote Chat never receives an initiative);
- an explicit local confirmation, mutation, Dismiss, snooze, or other
  allowlisted state-changing user control; or
- an explicit settings change.

GET/status polls, page load, focus, visibility, manual Speak/Stop playback, a
scheduler tick, model output, application events, background work, and mere
passage of time do not count.
Call sites publish only `{kind, occurred_at_utc}` to the initiative service; no
request text is copied. A durable `activity_revision` increments so one silence
episode has one stable identity.

“User active” means a meaningful interaction occurred in the previous 15
minutes. Browser focus, visibility, polling, refresh, reconnect, and passive
page presence do not affect this interval.

“Tori busy” is conservative. Delivery requires a quiet acquisition from the
existing `OperationCoordinator` and a read-only readiness projection showing
no foreground turn, command, backup/restore, Capability Growth review,
scheduled capability execution, memory confirmation/extraction transition,
Voice finalization, Remote Chat delivery transition, or Coding Work lifecycle
transition. Long-lived Coding Work in stable `waiting` state is a resume anchor,
not perpetual busyness. Unknown or unreadable readiness suppresses the check-in.

## 7. Initiative lifecycle

```text
not eligible -> eligible -> pending -> delivering -> delivered -> acknowledged
                              |            |
                              |            +-> pending/reconciled after safe failure
                              +-> expired / suppressed / dismissed
```

Eligibility is recomputed from authoritative current state. A scan creates or
loads one candidate using a deterministic deduplication key. Policy then
rechecks all suppressions before an immediate SQLite claim. Only the claim
winner may append the fixed event to the fixed active chat revision.

After delivery, the candidate remains `delivered` across unrelated meaningful
activity, chat navigation, refresh, reconnect, and activity in other chats.
Dismiss on the exact event or a valid same-chat reply marks it resolved. Pause
from that event atomically acknowledges it and creates a global
`snoozed_until_utc`; Settings pause without an event remains a global policy
control rather than pretending the user answered a specific check-in. Candidates
whose windows or anchors cease to qualify become terminal `expired` or
`superseded` history.

Type priority when several become eligible on the same scan is:
resume-work, morning, then long-silence. Only one can be claimed.

## 8. Persistent state

Use a separate owner-private exact-schema SQLite store at
`runtime/companion_initiative/tori_companion_initiative.db`. Initiative policy,
settings, activity, claims, and delivery history need one transaction boundary;
expanding the current capability-settings singleton or the Conversation store
would couple unrelated ownership.

Conceptual schema:

- `initiative_settings`: singleton revision; master and per-type booleans;
  morning start/end; quiet-hours start/end; durable global snooze; timestamps.
- `initiative_activity`: singleton `activity_revision`, last meaningful
  interaction UTC, and last interaction kind. No text or client identity.
- `initiative_activity_signals`: bounded hashes of authoritative interaction
  identities, kind, UTC timestamps, and their activity revisions for replay-safe
  idempotency. Raw request, browser, actor, and message identifiers are not stored.
- `initiative_candidates`: ID, type, unique dedupe key, optional bounded anchor
  kind/ID/revision, eligibility start/expiry, state/revision, fixed event ID and
  exact application-authored wording, target chat/revision, lease owner/expiry,
  created/delivered/acknowledged timestamps, and terminal reason.

The deterministic archive event ID is the archive-compatible
`event-<32 lowercase hex>` form derived from the full candidate-key digest.
Candidate identity and deduplication retain the full digest/key, so recovery
always reuses the same fixed event ID rather than minting one during delivery.

The store has fixed field sizes, enum/check constraints, unique indexes on
dedupe key and event ID, hard history bounds, revision-safe settings/actions,
safe owner-private creation, exact schema validation, no silent repair, and
read-after-write verification. Retire only the oldest terminal candidates;
never discard pending, delivering, delivered-unacknowledged, or snoozed state.
Verified Backup/Restore must include this store under a consistency guard.
An absent store reads as the default-Off state and is created only by an
explicit settings write, not by startup or a status read.

Deduplication keys are:

- `morning:<effective-timezone>:<local-date>`;
- `resume:<anchor-kind>:<anchor-id>:<anchor-revision>`; and
- `silence:<activity-revision>`.

This state makes dismissals, snoozes, cooldowns, caps, and one-per-episode rules
survive restart without storing conversational content.

Resume anchors remain read-only projections of their source subsystems until an
eligible candidate is created. Coding Work exposes only waiting-state identity,
revision, origin links, and update time; Conversation exposes only active
Project title/identity plus its associated chat's latest ordinary completed
exchange sequence/time. The initiative candidate then stores the bounded anchor
identity and revision already described above. Objectives, briefs, transcript
bodies, progress, results, and command output never cross this boundary.

## 9. Timing and Scheduled Work

V1 does **not** use Scheduled Work and does not create a persistent scheduler.
A process-local evaluator reuses Tori's domain-neutral `DeadlineLoop` only as a
bounded 30-second wake/recheck lifecycle. Each wake calls
`CompanionInitiativeService.evaluate()`; the service still recomputes and owns
every eligibility, suppression, destination, claim, and delivery decision. The
loop starts and stops with the Web process, performs no catch-up after Tori was
stopped, and cannot wake a sleeping or stopped host.

The existing Web client continues to poll application attention solely for
presentation. Attention and session reads reconcile the process's cached active
transcript revision against the authoritative Conversation archive before
reporting state, so an externally appended initiative appears in an already-open
chat and in clients that connect later. Polling itself is never meaningful
activity and never triggers eligibility.

Scheduled Work currently means durable definitions, explicit/system-derived
authorization, due-run claiming, capability execution, missed-run policy, and
result notification. Encoding “permission to speak” as a scheduled capability
would wrongly imply execution authority and create duplicate policy state.
`DeadlineLoop` also is unnecessary while V1 has no headless delivery.

If a future non-Web local surface needs exact wake-ups, scheduling may be
generalized into a shared timing-only coordinator. Even then it may wake
`CompanionInitiativeService.evaluate()` only; the service must still own and
recheck every eligibility and suppression rule immediately before delivery.

## 10. Type semantics

### Morning check-in

- User configures one same-day local civil window; default values are 08:00 to
  10:00 in Tori's configured timezone, but the type remains Off.
- At most one candidate exists for a local date.
- It is eligible only inside the window and outside quiet hours.
- If Tori is stopped for the whole window, that day's check-in expires. It is
  never delivered later as catch-up. A running process may deliver to its safe
  active chat with no browser connected.
- DST uses the existing civil-time rules. A nonexistent boundary advances to
  the next valid instant; an overlap is one window, not two opportunities.

### Resume-work check-in

Resume work uses a narrow `ResumeAnchorProvider` projection, not Projects as a
mandatory owner and not a model classifier. V1 admits only:

1. durable Coding Work in stable `waiting` state, using its ID, revision,
   `updated_at_utc`, origin chat, and optional associated Project title; or
2. an active Project with an associated chat whose most recent ordinary
   user/model exchange is recent.

The service never reads Coding Work files, objectives, command output, Project
objective/brief text, or transcript bodies. Add a metadata-only archive query
for the latest ordinary completed exchange rather than loading entries. Wording
may use only a validated Project title; otherwise it is generic. Planning
tasks/reminders, arbitrary chat labels, filesystem activity, and inferred
“unfinished” conversation are not resume anchors in V1.

An anchor is eligible after four hours of quiet, expires after 72 hours, and is
offered once per anchor revision. A changed revision is a new state, not an
automatic entitlement; all normal cooldowns apply. Terminal Coding Work and
paused/completed Projects are ineligible.

### Long-silence check-in

- Eligible after seven full days without meaningful interaction.
- One candidate is allowed per `activity_revision`; ignoring it cannot cause a
  second message in the same silence episode.
- It never mentions absence duration, asks where the user has been, claims to
  miss or need the user, or implies concern unsupported by evidence.
- It contains no inferred mood, health, relationship, or productivity claim.

## 11. Anti-annoyance defaults and suppression

All controls default Off. When enabled, fixed V1 policy is:

- quiet hours: 22:00–08:00 local time;
- recent-user-activity suppression: 15 minutes;
- global cooldown: 24 hours after any delivered initiative;
- global caps: no more than 3 deliveries in rolling 7 days and 8 in 30 days;
- morning: once per local date and only inside its window;
- resume: once per anchor revision, at least 72 hours between resume messages;
- long silence: once per silence episode and at least 14 days between messages;
- only one delivered-unacknowledged initiative at a time; and
- Dismiss acknowledges the exact current item; Pause from that item
  acknowledges it and suppresses all types for one day or one week; unrelated
  meaningful activity cannot resolve it; master Off supersedes pending work
  immediately.

Do not silently relax caps after downtime, clock change, provider failure, or
missed delivery. Backward wall-clock movement suppresses until stored times are
again coherent. Timezone changes make old delivery records remain valid global
cooldown evidence; they do not manufacture a second local morning.

## 12. Conversation and provenance

Add `companion_initiative` to the existing bounded application-event type
allowlist. The archive entry is:

- role `assistant`;
- fixed globally unique `application_event_id` from the candidate;
- `application_event_type=companion_initiative`;
- no provider, model, source, Search, or context attribution; and
- no fabricated user turn.

This matches current reminder and Scheduled Work result delivery.
`completed_model_history()` already excludes application events, so initiative
messages cannot masquerade as completed model exchanges or trigger Memory
extraction. The existing chat must remain active and at the claimed revision;
V1 neither creates an event-only chat nor switches conversations.

Because model history intentionally excludes application events, a delivered
candidate also supplies one bounded, one-use supplemental system context to
the next local user turn in the same chat: initiative type, exact displayed
text, and safe anchor title if any. It is data only, carries no permission, and
is consumed on that user interaction. Reuse the existing supplemental-system
seam in `ConversationTurnService`. This makes “yes” or “not today” coherent
without inserting fake history. Existing deterministic handlers still decide
whether clarification, Search consent, or confirmation is required.

Slice 3 claims this context transactionally before recording the admitted
turn's meaningful-activity signal. The claim acknowledges the delivered
candidate and is consumed even if the provider later fails, preventing stale
context from leaking into a later turn. Malformed or unavailable context is
dropped without failing the ordinary Conversation operation.

Meaningful-activity persistence and candidate acknowledgement are deliberately
separate transactions. A turn in another chat, chat selection/new-session
control, Settings change, confirmation, or unrelated mutation may advance the
content-free activity revision without changing the delivered candidate. The
target chat ID on the candidate is the sole scope for reply-context claim and
for presenting Dismiss/Pause controls.

The Web transcript revision is the delivery signal. Every tab sees the same
server-authored event after normal `/api/attention` and `/api/session`
reconciliation; no tab-local message is authoritative.

## 13. Duplicate prevention and crash recovery

One SQLite `BEGIN IMMEDIATE` claim moves a candidate from `pending` to
`delivering`, binds process incarnation, event ID, exact text, chat ID, and
expected chat revision, and sets a short lease. Multiple tabs, repeated polls,
and concurrent request threads therefore have one winner.

Delivery is a recoverable cross-store transaction:

1. durably claim the candidate;
2. call idempotent `ChatService.append_application_event()` with its fixed
   event ID and asserted semantics;
3. verify the archived event; and
4. mark the candidate delivered.

Startup and expired-lease recovery inspect the event ID. If the exact event is
already archived, finish the delivery record. If it is absent, return the
candidate to pending only if it is still eligible. If the ID has different
semantics, fail closed and terminalize a safe conflict. A stale active-chat
revision releases/supersedes the claim and re-evaluates later; it never appends
to a different chat. Add a narrow archive lookup by application event ID so
recovery does not scan transcript text.

A disconnect before claim causes no delivery. A disconnect after the archive
append may leave a durable message that the user sees on reconnect; this is one
verified delivery, not a retry.

## 14. Model role and speech

Deterministic application wording is sufficient and recommended for V1. It is
fast, provider-independent, reviewable, private, and cannot accidentally
perform retrieval or expand authority. There is no initiative model call.

A future optional phrasing adapter may receive only the already-authorized
type and bounded safe display fields, with no tools, transcript, Memory,
Knowledge, Search, or eligibility control. Its failure must fall back to fixed
wording, and its output must pass strict length/content validation before the
same claimed event is archived. That adapter is deliberately deferred.

Proactive messages never start TTS, even when browser **Auto voice** is On.
Existing manual **Speak** remains an explicit presentation-only user action. It
does not record meaningful activity, acknowledge or resolve the candidate,
consume reply context, or hide Dismiss/Pause controls. There is no sound,
notification tone, microphone activation, or background audio.

## 15. Privacy boundaries

Initiative may inspect only timestamps, enums, revisions, stable IDs, current
active-chat identity, application busy/readiness flags, a validated Project
title, and whether a qualifying structured anchor exists. It may consume a
content-free signal that a meaningful interaction occurred.

It may not inspect or persist arbitrary transcript text, Memory contents,
Project objective/continuity text, Coding Work objective/output/files,
filesystem activity, browser history, other applications, microphone/audio,
camera, location, external services, or Web activity. It performs no network
request. Presence is ephemeral and contains no IP-derived identity beyond the
existing accepted local request boundary.

## 16. Failure behavior

- Missing, corrupt, unsafe, or unsupported initiative state fails the entire
  feature closed as Off; normal Tori operation continues with a sanitized
  Settings warning. Existing state is never replaced or repaired silently.
- Unavailable timezone, archive, active chat, anchor source, or readiness
  suppresses the affected evaluation and records only a bounded error code.
- Wording needs no provider. A stopped/unavailable model does not block a
  deterministic check-in, but the user's later request reports normal provider
  availability honestly.
- Archive append/verification failure is not reported as delivery. Recovery
  uses the fixed event ID; it never emits a second message to hide uncertainty.
- Disabling the feature fences new claims. A claim already archived remains
  visible history; a claim not yet archived is terminalized or allowed to
  expire after the fence wins.
- Shutdown stops and joins the process-local evaluator before dependent runtime
  services, and leaves any uncertain claim recoverable by lease/event
  reconciliation.

Operator events contain only type, state, bounded result/error code, and no
wording, title, chat text, or user content.

## 17. Settings design

Add one compact **Companion Initiative** section:

- master Off/On;
- Morning, Resume work, and Long silence toggles, all initially Off;
- morning start/end time;
- quiet-hours start/end time;
- current application timezone shown read-only;
- Pause for one day / one week and Resume now; and
- sanitized last-delivery type/time plus current snooze state.

Keep fixed cooldowns and caps visible in short explanatory copy, not adjustable
in V1. Enabling the master with no types selected remains truthfully enabled
but inactive. Settings changes are revision-safe, durable, and shared across
tabs. No runtime configuration file change is required.

## 18. Implementation slices

1. **Core policy and store:** exact-schema store, pure deterministic evaluator,
   civil-time/window logic, revisions, caps, candidate keys, leases, recovery,
   and backup/restore guard; test with temporary stores only.
2. **Narrow signals and anchors:** content-free meaningful-interaction hooks,
   readiness projection, Coding Work/Project resume providers, and privacy/
   false-positive tests.
3. **Conversation delivery:** new application event, archive event lookup,
   cross-store recovery, one-use supplemental reply context, and authority tests
   proving no model/capability call and no fabricated user turn.
4. **Local Web and Settings:** process-local bounded evaluation,
   attention/session archive reconciliation, check-in marker/actions, settings
   controls, mobile layout, and multi-tab race tests.
5. **Lifecycle and acceptance:** startup/shutdown composition, failure
   isolation, complete backup/restore coverage, full verification, and physical
   desktop/mobile/restart/no-browser/TTS acceptance.

No slice may enable the feature by default or introduce Discord delivery.

## 19. Physical acceptance checklist

- [x] Fresh install and migrated install show master Off and all types Off.
- [x] Enabling each type produces only its documented bounded wording under a
      forced disposable clock; no Search, model, command, Coding Work, Planning,
      Project, Skill, Capability Growth, Remote Chat, or network call occurs.
- [x] A weather/day offer performs nothing until a real user reply traverses
      existing consent/authority paths.
- [x] Morning delivery occurs only inside its local window; stopped-through-
      window does not catch up; a running no-browser process may deliver.
- [x] Resume uses only a qualifying structured anchor and never transcript/file
      inspection; stale, terminal, or revised anchors behave as specified.
- [x] Long silence is keyed to meaningful interaction, does not repeat when
      ignored, and uses non-guilting wording.
- [x] Recent user activity, quiet hours, global/type cooldowns, caps, snooze,
      an unresolved check-in, and every busy state suppress delivery. Browser
      focus and visibility do not affect eligibility.
- [x] Dismiss, one-day pause, one-week pause, master Off, and per-type Off
      survive restart and reconcile across desktop and physical mobile tabs.
- [x] Simultaneous tabs and repeated polls archive exactly one event; both tabs
      converge on the same transcript revision.
- [x] Crash points before claim, after claim, after archive append, and before
      delivery finalization recover without duplication.
- [x] No active chat means no message and no fabricated user/chat history.
- [x] A concise reply such as “yes” receives the one-use initiative context but
      no authority; an unrelated/later turn does not retain it.
- [x] Proactive delivery is silent with Auto voice both Off and On; manual Speak
      still requires a user gesture.
- [x] Store corruption, archive failure, invalid timezone/clock movement, and
      anchor-source failure fail closed without impairing normal Conversation.
- [x] Verified Backup/Restore preserves settings, snooze, candidates, and
      dedupe state; canonical runtime is byte-for-byte unchanged by tests.
- [x] Desktop and physical mobile presentation are readable, nonmodal, and do
      not steal composer focus or scroll position unexpectedly.

## 20. Deliberately deferred

Discord or any remote outreach; OS/mobile push notifications; CLI initiation;
model-written V1 phrasing; personalized or learned schedules; transcript or
Memory-derived topics; sentiment, loneliness, health, mood, or safety inference;
location/weather lookup; calendar/task summaries inside the initiative;
initiative-triggered actions; multiple-user policy; cross-host delivery; wake
phrase/passive audio; arbitrary plugins; background Capability Growth research;
and a generalized scheduler refactor.

These require separate scope, authority, privacy, delivery, and acceptance
decisions. None is implied by enabling Companion Initiative V1.
