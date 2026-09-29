# Projects & Continuity V1 Architecture

**Project:** Tori

**Document:** Projects & Continuity V1 Architecture

**Status:** Finalized architecture; all six slices complete and Projects & Continuity V1 human accepted

**Reading note:** Section 2's “current reality” is the schema-6 architecture-review snapshot at `private revision omitted`; it is not the current schema or an incomplete-Projects claim. The separately accepted completion below and [Current State](FINAL_STATE.md) describe today's schema-7 Projects & Continuity V1.

**Architecture-review checkpoint:** `main` at `private revision omitted` (`Refresh project documentation`)
**Final completion checkpoint:** `main` at `private revision omitted` (`private revision omitted`)
**Authority:** Subordinate to `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`, `docs/ARCHITECTURE_GOVERNANCE.md`, and explicit current user direction

## 1. Verdict and purpose

Projects & Continuity V1 should be implemented as an in-place extension of the
existing canonical Project foundation. It should not introduce a second Project
store, a generic task manager, an autonomous agent, or a model-authored source of
truth.

A Project is Tori's durable continuity layer for an ongoing objective. It should
answer, from user-owned canonical state and source-owned capability records:

- What are we working on?
- Where did we leave off?
- What decisions have been made?
- What questions remain?
- Which conversations, Research jobs, Coding Work, Attention items, Night Owl
  findings, Scheduled Work definitions, and Knowledge sources belong here?
- What is the next planned step?

The governing interaction remains:

```text
Tori notices or proposes
-> the user decides
-> a bounded capability receives explicit authority
-> Tori owns and verifies the resulting state
```

Project membership is organization and context. It is never capability
authority.

## 2. Current reality and reusable foundation

The repository and the canonical runtime agree that the current conversation
archive schema is **6**. `ConversationArchiveStore` declares
`ARCHIVE_SCHEMA_VERSION = 6`; a read-only canonical-runtime inspection also
reported schema 6 with integrity `ok`. No runtime state was changed for this
architecture review.

### 2.1 Canonical Project persistence

`src/tori/conversation_archive.py` owns the existing `projects` table and the
nullable `chats.project_id` relationship:

- `projects.identifier` is an immutable `project-` plus 32 lowercase hex ID;
- `ProjectRecord` contains `identifier`, `title`, `status`, `objective`,
  `continuity_brief`, `revision`, `created_at`, and `updated_at`;
- Project status is `active`, `paused`, or `completed`;
- one Project can have many chats, while a chat has zero or one Project;
- `chats.project_id` references `projects(identifier) ON DELETE SET NULL`;
- create-plus-first-chat-association is atomic;
- Project, chat-association, lifecycle, and deletion mutations use optimistic
  revisions and fresh verification reads;
- `ConversationArchiveStore.delete_project()` explicitly detaches associated
  chats and increments each chat revision before removing the Project;
- ordinary Project deletion preserves transcript entries and archive memory
  extraction records.

`ChatService` exposes these store operations without transport concerns.
`ProjectApplicationService` is already the presentation-neutral boundary for:

- `list_projects()` and `get_project()`;
- `project_for_conversation()`;
- `create_project()` and `update_project()`;
- `transition_project()`;
- `associate_conversation()` and `detach_conversation()`; and
- `delete_project()`.

V1 should extend `ProjectApplicationService`; it should not bypass it with new
Project mutations in `WebApplication` or browser JavaScript.

### 2.2 Current Conversation and UI behavior

`WebApplication` currently owns Project HTTP orchestration and process-local
new-chat selection:

- `GET /api/projects` lists Project records and the Project associated with the
  active conversation;
- `/api/projects/create`, `/api/projects/update`,
  `/api/projects/lifecycle`, `/api/projects/associate`, and
  `/api/projects/delete` expose the existing bounded mutations;
- `_pending_new_chat_project_id` allows an explicitly selected Project to be
  applied when the first completed turn creates a new canonical chat;
- `_persist_archive()` passes that ID to `ChatService.create_chat()` and clears
  the pending selection only after verified persistence;
- the current Manage -> Projects surface can create, edit, transition,
  associate, detach, and delete Projects;
- Recent Chats can display a Project-title badge; and
- the conversation header can display the active Project.

This is enough canonical machinery for **New Project Chat**, but the complete
Project-to-conversations navigation and first-class Project Home workflow do not
exist. The roadmap and user guide correctly describe Projects as preserved but
deferred and not yet a completed primary workspace.

V1 should expose an explicit **New Project Chat** action from Project Home. It
must select one exact Project ID and revision, start a fresh conversation through
the existing new-session lifecycle, and retain only a process-local pending
association until the first canonical chat is created. It must never infer an
association from conversation content.

### 2.3 Current Project context behavior

`src/tori/projects.py` currently provides:

- `build_project_context(ProjectRecord)`, which renders title, status,
  objective, and the entire continuity brief as labeled data;
- `PROJECT_CONTEXT_LABEL`, which explicitly says Project context is data only;
- `ContinuitySections`, `render_continuity_brief()`, and
  `parse_project_continuity_brief()` compatibility handling;
- `build_continuity_update()`, which constructs a proposed four-section brief;
  and
- bounded conversational Project intent recognition.

`WebApplication._supplemental_context()` currently finds the Project itself and
calls `build_project_context()`. `ConversationSession` then treats the rendered
string as a mandatory suffix in the existing `plan_context()` budget. Generic
`ArchiveContext` telemetry records token counts and included/omitted ordinary
history counts, but it does not record which Project fields or records were
actually supplied.

Two V1 changes are required:

1. Project selection, tiering, rendering, and omission accounting must move out
   of `WebApplication` into an application-level `ProjectContextService`.
2. The exact Project context supplied for each model turn, plus an explicit
   omission manifest, must be inspectable later.

### 2.4 `continuity_brief` is compatibility state

The existing `continuity_brief` is one bounded four-section string:

```text
Current focus
...

Key decisions
...

Open issues / blockers
...

Next step
...
```

It remains canonical only as a legacy compatibility value. It is not the future
canonical representation of Project state, decisions, questions, or plans.

`build_continuity_update()` currently appends recent ordinary user messages to
the `Key decisions` section. That behavior is unsuitable for V1 canonical state:
recent conversation text is evidence for a suggestion, not user approval of a
decision. V1 must retire that update path. The legacy brief remains readable,
but normal editing and synthesis into it end when V1 becomes active, and it
must not populate or rewrite structured records.

The compatibility reader must tolerate a safe bounded legacy brief that is not
structurally parseable. It should label it as unstructured legacy material and
must not silently repair it. Schema 7 retains the column and existing value,
but V1 removes it from normal Project creation and update workflows. New
Projects store the required empty compatibility value. No automatic continuity
updater may create canonical decisions, questions, plan items, or state from
the brief or from recent conversation text.

### 2.5 Current cross-capability ownership

The current capability stores already establish the correct ownership split:

| Capability | Current authoritative record | Existing Project relationship | V1 reuse decision |
| --- | --- | --- | --- |
| Conversations | schema-6 `chats` and `transcript_entries` | Native `chats.project_id` FK | Reuse directly; add Project-scoped listing and New Project Chat workflow. |
| Research Worker | `SQLiteResearchStore.research_jobs` / `ResearchJob` | Native nullable `project_id` | Reuse directly; Project Home reads Research projections, never copies reports or job state. |
| Coding Work | `SQLiteCodingWorkStore.coding_work` / `CodingWork` | Native nullable `project_id` | Reuse directly; Project Home reads `CodingWorkApplicationService` projections. |
| Companion Attention | `SQLiteCompanionInitiativeStore.attention_items` / `AttentionItem` | Native nullable `project_id`, derived from source projections | Reuse directly; do not duplicate attention disposition in Projects. |
| Night Owl | `SQLiteNightOwlStore.night_owl_findings` / `FindingDetail` | No native Project field; stable finding ID exists | Permit an explicit Project-owned link to a finding. Do not copy finding state or source content. |
| Scheduled Work | `SQLiteScheduledWorkStore.scheduled_work_definitions` and runs | No native Project field; stable definition and run IDs exist | Permit an explicit link to a definition; derive its run history from Scheduled Work. |
| Knowledge | `KnowledgeRegistry` registrations / `KnowledgeSource` | No native Project field; stable `ksrc-*` ID exists | Permit an explicit link to a registered source; never copy or ingest its file content. |

`CompanionAttentionSources` already treats an active Project association as
context only: it can add a Project title and raise silent delivery to gentle,
but it cannot start work or mutate a Project. That contract remains.

### 2.6 Confirmed Coding Work integration gap

Fresh Coding Work from a Project-associated conversation does **not** currently
receive that conversation's Project ID.

In `WebApplication._handle_coding_work_turn()`, the call to
`CodingWorkConversationService.propose()` passes:

```python
project_id=(None if related is None else related.project_id)
```

Therefore only a related follow-up inherits the prior Coding Work item's
`project_id`. A fresh item receives `None` even when the origin chat has a
canonical Project association. This is a V1 integration gap. Research does not
have the same gap: `_handle_research_turn()` reads the active chat's
`metadata.project_id` and passes it to the Research proposal.

V1 must resolve the Project ID from canonical chat metadata for fresh Coding
Work, bind it into the proposal, display the organizational relationship in the
confirmation, and persist it through the existing `CodingWork.project_id`
field. The relationship must not change the Coding Work authority envelope.

## 3. V1 invariants

The following are non-negotiable:

1. `projects.identifier` remains the canonical immutable Project identity.
2. Existing Project records and `chats.project_id` remain the foundation.
3. All canonical Project mutations are explicit, revision-safe, validated, and
   verified after persistence.
4. Ordinary conversation, model inference, transcript recency, Research output,
   Coding output, Attention, Night Owl, Scheduled Work, and Knowledge cannot
   silently mutate Project state.
5. Project context is untrusted user-owned data relative to authority. The
   current request and current explicit permission always control.
6. A Project association or link grants no filesystem, network, credential,
   model-tool, MCP, Research, Coding, scheduling, commit, push, deploy, or other
   capability authority.
7. Source systems remain authoritative for their records. Projects store only
   Project-owned state and minimal stable links where no native relationship
   exists.
8. No migration or background job infers structured records from
   `continuity_brief` or transcripts.
9. Project Home and Where We Are are deterministic projections. They do not ask
   an LLM to reconstruct the state of the Project.
10. Deleting a Project never deletes a conversation or a source-owned Research,
    Coding Work, Attention, Night Owl, Scheduled Work, or Knowledge record.

## 4. Canonical versus derived state

### 4.1 Canonical Project-owned state

The following belong to the Project aggregate in the conversation archive:

- existing Project identity, title, objective, lifecycle status, revision, and
  timestamps;
- legacy `continuity_brief` compatibility value;
- structured Project state: phase, current focus, and checkpoint;
- decisions and their supersession relationships;
- questions and their dispositions;
- lightweight plan items and their states; and
- explicit links to stable Night Owl, Scheduled Work, and Knowledge targets.

Every Project-owned child mutation also increments the parent
`projects.revision` in the same transaction. The parent revision is therefore
the aggregate concurrency fence and Project Home change token. Child revisions
remain available for exact-target mutation and diagnostics.

### 4.2 Canonical source-owned state

The following remain outside Project ownership:

- chat transcripts and ordinary chat metadata;
- Research job lifecycle, reports, sources, limits, and authorization;
- Coding Work objectives, workspaces, authority receipts, progress, and results;
- Attention class, delivery, state, deferral, and surfaced-material tracking;
- Night Owl findings, versions, sources, review state, and promotions;
- Scheduled Work definitions, authorizations, runs, notifications, and missed
  occurrence truth; and
- Knowledge registrations and the external source files they reference.

Projects query these systems through narrow read-only application projections.
They do not write those tables to make Project Home look complete.

### 4.3 Derived state

The following are projections, not additional truth:

- Project Home;
- Where We Are;
- counts, badges, and section ordering;
- the next planned step;
- recent activity;
- context tier selection and rendering; and
- attention summaries shown inside Project Home.

Derived views must expose unavailable or stale source records honestly. They
must not repair, cache as canonical truth, or overwrite the source system.

## 5. Proposed conversation archive schema 7

Schema 7 should add Project-owned tables beside the existing `projects` table,
not replace it. Keeping structured state separate avoids rewriting schema-6
Project rows and makes the absence of migrated structured state explicit.

All text limits below are application constants mirrored by SQLite checks. All
IDs are application-generated lowercase hexadecimal identities. Exact names and
limits should be locked by migration tests before implementation.

### 5.1 `project_state`

One optional structured state record per Project:

| Column | Meaning |
| --- | --- |
| `project_id` | Primary key and FK to `projects(identifier) ON DELETE CASCADE`. |
| `phase` | Optional user-owned phase label, at most 120 characters. |
| `current_focus` | Optional current focus, at most 1,000 characters. |
| `checkpoint` | Optional verified stopping point/hand-off, at most 2,000 characters. |
| `revision` | Positive row revision. |
| `created_at`, `updated_at` | Canonical UTC timestamps. |

At least one of `phase`, `current_focus`, or `checkpoint` must be non-null and
non-empty. Absence of a row means **not yet recorded**, not a migration failure
and not permission to parse the legacy brief.

### 5.2 `project_decisions`

| Column | Meaning |
| --- | --- |
| `identifier` | Immutable `decision-*` ID. |
| `project_id` | FK to `projects(identifier) ON DELETE CASCADE`. |
| `text` | Immutable accepted decision text, at most 2,000 characters. |
| `importance` | `normal` or `important`; controls Stable context priority only. |
| `state` | `active` or `superseded`. |
| `supersedes_decision_id` | Optional unique self-reference to the prior active decision. |
| `revision` | Positive row revision. |
| `created_at`, `updated_at` | Canonical UTC timestamps. |

Decision text is never edited in place. A changed decision creates a new row in
one transaction, points `supersedes_decision_id` at the old row, and marks the
old row `superseded`. V1 supersession is linear: a new decision has zero or one
direct predecessor, and the unique `supersedes_decision_id` constraint permits
any decision to have at most one direct successor. The application verifies
that both rows belong to the same Project, that the old row is active, that its
expected revision still matches, and that adding the edge cannot form a cycle.
Branching and merging decision graphs are rejected. This preserves historical
meaning and one auditable chain.

V1 does not support deleting individual decisions. A correction is represented
as a superseding decision. Project deletion removes all Project-owned decision
rows by cascade.

### 5.3 `project_questions`

| Column | Meaning |
| --- | --- |
| `identifier` | Immutable `question-*` ID. |
| `project_id` | FK to `projects(identifier) ON DELETE CASCADE`. |
| `text` | Immutable question text, at most 1,500 characters. |
| `state` | `open`, `resolved`, `deferred`, or `dismissed`. |
| `disposition_note` | Optional bounded resolution/deferral/dismissal note, at most 2,000 characters. |
| `revision` | Positive row revision. |
| `created_at`, `updated_at` | Canonical UTC timestamps. |

`open <-> deferred` is allowed. `open` or `deferred` may become `resolved` or
`dismissed`. Resolved and dismissed questions are terminal in V1; if the issue
returns, create a new question rather than rewriting history.

### 5.4 `project_plan_items`

| Column | Meaning |
| --- | --- |
| `identifier` | Immutable `plan-item-*` ID. |
| `project_id` | FK to `projects(identifier) ON DELETE CASCADE`. |
| `text` | One bounded concrete step, at most 1,000 characters. |
| `state` | `planned`, `active`, `blocked`, `deferred`, or `completed`. |
| `state_note` | Optional bounded blocker/completion/deferral note, at most 1,000 characters. |
| `sort_order` | Non-negative integer used only for user-owned ordering. |
| `revision` | Positive row revision. |
| `created_at`, `updated_at` | Canonical UTC timestamps. |

The plan is deliberately flat. V1 has no projects-within-projects, epics,
sprints, assignees, estimates, story points, labels, dependency graph, or
general task automation. Plan changes are explicit Project mutations and do not
create Scheduled Work or calendar records.

### 5.5 `project_links`

This is the only new explicit cross-capability association table:

| Column | Meaning |
| --- | --- |
| `identifier` | Immutable `project-link-*` ID. |
| `project_id` | FK to `projects(identifier) ON DELETE CASCADE`. |
| `target_type` | `night_owl_finding`, `scheduled_work_definition`, or `knowledge_source`. |
| `target_id` | Stable source-owned identifier. |
| `revision` | Positive row revision. |
| `created_at`, `updated_at` | Canonical UTC timestamps. |

`(project_id, target_type, target_id)` is unique. A link can be created only
after the matching source application confirms that the target exists and the
user approves the exact Project and target. The link stores no title, summary,
content, status, authority, schedule, path, or report.

No `project_links` row is created for conversations, Research, Coding Work, or
Attention because those systems already own native `project_id` relationships.
For Scheduled Work, link the durable definition, not each run. Run history is
derived through `ScheduledRun.job_id`. For Night Owl, link the durable finding,
not a transient version. Knowledge links reference only the registration ID,
never a file path or copied passage.

If a source-owned target later disappears, the link remains a truthful missing
reference until the user removes it or deletes the Project. Project Home shows
it as unavailable; it does not recreate or silently drop it.

### 5.6 `project_context_receipts`

Context transparency belongs to the conversation turn that used the context,
not to mutable Project truth. Add a conversation-owned receipt keyed by the
ordinary assistant entry:

| Column | Meaning |
| --- | --- |
| `chat_id`, `assistant_sequence` | Composite primary key and composite FK to `transcript_entries(chat_id, sequence) ON DELETE CASCADE`. |
| `project_id` | Exact Project ID used and FK to `projects(identifier) ON DELETE CASCADE`. |
| `project_revision` | Parent aggregate revision read for the pack. |
| `estimator_version` | The existing context estimator version. |
| `budget_tokens` | Project-context allocation for this turn. |
| `stable_json` | Ordered exact Stable items supplied. |
| `working_json` | Ordered exact Working items supplied. |
| `historical_json` | Ordered exact Historical items supplied. |
| `omitted_json` | Ordered item/category omissions and reasons. |
| `rendered_context` | Exact system text sent to the provider. |
| `rendered_digest` | SHA-256 of `rendered_context`. |
| `created_at` | Canonical UTC timestamp. |

The receipt is committed atomically with the ordinary assistant entry and
existing `ArchiveContext` telemetry. It has two ownership fences: its composite
FK to `transcript_entries(chat_id, sequence) ON DELETE CASCADE` removes it when
the owning conversation is permanently deleted, and its Project FK removes it
when that Project is deleted. The referenced transcript entry must be an
ordinary provider-backed assistant entry; application-event entries cannot own
receipts.

Receipt cardinality is at most one row per qualifying assistant turn. Every
text/JSON column and the total serialized receipt have finite application
limits mirrored by schema checks; the exact storage ceilings are locked with
schema-7 tests before implementation. JSON has a closed versioned shape. A
receipt contains only context actually supplied or explicit omission metadata;
it does not store chain-of-thought, credentials, source-system reports, Coding
output, unrelated transcript text, or omitted content. Receipts are audit and
transparency records only: they are never candidates for Stable, Working,
Historical, memory, Knowledge, or ordinary conversation context.

This dual cascade deliberately gives exact historical inspection while both
owners exist without preserving deleted Project content indirectly. Project
deletion leaves the conversation and transcript intact but removes that
Project's receipts; permanent conversation deletion removes its receipts even
when the Project still exists.

### 5.7 Indexes

Schema 7 should add only query-driven indexes:

- each Project-owned table by `(project_id, state, updated_at)` where a state
  exists;
- plan items by `(project_id, sort_order, identifier)`;
- links by `(project_id, target_type, target_id)` through the unique constraint;
- context receipts by `project_id` only if inspection queries require it; and
- no full-text or vector index in V1.

## 6. Structured mutation model

`ProjectApplicationService` should gain presentation-neutral use cases with
typed immutable request/result records. The exact implementation may split the
store-facing code into a focused repository helper, but the public application
boundary should include:

- `get_project_home(project_id)`;
- `list_project_conversations(project_id)`;
- `update_project_state(...)`;
- `add_decision(...)` and `supersede_decision(...)`;
- `add_question(...)` and `transition_question(...)`;
- `add_plan_item(...)`, `update_plan_item(...)`, and
  `transition_plan_item(...)`;
- `link_resource(...)` and `unlink_resource(...)`; and
- `prepare_new_project_chat(project_id, expected_project_revision)`.

Every operation receives an exact Project ID and expected parent revision.
Updates to existing child records also receive the child's exact ID and expected
revision. The store uses one `BEGIN IMMEDIATE` transaction, rechecks all
revisions and relationships, performs the mutation, increments
`projects.revision`, commits, and verifies by a fresh read.

The model may suggest an exact candidate such as:

> That sounds like a Project decision. Add it?

The suggestion is process-local and inert. Canonical creation requires a
visible proposal containing the exact text, target Project, and current
revision, followed by the user's one-use confirmation. Application code—not the
model—resolves IDs, allowed transitions, and persistence arguments.

## 7. Project Home

Project Home is a presentation-neutral projection assembled by
`ProjectApplicationService`, with narrow read-only ports for source-owned
systems. The custom web UI is one client; the projection must be usable by a
future CLI or remote client without moving domain rules into JavaScript.

### 7.1 Projection sections

`ProjectHome` should contain:

- Project identity, title, objective, lifecycle status, aggregate revision, and
  timestamps;
- structured phase, current focus, and checkpoint;
- a deterministic Where We Are projection;
- ordered plan items;
- active and historical decisions;
- open/deferred and resolved/dismissed questions;
- associated conversation metadata, never transcript previews by default;
- Research jobs whose native `project_id` matches;
- Coding Work whose native `project_id` matches;
- Attention items whose native Project/source relationship matches;
- explicitly linked Night Owl findings;
- explicitly linked Scheduled Work definitions plus bounded run summaries;
- explicitly linked Knowledge registration metadata; and
- recent activity derived from the canonical records above.

Each source section includes source identity, source revision, lifecycle state,
updated time, and a safe route/reference for opening the source owner. Project
Home does not flatten source records into generic Project tasks.

### 7.2 Where We Are

Where We Are is built without a model. Its fields are deterministic:

- `status`: `projects.status`;
- `phase`: `project_state.phase`, otherwise “Not yet recorded”;
- `current_focus`: `project_state.current_focus`, otherwise “Not yet recorded”;
- `checkpoint`: `project_state.checkpoint`, otherwise “Not yet recorded”;
- `next_planned_step`: the lowest `sort_order` active plan item, otherwise the
  lowest planned item, otherwise none;
- `blocked`: ordered blocked plan items and their exact state notes;
- `open_questions`: count and bounded ordered list of open questions;
- `deferred_questions`: count only in the compact projection; and
- `last_updated_at`: the newest timestamp among Project-owned structured state.

No transcript summary, Research report, Coding result, or legacy brief is
silently transformed into these fields. If structured state is absent, Where We
Are says so. The legacy brief appears separately under **Legacy continuity**.

### 7.3 Recent activity

Recent activity is a bounded merge of source-owned and Project-owned event-like
facts already represented by canonical rows and timestamps. V1 should not add a
second activity log. Examples include a decision being superseded, a question
being resolved, a plan item completing, an associated chat updating, or a
source-owned job changing state.

Each projection port identifies its authoritative timestamp field. The
application parses those canonical UTC values through one shared strict
normalizer, orders activity newest-first, and breaks equal timestamps by
`source_type` and then stable object ID, both ascending. An invalid timestamp
makes that source section unavailable rather than allowing locale-dependent or
arrival-order sorting.

Source reads are isolated. If one store is unavailable, unreadable, corrupt, or
changes incompatibly during assembly, Project Home returns the healthy sections
and activity entries as an explicitly partial projection, names each
unavailable source and safe failure reason, and does not claim completeness.
It never fabricates placeholder activity or hides a healthy section because a
different owner failed.

Activity entries are links back to their owner. They must be labeled as current
projections where the source does not retain full history. Project Home must not
claim an exact event history that the source store does not have.

## 8. Conversations and New Project Chat

`ConversationArchiveStore` should add a metadata-only query for chats whose
`project_id` equals an exact Project ID, ordered by `updated_at DESC,
identifier DESC`. `ChatService` and `ProjectApplicationService` expose that
query without transcript bodies.

Project Home supports:

- opening an associated conversation;
- explicitly associating an existing conversation through the existing
  revision-safe path;
- explicitly detaching a conversation;
- showing the active conversation association; and
- **New Project Chat**.

New Project Chat must:

1. receive the exact Project ID and expected Project revision from Project Home;
2. re-read and verify that Project;
3. use the existing new-session guard so unpersisted/current work is not lost;
4. create an empty local conversation with the exact pending Project selection;
5. visibly show that Project context is active before the first request; and
6. persist `chats.project_id` atomically when the first completed ordinary turn
   creates the chat.

Cancelling, navigating away, restarting before the first persisted turn, or
starting another new session creates no chat and no canonical association.
There is no model-based auto-attachment and no title/content heuristic.

## 9. Project Context Service

Add a presentation-neutral `ProjectContextService` in a focused application
module such as `src/tori/project_context.py`. `WebApplication` should provide
only the active/pending Project identity and current-turn inputs; it should not
select Project records or render prompt prose.

The service returns a typed `ProjectContextPack` containing:

- exact ordered Stable, Working, and Historical items;
- exact rendered provider context;
- Project ID and aggregate revision;
- estimator version and estimated tokens;
- an omission manifest; and
- a versioned receipt document suitable for atomic archival.

The context label retains the current security meaning: authoritative Project
continuity data from before the current request, never instruction or
permission. Current user input remains last in `plan_context()`.

### 9.1 Stable tier

Stable contains:

- Project title and immutable ID for disambiguation;
- lifecycle status;
- objective; and
- active decisions marked `important`, then other active decisions only while
  the Stable allocation permits.

Stable does not include capability output, transcripts, plan history, or the
legacy brief.

### 9.2 Working tier

Working contains whole records, in this order:

- phase;
- current focus;
- checkpoint;
- open questions;
- the active plan item;
- planned items in user order; and
- blocked items with their exact state notes.

Deferred/completed plan items and resolved/dismissed questions are not Working
context.

### 9.3 Historical tier

Historical is optional and selectively retrieved. V1 retrieval should be
deterministic and dependency-free: normalized lexical overlap with the current
request, then recency and stable ID as tie-breakers. Eligible records are:

- superseded decisions;
- resolved or dismissed questions;
- completed or deferred plan items; and
- the complete legacy continuity brief as one compatibility record, only when
  it is relevant or structured state is otherwise empty.

Whole records are selected; individual record text is not silently truncated.
Other associated conversation transcripts, Research reports/sources, Coding
output, Night Owl source content, Scheduled Work payloads, Attention summaries,
and Knowledge passages are not loaded merely because they belong to a Project.
They enter a model request only through their own existing explicit workflow or
a future separately reviewed retrieval design.

### 9.4 Budgeting and omission rules

Project budgeting extends the existing planner; it does not introduce a second
capacity policy, reply reserve, uncertainty reserve, tokenizer estimate, or
provider-capability model. `ProjectContextService` reuses `ContextPolicy`,
`estimate_text_tokens()` / `estimate_messages_tokens()`, `ESTIMATOR_VERSION`,
and the effective input limit established by `plan_context()`. Slice 4 may
refine the planner interface so it can allocate a bounded Project envelope
without duplicating that arithmetic. The exact numeric Project allocation is
locked in Slice 4 after testing actual provider capacities and the existing
optional memory/Knowledge behavior.

Slice 4 locks the allocation rule without creating a second token policy. The
service reads the effective input limit produced by the existing conversation
policy, verified provider capacity when known, reply reserve, uncertainty
reserve, and lexical estimator. The Project allocation is the remaining input
capacity after mandatory Tori guidance, the current user request, and other
mandatory current-turn system data. Stable and Working are protected within
that remainder. Historical is admitted only when the resulting Project message
also fits alongside all currently selected optional Memory/Knowledge messages;
therefore Historical is removed before those optional sources or any
Stable/Working record. Ordinary conversation exchanges continue to use the
existing planner's whole-exchange trimming after this selection.

Selection is deterministic and uses whole records. The minimum Stable spine is
Project ID, title, status, and objective. Remaining Stable records are ordered
important active decisions first and then other active decisions by canonical
time and stable ID. Working follows in the order defined above. Historical is
considered only after the selected Stable and Working candidates; when capacity
is constrained, every Historical record is discarded before any Stable or
Working record is omitted. If Stable or Working still exceeds its allocation,
lower-priority whole records are omitted in reverse deterministic selection
order. Record text is never silently clipped.

The omission manifest records category, stable record IDs or an exact count
when IDs would exceed its own bound, provenance, and one closed reason:
`budget`, `not_relevant`, `source_not_loaded`, or `unavailable`. It never stores
the omitted text, and omitted state is never represented as absent from the
Project. If even the minimum Stable spine cannot fit, planning fails through
the existing `ContextPlanningError` path before provider contact.

Ordinary conversation history continues to trim according to
`plan_context()`, using its existing whole-exchange behavior. Project
association never means that all Project history is inserted into every prompt.

## 10. Context transparency

When a Project pack is active, every conversation surface should show a compact
**Project context active** indicator before submission. After completion, turn
inspection should show the stored `project_context_receipts` record:

- exact Stable items supplied;
- exact Working items supplied;
- exact Historical items supplied;
- the exact rendered system text and digest;
- estimated token allocation and estimator version; and
- what was not loaded and why.

The UI should not reconstruct this disclosure from current Project state. It
must read the receipt tied to that historical assistant turn. A receipt is also
useful through a presentation-neutral transcript/API document so transparency
does not depend on the custom web client.

Receipt inspection is read-only. Receipt content is never fed back to the model
or used as a retrieval corpus. If the owning Project has been deleted, its
receipts have also been deleted and the transcript UI truthfully reports that
no Project-context audit record remains for that turn.

If no Project context was supplied, the turn shows no receipt. If Project
context planning failed, no provider request and no success receipt exists; the
safe error explains that required current-turn context did not fit.

## 11. Cross-capability integration

### 11.1 Research Worker

Keep `ResearchJob.project_id` authoritative for organizational association.
The current fresh-proposal path already copies the active chat's canonical
Project ID. V1 should add a bounded Project-filtered read method or application
projection rather than scanning and copying Research rows into Projects.

The Project ID is never included in the worker's public objective payload and
never expands `ResearchAuthority`. Project Home may show job metadata and open
the Research owner; it does not inline a report into Project context.

### 11.2 Coding Work / Delegated Work

Fix the confirmed fresh-work gap by resolving the origin chat's canonical
`project_id` before constructing `CodingWorkProposal`. Include the Project ID
and title in the human-reviewable proposal as organization-only metadata and
persist it through `CodingWorkApplicationService.create_work()`.

Follow-up work may continue inheriting `related.project_id`, but the application
must reject a conflicting current-chat Project rather than silently choose one.
No Project field changes `CodingWorkAuthority`, workspace validation, sandbox,
network isolation, Git restrictions, or confirmation requirements.

### 11.3 Companion Attention

Reuse `AttentionItem.project_id` and `CompanionAttentionSources`. Project Home
reads attention items; it does not copy or overwrite `state`, `revision`,
deferral, or material keys. Review/Later/Dismiss continues through the Companion
Attention owner.

For Night Owl or Scheduled Work attention without a native `project_id`, Project
Home may derive relevance through an explicit source link: Night Owl attention
matches a linked finding ID; Scheduled Work attention resolves its run to a
linked definition ID. Do not add duplicate Project attention records.

### 11.4 Night Owl

Night Owl continues to choose research topics only from its explicit grant and
fixed categories. Project content does not form queries and a Project link does
not authorize a run. Users may explicitly link an existing finding after source
validation. Project Home shows current finding metadata and routes review back
to `NightOwlApplicationService`.

### 11.5 Scheduled Work

Scheduled Work keeps all schedule, authorization, run, missed-occurrence, and
notification truth. A user may explicitly link an existing durable definition.
Creating a plan item or linking a definition never creates, edits, resumes, or
runs Scheduled Work.

If a Project-associated conversation creates Scheduled Work, its capability
confirmation may offer a separate explicit organization choice. Because the
conversation archive and Scheduled Work use different databases, failure to
create the optional Project link must be reported as a partial outcome; the
verified Scheduled Work record must not be rolled back or falsely reported as
uncreated.

### 11.6 Knowledge

Projects may link a `KnowledgeSource.identifier` after `KnowledgeRegistry`
verifies it exists. The link grants no additional file access: registration
semantics, live safe-file validation, size/format limits, and removal remain
owned by Knowledge. Project context never loads Knowledge passages implicitly.

## 12. Migration and legacy compatibility

### 12.1 Recommended 6 -> 7 evolution

Implement a dedicated module such as
`src/tori/conversation_archive_schema7_migration.py` and update the explicit
`scripts/migrate-conversation-archive-schema` entry point only when the
implementation mission is authorized.

The migration must:

1. require one exact existing schema-6 archive;
2. require Tori to be stopped and reject `-journal`, `-wal`, and `-shm`
   sidecars;
3. use descriptor-bound no-follow opening and recheck file identity;
4. run read-only preflight integrity, exact schema-object, metadata, and foreign
   key validation;
5. capture all schema-6 values in deterministic order;
6. use `BEGIN IMMEDIATE`;
7. create only the schema-7 tables and indexes, leaving existing `projects`,
   `chats`, `transcript_entries`, `archive_state`, and `memory_extractions`
   values unchanged;
8. update `archive_metadata.schema_version` from exactly `6` to exactly `7`;
9. run the full schema-7 validator, `PRAGMA integrity_check`, and
   `PRAGMA foreign_key_check` before commit;
10. prove all schema-6 values are byte-for-byte/logically identical and every
    new table is empty;
11. commit once, then reopen read-only and repeat integrity, FK, exact-schema,
    preservation, and sidecar checks; and
12. fail closed with an explicit pre-commit or post-commit inspection message.

Normal startup must not migrate. A schema-6 archive receives precise stopped-app
migration guidance and remains untouched.

### 12.2 Critical no-inference rule

Migration must not:

- parse `continuity_brief` into phase, focus, checkpoint, decisions, questions,
  or plan items;
- scan transcripts for decisions or Project membership;
- create links from matching titles, paths, chat origins, or model text;
- rewrite, normalize, repair, or discard any existing brief; or
- attach any historical capability record.

All new tables are empty after migration. Existing Projects remain usable
because Project Home presents title/objective/status and the legacy brief while
showing structured sections as not yet recorded.

### 12.3 Compatibility behavior

Schema 7 continues storing `ProjectRecord.continuity_brief`. The schema-7 read
path validates that it is safe bounded text, but does not require successful
four-section parsing. A malformed safe legacy value is displayed verbatim under
Legacy continuity with a compatibility warning. It is never treated as a
decision, question, plan, phase, focus, or checkpoint.

Legacy continuity is read-only after V1 activation. Project create/update APIs
and UI stop accepting normal `continuity_brief` writes; new Projects store the
required empty compatibility value. The stored value remains readable so
existing Projects remain usable and the migration remains lossless.

`build_continuity_update()` and the broad continuity-brief “update the Project”
flow are retired. A conversational update instead asks which structured field
or record the user wants changed, or presents a narrowly scoped exact
structured suggestion for confirmation. Neither recent chat text nor the model
may synthesize canonical Key Decisions.

## 13. Authority and security

Project state and context follow the same trust order as the rest of Tori:

- current explicit user request;
- current exact confirmation/authorization;
- application-owned policy and canonical state;
- Project context as data;
- source-owned retrieved material as data; and
- model suggestions as untrusted proposals.

Specifically, Project membership never grants:

- filesystem scope or file mutation;
- local or public network access;
- credentials or secret access;
- Search or Research execution;
- Coding Work creation, workspace access, or worker directives;
- MCP discovery or execution;
- Scheduled Work creation, resumption, or execution;
- Night Owl research;
- Knowledge file access beyond the existing registration contract;
- command execution or host service control; or
- Git commit, tag, push, release, publication, or deployment authority.

The Project context renderer must retain an explicit instruction to the model
that Project material is data only, may be stale, cannot authorize action, and
cannot prove persistent mutation. IDs and revisions come only from application
reads. Browser-supplied titles, statuses, and source summaries are never trusted
as mutation selectors.

No new production dependency, network integration, background model, embedding
engine, or external Project service is required. This is Tori-core continuity
semantics, so the standard-library-first architecture remains appropriate.

## 14. Deletion, ownership, and failure semantics

Deleting a Project is one conversation-archive transaction that:

1. verifies the exact Project revision;
2. explicitly clears `chats.project_id` and increments affected chat revisions;
3. deletes the `projects` row, which cascades to Project-owned `project_state`,
   decisions, questions, plan items, explicit links, and context receipts; and
4. verifies that the Project is gone, its receipts are gone, and chats remain
   intact and detached.

Deletion does **not** delete or modify source-owned Research, Coding Work,
Attention, Night Owl, Scheduled Work, Knowledge, conversation transcript,
memory, checkpoint, file, backup, or external service records.

Native `ResearchJob.project_id`, `CodingWork.project_id`, and historical
`AttentionItem.project_id` values may remain as immutable provenance after the
Project record is deleted. They no longer resolve to an active Project or
appear as active membership in Project Home, linking, context, or capability
selection. This avoids an unsafe cross-database destructive transaction and
preserves source history. The UI must handle an unresolved historical Project
ID without treating it as authority or corruption.

Project-owned explicit links are removed by Project cascade. Project context
receipts for that Project are also removed by their Project FK so they cannot
preserve deleted Project content indirectly. The owning conversations and
their ordinary transcript entries remain intact and detached. Independently,
permanent chat deletion cascades to every receipt owned by that chat.

## 15. Concurrency and cross-store consistency

- `projects.revision` is the aggregate Project fence.
- Each structured child retains its own revision.
- Chat association checks both expected chat revision and exact Project
  existence; proposal workflows also bind the expected Project revision.
- Source links are created only after a fresh source-owner existence check and
  exact Project revision check.
- Project Home is a read projection across stores, not a distributed snapshot.
  It includes per-source revisions/timestamps and may report that one section
  changed during assembly rather than claiming impossible global atomicity.
- Cross-database operations use ordered, verified steps and truthful partial
  failure. They do not pretend SQLite transactions span separate files.
- A context pack binds one exact parent Project revision. Later Project changes
  do not rewrite its receipt while both owners exist; deleting either the
  Project or owning conversation deletes the receipt by FK cascade.
- Multi-browser clients refresh against the parent revision and treat stale
  writes as conflicts, never last-write-wins overwrites.

## 16. Refined implementation slices

Implementation should proceed only after this architecture is accepted and a
separate implementation mission is authorized.

### Slice 1 - schema-7 and migration foundation

- add exact schema-7 definitions, typed records, validators, and read APIs;
- add the explicit 6-to-7 migration and adversarial preservation tests;
- preserve normal-startup migration refusal;
- do not migrate canonical runtime in this slice.

### Slice 2 - structured Project domain and application layer

- implement structured state, decision supersession, question lifecycle, flat
  plan, links, aggregate revision fencing, and deletion semantics;
- extend `ProjectApplicationService` and keep transports out of it;
- retire automatic transcript-to-Key-decisions behavior for canonical updates.

### Slice 3 - Project Home, Where We Are, and conversations

- implement deterministic `ProjectHome` and Where We Are projections;
- add Project-scoped conversation listing;
- complete open/associate/detach/New Project Chat workflows;
- add read-only source projection ports and honest unavailable states.

### Slice 4 - Project Context Service and transparency

- move Project prompt construction out of `WebApplication`;
- implement Stable/Working/Historical selection and bounded omission manifest;
- atomically persist exact context receipts with completed turns;
- expose presentation-neutral context inspection and the web disclosure UI.

### Slice 5 - cross-capability integration

- fix fresh Coding Work Project propagation and proposal disclosure;
- add bounded Project-filtered Research/Coding/Attention reads;
- add explicit Night Owl, Scheduled Work, and Knowledge link workflows;
- prove every capability authority envelope is unchanged.

### Slice 6 - UI, authorized migration, and human acceptance

- complete responsive Project Home and structured editors;
- run desktop and narrow/mobile multi-browser acceptance;
- only under separate exact authorization, stop Tori and run the canonical
  schema-6-to-7 migration;
- reverify complete runtime preservation, restart behavior, context inspection,
  and capability boundaries;
- obtain human acceptance before describing Projects as a completed workspace.

## 17. Acceptance tests

### 17.1 Schema and migration

- fresh stores create exact schema 7 with all foreign keys and indexes;
- normal startup refuses exact schema 6 with migration guidance and no writes;
- the explicit migrator accepts only exact schema 6 and rejects versions 2-5,
  schema 7, lookalikes, extra objects, changed file identity, unsafe paths, and
  sidecars;
- injected failures at every pre-commit stage roll back to exact schema 6;
- post-commit verification proves integrity, FKs, exact schema, and no sidecars;
- every schema-6 value, including every byte of every `continuity_brief`, is
  preserved;
- all new Project structured/link/receipt tables are empty after migration; and
- no migration test reads or writes canonical `runtime/`.

### 17.2 Structured Project state

- phase/focus/checkpoint writes are bounded, revision-safe, and verified;
- a stale parent or child revision changes nothing;
- a decision cannot be edited in place;
- supersession atomically inserts the new decision and marks exactly one old
  same-Project active decision superseded;
- each decision has at most one direct predecessor and one direct successor;
- cross-Project, already-superseded, branching, and cyclic supersession fail
  closed;
- question transitions follow the allowed lifecycle and preserve text;
- plan ordering and states are deterministic without task-system side effects;
- all user-visible suggestions remain inert until confirmed; and
- recent conversation text never becomes a canonical decision automatically.

### 17.3 Project Home and conversations

- Where We Are uses only structured fields and deterministic plan/question
  rules;
- absent structured state is shown as not recorded, not inferred from legacy;
- legacy briefs, including safe malformed briefs, remain visible and unchanged;
- normal V1 create/update flows cannot edit or synthesize a legacy brief;
- one Project lists all and only its associated chat metadata;
- New Project Chat sets only an exact pending selection until first persistence;
- cancelling or restarting before first persistence creates no association;
- explicit association/detachment preserves every transcript entry; and
- Project Home tolerates one unavailable source without hiding healthy sections;
- recent activity uses normalized authoritative timestamps newest-first, with
  source type and stable object ID as deterministic tie-breakers; and
- an unavailable source is named and makes the projection explicitly partial.

### 17.4 Context service and transparency

- Stable/Working/Historical order is deterministic;
- all Historical records are omitted before any Stable or Working record is
  omitted for budget;
- budgeting reuses the existing planner, estimator, capacity, and reserves;
- current user input is last and Project context is labeled data-only;
- whole-record budgeting produces exact omission reasons;
- associated transcripts/reports/outputs are not implicitly loaded;
- minimum required overflow fails before provider contact;
- the stored receipt exactly matches provider-visible Project context and
  digest;
- receipts are never selected as model context;
- changing a Project does not rewrite an existing receipt;
- deleting the Project removes its receipts but preserves owning conversations;
- permanently deleting a conversation removes its receipts; and
- the client displays active context and exact included/omitted inspection.

### 17.5 Cross-capability boundaries

- fresh Research from a Project chat retains the canonical Project ID but sends
  no Project content or authority to the worker;
- fresh Coding Work from a Project chat retains the canonical Project ID;
- fresh Coding Work authority, workspace, sandbox, network, Git, and
  confirmation behavior are byte-for-byte/semantically unchanged;
- Project links cannot start Night Owl, Scheduled Work, Knowledge retrieval,
  Research, Coding Work, MCP, or commands;
- source-owned lifecycle/disposition changes occur only through the source
  application service;
- Project Home contains references/projections, not copied source truth; and
- deleting a Project leaves every source-owned record and historical native
  Project ID intact, but the ID no longer resolves as active membership.

### 17.6 Concurrency, deletion, and runtime preservation

- concurrent browser writes produce stale-revision conflicts;
- Project deletion atomically removes Project-owned structured rows and links,
  removes its context receipts, detaches chats with revision increments, and
  preserves transcripts;
- historical native Project IDs remain readable as source-owned provenance
  without resolving to active membership or authority;
- all tests use temporary stores;
- `./scripts/verify-milestone` passes at the final implementation checkpoint;
  and
- complete before/after no-follow canonical runtime inventory and regular-file
  hashes are identical except for a separately authorized canonical migration.

## 18. Risks and implementation validation points

1. **Context-planner integration:** the exact numeric Project allocation remains
   a Slice 4 implementation decision. It must be tested against actual provider
   capacities and optional memory/Knowledge context without duplicating the
   existing estimator, capacity policy, or reserves.
2. **Receipt sensitivity and growth:** exact receipts duplicate a bounded amount
   of Project text. Schema limits, one-row-per-turn cardinality, omission of
   unrelated source content, non-retrieval, and dual Project/conversation
   cascades are mandatory controls.
3. **Decision importance:** V1 defaults new decisions to `normal`. Promotion to
   `important` is a separate explicit revision-safe mutation shown in the
   confirmation; model inference cannot promote it silently.
4. **Historical native IDs:** source stores may retain a deleted Project ID.
   Every resolver and UI must distinguish historical provenance from a live
   Project and must never translate a dangling ID into authority.
5. **Cross-store projection races and failures:** Project Home cannot obtain one
   SQLite snapshot across independent stores. Per-source timestamps/revisions,
   deterministic ordering, explicit partial status, and bounded refresh are
   required instead of distributed locking.
6. **Link scope:** V1 permits links only for Night Owl findings, Scheduled Work
   definitions, and Knowledge sources. Another target type requires a stable
   source ID, owner-provided read contract, UI need, tests, and architecture
   review rather than an arbitrary type string.
7. **Project status and active work:** completing, pausing, or deleting a Project
   does not cancel source-owned work. Project Home must surface active work and
   direct the user to separate owner-authorized actions.

## 19. Explicit non-goals

Projects & Continuity V1 does not include:

- Jira, issue-tracker, scrum, sprint, ticket, or team-workflow semantics;
- autonomous planning, self-directed agents, or worker-to-worker delegation;
- automatic conversion of transcripts or `continuity_brief` into canonical
  state;
- LLM-authored Where We Are, status reconstruction, or silent Project updates;
- automatic chat attachment based on model inference, title similarity, or
  content matching;
- importing all associated conversation history into every prompt;
- copying Research reports, Coding output, Attention state, Night Owl sources,
  Scheduled Work records, or Knowledge content into Project tables;
- executing Research, Coding Work, MCP, commands, Night Owl, or Scheduled Work
  from Project membership alone;
- new filesystem, network, credential, Git, deployment, or publication
  authority;
- replacing Planning, reminders, Scheduled Work, Knowledge, or Attention;
- project templates, dependencies, nested projects, assignees, due dates,
  estimates, labels, or external collaboration;
- embeddings, vector search, external Project services, or new production
  dependencies;
- canonical schema migration during the architecture mission; or
- any edit to the seven founding documents.

## 20. Architecture-gate conclusion

Projects & Continuity V1 belongs in Tori core because it defines continuity,
Project meaning, context selection, user authority, and canonical state. The
existing schema-6 Project identity, chat association, revision-safe store,
`ChatService`, and `ProjectApplicationService` are the correct foundation.

The next milestone should extend that foundation with schema-7 Project-owned
structured records, deterministic projections, exact context transparency, and
narrow read-only capability integration. Source systems remain replaceable and
authoritative for their own records. Project association remains useful context
without ever becoming permission to act.

The human-review decisions are incorporated. Slice 1 established schema-7
persistence and completed the separately authorized canonical 6-to-7 migration;
Slice 2 now implements the presentation-neutral structured Project domain and
application mutations with aggregate revision fencing and read-only legacy-brief
compatibility. Slice 3 now implements presentation-neutral Project Home and
deterministic Where We Are projections, metadata-only associated-conversation
navigation, and revision-checked New Project Chat using the existing pending
association path. Slice 4 now implements the presentation-neutral
`ProjectContextService`, deterministic Stable/Working/selective-Historical
whole-record selection through the existing planner budget and reserves, atomic
per-turn exact receipts, and persisted-receipt transparency in Conversation and
CLI turns. The Slice 4 live browser acceptance verified one real provider turn,
its exact retained receipt, and inspection after restart. Slice 5 now adds
bounded source-owned Related Work and current-record activity, source-verified
explicit links, truthful partial-source reporting, and organization-only
Project inheritance for fresh Coding Work. Broad structured editing, final
UI/live acceptance, and milestone-wide human acceptance remain deferred.

Slice 6 completed explicit, source-verified Night Owl/Scheduled Work/Knowledge
link management and final Project Home Related Work presentation.
`ProjectHome.links` exposes Project-owned identity and revision separately from
source-owned metadata, so a link stays visible and removable if its source
becomes unavailable. Human-readable Source and Item selectors retain stable IDs
internally; the browser sends exact Project/link revisions through the existing
application and Web boundaries, and the source owner re-verifies existence at
mutation time. No capability-execution route is created. The canonical
schema-6-to-7 migration and manual desktop/mobile acceptance are complete.

Acceptance corrections kept this authority boundary intact: recurring Scheduled
Work definition revisions may advance operationally without rewriting or
invalidating an unchanged immutable Persistent authorization; material
authority changes and impossible future authorization revisions still fail
closed. The right Attention rail is compact without removing its actions.
SQLite stayed healthy during an acceptance incident in which an origin-less
Scheduled Work result was routed into a disposable Project proposal chat,
leaving an invalid event sequence. Reviewed recovery removed only that
malformed test chat. Background routing now rejects incompatible special-origin
targets, and the archive validates such appends before commit. The legacy brief
remains read-only compatibility data, not structured Project truth.

Projects & Continuity V1 is complete and human accepted. Broader structured
editors, a reviewed OpenCode version compatibility policy, Project Home load
optimization, DeepSeek Harness evaluation, Qwen3.8 Flash Next benchmarking,
and any reproducible unrelated Remote Chat timing flake remain deferred; they
grant no V1 authority and are not completion blockers.
