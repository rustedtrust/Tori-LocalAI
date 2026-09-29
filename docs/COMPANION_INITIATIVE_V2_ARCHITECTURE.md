# Companion Initiative V2 — Attention & Relevance

**Status:** Complete; controlled physical acceptance, verification, repository
closeout, and verified production backup passed

**Authority:** Subordinate to the seven accepted founding documents and the
authority contracts of every source capability.

## Purpose

Companion Initiative V2 extends the accepted V1 system so meaningful Tori-owned
state—not browser presence or elapsed time—is the reason for proactive
attention. Presence and activity remain delivery-timing signals. Initiative is
still permission to speak, never permission to act.

## Attention model

The existing owner-private Companion SQLite database owns bounded attention
items keyed by source subsystem and source object. Each item records a stable
identity, kind, title, bounded deterministic summary, understandable attention
class, delivery level, source revision, material key, optional Project
association, source/update timestamps, disposition, deferral, and last surfaced
material. Candidate-to-attention links make conversational delivery and
anti-nagging one durable transaction.

The classes are `needs_attention`, `worth_reviewing`, and `informational`.
Delivery is `silent`, `gentle`, or `conversational`; these are policy classes,
not numerical relevance scores.

## Authoritative sources

Read-only adapters project only current Tori-owned state:

- Research: completed, completed-with-limits, failed, and interrupted jobs;
- Delegated/Coding Work: completed, failed, and waiting work, including exact
  user-decision requirements;
- Night Owl: current `new` finding versions and material fingerprints; and
- Scheduled Work: failed/interrupted runs and genuinely missed skipped runs.

Routine successful Scheduled Work is omitted. Projects do not create duplicate
items; an exact active-Project association adds context and can raise a silent
item to gentle visibility. Project association never grants authority.
Capability Growth remains outside the initial V2 source set because its own
recommendation UI already owns review lifecycle and adding it would duplicate
user decisions.

## Relevance and material change

Policy is deterministic. Failed/interrupted work and explicit decisions rank
above completed work; completed-with-limits ranks above routine completion;
active-Project association raises visibility; routine scheduled success is
suppressed. No model decides whether to interrupt.

Each adapter computes a material key from user-relevant lifecycle facts, not
timestamps. Re-observation or timestamp-only change preserves disposition.
Changed outcome, failure, result evidence, missed-run range, authorization need,
or Night Owl material fingerprint may reopen an item. Missing current source
state resolves only open/deferred items; unavailable source reads fail closed
and do not erase prior attention.

## Anti-nagging

`Review`, `Later`, and `Dismiss` are revision-safe durable transitions. Later
uses a bounded one-day deferral. Dismissed/reviewed items remain suppressed while
their material key is unchanged. Conversational delivery stores the exact
surfaced material key, preventing repeat delivery after restart. A genuinely
new material key reopens the canonical item rather than creating duplicates.

## Delivery

- Silent items remain in Workspace.
- Gentle items appear in the Workspace Attention surface without an unsolicited
  Conversation message.
- Conversational items may use the accepted V1 delivery claim, cooldown, caps,
  quiet hours, readiness, active-chat, and exactly-once recovery boundaries.

Existing Companion master and type toggles remain the opt-in boundary.
Non-Night-Owl conversational attention uses the existing Resume Work opt-in;
Night Owl retains its dedicated opt-in. Morning uses the existing Morning
opt-in and produces a maximum three-item brief only when unsurfaced meaningful
attention exists. Empty morning briefs and V2 timer-only Long Silence delivery
are suppressed in the V2 source composition. Existing V1 behavior remains
available in isolated legacy compositions used for compatibility tests.

## Conversation and Workspace

Workspace shows Needs Attention, Worth Reviewing, and a bounded Recently
Resolved group. Review updates Companion disposition and routes toward the
authoritative source surface where one exists; it does not copy full reports or
results into Companion state.

Bounded exact phrases support “What needs my attention?”, “What changed while I
was away?”, “Anything worth reviewing?”, and “Remind me about that later.” The
responses are provider-free application events. Recognition is deliberately not
a general task parser.

## Authority and privacy

Attention adapters can read bounded source projections and write only Companion
attention state. They cannot launch Research, Coding Work, MCP, commands,
Scheduled Work, or Night Owl; mutate Projects; install software; or grant
capability authority. Follow-up choices enter the existing proposal,
confirmation, and authorization paths.

Canonical attention state stores no generated prose as truth, credentials,
transcript bodies, Research reports, Coding output, or Night Owl source content.
Summaries are deterministic projections. The existing maintenance guard and
verified backup include the extended Companion database.

## Startup and failure

Startup preserves V1 delivery-lease reconciliation. Each evaluation reconciles
available authoritative sources before considering delivery. Exact-schema V3
stores migrate transactionally to V4 on the first authorized write; reads do not
silently replace corrupt or unsafe state. Restart does not reset dispositions or
surface history.

## Physical acceptance

On 2026-09-21, a disposable real Tori Web composition exercised controlled
Research completion, Night Owl finding, failed Delegated/Coding Work, and missed
Scheduled Work attention. Desktop and 390×844 narrow layouts showed correct
Needs Attention / Worth Reviewing / Recently Resolved ordering. Dismiss and
one-day Later survived reload; deferred items displayed their exact defer time.
The bounded Morning brief contained only two meaningful items, and the later
“What changed while I was away?” query correctly produced no unchanged recap.
A Research follow-up opened the normal exact authorization dialog; cancellation
recorded that no worker started. The disposable run wrote no canonical runtime.
