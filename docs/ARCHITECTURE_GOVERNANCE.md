# Tori Architecture Governance

**Project:** Tori
**Document:** Architecture Governance
**Status:** Accepted engineering governance
**Authority:** Subordinate to `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`

## Purpose

This document turns Tori's accepted founding architecture into mandatory engineering rules. It is not an eighth founding document. If this document conflicts with a founding document, the founding document governs.

These rules apply to every future milestone, capability, integration, refactor, and completion review.

## 1. Tori is the core

Tori owns her identity, personality, relationship with the user, user-authority and permission policy, judgment and decision policy, conversation and context semantics, continuity, Project and task meaning, provenance and trust, and capability selection and coordination.

External systems extend Tori. They do not become Tori.

## 2. Tools have capability, not authority

External tools, services, agents, MCP servers, models, memory engines, planners, coding systems, speech systems, and other integrations:

- possess no independent Tori identity;
- receive no authority merely because they are installed;
- cannot silently expand permissions;
- operate only through validated, Tori-controlled boundaries; and
- perform approved work and return structured results or evidence.

The user directs Tori. Tori coordinates approved capabilities only within that authority.

## 3. Open-source-first implementation rule

Before implementing a new capability, engine, subsystem, frontend, provider, memory technology, planner, learning system, or other replaceable technology:

1. Research current, maintained open-source and local/self-hostable options.
2. Evaluate whether an existing project can be integrated.
3. Prefer integration through a stable interface when it reasonably meets Tori's needs.
4. Build a new implementation only when existing options materially fail the requirements.
5. Treat direct technology-specific hard coding in Tori core as the last resort.

Research must be repeated when the capability is actually planned; an earlier ecosystem survey is not assumed to remain current.

## 4. Replaceability is part of completion

A subsystem is not complete merely because its first implementation works. If its underlying technology is expected to evolve, completion also requires a documented replacement boundary.

Where practical, replacing an implementation should require only configuration, provider/profile selection, or one conforming adapter. It should not require redesigning unrelated Tori core code.

## 5. Core policy versus replaceable technology

Legitimate core hard coding includes stable Tori-owned invariants such as authority, consent, safety boundaries, canonical schema semantics, provenance, verification requirements, lifecycle and domain rules, context-authority ordering, and bounded limits.

Replaceable technology choices must not leak through core consumers. Examples include TTS and STT engines, search engines, model runtimes, memory and retrieval engines, RAG systems, coding tools, calendar providers, browser automation, frontends, and learning or adaptation engines.

## 6. Standards and ports first

Prefer established interfaces when they genuinely fit, including OpenAI-compatible APIs, MCP, narrow application-owned `Protocol` or port contracts, stable versioned HTTP/SSE documents, and typed event interfaces.

Do not force a generic standard when it weakens safety or adds unnecessary complexity. Tori-owned validation and authority boundaries remain controlling even when a standard protocol is used.

## 7. Complete the product workflow before implementation

Before implementation begins, define the intended user experience across every relevant surface, including desktop and mobile when applicable. Planning must answer:

- How is the feature discovered?
- How is it invoked?
- How is its state visible later?
- How is it changed or removed?
- How does it interact with Conversation?
- How does it behave across devices and restart?
- What happens on failure?

Basic usability discovery must not be deferred to final acceptance.

## 8. Architecture gate before implementation

Every future milestone or capability plan must identify:

- what belongs to Tori core;
- what belongs to an external or replaceable implementation;
- the interface or contract between them;
- authoritative versus derived state;
- the permission and authority boundary;
- likely alternative implementations;
- the configuration model;
- the replacement strategy;
- UI impact; and
- the test and contract strategy.

Implementation may begin only after this gate is explicit enough to review.

## 9. Proof of modularity

When practical, verification must prove the abstraction rather than only the first implementation. Appropriate evidence may include an alternate adapter, a fake conforming adapter, a second provider, an alternate frontend or client, or a reusable contract-test suite.

A large implementation-specific test suite alone does not prove modularity.

## 10. Avoid both extremes

Do not create speculative abstractions before evidence exists. Once multiple real implementations reveal a common boundary, refusing to consolidate it is also architectural debt.

Architecture evolves through evidence-based refinement.

## 11. External-system safety

No external memory engine, learning system, persona framework, model, MCP server, planner, coding agent, or automation engine may silently modify Tori's identity, authority or permission policy, canonical user facts, executable policy, or Project/task canonical state.

Such a change is permitted only through a Tori-owned workflow that explicitly authorizes and verifies that exact change.

## 12. Interface independence

The custom web UI is a client of Tori, not Tori itself. Long-term architecture must support alternate clients without moving identity, authority, or domain semantics into those clients.

Adding a capability must not require destabilizing unrelated Conversation layout or behavior.

## 13. Permanent completion question

Every future completion review must answer both:

> Does it work?

and:

> Does this preserve or improve Tori's ability to replace the underlying technology later?

If a change makes future replacement materially harder, that debt must be explicitly justified and recorded.
