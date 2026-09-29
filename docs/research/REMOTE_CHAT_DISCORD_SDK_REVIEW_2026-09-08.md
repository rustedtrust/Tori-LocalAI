# Remote Chat Discord SDK review — 2026-09-08

**Decision:** Pin `hikari==2.6.0` for the one production Discord adapter.
This was an implementation dependency decision; Remote Chat V1 subsequently
passed physical human acceptance.

## Sources checked

- Hikari [2.6.0 release](https://github.com/hikari-py/hikari/releases/tag/2.6.0),
  [PyPI metadata](https://pypi.org/project/hikari/),
  [GatewayBot lifecycle](https://docs.hikari-py.dev/en/stable/reference/hikari/impl/gateway_bot/),
  and [DM message events](https://docs.hikari-py.dev/en/stable/reference/hikari/events/message_events/).
- discord.py [2.7.1 release/PyPI metadata](https://pypi.org/project/discord.py/),
  [client API](https://discordpy.readthedocs.io/en/stable/api.html), and
  [gateway-intent guide](https://discordpy.readthedocs.io/en/stable/intents.html).
- Discord's authoritative [Gateway and intents](https://docs.discord.com/developers/events/gateway),
  [message resource](https://docs.discord.com/developers/resources/message),
  and [application setup](https://docs.discord.com/developers/quick-start/getting-started)
  documentation.

## Current upstream comparison

| Review point | Hikari 2.6.0 | discord.py 2.7.1 |
|---|---|---|
| Current release checked | 2.6.0, 2026-08-19 | 2.7.1, 2026-03-03 |
| License | MIT | MIT |
| Supported Python | `>=3.10,<3.15` | `>=3.8` |
| Gateway lifecycle | Awaitable `GatewayBot.start()`, `close()`, and `join()`; start returns after shards are ready | Awaitable client start/close with reconnect support; `run()` is a convenience runner |
| DM boundary | A distinct `DMMessageCreateEvent` carries a complete message | General `on_message`/message channel objects require explicit DM/guild/group classification |
| Commands required | No | No, although command extensions ship in the distribution |
| Base dependency surface | `aiohttp`, `attrs`, `colorlog`, `multidict` | `aiohttp` (`audioop-lts` on Python 3.13+) |
| Outbound correlation | 2.6.0 restored `create_message(..., nonce=...)` | Message send APIs are mature, but no advantage for Tori's existing port was found |

Hikari's transitive installation in Tori's Python 3.12 environment consists of
`aiohttp` plus its HTTP support packages, `attrs`, `colorlog`, and `multidict`.
No voice or command-framework extra is installed. Both candidates are capable;
neither owns Tori's replay, authority, archive, or delivery truth.

The resolved environment was inventoried after installation: Hikari 2.6.0
(MIT), aiohttp 3.14.3 (Apache-2.0 and MIT), attrs 26.1.0 (MIT), colorlog 6.12.0
(MIT), multidict 6.7.1 (Apache-2.0), aiohappyeyeballs 2.7.1 (PSF-2.0), aiosignal
1.4.0 (Apache-2.0), frozenlist 1.8.0 (Apache-2.0), propcache 0.5.2
(Apache-2.0), typing_extensions 4.16.0 (PSF-2.0), and yarl 1.24.5
(Apache-2.0). The review found no reason to add either SDK's voice/speed/server
extras. Public upstream release/advisory searches found no Hikari 2.6.0 advisory;
this is a point-in-time review, not a permanent vulnerability guarantee.

## Discord protocol conclusions

Tori requests only the standard `DIRECT_MESSAGES` Gateway intent. That intent
carries DM `MESSAGE_CREATE`; Discord expressly supplies message content in DMs
with the app even when the privileged `MESSAGE_CONTENT` intent is absent. Tori
does not request Guilds, Guild Messages, Members, Presences, reactions, typing,
or Message Content.

Discord text messages are limited to 2,000 characters, so the adapter advertises
2,000 as its physical limit beneath Tori's existing 4,000-character logical
reply limit. Every send disables all mentions. A deterministic application
request hash supplies a maximum-25-character nonce. Tori acknowledges a chunk
only when the REST response contains a valid Discord message ID and the exact
nonce; otherwise its already-authorized send remains ambiguous.

## Selection rationale

Hikari best fits the already-accepted `RemoteChannelPort`: it exposes a specific
DM-create event, a small explicit asyncio lifecycle, typed identities, explicit
Gateway intents, REST message results, and no required commands layer. The
adapter can turn off member chunking and its cache, bound HTTP retry/rate-limit
waiting, and keep every SDK object below the port. This is a fit decision, not a
popularity judgment.

The production adapter therefore uses exactly `hikari==2.6.0`. It does not
implement discord.py as a fallback and does not add a second transport.

## Security and acceptance consequences

Only an official bot application token is valid; Discord user tokens/self-bots
are prohibited. The bot must be private and installed in exactly one owner-held
private test server so startup can verify the configured application, bot user,
and installation guild without member enumeration. Guild messages remain
rejected. The owner opens a one-to-one DM with that bot; group DMs and
user-installed command semantics are outside V1.

Physical Discord acceptance subsequently passed. The repository state is
**Remote Chat V1 complete**; this review remains a point-in-time SDK decision.
