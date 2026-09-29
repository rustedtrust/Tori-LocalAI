# Tori Target Modular Architecture — Research Draft

**Project:** Tori
**Document:** Historical architecture research draft<br>
**Status:** Preserved research and design exploration; non-authoritative<br>
**Authority:** Subordinate to the founding documents, [Architecture Governance](../ARCHITECTURE_GOVERNANCE.md), and the current authoritative [Target Architecture](../TARGET_ARCHITECTURE.md)

> **Research / historical architecture note:** This document preserves detailed rationale, candidate technologies, and design exploration from the architecture-recovery review. It is not an architecture contract. Current implementation direction is defined by the authoritative Target Architecture under Architecture Governance and the seven founding documents.

## 1. Purpose

This document records the detailed architecture exploration that preceded Tori's current target architecture.

It does not replace or supplement the current architecture authorities. The founding documents define what Tori is and why she exists, Architecture Governance defines permanent engineering rules, and the authoritative Target Architecture guides current implementation decisions. The material below remains useful as historical reasoning and research rather than binding design.

The central architectural decision is:

> **Tori is the core system. Replaceable technologies extend Tori; they do not define Tori.**

Tori owns her identity, personality, relationship with the user, authority model, continuity, policy, context, canonical domain semantics, capability coordination, provenance, and trust.

Models, speech systems, search engines, memory engines, agents, coding systems, frontends, planners, retrieval systems, automation engines, and other external technologies are replaceable implementations beneath stable Tori-owned boundaries.

The user directs Tori. Tori may coordinate approved capabilities within the authority granted by the user. No installed tool, model, agent, plugin, MCP server, skill, or external service gains independent authority merely by being available.

---

## 2. Architectural Goal

Tori should behave as one continuous assistant even while the technology underneath her changes.

Replacing:

- an LLM runtime,
- a TTS engine,
- an STT engine,
- a memory retrieval engine,
- a search service,
- a research agent,
- a coding agent,
- a calendar provider,
- a knowledge retriever,
- a frontend,
- or another future capability

should not require redesigning Tori's identity, authority, conversation semantics, Projects, tasks, memory policy, or unrelated application code.

Where reasonable, replacement should require only configuration or a conforming adapter.

The architecture should support new technology without forcing Tori to know its internal implementation details.

---

## 3. High-Level Architecture

```text
                              USER
                               │
                               ▼
                      ┌───────────────────┐
                      │     TORI CORE     │
                      │                   │
                      │ Identity          │
                      │ Persona           │
                      │ Relationship      │
                      │ Conversation      │
                      │ Context           │
                      │ Authority         │
                      │ Memory Policy     │
                      │ Projects / Tasks  │
                      │ Capability Policy │
                      │ Trust/Provenance  │
                      │ Learning Policy   │
                      └─────────┬─────────┘
                                │
                         APPLICATION CORE
                                │
                    ┌───────────┴───────────┐
                    │                       │
              CONTROL PLANE            DATA PLANE
                    │                       │
        state / jobs / permissions     tokens / audio
        config / revisions             screenshots
        proposals / capabilities       transcripts
        lifecycle / events             worker progress
                    │                       │
          ┌─────────┴───────────────────────┴─────────┐
          │                                           │
          ▼                                           ▼
    INTERNAL DOMAINS                         REPLACEABLE SYSTEMS
          │                                           │
 Conversation Archive                       Model Providers
 Canonical Memory                           TTS / STT
 Projects                                   Search
 Tasks / Reminders                          Research Agents
 Scheduled Work                             Coding Agents
 User Settings                              Calendar Providers
 Capability Registry                        Browser/Computer Tools
 Job Registry                               Knowledge/RAG Engines
 Skill Registry                             Memory Helpers
                                            MCP Servers
                                            Future Capabilities
          │
          ▼
       CLIENTS
          │
    Tori Web UI
    future mobile/native client
    optional external frontend
    API clients
```

The primary rule is that arrows point **outward from Tori-owned policy toward implementations**, not inward from implementations into Tori's authority.

---

## 4. What Belongs to Tori Core

Tori Core owns semantics that should survive technological replacement.

### 4.1 Identity

Tori's foundational identity does not belong to an LLM, persona package, memory engine, frontend, or agent.

Changing the model must not change who Tori is.

Identity may evolve only through deliberate Tori-owned processes consistent with the founding documents.

### 4.2 Personality

Personality is a first-class Tori subsystem rather than one static system prompt.

The personality system controls how Tori's stable identity is expressed in a particular interaction.

Its implementation may use model-specific rendering or external evaluation tools, but the personality definition remains Tori-owned.

### 4.3 Relationship

Tori may develop deeper understanding of the user over time.

Derived relationship understanding must remain subordinate to:

1. the user's present statement,
2. canonical user-controlled memory,
3. explicit Project and task state,
4. historical evidence.

Relationship inference is advisory rather than authoritative.

### 4.4 Authority

Tori owns all meaningful authority decisions.

A model may suggest an action.

An agent may request a tool.

A skill may describe a procedure.

An MCP server may advertise a capability.

None of these constitute permission.

Tori evaluates the operation against user authorization and application policy before execution.

### 4.5 Conversation and Context

Tori owns:

- conversation identity,
- transcript semantics,
- context authority ordering,
- provider/model attribution,
- context budgeting,
- active Project context,
- memory inclusion,
- knowledge inclusion,
- current-user priority,
- provenance labels.

External systems may generate or retrieve context but may not determine its authority.

### 4.6 Projects, Tasks, and Commitments

Tori owns the meaning and canonical state of Projects, tasks, reminders, commitments, and Scheduled Work.

External planners and agents may suggest changes.

They do not silently mutate canonical Project/task state.

### 4.7 Memory Policy

Tori decides what is eligible to become personal memory.

Storage, indexing and retrieval technologies may change independently.

### 4.8 Learning Governance

Tori determines whether an observed experience becomes:

- a memory,
- a relationship insight,
- a reusable skill,
- a second-brain note,
- a Project update,
- or nothing at all.

Learning engines provide analysis and proposals. They do not silently rewrite Tori.

---

## 5. Application Core

The current `WebApplication` must cease being the application kernel.

Presentation-neutral Tori use cases should live in an application layer independent of HTTP, CLI, browser JavaScript, or any particular frontend.

Examples include:

```text
ConversationService
ProjectService
TaskService
ReminderService
ScheduledWorkService
MemoryService
PersonaService
CapabilityService
JobService
SkillService
KnowledgeService
SettingsService
```

These names are conceptual rather than mandatory class names.

HTTP handlers, CLI commands, browser clients and future interfaces call these application services.

Application policy must not live exclusively inside web routes.

---

## 6. Ports and Adapters

Replaceable systems communicate through narrow Tori-owned contracts.

Examples include:

```text
ModelGenerationPort
SpeechSynthesisPort
SpeechRecognitionPort
WakeWordDetectorPort
MemoryRepository
MemoryRetriever
RelationshipModelPort
KnowledgeCatalog
KnowledgeRetriever
SearchPort
ResearchWorkerPort
CodingWorkerPort
CalendarPort
BrowserControlPort
CapabilityAdapter
JobWorkerPort
```

An external technology may require a dedicated adapter.

The adapter translates between that technology and the Tori contract.

The external technology must not force implementation-specific types throughout the core.

---

## 7. Model Provider Architecture

The existing provider-neutral model work should be preserved and refined rather than replaced.

Tori should send a generic generation request resembling:

```text
GenerationRequest
    exact provider/profile/model identity
    messages
    context budget
    response mode
    portable generation options
    optional namespaced provider extensions
```

Portable settings may include capabilities such as:

```text
temperature
top_p
top_k
repeat_penalty
presence/frequency penalties
seed
maximum output
stop sequences
```

Support depends on the selected backend.

Backend-specific settings may exist under explicitly scoped extensions such as:

```text
ollama.*
llama_cpp.*
lm_studio.*
text_generation_webui.*
```

A backend-specific feature such as KV-cache format, GPU-layer allocation, CPU offload or runtime-specific performance control should remain in that backend's namespace unless a meaningful cross-provider standard exists.

Tori must not pretend unsupported options are active.

Provider interfaces should expose generic text or structured generation rather than Tori-specific operations such as memory extraction or task interpretation.

Those remain Tori application use cases.

---

## 8. Persona and Personality Architecture

The current static identity prompt becomes one input into a broader Persona subsystem.

Target pipeline:

```text
Immutable Founding Identity
            +
Stable Personality Definition
            +
Relationship Context
            +
Relevant Canonical Memory
            +
Current Project / Task Context
            +
Current Interaction Mode
            +
Learned Style Preferences
            +
Model-Specific Calibration
            │
            ▼
       Persona Compiler
            │
            ▼
 Current Tori Expression
```

### 8.1 Stable identity

The founding identity is highly protected and changes rarely.

Learning systems cannot directly alter it.

### 8.2 Stable personality

This defines Tori's recognizable traits, voice, interpersonal style, curiosity, humor, steadiness, conversational depth and other persistent characteristics.

It should be substantially richer than generic instructions to be pleasant or helpful.

### 8.3 Relationship context

This reflects accumulated understanding of how Tori and the user work together.

It is derived and advisory.

### 8.4 Interaction mode

Tori may naturally shift between modes such as:

```text
casual conversation
focused technical work
planning
reflection
research discussion
urgent problem solving
playful conversation
```

These are expressions of the same Tori, not different personas.

### 8.5 Model calibration

Different models may need slightly different prompt structures or examples to produce equivalent Tori behavior.

Calibration may vary.

Identity must not.

### 8.6 Evaluation

Personality changes require behavioral regression testing across supported model families.

External tools such as DeepEval or Promptfoo may assist evaluation but do not become runtime requirements.

Tests should assess recognizable Tori behavior, relationship continuity, truthfulness, authority boundaries, adaptability and resistance to personality drift.

---

## 9. Continuity Architecture

“Memory” is intentionally divided into distinct systems.

### 9.1 Canonical Personal Memory

Answers:

> What should Tori reliably remember about the user or relationship?

Examples include durable preferences, important facts, recurring priorities and explicit corrections.

This memory is authoritative only according to Tori's memory policy and provenance rules.

The current curated SQLite implementation may remain the initial canonical repository.

It must be placed behind a stable repository interface.

### 9.2 Relationship Model

Answers:

> What patterns has Tori observed about how the relationship works?

This is derived and advisory.

A relationship system may infer patterns such as preferred collaboration style but may not silently promote those patterns to canonical facts.

Possible future implementations may include Honcho-like systems or a Tori-owned derived model.

### 9.3 Conversation Archive

Answers:

> What was actually said?

The transcript remains historical evidence rather than personal memory.

### 9.4 Projects

Answers:

> What are we working toward and where did we leave it?

Projects remain explicit Tori-owned state rather than inferred memory.

### 9.5 Second Brain

Answers:

> What have we researched, written, discovered, collected or developed?

Second Brain material is primarily knowledge rather than personal memory.

The preferred direction is human-readable local files, likely Markdown, with optional graph/retrieval intelligence.

Understory is a leading candidate for the intelligent layer.

Obsidian is a leading human-facing interface.

Tori must remain capable of using the underlying information without requiring one proprietary interface.

### 9.6 Skills

Answers:

> How has Tori learned to perform something?

Skills are procedural memory.

The preferred interchange format is the Agent Skills ecosystem using `SKILL.md` plus optional references/scripts/assets.

A skill teaches procedure.

A skill never grants authority.

### 9.7 RAG

RAG is not a distinct authority or memory category.

It is a retrieval technique that may be used by:

- knowledge,
- canonical memory retrieval,
- the second brain,
- Projects,
- research sources,
- or other information domains.

Retrieval does not change source authority.

---

## 10. Memory Technology Strategy

The existing canonical-memory policy should be preserved unless evidence demonstrates a superior safe replacement.

The target design separates:

```text
MemoryPolicy
MemoryRepository
MemoryRetriever
MemoryExtractionPort
```

SQLite can remain the first `MemoryRepository`.

More advanced systems such as MemOS, Hindsight or future engines may initially serve as:

- retrieval helpers,
- derived indexes,
- relationship inference,
- temporal reasoning,
- reflection/synthesis systems.

Derived indexes should be rebuildable where practical.

Deleting canonical information must have a reliable way to remove or invalidate derived representations.

No external memory engine may make an inferred fact authoritative without passing through Tori's canonical memory policy.

---

## 11. Knowledge and Second Brain

Knowledge sources remain distinct from personal memory.

Target components:

```text
KnowledgeCatalog
KnowledgeReader
KnowledgeRetriever
KnowledgeContextPolicy
```

The catalog records trusted sources and permissions.

Readers safely access material.

Retrievers may use keyword search, vector search, graphs, hybrid retrieval or external systems.

Tori labels retrieved content as source material rather than instruction.

Second Brain should use this knowledge architecture while providing richer organization around research, ideas, notes and accumulated work.

Human readability and portability are strong preferences.

---

## 12. Search and Research

Search and Research are separate capabilities.

### 12.1 Search

Search is a relatively direct operation:

```text
query
→ search provider
→ normalized results
→ citations/provenance
→ Tori answer
```

SearXNG remains a valid first implementation.

It should sit behind `SearchPort`.

Another compatible search provider should be substitutable through configuration or an adapter.

### 12.2 Research

Research is a longer-running specialist workflow.

```text
research objective
→ authorized Research Job
→ specialist research worker
→ search/read/analyze/revise
→ source-backed report
→ Tori interpretation/discussion
```

GPT Researcher is a leading candidate for an initial research worker but not an architectural dependency.

A future research implementation may replace it without changing Tori Projects or authority semantics.

---

## 13. Capability Architecture

Tori requires a Capability Registry above any particular tool protocol.

Each installed capability has a Tori-owned manifest describing properties such as:

```text
stable capability ID
version
adapter/transport
trusted implementation identity
input/output schema
risk classification
read/write/destructive characteristics
required authority
network requirements
filesystem scope
data disclosure
Project/workspace scope
progress support
cancellation support
verification contract
availability
```

A capability may be implemented through:

```text
MCP
HTTP
OpenAI-compatible API
local stdio/RPC
Python SDK
native Tori implementation
other future protocols
```

Transport does not define authority.

---

## 14. MCP

MCP is a preferred interoperability mechanism when appropriate.

It is not Tori's authority layer.

Flow:

```text
MCP server
   ↓
MCP adapter
   ↓
Tori Capability Registry
   ↓
Tori policy / authority evaluation
   ↓
model/tool selection
   ↓
explicit confirmation if required
   ↓
execution
   ↓
validated structured result
```

Capabilities advertised by an MCP server are inventory, not permission.

MCP annotations may inform policy but are not automatically trusted.

Tori may restrict, hide or entirely reject available MCP tools.

---

## 15. Specialist Agents

Specialist agents are permitted and encouraged where they are the best implementation.

Examples may include:

```text
Coding Agent
Research Agent
Planning Agent
Browser Agent
Reflection Agent
Knowledge Agent
future specialists
```

An agent receives a bounded objective, context and authority.

It does not become an independent Tori.

Agents may reason autonomously within their approved job but cannot expand the job's authority.

Tori remains responsible for presenting important outcomes and preserving canonical state.

---

## 16. Learning and Adaptation

Learning is broader than factual memory.

Tori should support at least:

```text
factual learning → canonical/advisory memory
relationship learning → relationship model
procedural learning → Skills
knowledge accumulation → Second Brain
Project learning → proposed Project update
personality adaptation → bounded relationship/style evolution
```

Learning begins conservatively.

A typical procedural-learning flow is:

```text
Tori encounters meaningful experience
            ↓
Reflection identifies reusable procedure
            ↓
Candidate skill created
            ↓
scope/safety validation
            ↓
user review where appropriate
            ↓
skill activated
            ↓
future outcomes evaluated
```

No learning process may silently modify:

- Tori's founding identity,
- authority model,
- permission rules,
- canonical user facts,
- executable policy,
- Projects,
- tasks,
- or other authoritative state.

Automatic low-risk learning may be introduced later only after clear trust boundaries and rollback/history exist.

---

## 17. Agent Skills

Agent Skills is the preferred initial procedural-learning format.

Skills may contain:

```text
SKILL.md
references
examples
scripts
assets
```

Descriptions may be indexed for discovery while detailed instructions load only when relevant.

Skill tool declarations indicate requirements, not authorization.

Tori evaluates required capabilities separately.

Skills should be user-inspectable and preferably versionable.

A skill should be removable without corrupting canonical personal state.

---

## 18. Durable Jobs

Long-running work requires a first-class Tori Job domain.

Examples:

- coding work,
- deep research,
- large document processing,
- complex Project execution,
- future computer tasks.

A Job belongs to Tori rather than to one browser connection.

Conceptually:

```text
Job
    immutable ID
    requested objective
    originating user/context
    Project binding if applicable
    authority/permission snapshot
    worker type
    lifecycle state
    progress/events
    artifacts
    result
    verification
    timestamps
```

Likely lifecycle:

```text
proposed
authorized
queued
running
completed
failed
cancelled
interrupted
```

Job events should be durable enough that a client can disconnect and later reconstruct what occurred.

Clients observe Jobs.

Clients do not own Jobs.

Pithagoras is an architectural reference for reconnectable long-running work.

---

## 19. Coding and Project Execution

OpenCode, Pi, Open Terminal, Codex, OpenHands and future systems may serve as coding workers.

Tori owns:

- Project objective,
- workspace scope,
- requested result,
- authority,
- restrictions,
- user-facing plan,
- acceptance criteria,
- result interpretation.

The coding worker owns:

- editing,
- build/test execution,
- analysis of source,
- implementation mechanics,
- progress reporting.

Pi is a leading initial candidate because its RPC architecture appears well suited to embedding beneath Tori.

The first integration should favor strong process separation such as RPC/stdio rather than deep runtime coupling.

Worker output should include structured progress, changed artifacts, verification evidence and final status.

A coding agent must not infer permission to modify unrelated workspaces or canonical Tori state.

---

## 20. Planning, Calendar and Scheduling

The current Tori-owned meaning of:

- Tasks,
- Reminders,
- Scheduled Work,
- missed-run policy,
- time interpretation,
- durable authorization,
- and lifecycle state

should remain.

External calendar systems should be integrations rather than replacements for Tori's semantic model.

A future `CalendarPort` may support:

```text
query events
check availability
propose event
create/update/delete event
synchronize selected state
```

Calendar writes remain governed by Tori authority.

The UI should eventually provide a useful visual calendar or scheduling surface rather than relying exclusively on conversational commands.

External planning agents may suggest Project plans or schedules but may not silently mutate Projects or Tasks.

---

## 21. Voice Architecture

Voice should be designed as a complete session system rather than separate TTS and STT features.

Target:

```text
                    VoiceSessionService
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
 Activation            Listening             Output
       │                    │                    │
 push-to-talk              VAD                   TTS
 wake phrase               STT              playback
 manual toggle        turn detection        cancellation
       │                    │                    │
       └────────────────────┴────────────────────┘
                            │
                           Tori
```

### 21.1 Voice activation

Supported future activation methods should include:

- button/tap,
- push-to-talk,
- configurable listening word or phrase.

A local wake-word implementation such as openWakeWord may be evaluated behind a `WakeWordDetectorPort`.

### 21.2 Barge-in

The user should be able to interrupt Tori while she is speaking.

Intentional speech should:

1. interrupt or pause current TTS,
2. capture the user's turn,
3. transcribe it,
4. submit it to Tori,
5. continue naturally.

False interruptions should be handled gracefully.

Existing projects such as Pipecat and LiveKit should be evaluated when this feature is implemented rather than recreating mature voice-turn logic from scratch.

### 21.3 Speech providers

TTS and STT engines remain replaceable.

OpenAI-compatible audio APIs are preferred where they provide an adequate contract.

An optional speech router such as Open Unified TTS may allow several local TTS implementations behind one stable endpoint.

Tori owns when and what to speak.

The frontend does not decide conversational speech behavior.

### 21.4 Network consequence

Mobile browser microphone support may require HTTPS/TLS on LAN deployments. Voice-input implementation must account for secure-browser-context requirements.

---

## 22. Control Plane and Data Plane

The architecture intentionally separates application control/state traffic from high-rate streaming traffic.

### 22.1 Control plane

Examples:

```text
permissions
proposals
Projects
Tasks
Jobs
settings
capability registration
lifecycle changes
revisions
active conversation state
configuration
```

### 22.2 Data plane

Examples:

```text
LLM token streams
TTS audio
microphone audio
STT partial transcripts
coding logs
research progress
screenshots
vision streams
large artifacts
```

The exact protocols may differ.

The architectural requirement is that high-volume streaming does not force all state and application policy through one monolithic coordinator.

---

## 23. Events

Tori should expose stable typed application events.

Examples might include:

```text
conversation.changed
conversation.busy
project.changed
task.changed
reminder.due
job.started
job.progress
job.completed
job.failed
capability.changed
proposal.created
proposal.resolved
memory.changed
voice.listening
voice.speaking
```

Event names are illustrative.

Consumers should subscribe to events rather than repeatedly gaining direct knowledge of unrelated internals.

Events do not replace authoritative queries. They communicate change.

---

## 24. Frontend Architecture

The custom Tori interface remains the preferred primary frontend.

Its implementation must be refactored into a real client of Tori application services rather than containing Tori application policy.

The product direction should combine:

- Tori's current visual identity,
- the compact organization and settings accessibility of Open WebUI,
- useful conversational/voice concepts demonstrated by SillyTavern and companion-oriented systems,
- Tori-specific authority, Projects, continuity and personality experiences.

The UI should become smaller and more composable, not a single expanding page.

Primary conceptual navigation may eventually include:

```text
Conversation
Projects
Tasks / Calendar
Second Brain
Capabilities
Memory
Settings
```

Not every function deserves permanent primary navigation.

### 24.1 Modular views

Views should register declaratively through one application-owned mechanism.

Each view/module owns:

- its rendering root,
- state adapter,
- frontend module,
- scoped styling,
- relevant API calls.

Adding Calendar must not require modifying Conversation's layout.

Adding a new capability must not shift chat geometry.

### 24.2 Conversation isolation

Conversation should have a stable layout contract.

Feature chrome should not compete with the transcript for global layout rows.

### 24.3 Mobile

Desktop and mobile workflows are designed together rather than mobile being repaired during final acceptance.

### 24.4 Alternate clients

Tori's API should eventually be clean enough that Open WebUI or another external frontend can interact with selected Tori functionality.

This is both useful compatibility and proof that Tori is independent from her custom UI.

The external client does not own personality, authority or canonical state.

---

## 25. Configuration Architecture

Configuration should be layered.

Conceptually:

```text
Tori defaults
      ↓
installation/admin configuration
      ↓
provider/capability profiles
      ↓
user-visible settings
      ↓
session/request overrides where appropriate
```

Secrets and infrastructure details should not be mixed indiscriminately with normal user preferences.

Replaceable technology should usually be represented through profiles.

Example:

```text
Speech Profile
    implementation
    endpoint
    model
    voice
    portable settings
    implementation-specific extensions
```

The same pattern can apply to model, search, STT and other provider families.

Unsupported settings must fail honestly or be visibly unavailable rather than silently ignored.

---

## 26. Canonical and Derived State

Every persistent system must identify whether its state is:

**Canonical** — authoritative Tori-owned state.

**Derived** — rebuildable or inferred state generated from canonical/source material.

**External authoritative source** — information owned elsewhere, such as calendar events or user-managed files.

Derived state should not silently become canonical.

Examples:

```text
canonical memory        → canonical
memory vector index     → derived
relationship inference  → derived/advisory
conversation archive    → canonical historical record
Understory index        → derived
Second Brain Markdown   → user-owned source material
Project state           → canonical
Skill file              → procedural source
external calendar       → externally authoritative
```

Backup/restore and deletion semantics must respect these classifications.

---

## 27. Security and Trust

Local-first does not mean automatically trusted.

External tools may contain bugs or malicious behavior.

Tori should apply least privilege to:

- filesystem,
- network,
- credentials,
- Project workspaces,
- external services,
- MCP servers,
- coding agents,
- scripts included in Skills.

Installation and availability are separate from execution permission.

Capabilities should declare required access.

Tori decides whether that access is permitted.

High-risk external workers should preferably execute behind process or OS isolation rather than inside the Tori application process.

---

## 28. OSS Selection Policy

The OSS-first governance rule is implemented through an explicit selection process.

Before building a replaceable technology, research current candidates against:

```text
functional fit
architecture/API fit
local/self-hosted operation
license
maintenance/activity
data ownership
security model
telemetry
resource requirements
replaceability
failure behavior
community/ecosystem
integration cost
```

A well-fitting existing implementation should normally be wrapped rather than recreated.

An external project must not be selected merely because it is popular.

A small Tori-owned implementation may be preferable when the actual requirement is narrow and stable.

---

## 29. Current Candidate Map

Candidate projects guide initial integrations but are not permanent architecture dependencies.

| Area | Leading candidates / references |
|---|---|
| Model runtime | Ollama, LM Studio, llama.cpp, text-generation-webui, other compatible backends |
| TTS | Qwen, Kokoro, Open Unified TTS, future engines |
| STT | Whisper-family/local OpenAI-compatible recognition services |
| Wake word | openWakeWord or later replacement |
| Voice pipeline | Pipecat, LiveKit as design/implementation candidates |
| Canonical memory | Current Tori SQLite initially |
| Memory enhancement | Hindsight, MemOS, future candidates |
| Relationship model | Honcho-like systems / future Tori adapter |
| Second Brain | Understory + Markdown |
| Human Second Brain UI | Obsidian |
| Semantic Obsidian enhancement | Smart Connections or future alternatives |
| Procedural learning | Agent Skills |
| Coding worker | Pi leading; OpenCode/OpenHands/Codex also candidates |
| Research worker | GPT Researcher leading |
| Search | SearXNG first implementation |
| Personality references | AIRI, Marinara, SillyTavern/SillyBunny concepts |
| Persona evaluation | DeepEval / Promptfoo |
| Capability transport | MCP, HTTP, stdio/RPC, SDK |
| Training/fine-tuning laboratory | Unsloth if later justified |

Every candidate can be replaced.

---

## 30. Research Basis and Architectural References

The projects in this section are **research references and candidate implementations**, not architectural authorities.

Tori's architecture does not depend on any one of them remaining maintained or available.

For each project, this section records:

- why it was studied;
- what architectural lesson influenced Tori;
- what may be reused or integrated;
- what Tori deliberately does not delegate to it;
- its intended status.

### 30.1 Open WebUI

**Studied for:** frontend organization, settings accessibility, provider configuration, model controls, extensibility, tool/MCP presentation.

**Influence on Tori:**

- compact interface organization;
- advanced settings accessible without dominating Conversation;
- model/provider configuration patterns;
- capability/tool discoverability;
- proof that one frontend can accommodate a large feature set without permanently displaying every feature.

**Not adopted as Tori architecture:**

- Tori identity/personality does not belong to the frontend;
- Tori authority and confirmation semantics remain in the core;
- frontend-controlled post-response TTS behavior is specifically undesirable;
- multi-user/authentication functionality is not presently a Tori requirement.

**Target status:** Design reference and future compatibility client, not required primary frontend.

### 30.2 SillyTavern

**Studied for:** conversational UX, layered persona/context composition, extensions, TTS integration, vectorized contextual material, character-oriented interaction.

**Influence on Tori:**

- personality should be first-class rather than one generic system message;
- different contextual/persona material can be selectively activated instead of permanently consuming context;
- conversational speech should stream naturally;
- extensions should remain separate from the conversational identity.

**Not adopted:**

- Tori is not a Character Card;
- probabilistic lore/personality activation is not an authority system;
- character definitions do not replace Tori's founding identity;
- plugin architecture is not automatically trusted.

**Target status:** Persona, conversation and extension-design reference.

### 30.3 Project AIRI

**Studied for:** persistent AI companion architecture, voice interaction, modular services/plugins, capability routing, central control and streaming infrastructure.

**Major architectural influence:**

AIRI helped validate separation between:

**Control-plane concerns**

- permissions;
- configuration;
- lifecycle;
- capability registration;
- routing;

and **high-volume data-plane concerns**

- audio;
- transcription;
- streamed model output;
- other realtime data.

This influenced Tori's explicit Control Plane / Data Plane separation.

AIRI also provides useful evidence that a companion can be composed from multiple technical modules while maintaining one higher-level presence.

**Persona influence:**

Its companion-oriented architecture and experimentation around accumulated experience reinforced the distinction among:

- foundational identity;
- stable personality;
- slowly evolving relationship influence;
- temporary conversational state.

**Not adopted:**

- AIRI does not define Tori's authority model;
- AIRI plugins do not receive implicit Tori permissions;
- Tori's identity remains defined by Tori's founding documents;
- Tori is not being rebuilt as AIRI.

**Target status:** Major architecture/persona/voice design reference.

### 30.4 Marinara Engine

**Studied for:** specialist-agent pipelines, modular agent packages, character/persona evolution, reviewable agent output, extension installation and security patterns.

**Influence on Tori:**

- specialist agents may operate at bounded stages without becoming the primary assistant;
- learned/personality changes can be proposed for review rather than silently applied;
- optional functionality can be packaged separately from the base core;
- capability packages should have identity, validation and installation boundaries.

**Not adopted:**

- external agents cannot rewrite Tori's personality autonomously;
- Marinara's character model does not define Tori;
- its extension authority does not supersede Tori's permissions.

**Target status:** Agent/persona/capability-package design reference.

### 30.5 Understory

**Studied for:** local second-brain architecture, Markdown/YAML storage, knowledge graphs, MCP access and portable human-readable knowledge.

**Influence on Tori:**

It strongly influenced separating:

> Personal Memory

from:

> Second Brain / accumulated knowledge.

Second Brain information should preferably remain inspectable without Tori.

Markdown-backed knowledge also aligns with:

- portability;
- Git/history;
- Obsidian;
- manual inspection;
- long-term independence from one AI engine.

**Not adopted:**

- Understory does not become canonical personal memory;
- its model cannot decide authoritative facts about the user;
- its graph/index is subordinate to source material and Tori policy.

**Target status:** Leading initial Second Brain candidate.

### 30.6 Obsidian

**Studied for:** human-facing second-brain workflow.

**Influence on Tori:**

The user should retain a useful human interface into research, notes, journal-like material, Project material and accumulated knowledge without requiring AI mediation.

This reinforces a preference for ordinary portable files underneath the Second Brain.

**Not adopted:**

- Obsidian is not required for Tori operation;
- its vault does not become canonical Tori memory;
- Tori should interact with the underlying knowledge rather than depend permanently on one UI.

**Target status:** Preferred human Second Brain interface candidate.

### 30.7 Agent Skills

**Studied for:** portable procedural learning.

**Major architectural influence:**

Established the distinction:

> **Memory = what Tori knows.**

> **Skill = how Tori has learned to do something.**

A skill may provide procedures, references, scripts or supporting assets and may be loaded only when relevant.

**Critical authority rule:**

A Skill may declare that a tool is required.

That declaration **never authorizes the tool**.

Tori's authority layer separately decides whether execution is permitted.

**Target status:** Preferred initial procedural-learning format.

### 30.8 Hermes Agent / OpenClaw

**Studied for:** experiential learning, persistent memory and self-improving procedural Skills.

**Influence on Tori:**

Their learning behavior helped demonstrate that useful agent learning does not necessarily mean modifying model weights. A system can learn reusable procedures from:

- successful workflows;
- corrections;
- failures followed by solutions;
- repeated patterns.

This influenced Tori's proposed:

```text
experience
→ reflection
→ candidate lesson/skill
→ validation
→ approval where required
→ activation
→ future evaluation
```

**Not adopted:**

Tori will initially favor governed/proposed learning rather than permitting an autonomous learning loop to rewrite authoritative state.

**Target status:** Learning-system design references.

### 30.9 Pi

**Studied for:** specialist coding-agent execution.

**Why it is important:**

Its RPC/SDK approach demonstrates that a capable coding agent can be embedded beneath another system without that system having to implement the coding loop itself.

**Influence on Tori:**

- coding should become a specialist worker;
- process/RPC separation is preferable initially;
- Tori owns Project objective, permission and workspace scope;
- the worker owns coding mechanics;
- progress/results should return to Tori structurally.

**Important limitation:**

Worker availability does not constitute sandboxing or authorization. Tori remains responsible for execution boundaries.

**Target status:** Leading initial Coding Worker candidate.

### 30.10 Pithagoras

**Studied for:** persistent long-running agent jobs.

**Major architectural influence:**

Its server-owned execution/reconnect pattern influenced Tori's proposed durable Job domain:

```text
create Job
→ worker executes independently of browser connection
→ durable progress/events
→ client disconnect/reconnect
→ reconstruct state
→ final result
```

**Not adopted as a required dependency.**

The pattern is more important than the project itself.

**Target status:** Durable-Job architectural reference.

### 30.11 GPT Researcher

**Studied for:** deep multi-step research.

**Influence on Tori:**

Reinforced separation between:

**Search**

- fast query/retrieval;

and:

**Research**

- planned multi-step investigation;
- multiple sources;
- analysis;
- source-backed report;
- longer-running execution.

Research therefore belongs naturally in Tori's Job/agent architecture rather than being implemented as increasingly complicated search logic.

**Target status:** Leading initial Research Worker candidate.

### 30.12 MemOS / Hindsight

**Studied for:** modern long-term memory, retrieval, temporal/graph relationships and reflection.

**Influence on Tori:**

Their capabilities reinforced separation between:

- canonical memory;
- retrieval;
- derived indexes;
- reflection;
- relationship/temporal synthesis.

Research also reinforced that indiscriminately retrieving more memories is not necessarily beneficial.

**Not adopted:**

Neither system is currently selected to replace Tori's canonical personal memory.

The existing curated SQLite memory remains the baseline because its authority, provenance, correction and consent semantics fit Tori well.

**Target status:** Candidates for advanced retrieval/derived-memory experiments behind ports.

### 30.13 Honcho

**Studied for:** relationship modeling.

**Influence on Tori:**

Helped clarify that:

> “What is reliably true about the user?”

and:

> “What patterns has Tori observed about the relationship?”

should not be stored with identical authority.

This directly influenced creation of the advisory `RelationshipModelPort`.

**Not adopted:**

Derived relationship conclusions do not become canonical personal facts automatically.

**Target status:** Relationship-model research candidate/reference.

### 30.14 Open Unified TTS

**Studied for:** backend-independent speech synthesis.

**Influence on Tori:**

Demonstrated that multiple TTS engines can potentially sit behind one relatively stable speech API.

This reinforces the requirement that changing Qwen, Kokoro or another engine should not require changes to Conversation.

**Target status:** Speech-router candidate, not mandatory architecture.

### 30.15 Pipecat / LiveKit

**Studied for:** realtime voice sessions.

**Influence on Tori:**

Provided mature reference patterns for:

- VAD;
- conversational turns;
- interruption/barge-in;
- false interruption handling;
- realtime audio flow.

This influenced the decision to model voice as a **Voice Session**, rather than independently implementing TTS and STT.

**Target status:** Voice-pipeline implementation/design candidates to revisit during the Voice milestone.

### 30.16 openWakeWord

**Studied for:** local wake-word activation.

**Influence on Tori:**

Demonstrates that a listening phrase can be implemented as another replaceable voice component behind a narrow wake-word detection contract.

**Target status:** Initial wake-word candidate, subject to reevaluation when voice work begins.

### 30.17 Unsloth

**Studied for:** local model optimization and fine-tuning.

**Influence on Tori:**

Shows a possible future path for model experimentation or Persona calibration.

**Not adopted:**

Tori's identity must never depend on a particular fine-tuned model.

**Target status:** Future model laboratory, not Tori Core.

### 30.18 SillyBunny

**Studied for:** companion-oriented conversational interface ideas, personality presentation, extension concepts, and modern character/assistant UX.

**Influence on Tori:**

- useful reference for immersive conversational presentation;
- reinforces that personality should be visible through the experience, not only hidden in a system prompt;
- provides additional UI and extension ideas to compare with SillyTavern and AIRI.

**Not adopted:**

- Tori is not a character-card application;
- its plugin/persona model does not become Tori's authority or identity architecture.

**Target status:** UI/persona design reference.

### 30.19 AI Engineering From Scratch

**Studied for:** current agent, MCP, memory, skills, orchestration and AI-engineering patterns.

**Influence on Tori:**

Used as a research/reference library when comparing modern implementation patterns and identifying existing standards before custom development.

**Not adopted:**

It is not a Tori dependency or architecture authority.

**Target status:** Engineering reference library.

---

## 31. Architectural Use of Research References

The projects above serve three distinct roles.

### 31.1 Design references

Used to learn a proven architectural pattern.

Examples:

- AIRI → control/data-plane and modular companion concepts.
- Pithagoras → durable reconnectable Jobs.
- SillyTavern → layered contextual/persona composition.
- Marinara → reviewable agent/adaptation patterns.

Tori may never install these projects.

### 31.2 Candidate implementations

Potential initial implementations behind a Tori port.

Examples:

- Pi → Coding Worker.
- GPT Researcher → Research Worker.
- Understory → Second Brain.
- openWakeWord → wake-word detection.
- Hindsight/MemOS → advanced memory retrieval.

They remain replaceable.

### 31.3 Standards/ecosystems

Interfaces intended to reduce Tori-specific integration.

Examples:

- MCP → capability transport.
- Agent Skills → procedural-learning interchange.
- OpenAI-compatible APIs → model/audio provider compatibility.

Standards are preferred when appropriate but never override Tori's safety and authority rules.

---

## 32. Reference Preservation Rule

Any architecture materially influenced by an external project should record:

1. the project or standard studied;
2. the architectural lesson taken from it;
3. what Tori deliberately does differently;
4. whether it is a reference, candidate implementation or required standard;
5. the Tori-owned boundary that prevents dependence on it.

This allows future maintainers to understand **why the architecture exists** even if the external project changes or disappears.

---

## 33. Testing Architecture

Tests should increasingly follow boundaries rather than implementations.

Target categories:

```text
Domain invariant tests
Application use-case tests
Port contract suites
Adapter tests
API/event contract tests
Real-browser tests
Migration/storage tests
Persona behavioral evaluations
Security/authority tests
Cross-client convergence tests
```

A provider adapter passes the same contract suite regardless of implementation.

Application services can be tested against fakes without starting the web server.

Browser tests should test actual user behavior rather than primarily source-string assumptions.

Complete full-suite verification remains useful at appropriate milestone gates but should no longer be required after every narrow correction simply because dependencies are unclear.

---

## 34. Definition of Modular Completion

A replaceable subsystem is not complete solely because one implementation works.

Where applicable, completion should demonstrate at least one of:

- second implementation,
- fake implementation satisfying the contract,
- reusable adapter contract tests,
- alternate frontend/client,
- runtime provider switch with no core modification.

Example:

> Speech architecture is not considered fully modular merely because Qwen TTS works.

A stronger acceptance test is:

> Configure a second compliant TTS implementation and speak successfully without changing Conversation or Tori core source.

---

## 35. Architecture Recovery Strategy

Recovery should use incremental strangler refactoring rather than a rewrite.

Current canonical data remains in place.

Existing implementations become the first adapters behind new ports.

Only after consumers move behind stable boundaries should old coupling be removed.

The target sequence is approximately:

1. Preserve current schema-6 checkpoint.
2. Establish application-core services outside `WebApplication`.
3. Extract repository/storage ports.
4. Introduce unified proposal/confirmation infrastructure where appropriate.
5. Define stable application HTTP/SSE/event contracts.
6. Refactor the custom UI into modular clients of those contracts.
7. Refine model-provider generation options.
8. Introduce Capability Registry and manifests.
9. Externalize Search behind its port.
10. Externalize speech providers.
11. Introduce durable Jobs.
12. Prove a coding worker integration.
13. Prove a research worker integration.
14. Separate memory policy/repository/retrieval.
15. Establish Second Brain integration.
16. Establish procedural Skill support.
17. Implement Persona subsystem and behavioral evaluation.
18. Resume and complete M25 through the recovered architecture.
19. Continue future capabilities under architecture-governance gates.

This order may change if implementation evidence justifies it.

Architecture boundaries take priority over milestone numbering.

---

## 36. M25 Status in the Target Architecture

Milestone 25 remains incomplete and frozen.

The following M25 concepts should be preserved:

- schema-6 Project persistence,
- immutable Project IDs,
- chat association,
- Project status/objective/continuity,
- Project context integration,
- revision safety,
- no implicit Project mutation,
- no authority from Project context.

Project behavior should be moved behind presentation-neutral Project application services.

The custom web implementation should not remain its permanent orchestration layer.

The missing Project → associated conversations workflow remains a product requirement.

M25 acceptance resumes only after enough recovery architecture exists that further Project work will not deepen current `WebApplication` and UI coupling.

---

## 37. Known Future Voice Requirement

Future voice work must support:

- push-to-talk/listen button,
- configurable wake phrase/listening word,
- streaming STT,
- replaceable STT engine,
- streaming TTS,
- replaceable TTS engine,
- user interruption/barge-in while Tori is speaking,
- speech cancellation,
- mobile browser operation,
- appropriate TLS/secure-context support.

This is a planned capability, not part of the initial architecture-recovery implementation.

---

## 38. Non-Goals

This target architecture does not require:

- converting Tori into a generic agent framework,
- replacing all existing code,
- adopting every listed OSS project,
- making MCP the only tool protocol,
- outsourcing Tori's identity or authority,
- allowing autonomous agents unrestricted control,
- putting all information into one memory system,
- fine-tuning a model to become Tori,
- abandoning the custom UI,
- creating abstractions merely for theoretical flexibility.

The purpose is controlled replaceability, not abstraction for its own sake.

---

## 39. Architectural Success Criteria

Architecture recovery is successful when adding or replacing an external technology normally requires work localized to its adapter/configuration and contract tests rather than changes across unrelated Tori domains.

Representative proofs should eventually include:

```text
Switch TTS implementation without changing Conversation.

Switch Search implementation without changing search policy.

Use a different model backend without changing memory/task logic.

Run a coding Job through a replaceable worker.

Run a research Job through a replaceable worker.

Replace memory retrieval without changing canonical memory policy.

Use Tori through another client without moving authority into that client.

Add a new management view without modifying Conversation layout.

Install a procedural Skill without granting new authority.

Use an MCP capability while Tori continues to enforce its own permission rules.
```

The deeper success criterion is simpler:

> **Tori should become more capable over time without becoming harder to change.**

---

## 40. Final Architectural Principle

Tori is not the sum of her tools.

Models will change.

Memory technology will change.

Speech engines will change.

Agents will change.

Interfaces will change.

The open-source ecosystem will change.

Tori's role is to remain the stable intelligence, relationship, policy, continuity and authority layer that makes those technologies work together as one coherent assistant.

Technology should be replaceable.

**Tori should remain Tori.**
