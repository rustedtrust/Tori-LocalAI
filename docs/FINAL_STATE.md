# Tori — Current State and Closeout Checkpoint

**Status:** v0.9.0 Stable Private Testing Checkpoint source. This document retains the established `FINAL_STATE.md` path for existing links; its former 2026-08-31 V1 closeout was an earlier checkpoint. The seven [founding documents](00_MISSION.md) through [architecture](06_ARCHITECTURE.md) remain authoritative. See the [User Guide](USER_GUIDE.md) for use, the [documentation map](README.md) for contracts and evidence, and the [roadmap](IMPLEMENTATION_ROADMAP.md) for completed milestone history.

**Private closeout:** Gate 6 core installation and Gate 6B independent fresh-GitHub-clone acceptance passed; Gate 7 whole-product production smoke passed with no known closeout defect. Research Worker was available under normal owner launch. Automatic Research Worker and Voice Input installer provisioning remain explicitly deferred; separately managed prerequisites remain separate. The v0.9.0 tag is reserved for this source only after a verified final production backup and disposable restore pass. Public Release Readiness, including privacy and licensing review, is separate future work; this is not a public or v1.0 release.

**Code checkpoint entering documentation Gate 4:** `private revision omitted` — `Fix Remote Chat generation fencing` (`main` = `origin/main` at gate entry). Gate 1 capability/forgotten-item audit, Gate 2 external-folder dependency audit, Gate 3 capability-awareness/Commands/Security Settings/voice corrections, and Remote Chat lifecycle fencing are complete and committed. The entering offline verifier baseline was 2,127 Python tests with three established skips. At this entry checkpoint, Gate 4 documentation awaited review and commit; Gate 5 security/architecture composition audit, installer and fresh-clone work, final restore validation, and final project backup/freeze had **not** been completed. A later code checkout should verify Git state rather than treating this hash as a perpetual HEAD claim.

**Public preview qualification:** verified backup creation is available.
Automatic Restore trusts only the pinned public `rustedtrust/Tori-LocalAI` Git
origin and source history; a history-free ZIP cannot perform automatic Restore.
The detailed private closeout observations below describe the earlier private
checkpoint, not a promise that optional services or models work in a fresh
public download.

## Implemented capabilities

- **Conversation and continuity:** CLI and responsive streamed Web chat, stable identity and situational companion guidance, automatically archived chats and per-turn provider provenance, explicit dormant checkpoints, selected provider/model/context, curated Memory with bounded candidate extraction and confirmation, and exact user-selected `.txt`/`.md` Knowledge registration with live bounded passage retrieval. Knowledge source files remain authoritative; research, chat archives, checkpoints, and Memory are separate stores/meanings.
- **Information and research:** Consent-bound SearXNG Web Search and public-source retrieval; separately authorized, durable Research Worker jobs with bounded public-web evidence, claim/evidence validation, cancellation and restart truth; default-Off Night Owl category research; Security Center external primary-source threat intelligence and static Environment Watch relevance. Security Center has no connected alert sources or local vulnerability-scan claim.
- **Organization and advice:** Human-accepted Projects & Continuity V1 with structured Project Home, source-owned Related Work and bounded context receipts; implemented Planning/CalDAV/Radicale projection (Today, upcoming, tasks and nearby calendar agenda), confirmed conversational edits and Reminder Bridge; tasks/reminders, bounded Scheduled Work, and optional suggestion-only Companion check-ins and durable attention. Historical Milestone 25 was frozen and unaccepted; the later Projects V1 completion is separately accepted.
- **Capabilities and actions:** Managed Skills with explicit lifecycle and grants; advisory Capability Growth/Skills Review; one exact supervised local MCP Time server with only `get_current_time` approved; explicitly confirmed Delegated Work through pinned OpenCode with fresh authority for related follow-ups; local Supervised Terminal with four-state policy, exact commands, one-use grants, PTY/xterm browser drawer, human keyboard takeover and Private Input. Terminal execution is restricted to direct loopback local clients and approved local conversation paths, not LAN or Remote Chat. A historical `/run` compatibility route is not a browser Commands recommendation.
- **Voice and remote:** Desktop-local push-to-talk Voice Input with explicit Off/Ready, bounded RealtimeSTT runtime and manual barge-in; optional TTS profiles and manual/automatic transient browser playback. Discord Remote Chat is a one-owner private-text-DM integration with seven bounded operations, including authority-reducing self-disable; each process starts Off, requires fresh local enablement, uses a dedicated archive, and fences stale generations across disable/re-enable. Search requires its own consent; no remote host execution, local confirmation, Skill administration or broader authority.
- **Operations:** Finance V1 is implemented and human accepted: an external seven-sheet `.xlsx` workbook supports deterministic budgeting, spending, bills, debts and goals, reviewed CSV/XML OFX/QFX imports and confirmed verified writes, without bank connections or payments. Bounded host/system reads, allowlisted desktop opening and confirmed fixed Ollama/Radicale service controls are available. Verified backups and whole-runtime restore with mandatory safety backup, selected-backup re-verification, trusted source-history check, external helper, local health check and bounded rollback are implemented. Settings provides supported provider profiles, model/context navigation, Search, voice, Night Owl, Remote Chat, Maintenance and other bounded preferences; the richer standalone Model Settings workspace is deferred.

## Intentional V1 boundaries and deferred directions

No direct image generation or image-generation integration is present. Tori can discuss the topic and Night Owl can research projects/tools, but researching a tool does not create images. Direct generation is intentional future scope.

Knowledge supports only exact registered `.txt`/`.md` files and live bounded passage reads: no folder or PDF ingestion, vector database, automatic broad Second Brain ingestion, or unified research/Project/Memory system. Richer [Knowledge design](design/KNOWLEDGE_PROVIDER_CONTRACT.md) is a design reference, not present functionality. Optional full-text archive search is also deferred.

Other intentional future work: wake word/passive or hands-free voice and broader automatic voice follow-up; broader MCP transports, writes and arbitrary server administration; automatic Skill creation/update; generic autonomous agents and broader self-management; sensitive-memory/secrets vault; broader Discord/remote authority; connected security-product/alert ingestion; and richer standalone Model Settings. No unattended capability growth, payments, bank connections, unrestricted command execution, autonomous coding, or silent provider fallback is implied. Full calendar grids and attendees, backup pruning, and selective/configuration restore remain outside the accepted V1 scope. These are deferrals, not missing V1 bugs. Any expansion needs fresh scope under [architecture governance](ARCHITECTURE_GOVERNANCE.md).

## Deployment, data and recovery boundaries

Tori core owns identity, state, authority, policy and verification; adapters and endpoints are replaceable. The source tree is not a self-contained copy of user data or every optional worker:

| Location or integration | Current role and recovery implication |
| --- | --- |
| `runtime/` and per-machine root `tori.toml` | Canonical local state and private machine configuration; ordinary backup includes runtime, restore preserves this machine's `tori.toml`. Never clean unknown runtime entries as test residue. |
| Sibling `<installation-name>_backups/` directory | Verified project backups; retain separately from the live installation. |
| `~/.local/share/tori/radicale/collections/` | Planning/CalDAV collection data outside normal Tori backup/restore; preserve separately. |
| Configured external Finance root; registered Knowledge paths | Authoritative workbook/statements and live source files outside normal restore; back up separately. |
| `~/.config/tori/` | Owner-private provider token and Remote Chat configuration/credentials outside repository and normal Tori backup; use private recovery, never publish secrets. |
| Installed bounded host helpers | Fixed Ollama service-control helper/sudoers and local user-service deployment may require separate reinstallation/validation after host recovery. |

**Research Worker deployment dependency:** The optional worker requires a separately installed external wrapper, its own environment, and operator-configured absolute paths. Core Tori works without it; `install.sh` does not provision it. A clean source download or core backup is not a complete Research Worker deployment.

Ollama, LM Studio/OpenAI-compatible endpoints, SearXNG, TTS endpoints, Discord, OpenCode CLI and Radicale are separate optional services/tools. Endpoint-driven integration does not imply dependence on any service's source checkout. Tori uses Python 3.11+ and standard-library-first core with pinned adapters; optional service provisioning belongs to its own operator/integration setup. Voice model assets and its separate prepared runtime have their own [deployment notes](../deploy/voice/README.md).

## Returning to development

Start with the founding documents, this checkpoint, and current code/tests. Review Git state and external data before any change; the [roadmap](IMPLEMENTATION_ROADMAP.md) preserves earlier slices and historical acceptance rather than granting standing future scope. This public preview derives from a separately maintained private v0.9.0 checkpoint; no private Git history was imported.
