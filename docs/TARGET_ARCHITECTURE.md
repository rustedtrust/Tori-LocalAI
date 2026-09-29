# Tori Target Architecture

**Project:** Tori
**Document:** Target Architecture
**Status:** Accepted architecture direction
**Authority:** Subordinate to `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`

## Purpose

This document defines Tori's future architecture direction and guides implementation decisions. It is subordinate to the seven accepted founding documents and must be applied together with `docs/ARCHITECTURE_GOVERNANCE.md`.

This is not a product roadmap or technology-selection document. It defines durable ownership and replacement boundaries without selecting a particular implementation prematurely.

## Tori Core Philosophy

Tori is the core system responsible for identity, personality, continuity, authority, policy, and coordination.

Tools provide capabilities. Tools do not own authority. Installing or connecting an external system grants it no permission to act or to expand its own permissions.

External systems cannot silently modify:

- Tori's identity;
- permissions;
- canonical memory;
- Project state;
- task state; or
- execution policy.

Any such change must pass through a Tori-owned, explicitly authorized, validated workflow.

## Core Versus Adapter Principle

Tori core owns:

- user intent;
- consent;
- permissions;
- context assembly and authority ordering;
- memory policy;
- Project semantics;
- task semantics;
- capability selection;
- truthfulness; and
- failure handling.

Replaceable adapters may provide:

- model runtimes;
- text-to-speech engines;
- speech-to-text engines;
- search engines;
- retrieval-augmented generation systems;
- coding tools;
- calendar systems;
- external automation; and
- MCP integrations.

Implementation-specific details must remain behind narrow Tori-owned contracts rather than spreading through unrelated core consumers.

## Open-Source First, Build Last

Before implementing a replaceable capability:

1. Research existing solutions.
2. Evaluate their license, local or self-hosted operation, security, maintenance activity, API quality, and replaceability.
3. Prefer integration over recreation when a suitable option exists.
4. Create a custom implementation only when available solutions materially fail Tori's requirements.

Direct hard coding of replaceable technology into Tori core is the last option. Ecosystem research must be refreshed when a capability is actually planned.

## Replaceability Requirement

A feature is not complete merely because its first implementation works. Completion review must also ask:

- Is the interface clear?
- Can another implementation replace the current one?
- Are core policies separated from implementation details?
- Does the UI avoid owning business logic?
- Is authority still controlled by Tori?

Where practical, replacement should require configuration, provider or profile selection, or one conforming adapter—not redesign of unrelated core code.

## Frontend Direction

The frontend is a replaceable client of Tori.

Tori owns behavior, canonical state, permissions, and workflows. A frontend owns presentation, user interaction, and visualization. Identity, authority, persistence semantics, and capability policy must not migrate into a client.

Open WebUI and SillyTavern are inspiration sources for local-AI interface organization, provider and settings usability, personality/context interaction, and extensibility. Neither is an architectural dependency.

The goal is a Tori-specific experience that remains replaceable and does not destabilize Conversation when capabilities are added.

## Provider Architecture

LLM runtimes are adapters. Tori should support explicit provider selection, model profiles, and backend-independent generation settings where those settings have stable shared meaning.

Portable settings may include temperature, top-p, repetition penalty, context settings, and output limits. Backend-specific options remain explicitly scoped extensions. Adapters translate supported settings for their runtime and must report unsupported behavior honestly rather than silently ignoring it.

Provider choice must not define Tori's identity, authority, memory policy, Project semantics, or task semantics.

## Speech Architecture

Text-to-speech and speech-to-text are separate replaceable capabilities.

Tori owns speech policy, permissions, when speech occurs, interruption behavior, and how speech participates in Conversation. Engines provide synthesis, recognition, or related signal-processing capability.

Future possibilities include push-to-talk, a wake phrase, interruption of voice output, and streaming voice interaction. These are architecture goals, not claims about current implementation or approved product scope.

## Memory Architecture

Memory is a critical architectural boundary. Tori owns memory policy, consent, canonical facts, provenance, conflict handling, updates, deletion, and forgetting semantics.

External systems may provide retrieval, embeddings, indexing, ranking, or other memory assistance. Such derived mechanisms do not determine truth and cannot silently promote inferred material into canonical memory.

Canonical memory remains controlled by Tori and separable from its retrieval technology.

## Personality Architecture

Tori is not a character card. Her identity cannot be delegated to one model, prompt format, frontend, or persona framework.

Future personality architecture should distinguish immutable identity, stable personality traits, relationship context, user preferences, and bounded situational adaptation. External systems may assist with rendering, calibration, or evaluation, but they cannot redefine Tori.

## Search, Research, and RAG

These are distinct concerns:

- **Search** finds information.
- **Research** performs a deeper, potentially multi-step investigation.
- **RAG** retrieves trusted information to supply as context.

They may share adapters or sources, but they must not become one unclear system. Retrieval does not change the authority or provenance of source material.

## Coding and Execution

Tori remains the planner, policy, and authority layer. Execution systems provide bounded capability and return results or evidence.

Every execution integration requires explicit scope, appropriate permission, verification, artifact or result reporting, and cancellation behavior. An execution tool cannot independently modify Tori's identity, permissions, canonical memory, Project state, task state, or execution policy.

## Scheduling and Calendar

External systems may provide calendar, scheduling, reminder, or synchronization integrations.

Tori retains ownership of meaning, consent, and user intent. External records and providers do not silently redefine Tori's task, reminder, Project, or Scheduled Work semantics.

## Learning and Adaptation

Learning systems may propose workflow improvements, preference observations, or behavioral adjustments. They cannot silently rewrite identity, permissions, canonical memory truth, or execution policy.

Learning requires explicit boundaries, review appropriate to its risk, and continuing user control. Derived observations remain advisory until a Tori-owned workflow deliberately accepts any canonical change.

## Open-Source Research References

The supporting architecture-research notes discuss projects and ecosystems including Open WebUI, SillyTavern, AIRI, projects from thecodacus, and MCP. They are references and sources of inspiration, not dependencies or architectural authorities.

Tori should integrate suitable tools behind stable boundaries rather than become permanently dependent on any one project. Candidate selection must be revisited when the relevant capability is planned.

## Implementation Checklist

Before every future milestone or capability implementation, ask:

- Is this Tori core logic or a replaceable adapter?
- Does an existing open-source project already solve it?
- Can the capability be replaced later?
- Are the core, adapter, authority, state, and failure boundaries defined?
- Is authority retained by Tori?
- Is the UI becoming responsible for application logic?
- Are contracts tested independently of the first implementation?

The answers must be explicit enough to review before implementation begins.

## Supporting Research

The preserved research draft at `docs/research/TARGET_ARCHITECTURE_DRAFT_2026-08.md` contains exploratory design possibilities, candidate integrations, and recovery-sequencing ideas. It is reference material only and is not an architectural contract. Where it conflicts with this document, `docs/ARCHITECTURE_GOVERNANCE.md`, or a founding document, the higher-authority document governs.
