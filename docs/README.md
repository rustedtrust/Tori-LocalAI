# Documentation map

**Start here:** [root README](../README.md) for install/start and an overview; [User Guide](USER_GUIDE.md) for actual use; [Current State](FINAL_STATE.md) for the authoritative Gate 4 entry checkpoint, accepted capabilities, deferrals and external recovery/deployment dependencies. [Implementation Roadmap](IMPLEMENTATION_ROADMAP.md) preserves milestone and slice history; older “not yet” statements in its historical sections describe their dated stage, not today's product.

## Authority and engineering

- `00_MISSION.md` through `06_ARCHITECTURE.md` are the **protected accepted founding documents**, not release notes. [Architecture governance](ARCHITECTURE_GOVERNANCE.md) and [target architecture](TARGET_ARCHITECTURE.md) guide approved scopes without amending them.
- [Conversation behavior contract](CONVERSATION_BEHAVIOR_CONTRACT.md) covers deterministic conversational authority. The [implementation roadmap](IMPLEMENTATION_ROADMAP.md) records accepted engineering milestones. Run [`verify-milestone`](../scripts/verify-milestone) for the complete offline gate in a configured development environment.

## Accepted capability contracts and architecture

- [Projects & Continuity](PROJECTS_CONTINUITY_V1_ARCHITECTURE.md), [Planning/CalDAV](PLANNING_CALDAV_CONTRACT.md), [Finance](FINANCE_V1_CONTRACT.md), and [Security Center](SECURITY_CENTER_V1.md).
- [Search](design/SEARCH_PROVIDER_CONTRACT.md), [Knowledge](design/KNOWLEDGE_PROVIDER_CONTRACT.md) (richer ingestion is design only), [TTS provider](design/TTS_PROVIDER_CONTRACT.md), [TTS profiles](design/TTS_PROFILES_DESIGN.md), and [Voice Input](VOICE_INPUT_V1_ARCHITECTURE.md).
- [Research Worker](RESEARCH_WORKER_V1_ARCHITECTURE.md), [Night Owl](NIGHT_OWL_V1_ARCHITECTURE.md), [Capability Growth](CAPABILITY_GROWTH_V1_ARCHITECTURE.md), [Skills](SKILLS_V1_ARCHITECTURE.md), [MCP Time](MCP_V1_ARCHITECTURE.md), [Delegated Work](DELEGATED_WORK_V1_ARCHITECTURE.md), [Supervised Terminal](SUPERVISED_TERMINAL_V1_ARCHITECTURE.md), [Remote Chat](REMOTE_CHAT_V1_CONTRACT.md), and [Companion V1](COMPANION_INITIATIVE_V1_ARCHITECTURE.md)/[V2 attention](COMPANION_INITIATIVE_V2_ARCHITECTURE.md).

## Historical evidence and research

`design/` contains provider contracts. `research/` contains dated technology reviews, a superseded target-architecture draft, and the [old Deep Research V1 design](research/DEEP_RESEARCH_V1_CONTRACT.md). That older experiment's “not implemented” verdict applies **only to that design**; the separately accepted Research Worker is current, with a different authoritative-source retrieval policy. The [Projects contract](PROJECTS_CONTINUITY_V1_ARCHITECTURE.md) describes both its historical schema-6 baseline and later accepted schema-7 completion. Private acceptance artifacts are deliberately absent from this public candidate.
