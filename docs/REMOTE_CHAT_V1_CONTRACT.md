# Tori Remote Chat V1 Contract

**Status:** Complete and physically human accepted
**Authority:** Living contract subordinate to the seven founding documents, `docs/ARCHITECTURE_GOVERNANCE.md`, `docs/TARGET_ARCHITECTURE.md`, and `docs/CONVERSATION_BEHAVIOR_CONTRACT.md`
**Research basis:** `docs/research/REMOTE_CHAT_ECOSYSTEM_REVIEW_2026-09-04.md` and `docs/research/REMOTE_CHAT_DISCORD_SDK_REVIEW_2026-09-08.md`

**Implementation evidence:** Slice 1 provides immutable typed request origins, exact origin-aware operation authority, a presentation-neutral service that owns real ordinary complete/stream Conversation turns and is used by Web, origin-bound local confirmations, and an application-level foreground/quiet coordinator composed above Web. Slice 2 adds the SDK-free transport port/fake, exact identity admission, archive-proven dedicated-chat reservation/binding, owner-private durable inbound/logical-reply/physical-chunk ledger, approved Remote Search/upcoming-reminder handlers, compare-and-swap CLI configuration and secret storage, durable generation fences, quiescent backup participation, restart reconciliation, and provable non-daemon shutdown. Slice 3 pins Hikari 2.6.0 behind the port, composes the connector into the normal Web application lifecycle, validates the exact application/bot/single private installation/owner/one-to-one DM before admission, maps Discord's 2,000-character limit into existing durable chunking, and publishes redacted live CLI/Settings status. Physical acceptance proved connection, exact-owner conversation, dedicated context, consent-approved structured weather retrieval/synthesis/attribution/delivery, reminder reads, denial of a prohibited mutation, restart continuity, self-termination persistence/no-reconnect/local re-enable, loopback Settings lifecycle, LAN read-only status, and privacy-safe operator output. The prior timeout and affirmative-as-question defects were corrected and passed live retest.

## 1. Architecture decision

Remote Chat V1 is a one-owner, one-to-one Discord text-DM client for normal Tori. The selected design is an in-process transport adapter:

```text
Discord DM
    |
DiscordAdapter                 Discord protocol only
    |
RemoteChannelPort              typed, replaceable transport boundary
    |
RemoteChatService              identity, ledger, remote policy, lifecycle
    |
shared ConversationTurnService
    |
current Conversation, capability routing, Memory context, Search,
provider/model, archive, authority, and failure behavior
```

Tori opens an outbound Discord Gateway connection. Discord exposes no public
Tori listener, remote administration UI, model endpoint, SSH service, reverse
proxy, tunnel, or firewall port. The existing local/LAN Settings UI may display
sanitized connector status, but only the direct host-loopback boundary may
change owner enablement.

The Discord SDK stays behind `DiscordAdapter`. It owns no Tori identity, prompt, model, Memory truth, capability routing, authority, confirmation, Conversation state, or user-visible failure semantics. Another transport must be replaceable by implementing the same port.

An isolated bridge is not selected. Under the same OS user it would add an authentication protocol, secret, replay handling, process supervisor, and failure domain without meaningful filesystem isolation. A genuinely sandboxed or separately privileged bridge may be reconsidered if a concrete threat justifies it.

Generic gateways are not selected: their agent, session, tool, channel, or multi-user semantics are broader than this contract and would form a second source of application truth.

## 2. Product boundary

V1 provides:

- session-explicit Remote Chat behind an administrator ceiling and saved local enablement: every process begins Off until a fresh local enable action;
- one configured Discord bot/application, private installation-guild context, and one configured owner user ID;
- one-to-one text DM only;
- one dedicated durable normal Tori conversation named `Remote Chat`;
- no change to the browser active chat;
- normal Tori identity, personality, provider/model, context controls, Conversation history, and relevant curated Memory context;
- current Search/weather behavior with current explicit-request and one-use Search-consent rules;
- read-only reminder/upcoming-schedule answers;
- ordinary capability/status discussion;
- exact-owner self-termination from the bound Discord DM; and
- an immediate local kill switch independent of Discord availability.

The exact V1 remote operation allowlist is:

| Typed operation | Allowed behavior |
|---|---|
| `conversation.reply` | Ordinary conversation in the dedicated chat. |
| `conversation.context.read_own` | Completed context belonging only to that chat. |
| `memory.context.retrieve` | Bounded relevant curated Memory through normal context planning; no inventory or mutation. |
| `search.read` | Current bounded Search/source retrieval under current consent and attribution rules. |
| `reminders.upcoming.read` | Bounded current/upcoming reminder projection; no task-state change. |
| `capabilities.describe_remote` | Non-sensitive capability and effective remote-status explanation. |
| `remote_chat.terminate_self` | Exact command disables and disconnects only this Remote Chat connector; it cannot enable or administer anything. |

No local operation becomes remote-safe merely because it is read-only. The allowlist contains application-owned typed identifiers, never phrases, URLs, commands, tools, or model labels.

`Terminate Discord connection now` is the only accepted natural form of the
seventh operation. Application code recognizes it deterministically before
provider execution, revalidates the current generation plus exact connector,
owner, dedicated chat, and durable one-to-one DM binding, durably sets owner
enablement off, and fences the old generation before stopping Discord. It is
not a general service-control or Settings operation. Model output cannot invoke
it, and only local administration can enable Remote Chat again. The generation
fence normally suppresses a final acknowledgement; durable disablement takes
priority over an unprovable send.

## 3. Explicitly blocked scope

Remote Chat blocks before provider, helper, executor, or mutation-service contact:

- `/run` and all shell execution;
- Coding Work/OpenCode operations and details;
- service control;
- backup, restore, checkpoint, archive repair, and maintenance;
- Settings/capability/provider/model/context/TTS/credential changes through Conversation;
- all Finance access;
- Knowledge contents, inventory, paths, retrieval, registration, and removal;
- Project details, context, associations, and mutations;
- host telemetry, paths, usernames, hostnames, LAN addresses, and system details;
- Memory listing, creation, correction, deletion, extraction, and other mutation;
- reminder/task/Planning/Scheduled Work mutation;
- local proposal inspection or confirmation;
- application/folder opening;
- arbitrary filesystem, Git, process, credential, or network authority; and
- every unclassified or mixed-effect capability operation.

Project context is not injected into Remote Chat even if a local Project association exists. Knowledge retrieval is not performed remotely. These narrower rules supersede the historical contract and deferred implementation.

Blocked actionable requests receive concise application-authored local-only guidance. They do not reach the model in a form that permits a false success claim, solicitation of sensitive action details, or invented substitute workflow.

## 4. Ownership boundaries

Tori core owns:

- Conversation and archive revision;
- identity, personality, context planning, and Memory policy;
- provider/profile/model selection and failure behavior;
- capability classification and operation identifiers;
- remote-origin policy and every authority decision;
- Search consent, evidence, provenance, and attribution;
- user-visible receipts/refusals;
- durable admission/delivery state;
- backup/shutdown coordination; and
- redacted local status.

`RemoteChannelPort` represents only start/stop, connection status, a normalized inbound envelope, an advertised bounded physical-message limit, initiation and awaited outcome of ordered outbound chunks to one verified destination, acknowledged/failed/ambiguous delivery, and suppression after disable. `begin_send` may perform reversible adapter preparation without holding the application fence. Immediately before irreversible external entry, the adapter must invoke the supplied narrow application authorizer; a successful return is the send linearization point, while rejection forbids the external invocation. Waiting for the initiated attempt's result remains separate so a later fence can preserve uncertainty honestly.

The inbound envelope contains bounded typed values only: transport, connector ID, external message/user/DM IDs, expected bot/application IDs, received timestamp, plain text, channel kind, and unsupported-content flags. Discord IDs remain metadata and never enter model context. Discord SDK objects never cross the port.

`DiscordAdapter` alone owns Gateway/REST connection, reconnect/resume, Discord decoding, channel-type checks, advertising the current verified platform limit, REST rate limiting, mention suppression, and Discord error normalization. The application core deterministically prepares and durably records physical chunks before delivery starts; the adapter cannot silently split or merge them.

## 5. Shared Conversation architecture

The deferred `RemoteConversationApplication` must not return. It duplicated capability routing and now contains stale Search, Memory, Planning, Finance, Project, and system behavior.

The presentation-neutral `ConversationTurnService` accepts explicit conversation ID/revision, original text, and immutable `RequestOrigin`; binds the authoritative session by origin kind plus conversation ID; owns the real ordinary complete/stream `ConversationSession` call; limits contextual retrieval by origin; resolves a conservative typed operation before provider execution; and shares one coordinator. Web calls it for provider-facing turns, while HTTP/NDJSON formatting, speech, browser state, archive presentation, local-only capability-handler choreography, and HTTP error mapping remain Web concerns. A Web active-chat rebind cannot replace the separate Remote Chat binding. A non-Web caller can run an allowed ordinary Tori turn directly without importing Web or supplying an execution callback. Slice 2 implements the explicit Remote Search/upcoming-reminder application handlers at this shared boundary rather than duplicating Web routing.

`RequestOrigin` contains kind (`local_web`, `local_cli`, or future `discord_remote`) and, for remote only, bounded connector, originating message, verified actor, and external conversation identifiers held outside model text. Origin is not inferred from wording and advisory/model output cannot alter it.

The existing `CapabilityRegistry` remains descriptive. Effective Remote Chat state is:

```text
capability configured
AND typed operation explicitly permitted for discord_remote
AND required implementation currently available
```

Model-facing capability awareness must describe that effective state, including that blocked local capabilities are unavailable from Remote Chat.

## 6. Authority and confirmation

The model may interpret or discuss intent but never grants authority. A deny-by-default origin policy checks typed operations before execution. Unknown, ambiguous, mixed-effect, slash-command-shaped, or prompt-injected operations remain blocked or clarify safely.

A remote `yes`/`confirm` cannot claim any local Web proposal. Proposal tokens and details are not exposed remotely.

The only V1 continuation is Search consent. It binds to the Remote Chat conversation, the exact immediately following durable admission sequence, normalized query and weather state, originating external message, configured connector/owner/DM, expiry, and exact later decision message. Any intervening ordinary turn consumes and invalidates the pending consent, including when an application-authored proposal did not advance provider history. Claiming it authorizes only `search.read`; it cannot confirm any mutation. The affirmation is authority only: after retrieval, the validated original request—not the affirmation—is the provider-facing synthesis question.

## 7. Identity and admission

Before content reaches archive, context, Memory retrieval, Search, or provider, Tori verifies:

1. administrator ceiling, durable local configuration, and current-process local session enablement;
2. current connector generation (not killed);
3. authenticated application and bot IDs match configuration;
4. the authenticated bot is present in the configured private installation guild at Ready time;
5. a new one-to-one DM, not guild/thread/forum/group DM/webhook/interaction/system event;
6. a human author, not bot/application/webhook;
7. exact configured owner user ID;
8. exact durable bound DM channel after first verified binding;
9. bounded valid text/metadata; and
10. external message ID not already admitted.

Names, nicknames, avatars, guild roles, email, text, and model judgment never establish identity. Unauthorized/unsupported events are ignored before content retention or provider contact. Only bounded aggregate non-content rejection diagnostics may persist.

V1 admits original message-create text only. Edits/deletes do not rewrite history. Attachments, embeds, forwarded snapshots, reactions, commands, components, polls, and voice are unsupported and not fetched or retained.

## 8. Administration and secret model

Effective operation requires three independent gates:

1. administrator ceiling in Tori configuration, portable default `false`;
2. owner-private enablement, default `false`; and
3. healthy credential/identity/chat/ledger prerequisites.

Credential storage or SDK installation never enables or connects.

Security-sensitive administration is hybrid:

- local CLI is the only interface for add/replace/clear token and Discord application/bot/owner/DM identity changes;
- administrator ceiling is local configuration only;
- local CLI enable/disable is authoritative;
- Settings shows only sanitized state to every accepted browser; and
- Settings On/Off is writable only from a direct IPv4-loopback request, inside an already-on ceiling and complete private configuration. Off uses the existing durable generation fence and stops the active connector. On reuses that connector when it already exists in the running composition; otherwise it reports that restart is required. A LAN request can never change enablement, raise the ceiling, or write credentials/IDs.

The CLI reads the token without echo; it is never a command-line argument. The token and IDs live in an owner-private record beneath `$XDG_CONFIG_HOME/tori/` (fallback `~/.config/tori/`), outside Git, runtime, transcript, Memory, model context, browser storage, logs, and backup.

The store uses absolute/private ancestors, descriptor-relative no-follow opens, exact owner/type/link checks, directory `0700`, file and persistent lock `0600`, bounded schema/size, kernel-locked compare-and-swap revision checks, monotonic generations, complete write + file `fsync`, atomic replace + directory `fsync`, and fail-closed preservation on unsafe paths. Reads expose only redacted status. Authority use holds a shared generation fence; configuration mutation holds the exclusive fence through comparison and verified publication.

Rotation/clear publishes a new disabled generation together with the replacement/cleared secret only after all older shared authority guards leave their irreversible boundaries. No later old-generation admission, archive mutation, or send initiation can start. The running core then terminalizes older ledger work and stops; a restart reconciles the same durable configuration fence before work can resume. Explicit re-enable does not advance or roll back that fence.

## 9. Lifecycle and kill switch

States are `Off`, `Connecting`, `Connected`, `Stopping`, and `Error`. `Connected` requires authenticated Ready plus verified bot/application identity.

The kill switch works locally without Discord. The exact owner-DM self-termination operation reaches the same authority-reducing configuration/generation fence but cannot raise authority or change configuration. Each first closes process admission, then publishes a durable disabled configuration generation under compare-and-swap authority and reconciles the ledger to that generation while holding the application fence. Every admission, archive publication/outbound creation, and send initiation holds the matching fence. It suppresses unsent chunks, converts already-started uncertain sends to `ambiguous`, awaits adapter closure, and proves worker/event-loop termination before reporting Off. A configuration fence remains authoritative even if ledger reconciliation is delayed by process death; restart must reconcile it before work resumes.

Late callbacks from an old generation cannot archive, execute, or deliver. Completed archived turns remain history; incomplete model output is not committed; accepted-but-unstarted inputs become cancelled; completed-but-unsent replies become suppressed and are not delivered after re-enable.

## 10. Dedicated conversation binding

V1 uses one normal conversation named `Remote Chat`, identified by durable ID, never label or browser active pointer.

Creation/binding is a crash-safe saga: the ledger first reserves a stable target chat ID, binding generation, and random archive provenance event ID; Conversation creates that exact ID with the exact provenance marker or verifies both already exist; the ledger then marks it bound. Startup repeats the same reservation rather than allocating a new ID. A matching label without the exact reservation marker is a conflict, never proof of ownership.

A missing/conflicting/deleted mapping enters Error and never attaches another chat. Provider/model/context remain normal durable chat state changed only locally. Remote Chat never follows a later browser selection and never silently falls back.

## 11. Durable inbound semantics

A separate owner-private SQLite ledger under runtime is created only by explicit Remote Chat initialization and participates in verified backup. It is not a second Conversation archive.

Each inbound record is unique by `(transport, connector_id, external_message_id)`, has immutable envelope hashes and monotonic local receipt order, and moves through `accepted`, `processing`, explicit `reconciliation_required`, `completed`, `failed`, or `cancelled`, followed where relevant by outbound state.

The first write occurs only after identity/channel/type/size checks. Duplicate IDs with identical immutable metadata converge. The same ID with different metadata is a security error. One worker processes FIFO. Gateway sequence is diagnostic; message ID plus local receipt order governs application idempotency/order.

Pending content is bounded. After Conversation commit and terminal delivery, duplicate message/reply bodies are cleared from the ledger under documented retention; IDs, states, hashes, timestamps, and archive correlation remain.

Restart may resume current-generation `accepted`. `processing` or `reconciliation_required` reconciles against the reserved conversation, its provenance marker, exact base revision, and a deterministic admitted-turn archive event. It is never blindly regenerated: a verified completed turn proceeds to delivery, otherwise it becomes an interrupted failure asking the user to resend. Terminal records never duplicate archive turns.

## 12. Outbound semantics

Tori bounds one logical Remote reply at 4,000 characters as a transport-neutral application privacy, storage, and queue limit. Before archive publication or any delivery claim, the core deterministically creates non-empty ordered physical chunks no larger than the adapter's verified advertised limit. The ledger stores the logical reply separately from each chunk identity, order, hash, text, external acknowledgement ID, and `pending`, `sending`, `delivered_acknowledged`, `ambiguous`, `failed`, or `suppressed` state. This 4,000-character application bound is not a claim about Discord's per-message limit.

Destination comes only from the verified connector/DM binding; model text cannot select it. Every send explicitly disables user, role, everyone, and reply mentions. V1 sends plain text only.

Each logical reply and physical chunk has a deterministic application request ID; Slice 3 may map a chunk ID to a Discord nonce only after SDK/API support is proven. A returned Discord message ID acknowledges that chunk only. Acknowledged chunks are never resent. Reversible `begin_send` preparation occurs before the adapter calls its Tori-owned entry authorizer. That callback takes the application fence, revalidates closing and connector generation, and atomically performs the durable `pending`-to-`sending` claim. Rejection prevents external invocation; successful authorization is the irreversible linearization point and `begin_send` may return only after it. Timeout/disconnect/exception after authorization without acknowledgement makes that chunk ambiguous and suppresses its unsent tail. A crash after one acknowledged chunk and during a later chunk preserves both facts. Tori promises at-most-once application admission, not exactly-once network delivery.

Rate limits use SDK/API bucket and retry metadata with bounded retry/backoff. Authentication/permission failure is terminal. No Discord failure triggers transport or model fallback.

## 13. Privacy

Enablement discloses owner DM text, Tori reply text, and communication metadata to Discord. Discord is not local storage and its retention/account policies apply.

Relevant curated Memory may shape answers through normal bounded context, but Memory inventory/export/mutation remains blocked. Finance, Knowledge, Projects, host details, and unrelated conversations remain blocked to limit disclosure.

Discord identifiers/ledger state are not model context. Token is excluded from backup. Non-secret ledger plus dedicated chat are backed up only under quiescence so restore preserves dedupe; restore never auto-enables/connects.

## 14. Shared operation, backup, and shutdown

Remote Chat justifies extracting Web's private operation gate into an application `OperationCoordinator`, not adding another generation engine.

The implemented coordinator owns the current foreground generation boundary and quiet delivery reconciliation. Slice 2's Remote lifecycle uses that same instance without routing through Web. Its bounded FIFO targets the explicit dedicated chat and never changes browser active state.

Verified backup acquires the barrier, pauses Remote admission without acknowledging application work, boundedly drains generation/sends or fails busy, flushes/closes coordinated stores, includes non-secret ledger/chat and excludes secret, verifies before publication, then resumes only if the same enabled connector generation remains. No unverified backup publishes.

Shutdown closes admission, cancels/drains generation, persists terminal/ambiguous delivery, suppresses new sends, closes and awaits adapter, proves no owned worker remains, clears every process-local Remote Search/weather continuation, and verifies no current-generation `processing`, `reconciliation_required`, or `sending` state remains before success. An unprovable terminalization, durable inspection, cleanup, or worker timeout remains Error; abandoning a daemon thread after timeout is not shutdown.

## 15. Threat controls

| Threat | Required control |
|---|---|
| Stolen token | Password-equivalent handling; local-only rotation/clear; stop on auth failure; explicit Discord reset recovery. |
| Spoofed identity | Exact authenticated snowflake IDs; no names/roles/text as identity. |
| Wrong application/install context | Verify application ID, bot user ID, and private installation-guild membership before Connected; reject every guild message despite that membership. |
| Guild/group mistaken for DM | Exact one-to-one DM event/channel type and no guild context. |
| Malformed/oversized event | Typed bounded normalization before persistence. |
| Replay/reconnect duplicate | Unique ID admission before archive/provider; metadata mismatch is security failure. |
| Out-of-order events | Durable local FIFO; never model text/edit timestamps. |
| Ambiguous send | Durable sending state/nonce where supported; no blind resend. |
| Rate limit/outage | SDK/API retry metadata, bounded retries, failure isolation. |
| Crash during turn | Archive/ledger correlation; no blind regeneration. |
| Kill during work | Connector-generation fence through commit/delivery. |
| Prompt injection | Typed origin-aware application allowlist before executor. |
| Remote confirms local proposal | Disjoint origin/token; only exact Search consent claimable. |
| False action claim | Actionable blocks before model; application-authored receipts/refusals. |
| Sensitive leakage | Narrow allowlist; bounded errors/status; forbidden domains intercepted. |
| Token leakage | Separate local secret; no Web credential API; redaction and backup exclusion tests. |
| LAN changes authority | Local-only ceiling/credentials/IDs; LAN cannot change enablement. |
| Symlink/hardlink attack | No-follow ancestor/destination and exact owner/mode/type/link checks. |
| Backup during mutation | Shared maintenance barrier and Remote participant. |
| Shutdown with worker | Await/prove closure or fail lifecycle verification. |
| SDK compromise | Minimal pinned dependency, no extras/command framework, narrow adapter. Real OS-isolated bridge remains an option if justified. |

## 16. Discord library gate

The refreshed review selected and pinned **Hikari 2.6.0 (MIT)**. It supports Tori's Python 3.12 runtime, is typed and asyncio-based, distinguishes DM create events, exposes explicit `start`/`close`/`join` lifecycle and rate-limit controls, and supports send nonce. The adapter requests only `DM_MESSAGES`, disables member chunking and SDK caching, and installs no command or voice extra.

`discord.py` 2.7.1 was also reviewed and remains capable, MIT, async, rate-limit aware, and reconnect capable. It was not implemented because Hikari's distinct `DMMessageCreateEvent` and narrower explicit lifecycle fit this port more directly. There is no fallback SDK or second production adapter.

The detailed source and dependency record is `docs/research/REMOTE_CHAT_DISCORD_SDK_REVIEW_2026-09-08.md`. Hikari objects remain behind the port; Tori core retains all identity, replay, authority, persistence, and delivery meaning.

## 17. Future outbound seam

The port may later accept a Tori-owned `OutboundRemoteMessage` containing connector ID, preverified destination binding, application message ID, bounded text, and category. Only a separately approved Tori initiative/notification policy may create it. The adapter never decides when Tori speaks.

V1 uses outbound only for replies. Check-ins, morning weather, project prompts, summaries, news, and Scheduled Work/reminder delivery require a later authority/privacy contract.

## 18. Failure contract

| Condition | Result |
|---|---|
| Invalid/revoked token | Error, stop admission, no token detail. |
| Unexpected bot/application | Error and close before content admission. |
| Unauthorized sender/channel | Ignore before retention/provider; aggregate diagnostic only. |
| Provider failure | Truthful failure if safe to deliver; no fallback/incomplete history. |
| Search failure | Preserve current distinct backend/no-evidence/synthesis/attribution errors. |
| Blocked capability | Application-authored local-only boundary. |
| Queue/input limit | Reject before provider; never merge/silent truncate. |
| Discord outage | Connecting/Error with bounded retry; local Web healthy. |
| Ambiguous send | Retain ambiguous; no blind resend. |
| Missing/conflicting chat | Error; no active-chat attachment. |
| Unsafe secret/ledger path | Fail closed and preserve evidence. |
| Backup not quiescent | No publication. |
| Shutdown unproven | Remain Error/non-Off and fail verification. |

## 19. Acceptance contract

Automated tests must prove:

- fake and selected-SDK transport contracts;
- default-off/ceiling/enable truth table and kill-switch generation fence;
- local-only secret/identity administration and adversarial secret-file safety;
- LAN cannot write credentials/IDs/ceiling or change enablement;
- exact bot/application/owner/DM validation before retention/provider;
- unauthorized/guild/group/bot/webhook/malformed/oversized rejection;
- dedupe, metadata mismatch, FIFO, queue limits, reconnect replay, out-of-order handling;
- crash-safe single chat binding and browser active-chat independence;
- shared Web/Remote turn service and one coordinator;
- effective capability awareness plus the exact seven-operation allowlist,
  including only the authority-reducing owner-DM self-termination addition;
- all section 3 blocks before provider/executor/mutation;
- remote `yes` cannot claim local proposals;
- Search consent binds query/conversation/origin/message and preserves weather state;
- Memory context works while Memory inventory/mutation stays blocked;
- restart never duplicates generation/archive;
- chunking/order/mention suppression/acknowledgement/ambiguity/no-blind-resend;
- disable never sends suppressed old replies;
- backup secret exclusion and coherent quiescent ledger/chat snapshot;
- provable worker/event-loop shutdown;
- no credential/ID leakage to model/transcript/Memory/Web/log/backup;
- Discord failure isolation from local services; and
- a second fake transport works without core changes.

Separately authorized real Discord acceptance must cover private bot setup, default-off, exact owner DM, rejection of guild/group/second-user/bot/webhook/unsupported/duplicate traffic, normal Tori identity/provider/context, browser independence, Memory-informed conversation, Search consent/weather/attribution/failures, upcoming reads, capability discussion, representative forbidden actions, Unicode chunking/mention suppression/rate limits/reconnect/ambiguity, kill switch during generation/send/outage, restart at every durable state, backup coordination, clean shutdown, and token rotation/revocation/clear.

No real token, identifier, or private message belongs in fixtures, screenshots, reports, logs, or commits.

## 20. Implementation slices

1. **Shared application boundary and origin policy.** Extract `ConversationTurnService` and `OperationCoordinator`; add typed origin/effective policy; prove Web unchanged with fake Remote calls. No SDK/schema. Use **Sol, high reasoning** for cross-cutting authority correctness.
2. **Durable Remote core.** Implemented for review: fake port, chat binding, ledger, kill switch, CLI/secret store, backup/shutdown participation, and adversarial tests. No Discord SDK or connectivity.
3. **Discord adapter.** Implemented offline: reviewed and pinned Hikari 2.6.0; added DM normalization, reconnect state, bounded REST behavior, advertised 2,000-character physical limit, nonce/ack mapping, mention suppression, and lifecycle contract tests. Core-owned durable chunking is unchanged.
4. **Local status and real acceptance.** Redacted CLI status and production lifecycle composition are implemented. Secure local CLI remains the only setup/enable surface; the exact owner-DM command may only disable its own connector. No Web credential or Remote Chat enable UI was added. Real Discord acceptance is the remaining boundary.

Stop if a slice requires broader remote authority, a public listener, SDK objects in core, a second Conversation engine, browser credential entry, weaker backup/secrets, or proactive behavior.

## 21. Deferred

V1 excludes guild/group/multiple users, account linking, attachments/media/voice/TTS, embeds/buttons/reactions/slash commands, streaming partial replies, multiple remote chats, remote mutation/confirmation, every blocked information domain, arbitrary destinations, proactive behavior, Scheduled Work/reminder delivery, other transports, and bridge-process isolation.

## 22. Completion definition

Remote Chat V1 is complete only after automated and real-Discord acceptance prove: replaceable transport; no public inbound Tori listener; exact one-owner DM; default-off ceiling and independent kill switch; one durable browser-independent chat; shared current orchestration; typed origin-aware deny-by-default authority; only section 2 operations; no remote local-proposal confirmation; idempotent admission and truthful delivery ambiguity; quiescent backup/shutdown; owner-private secrets outside Web/model/archive/Memory/runtime/backup; and no proactive/deferred feature represented as implemented.
