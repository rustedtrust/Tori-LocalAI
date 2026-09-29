# Planning / CalDAV Contract

**Status:** Implemented foundation, Reminder Bridge, conversational operations, compact Workspace, and live local deployment
**Authority:** Living technical contract subordinate to the seven founding documents, `docs/ARCHITECTURE_GOVERNANCE.md`, and `docs/TARGET_ARCHITECTURE.md`

## Boundary and ownership

Planning plugs into the recovered target architecture as:

```text
Tori Conversation / Workspace
          |
          v
PlanningService (Tori application use cases)
          |
          v
PlanningPort (replaceable durable-planning contract)
          |
          v
CalDAVPlanningAdapter (standard mapping and transport)
          |
          v
Radicale (first local backend)
```

Tori owns intent interpretation, authority and confirmation policy, presentation, relationship context, truthful failure, and future reminder attention. `PlanningService` is presentation-neutral and accepts only Tori domain values. It is not a model tool and does not grant mutation authority. Conversation or a client must pass through a separately reviewed Tori-owned policy before calling durable mutation use cases.

`PlanningPort` owns no Radicale-specific types. Radicale is replaceable by another CalDAV server or a conforming non-CalDAV adapter without changing `PlanningService`, Conversation, Workspace, or the Tori domain. The first adapter uses the maintained Python `caldav` client rather than implementing WebDAV discovery, reports, or authentication itself.

## Portable objects

The foundation represents:

- `Task`: UID, title, description, collection identity, optional start/due, completion state and timestamp, priority, recurrence, reminders, and opaque revision.
- `Event`: UID, title, description, collection identity, start/end, all-day state, location, recurrence, reminders, and opaque revision.
- `RecurrenceRule`: an RFC 5545 RRULE value such as `FREQ=WEEKLY;COUNT=4`; it is not conversational grammar.
- `PlanningReminder`: a relative standard DISPLAY alarm trigger and description.
- `PlanningCollection`: opaque identity, display name, and advertised VTODO/VEVENT support.
- `PlanningRevision`: an opaque backend token. The CalDAV adapter currently projects the resource ETag.

The adapter mapping is:

| Tori value | iCalendar / CalDAV value |
|---|---|
| Task | `VTODO` |
| Event | `VEVENT` |
| Recurrence | `RRULE` |
| Reminder metadata | `VALARM` with `ACTION:DISPLAY` and a relative `TRIGGER` |
| Stable object identity | `UID` |
| Safe observed revision | HTTP `ETag` |

The portable domain intentionally excludes attendees, invitations, recurrence exceptions, absolute alarms, project-management fields, and offline shadow copies. The bounded conversational layer maps only its supported common recurrence phrases into standard RRULE values.

## Conversational Planning boundary

`PlanningConversationService` is the bounded Tori-owned policy above `PlanningService`. It performs no model call and exposes no model tool. Clear read requests execute immediately against fresh Planning data; durable requests produce a review only:

```text
Conversation read intent -> PlanningConversationService -> PlanningService -> current result

Conversation mutation intent -> PlanningConversationService -> Planning proposal
    -> explicit confirmation -> PlanningService -> CalDAV
    -> PlanningReminderBridge -> derived Scheduled Work
```

Reads cover Today, bounded upcoming/date ranges, open/due/overdue/completed tasks, and date- or weekday-scoped calendar queries. Results use configured local civil time, expand recurring objects with bounded search, limit output, and omit UIDs, revisions, URLs, and raw iCalendar values.

Mutations cover task, standalone reminder, and event creation; due/event-time, recurrence, and event-reminder changes; task completion; and task/event deletion or cancellation. A standalone reminder is canonical VTODO state with a timed due value and zero-offset relative DISPLAY `VALARM`; it is never created directly as Scheduled Work. Common recurrence phrases map directly to RRULE values: daily, weekly, every N days/weeks, named weekdays, finite counts, and exact until dates. Explicit clock times, date-relative terms, weekday dates, time ranges/durations, all-day events, location, and priority are supported. Bare 1–6 clock hours resolve to PM and 7–11 to AM, and the proposal displays that resolved choice before authority. Vague mutation dayparts, absolute alarms, recurrence exceptions, and unsupported RFC variants are rejected or clarified rather than guessed.

Existing-object resolution prefers an exact normalized title, then one unique partial title, then the most recent Planning object in the same live conversation for bounded references such as “that” or “it.” Multiple plausible matches return a small disambiguation set and no proposal. Recent-reference convenience is process-local; after restart, unique canonical title matching remains available.

Every mutation proposal is process-owned, one-use, expires after five minutes, and is bound to the originating chat plus its archive revision. Existing-object proposals also capture the current opaque `PlanningRevision`. Confirmation pops the token, verifies chat/revision, rereads the object, and refuses a missing, revisionless, deleted, or externally changed object. It never blindly retries a stale write. Successful mutations call only `PlanningService`, then request Reminder Bridge reconciliation; Conversation never edits CalDAV client objects, Scheduled Work definitions, or their stores directly.

## Compact Workspace projection

The existing desktop Workspace rail and mobile utility sheet host one compact Planning module with Today, Upcoming, Tasks, and Calendar views. `GET /api/planning` returns a bounded projection assembled from a fresh `PlanningService` snapshot. Today includes all-day/timed events, tasks due on the local day, and overdue open tasks. Upcoming contains a server-expanded seven-day agenda. Tasks exposes Open, Due, Overdue, and Completed filters. Calendar exposes an agenda-only fourteen-day window around the current day with nearby-day navigation; full month/week grids are deferred.

Projected rows include an opaque display key, bounded title/notes, local display labels, task completion/priority/overdue state, event all-day/location state, collection display name, and human recurrence/reminder summaries. They exclude raw UID, revision/ETag, collection URL, ICS, RRULE, VALARM, credentials, and derived Scheduled Work identity. The browser does not expand recurrence or calculate alarms.

Workspace selection/filter/day state is ephemeral and never stored in local or session storage. Planning scrolls independently inside the existing compact rail/sheet, uses labelled touch controls, wraps content, and does not widen Conversation. The established attention loop refreshes at a modest ten-second cadence so external CalDAV edits converge without reload. Disabled or unavailable Planning returns one truthful compact state and does not affect Conversation.

Create Task/Event/Reminder, Done, Edit/Reschedule, and Delete/Cancel controls translate compact form input into the existing deterministic conversational Planning request. They reuse the same proposal, five-minute one-use token, chat/revision binding, confirmation UI, `PlanningService`, and Reminder Bridge path. There is deliberately no direct UI mutation endpoint. Ambiguous duplicate titles refuse rather than guess; external edits between proposal and confirmation retain stale-revision protection. Mutation errors remain visible while canonical projection refresh proceeds.

## Revision and external-edit behavior

Every fetched object carries the current ETag as an opaque revision. Update and deletion require the caller's expected revision. The adapter first compares the observed ETag and then sends the mutation through the CalDAV client's transport with `If-Match`; an intervening external edit produces a bounded revision conflict. A caller must reload rather than overwrite.

This establishes the minimum read/write synchronization seam for Apple Calendar, Apple Reminders, Thunderbird, or other CalDAV clients. Conversational reads fetch current backend truth each time. If an external client changes an item between proposal and confirmation, the old proposal fails and the external edit remains intact. A future reconciliation loop may list or sync collections, compare ETags or CalDAV sync tokens, and publish changed objects to Tori-owned consumers. The implementation adds no polling daemon, automatic merge, destructive resynchronization, or assumption that Tori originated every change.

## Scheduled Work and reminder ownership

The CalDAV object is canonical planning state. `PlanningReminderBridge` observes a planning object's UID, revision, recurrence, and `VALARM` intent and derives only the delivery/execution record Tori needs:

```text
VTODO / VEVENT + VALARM (canonical intent)
                 |
                 v
Tori Reminder Bridge (reconciliation owner)
                 |
                 v
Scheduled Work (derived delivery)
                 |
                 v
Tori attention / reminder presentation
```

The bridge binds derived work to a deterministic hash of collection/kind/UID, alarm properties, recurrence-instance start, and effective trigger time. It materializes one future one-shot Scheduled Work definition per next alarm occurrence, keeps RRULE expansion canonical in CalDAV, and reuses Scheduled Work's revision-safe replacement/cancellation and existing application-event delivery. Repeated reconciliation is a no-op; moved alarms or event/task times replace the existing derived definition; alarm removal, object deletion, and task completion cancel pending derived work. Multiple VALARMs receive distinct alarm keys; recurring objects advance one bounded next occurrence rather than copying RRULE into Scheduled Work. Scheduled Work definition arguments contain only the source/occurrence linkage fields, not a task/event mirror, so no separate bridge ledger is required. Scheduled Work remains Tori's application-level delivery engine; Radicale does not deliver Tori attention and does not own authority.

The bridge capability is explicitly system-derived and non-interactive. It cannot be selected by the model or ordinary Scheduled Work proposal flow. Its application boundary uses a fixed bridge provenance and `run_when_available` policy so a queued delivery can recover through the existing coordinator without changing canonical CalDAV state. A bridge reconciliation pass is safe to repeat after restart. If Radicale is unavailable, existing derived work is preserved; if Scheduled Work fails, the planning object is untouched and a bounded failure is returned for retry. The current implementation exposes manual `reconcile()` / `reconcile_object()` entry points; automatic startup/periodic orchestration remains deferred to avoid implicit live-state initialization.

## Configuration and lifecycle

`[planning]` uses the existing TOML configuration boundary:

```toml
[planning]
enabled = true
backend = "radicale"
url = "http://127.0.0.1:5232"
username = "tori"
# credential_environment = "TORI_CALDAV_PASSWORD"
default_task_list = "http://127.0.0.1:5232/tori/tasks/"
default_calendar = "http://127.0.0.1:5232/tori/calendar/"
timeout_seconds = 5
```

Only numeric IPv4 loopback is accepted by this local foundation. Passwords are never stored in tracked configuration; an optional `TORI_*` environment-variable name is stored instead. Production Tori enables the local backend with the `tori` principal and no password under the loopback-only authentication mode.

`PlanningRuntime` composes disabled, configured, and unavailable states. It closes the client on Tori shutdown. Status probing is bounded and verifies both CalDAV support and principal collection access. A disabled or unreachable backend does not stop ordinary Conversation. Reads and writes fail explicitly; Tori creates no local shadow record and claims no success.

## Radicale deployment and storage

The verified foundation uses Radicale 3.7.8 installed with `caldav` 2.2.6 into the repository-local `.venv`. The real integration gate starts a native loopback-only subprocess on an ephemeral port, uses authentication type `none` with a non-secret local principal name, stores all collections beneath a disposable `/tmp/tori-planning-radicale-*` directory, and deletes the task, event, collection, process, and temporary tree.

Persistent local use can be deployed as the `systemd --user` unit `tori-radicale.service`, running the selected checkout's virtual-environment executable, bound to `127.0.0.1:5232`, with storage under `%h/.local/share/tori/radicale/collections`. Authentication type `none` is acceptable only for this loopback-only single-user foundation; broader exposure requires a separate security decision. The committed template remains at `deploy/radicale/tori-radicale.service.in`; enablement and active state are host-local installation choices.

Persistent Radicale storage is outside `<tori-root>/runtime` and is not included in Tori's current verified backup scope. A future backup change must coordinate a consistent Radicale snapshot or supported export, include collection metadata and `.ics` resources, and add restore verification. This document does not authorize such a backup-scope change.

## Implemented proof and deferred work

`scripts/verify-planning-radicale` starts a real server and proves the foundation and Reminder Bridge cases plus a complete conversational and Workspace-projection lifecycle. The case creates and confirms a real task, reads and completes it, creates a real event with a 30-minute reminder, observes derived Scheduled Work and Today/Tasks/Upcoming/Calendar projections, reschedules the event and reminder, performs an external CalDAV edit, rejects the stale proposal while preserving and projecting that edit, then cancels/deletes the objects and verifies cleanup. All state is disposable.

The bridge currently supports relative DISPLAY alarms with concrete timed DTSTART/DUE references, daily/weekly and other bounded RFC 5545 RRULE expansion through the installed date-time stack, deterministic one-shot materialization, external reread/reconciliation, and existing Scheduled Work application-event delivery. Absolute alarms and alarms without a concrete timed reference remain bounded unsupported cases. Live acceptance has passed for the persistent service, `Tori Tasks`/`Tori Calendar` collections, task create/complete, event create/reschedule/cancel, VALARM delivery through Scheduled Work, restart persistence, desktop Workspace behavior, and physical iPhone portrait behavior. During acceptance, `make cookies` was found to be an unconfirmed Planning proposal rather than a missing projection row; no VTODO or legacy task was created until confirmation. The browser now queues a fresh projection read after an in-flight refresh, and Calendar shows its selected date separately from the Today action. Acceptance objects were removed through normal Planning confirmation flows. Deferred slices are richer recurrence/alarm support, automatic startup/periodic orchestration, background external-change reconciliation, full month/week grids, attendee/invitation workflows, and provider-specific integrations. No existing task/reminder or Scheduled Work store is migrated or replaced.
