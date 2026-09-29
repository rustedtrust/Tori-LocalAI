# Remote Chat ecosystem review — 2026-09-04

**Status:** Research evidence for `docs/REMOTE_CHAT_V1_CONTRACT.md`; not implementation authorization

## Scope

This review asks whether maintained open-source software can carry one authorized Discord text DM into Tori without taking ownership of Tori's identity, model, Conversation, Memory, tools, permissions, or canonical state. The best fit is the smallest maintained transport boundary, not the candidate with the most agent features.

## Candidates

| Candidate | Current upstream evidence | License | Fit and decision |
|---|---|---|---|
| Gatehook | Rust/Serenity Gateway-to-HTTP bridge with direct/guild filters and response actions. Repository archived 2026-05-24. | MIT | Transport-oriented, but `DIRECT` includes one-to-one and group DMs, it adds a webhook/action protocol, and it is archived. Reject; concepts only. |
| Discord Agent Gateway | Young FastAPI/SQLite shared-channel gateway with agent cursors/tokens, polling/ack, webhook posting, attachments, and admin API. Its README says it does not sandbox agents. Upstream showed two stars and no clearly discoverable license. | Unverified | Built for a guild channel, threads, and multiple agent/human peers. Reject for product/authority mismatch plus licensing and maturity uncertainty. |
| OpenClaw Discord | Active feature-rich multi-channel agent gateway: DM/guild policy, commands, actions, streaming, attachments, activities, exec approvals, sessions, tools, and its own control plane. | MIT | Useful comparative evidence, but transport is inseparable from a second agent/session/tool platform. Do not integrate. |
| Vexillon MIRA | Active self-hosted Rust assistant with built-in Discord and a signed HTTP channel-provider concept. Core also owns agents, Memory/Knowledge, tools, automation, policy, models, and UI. | AGPL-3.0-or-later | Thoughtful channel concepts, but a second assistant/control plane and large runtime. Concept reference only. |
| Matterbridge | Broad Go bridge for Discord and many protocols with edits/deletes, attachments, threading, spoofing, and API. Latest stable v1.26.0 is dated 2023-01-29. | Apache-2.0 | Channel-to-channel bridge, not one-owner DM; broad external binary/configuration surface and stale stable release. Reject. |
| `discord.py` | Production-stable async wrapper. PyPI 2.7.1 released 2026-03-03; reconnecting client, close, DM types, rate-limit handling, mention controls. Deferred Tori used it. | MIT | Good direct-adapter fit and useful historical test evidence. Acceptable fallback; old adapter must not be copied unchanged. |
| Hikari | Production-stable typed asyncio Discord v10 Gateway/REST wrapper. 2.6.0 released 2026-08-19; Python 3.10–3.14, distinct DM events, explicit lifecycle, rate limits, current message nonce support. | MIT | Best narrow-adapter fit. Preferred implementation spike, subject to fresh pin/transitive/security/license review. |

No additional maintained gateway found in this review was clearly better for Tori than a direct SDK adapter. Other current agent gateways likewise combine transport with their own models, tools, Memory, sessions, automation, and control plane.

### Transport details and unresolved evidence

- **Gatehook:** accepts direct-message events and can return Discord actions through an HTTP response. It exposes configurable event/body/action limits and sender-class filters. Its documented direct context combines one-to-one and group DMs, outbound text is truncated at 2,000 characters, and application shutdown guarantees are not sufficiently documented for Tori's gate. Serenity likely supplies lower-level reconnect/rate handling, but Tori must not assume that without implementation-time verification. Archived status is decisive.
- **Discord Agent Gateway:** persists a monotonic shared-room stream, gives each agent an HTTP bearer token/cursor, and supports inbox/post/ack plus attachment proxy and admin APIs. It watches a configured guild channel and threads, not an owner DM; identity filtering is room/registration oriented. The README warns that tool authority/sandboxing remains the agent's responsibility. Reconnect, ambiguous-send, message-limit, and shutdown guarantees were not sufficiently specified in the reviewed upstream material. Even if technically repairable, its extra FastAPI/SQLite/webhook/admin dependencies and unclear license rule it out.
- **OpenClaw:** supports DMs, allowlists, outbound replies/proactive messages, rate/lifecycle handling, configurable 2,000-character chunking, and extensive channel status. It also carries commands, actions, attachments, streaming, activities, exec approvals, session/history routing, tools, and configuration writes. Those agent/control semantics are intentionally inseparable from its channel implementation, so it is an architecture reference rather than a transport dependency.
- **MIRA:** documents per-user Discord bots, Gateway `MESSAGE_CREATE`, per-channel conversations, REST replies, paragraph-aware 2,000-codepoint chunks, proactive delivery, and an external signed-HTTP channel-provider protocol. Its channel layer is embedded in a large multi-user assistant with its own auth, agent loop, Memory, tools, automation, models, and policy. Its security ideas are useful, but importing the implementation would also introduce AGPL and a second application authority.
- **Matterbridge:** handles outbound/inbound bridge delivery, many protocols, files, edits/deletes, threads, usernames, avatars, and an API. Its Discord setup is server/channel oriented and its documentation does not establish Tori-grade one-owner DM admission, application idempotency, ambiguous send, or shutdown guarantees. The last stable release date makes fresh security compatibility uncertain.
- **`discord.py`:** provides one-to-one DM channel types, async Gateway connection with reconnect, REST sending, rate-limit handling, mention suppression, and async close. It does not supply Tori's owner policy, ledger, crash reconciliation, or delivery truthfulness; those remain application responsibilities. The base package is sufficient—voice and command extensions are unnecessary.
- **Hikari:** provides a distinct `DMMessageCreateEvent`, typed Gateway/REST APIs, reconnect-aware Gateway lifecycle, REST bucket/global rate limiting, explicit close semantics, and current nonce support. It likewise does not own Tori idempotency or authority. The base Gateway client is sufficient; no command framework, interaction server, speed extras, or public listener is required.

## Primary sources

- Gatehook: <https://github.com/a24k/gatehook>
- Discord Agent Gateway: <https://github.com/caesarnine/discord-agent-gateway>
- OpenClaw Discord: <https://github.com/openclaw/openclaw/blob/main/docs/channels/discord.md>
- OpenClaw license: <https://github.com/openclaw/openclaw/blob/main/LICENSE>
- Vexillon MIRA: <https://github.com/Vexillon-ai/MIRA>
- MIRA channels: <https://github.com/Vexillon-ai/MIRA/blob/main/mira-docs/features.md>
- Matterbridge: <https://github.com/42wim/matterbridge>
- Matterbridge releases: <https://github.com/42wim/matterbridge/releases>
- Matterbridge license: <https://github.com/42wim/matterbridge/blob/master/LICENSE>
- `discord.py`: <https://github.com/Rapptz/discord.py>
- `discord.py` release metadata: <https://pypi.org/project/discord.py/>
- `discord.py` lifecycle: <https://discordpy.readthedocs.io/en/stable/api.html>
- Hikari: <https://github.com/hikari-py/hikari>
- Hikari release metadata: <https://pypi.org/project/hikari/>
- Hikari Gateway lifecycle: <https://docs.hikari-py.dev/en/stable/reference/hikari/impl/gateway_bot/>
- Hikari 2.6.0: <https://github.com/hikari-py/hikari/releases/tag/2.6.0>
- Discord Gateway/resume/intents: <https://docs.discord.com/developers/events/gateway>
- Discord messages, limits, nonce, mentions: <https://docs.discord.com/developers/resources/message>
- Discord REST rate limits: <https://docs.discord.com/developers/topics/rate-limits>

## `discord.py` versus Hikari

| Area | `discord.py` 2.7.1 | Hikari 2.6.0 | Consequence |
|---|---|---|---|
| Maintenance | Current 2026 stable release; large mature ecosystem. | More recent 2026 stable release; active typed project. | Both pass basic maintenance review. |
| Python | Python 3.8+ documented. | Python 3.10–3.14 documented. | Both cover current Tori; recheck exact support at implementation. |
| Gateway | `Client.start(..., reconnect=True)` and async `close()`. | Explicit `GatewayBot` start/run/close and reconnect-aware shard lifecycle. | Both support outbound-only connection. |
| DM boundary | `DMChannel` checks; group/guild separately rejected. | Explicit `DMMessageCreateEvent`; group/guild separately rejected. | Hikari gives the clearer typed boundary. |
| Rate limits | Advertises proper rate-limit handling. | Explicit REST bucket/global-limit controls and bounded max wait. | Tori still owns bounded retry and status. |
| Idempotency | Inbound Discord IDs; outbound nonce must be checked for the chosen call. | 2.6.0 restored `create_message` nonce support. | Hikari has stronger current evidence for the request-ID seam; nonce is not exactly-once. |
| Mentions | Global/per-send `AllowedMentions.none()`. | Per-send suppression controls. | Explicitly suppress all classes regardless of defaults. |
| Shutdown | Async close; old Tori wrapper did not prove termination. | Explicit close/run; docs cover owned HTTP shutdown. | Either adapter must await and prove closure. |
| Dependencies | aiohttp-based; voice extra unnecessary. | aiohttp-based; speedups/command framework unnecessary. | Install base text package only and audit/pin transitives. |
| Testability | Mature; historical Tori tests are useful evidence. | Typed events and narrow Gateway/REST APIs suit adapter tests. | Hikari preferred; fake-port tests prove modularity. |

Hikari is a recommendation, not authorization. A small spike must prove connection, identity checks, DM-only admission, reconnect, rate-limit normalization, nonce/message acknowledgement, and provable shutdown.

## Platform constraints

- Gateway Resume can replay missed events; SDK reconnect does not replace application dedupe.
- Message/channel/author snowflakes are stable identity evidence; names are not.
- DM content is currently an exception to broad privileged Message Content restrictions, but exact portal/intents must be physically verified.
- Normal content is limited to 2,000 characters; Tori must split transport output while archiving one reply.
- default `allowed_mentions` behavior can notify users/roles/everyone; Tori must explicitly disable it.
- nonce can help verify/deduplicate recent sends but does not eliminate ambiguous network outcomes.
- REST limits are dynamic; follow returned bucket/retry metadata instead of hard-coding rates.

## Architecture comparison

### A. In-process adapter — selected

Least code, secrets, state, and lifecycle; no new local listener/auth protocol; easiest integration with shared Conversation, backup, and shutdown. Its supply-chain risk is mitigated by a pinned minimal SDK, no voice/command extras, narrow adapter, least intents, and no SDK objects in core.

### B. Isolated bridge — deferred

A same-user process provides little containment but adds IPC authentication, replay state, supervision, compatibility, and two-sided shutdown. If later justified, use real OS isolation; bridge owns only Discord token/protocol; Tori owns ledger/authority; prefer an owner-private Unix socket with peer checks. For TCP, numeric loopback plus rotating HMAC, body digest, timestamp window, unique request IDs, constant-time verification, and replay ledger are mandatory. No bridge model, tools, Memory, admin API, or autonomous policy.

### C. Generic gateway — rejected

Gatehook is archived; Discord Agent Gateway targets shared channels and has license uncertainty; Matterbridge is broad/stale; OpenClaw and MIRA own agent/session/tool semantics. Each requires more boundary code while preserving less Tori ownership than a direct SDK.

## Historical Tori branch disposition

Useful concepts from `deferred/remote-chat-v1`:

- transport-neutral envelope/port;
- exact ID and DM-only rejection tests;
- separate SQLite admission/delivery ledger;
- message-ID dedupe and ambiguous delivery;
- atomic no-follow owner-private secret-store mechanics;
- deterministic chunks and mention suppression; and
- fake-adapter lifecycle/security tests.

Do not port as-is:

- stale `RemoteConversationApplication`;
- broad read allowlist;
- LAN Web token/identity/enable APIs;
- daemon-thread shutdown that did not prove termination;
- inbound-cached outbound channel state;
- random chat creation followed by separate binding;
- lifecycle outside current backup coordination; or
- old requirements/docs/UI changes wholesale.

## Implementation-time research gate

Before adding a package: recheck latest stable/Python support, release notes and security advisories, exact transitive licenses/security, hashes and pin/update policy, least Discord scopes/intents with a private bot, DM content without guild-message privilege, outbound nonce/ack ambiguity under disconnect, and clean shutdown with no worker/task/socket.

No candidate code or dependency was installed, copied, or incorporated by this research.
