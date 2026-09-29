# Capability Growth / Self-Improvement V1 Architecture

**Status:** Complete and human accepted

**Authority:** Subordinate to the seven accepted founding documents and
`docs/ARCHITECTURE_GOVERNANCE.md`. This document does not amend either.

## 1. Decision

Capability Growth is an advisory Tori-core service with this fixed authority
flow:

```text
OBSERVE -> EVIDENCE -> PATTERN -> RESEARCH -> RECOMMEND -> USER DECIDES
```

It records bounded deterministic evidence about Tori's own capabilities,
derives known-good baselines and FIX / IMPROVE / EXPAND findings, and performs
bounded Skill research only after a clear local request. It does not implement
or authorize a recommendation.

The service is reusable independently of Web presentation so a future Night
Owl policy may call the same boundary only after that separate feature and its
authority are approved. Capability Growth V1 contains no scheduler or
background research.

## 2. Improvement Journal

The application-owned store is
`runtime/capability_growth/improvement_journal.sqlite3`. It is separate from
curated user Memory, Conversation archives, checkpoints, Knowledge, and Skill
lifecycle state. Its exact schema version is 1 and its file and parent are
owner-private. Unsafe paths, links, hard links, corrupt databases, unknown
tables/columns/indexes, or unsupported schemas fail closed and are not repaired
on startup.

The journal accepts only verified normalized fields: capability area and ID,
operation, evidence kind, bounded error code/severity, component ID, version,
optional SHA-256 digest, count, timestamps, lifecycle, and revision. It has no
field for a prompt, response, catalog description, model score, chain of
thought, secret, personal trait, or unrestricted payload.

Evidence kinds are `success`, `friction`, `failure`, `regression`,
`workaround`, and `opportunity`. Finding lifecycle is `open`, `monitoring`,
`resolved`, `obsolete`, or `historical`. Repeated identical outcomes
consolidate into one count. A failure after a verified success creates a
regression record while the success remains a known-good baseline. Priority is
deterministic: regression, repeated failure, severe failure, recurring
friction, opportunity, then known-good evidence.

All tables have hard application caps. Capacity may retire only the oldest
terminal history; active findings, decisions, and running reviews are never
silently discarded. If all capacity is active, the write fails honestly.

## 3. Capability inventory

The inventory is a compact read-only projection from application-owned state:

- native capability registry state;
- installed, enabled, disabled, and retained uninstalled Skill versions;
- currently approved MCP operations, if configured; and
- adapters exposed by those registered capability paths.

Model claims are not inventory. The review compares candidates with this
inventory to suppress duplicates and distinguish presence from usable
authority.

## 4. Manual Skills Review

A clear local request is one-use authority for that review's read-only
research. General review examines journal FIX and IMPROVE evidence, then at
most three missing areas from a fixed ten-area capability horizon for EXPAND.
A user-directed review searches only its bounded topic. Each search admits at
most three normalized skills.sh candidates and the whole review may inspect at
most two candidates.

Research reuses the existing trust pipeline:

```text
skills.sh -> normalized untrusted candidate -> public GitHub immutable commit
          -> quarantine and static inspection -> recommendation
```

Catalog descriptions and popularity are never proof. Legitimately empty
discovery completes as no new candidates; handled discovery or inspection
faults make a review partial, while only a review that cannot complete is
failed. Downloads remain
transient quarantine state and scripts are not executed. The durable review
record contains only scope, area, bounded counts, timestamps, status, and
normalized error codes. Remote Chat cannot administer or invoke this review.

## 5. Recommendations

Recommendations preserve lane, area, bounded rationale/evidence, immutable
candidate provenance when inspected, compatibility classification, required
next authority, lifecycle, and revision. Classifications are:

- ready under existing authority;
- needs Skill lifecycle or permission change;
- needs an application adapter;
- needs MCP or external integration;
- requires unsupported executable behavior;
- duplicate or little benefit; and
- not recommended.

Lifecycle is `open`, `dismissed`, `accepted`, `resolved`, or `obsolete`.
Deterministic identity deduplicates unchanged advice. Dismissal suppresses an
unchanged recommendation for 30 days; it is not a permanent prohibition, and
materially changed evidence may reopen it. `accepted` records only the user's
advisory disposition and triggers no lifecycle or authority action.
Success-only evidence remains a known-good baseline rather than creating an
IMPROVE recommendation. A general review reconciles only open evidence-derived
recommendations against current deterministic policy: unsupported entries move
to `obsolete` history, and a regression recommendation supersedes the matching
lower-priority failure recommendation without erasing that failure evidence.

## 6. Presentation and integration

The responsive **Skills & MCP** view includes Capability Growth inventory,
open findings, lane/priority/evidence, known-good baselines, recommendations,
immutable provenance, required authority, history, and recent review summaries.
Revision-safe controls update only journal lifecycle. Conversation recognizes
explicit general and directed Skills Review requests without a model call;
ambiguous “for this” wording asks for the missing topic.

Normalized `media.inspect` results and review-pipeline results are initial
deterministic evidence producers. Further producers must use the same narrow
typed contract rather than writing free-form observations.

## 7. Backup, restore, and boundaries

Verified Backup treats the journal as canonical SQLite and holds its
maintenance guard while snapshotting. Presence of Capability Growth runtime
without that guard blocks publication. Verified Restore's existing whole-runtime
copy and SQLite integrity validation restore the journal; transient discovery,
quarantine, and download state are not durable learning.

Capability Growth cannot install, enable, disable, update, grant, execute,
write a Skill, add MCP authority, create an agent, modify code/config/routing or
system prompts, change curated Memory, or change Tori's identity, personality,
principles, or founding behavior. Night Owl, background research, Agent
Plugins, automatic Skill updates/creation, image generation, Discord
integration, MCP administration expansion, personality self-modification, and
Deep Research remain deferred.
