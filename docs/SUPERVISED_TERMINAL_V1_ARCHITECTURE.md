# Supervised Terminal V1 architecture

**Status:** V1 implementation and Slice 5 security/acceptance audit complete. Remote terminal access and stronger hard-crash containment remain future work.

## Goals and boundary

Tori may eventually request essentially any host-user command, but every Tori-originated request passes through `USER INTENT -> TORI EXECUTION REQUEST -> POLICY -> APPROVAL IF REQUIRED -> EXECUTION GRANT -> TERMINAL BROKER -> OS`. The user owns editable policy. Slice 1 supplies request identity, policy evaluation and management, and one-use grants. It does not grant a model an unrestricted shell tool, start a terminal service, or change the accepted fixed capability paths.

The former `/run COMMAND` path used a separate exact-confirmation Bubblewrap runner. The loopback browser path now enters the common policy, proposal, one-use grant, and PTY broker. The CLI `/run` command is retired and does not launch a process. System capabilities separately use fixed executable vectors for NVIDIA status, desktop apps, and confirmed Ollama/Radicale service control. Delegated Work has its own durable workspace authority envelope, authorization digest, cancellation directive, receipt ledger, and Bubblewrap supervisor. These specialized contracts remain operational while the general terminal is built. The Slice 2 broker consumes the one policy authority for generalized Tori-originated commands; fixed capability adapters can retain their stricter argument constraints and confirmation requirements. A fixed capability is not a blanket whitelist for its executable name. In particular, the trusted, confirmed Ollama sudo helper is not permission for arbitrary `sudo`.

The execution-path audit also found fixed, non-general subprocess adapters for
MCP stdio, Research and its network helper, media inspection, RealtimeSTT,
OpenCode bootstrap/transport/readiness, and Verified Restore. Local slash
commands such as `/save` and `/remember` are application operations, not OS
command authorization. None of these fixed adapters gives a model a general
host shell. Their capability-specific authority remains in force; migrating
them to a common broker is a separate compatibility review, not an implicit
grant to run their executable with arbitrary arguments.

## Threat model and trust boundaries

Webpages, search results, repository files, terminal output, retrieved documents, model text, and worker events are untrusted data. They cannot create a grant or approve an execution. A command denylist is advisory policy, not kernel containment: Python, a shell, a compiler, or another arbitrary-code vehicle can reproduce a forbidden effect. The model never receives the broker's raw spawn primitive. The application creates a typed execution request from a user-authorized conversation action; policy decides it; the application records the human confirmation when required; a short-lived, single-use grant is consumed at the broker boundary. Every subsequent command arising after output requires a fresh request and decision.

The policy is for **Tori-originated execution**. A browser-session owner's keystrokes after taking direct control of a terminal are human terminal input, not Tori execution requests, and do not pass through the whitelist/blacklist evaluator. They pass directly from the attached browser to the broker's PTY. Take Control revokes any Tori terminal-input lease; Tori and the human cannot inject concurrently. Releasing control is deliberate. V1 currently provides no arbitrary model-driven stdin.

## Request identity and matching

A request records the original command text, a conservative shell lexical view of executable and argv when available, shell/control-operator and opaque-expansion metadata, exact absolute working directory, `HOST_USER` or `PROJECT_SANDBOX` scope, and requested environment metadata. The grant separately binds owner/session identity. Exact policy matchers bind the command text, cwd, scope, and environment-request digest. Whitespace, quoting, control operators, redirection, and appended commands remain material. A lexical `argv` is explanatory only; shell parsing is not equivalent to execution parsing. Unparseable commands remain ask-only. There is no executable-name prefix, substring, or implicit `git`/`python` family whitelist. An `nvidia-smi` substring in a larger command matches nothing.

V1 policy rules use only structured exact request matchers. Rule provenance distinguishes user rules from imported compatibility rules and application high-risk rules. A rule has an enabled state and timestamps. A rule that changes its matcher or class must pass the same service validation as creation. Missing or malformed storage fails closed; invalid individual rows cannot become whitelist authority.

## Four outcomes

Evaluation precedence is `BLACKLIST > ALWAYS_ASK > WHITELIST > DEFAULT_ASK`, even for contradictory stored rows. BLACKLIST rejects without a Run Anyway option. The user must edit/remove that rule through policy management first. ALWAYS_ASK requires a new explicit approval for each execution and cannot be whitelisted while it applies. WHITELIST permits prompt-free grant issuance. DEFAULT_ASK applies to everything else. Policy explanations include the deciding rule and reason; default is identified separately.

The initial application high-risk Always Ask classifier covers exact `sudo`/`su` executable requests; leading inline environment assignments; command-launching wrappers `env`, `xargs`, `find`, `nohup`, `timeout`, `command`, `exec`, `builtin`, `eval`, `source`, `time`, `.` and `!`; any direct `sh`, `bash`, `dash`, `zsh`, `fish`, or `ksh` invocation, including `-c`; any direct Python/Node/Perl/Ruby/PHP invocation, including eval and mutable script forms; obvious destructive filesystem/storage tools and forms (`rm`, `shred`, `mkfs*`, `wipefs`, `dd`, `fdisk`, `parted`, `sfdisk`); package/service/mount tools (`apt`, `apt-get`, `dnf`, `pacman`, `pip`, `pip3`, `npm`, `systemctl`, `mount`, `umount`); shell control/redirection and command substitution; and text-to-shell execution with a pipeline. These are conservative prompt triggers, not a complete effect analyzer. They are evaluated before user whitelist rules. The classifier prevents a whitelist from silently removing approval for these forms. An application-owned fixed capability with a narrower existing approval remains separate until an adapter can prove it does not widen authority.

## One-use grant

The Slice 1 grant record stores a digest of a random token, the request identity digest, an owner/session digest, scope, expiry, approval provenance, and a pending/consumed state. The raw token is returned once to the trusted caller and is not stored. Issuance rejects BLACKLIST and rejects ask outcomes without explicit application-owned approval. Consumption atomically marks pending as consumed before launch, rejects replay/expiry/changed command/arguments/cwd/scope/environment/owner, and re-evaluates current policy so a later blacklist or Always Ask edit cannot be bypassed by an older whitelist grant. A consumed grant that fails to launch is not reusable. Crash recovery treats an uncertain consumption as spent.

The existing ActionDispatcher's process-local token is a compatibility confirmation mechanism, not a substitute for the broker grant. Delegated Work's durable authority digest, workspace identity checks, process ownership, cancellation, and receipt patterns are reused conceptually. Its work authorization cannot be repurposed as a general terminal grant because it binds a coding objective and adapter-specific lifecycle.

## Scopes and environment

`HOST_USER` executes as the ordinary Tori/user account against the real host. It is deliberately high impact and receives no privileged daemon or special sudo API. `sudo` remains an ordinary command subject to policy and later human terminal interaction. `PROJECT_SANDBOX` uses the existing native Bubblewrap pattern: exact workspace binding, no default network, protected runtime masking, no unrelated project mount, and fail-closed availability. A cwd is context, never containment.

The broker will construct an allowlisted child environment rather than inheriting `os.environ`. Expected basics are a controlled `PATH`, appropriate `HOME`, `USER`, `LANG`, `TERM`, and temporary directory; project sandbox HOME stays private. Service/API tokens, provider credentials, remote-chat secrets, proxy credentials, and arbitrary `TORI_*` values are excluded. Explicit future environment requests must be shown in the proposal, bound into the grant, and filtered by policy; secret-bearing values must not appear in policy listings or receipts. The retired CLI runner used a smaller fixed allowlist; terminal children use the broker environment described below.

## Slice 2 process-centric PTY broker

`TerminalBroker` is an application-internal, process-centric service. A trusted
application caller supplies the exact Slice 1 `ExecutionRequest`, one-use grant,
grant owner, and browser-session owner. The broker consumes the grant before
opening or spawning a PTY. Slice 2 had no HTTP launch endpoint; Slice 3 adds
only a direct local-browser request/approval adapter described below. No model
tool receives `launch`, `human_input`, or a persistent shell. An unapproved or
changed request fails closed. For a safe structured request it uses parsed
executable/argv directly. Only an approved request containing shell operators
or opaque expansion uses `/bin/sh -c` with that exact command text. Shell and
interpreter requests remain subject to Slice 1 Always Ask classification.

Each session has a random non-secret ID, request digest, scope/cwd, owner digest,
PID/process-group leader, PTY descriptor, start/end/exit state, termination
reason, one active attachment, and a bounded byte buffer. The PTY starts at
24x80 and accepts only 2–200 rows and 2–400 columns. Output is kept in a
256 KiB per-session in-memory scrollback; a bounded per-attachment event queue
disconnects a slow reader. Snapshot and live events are ordered under one
broker lock. Full transcripts, PTY input, and ticket plaintext are never saved.
Terminal output remains untrusted evidence and cannot authorize a new action.

`HOST_USER` runs with the Tori account and a minimal explicit environment:
fixed `PATH`, account `HOME`/`USER`/`LOGNAME`, `/bin/sh` as `SHELL`,
`C.UTF-8`, `xterm-256color`, and `/tmp`. It does not inherit API credentials,
SSH agent access, proxy settings, `TORI_*` values, or arbitrary desktop/session
variables. This conservative V1 set may need explicit, request-bound additions
for desktop commands later. `PROJECT_SANDBOX` delegates its workspace binding,
runtime mask, no-network namespace, and Bubblewrap argv to the existing
Delegated Work sandbox plan. The broker checks that the plan preserves the
approved argv. Its PTY wrapper omits only the plan's inner `--new-session`
because the outer PTY child already starts a dedicated session and must retain
terminal job control; namespace, mount, runtime-mask, and no-network flags
remain intact. It fails closed when native isolation is unavailable. No
privileged daemon or alternate terminal service is introduced.

PTY children start in a new session/process group with a controlling terminal.
Interrupt, terminate, and force kill send SIGINT, SIGTERM, and SIGKILL to that
verified group, respectively. The unreaped group leader pins its PID while
descendants are signaled, reducing PID-reuse risk. The reaper cleans remaining
group members and waits the direct child. Orderly broker shutdown sends TERM,
then KILL after a grace interval, and waits for reaping. The child also requests
Linux `PR_SET_PDEATHSIG=SIGHUP`. Slice 3 corrected an important Linux detail:
the parent-death signal follows the **creating thread**, so HTTP request
threads cannot fork live terminal commands. A broker-owned, long-lived spawn
worker now creates every child; it remains alive until broker shutdown.
Bubblewrap uses `--die-with-parent` in sandbox
scope. These reduce hard-crash orphan risk but cannot guarantee that a detached,
daemonized descendant dies. A future cgroup supervisor would be needed for a
stronger guarantee. V1 never adopts a stale PID after restart; startup marks
unfinished durable receipts `interrupted` with unverified outcome.

## Browser ownership and WebSocket transport

Tori's current LAN web app has Host, Origin, and CSRF checks but **no account
login**. Slice 3 uses an ephemeral HttpOnly, SameSite=Strict
`tori_terminal_local_session` cookie scoped to `/`, issued only when a direct
loopback peer loads the ordinary app page. The root path lets reload send the
cookie back to Tori so the owner is retained. The new name avoids collision
with Slice 2's narrower-path cookie; an old cookie grants no Slice 3 authority. The server
keeps only its digest. This binds a terminal to the browser/application session
that launched it; it is not account authentication. Tori's existing LAN and
HTTP access boundary remains relevant, including its lack of transport
encryption. **Terminal authority is restricted to an actual `127.0.0.1` or
`::1` socket peer** in V1. Host, Origin, `X-Forwarded-For`, proxy headers,
and a client field cannot assert locality. The current application listener is
IPv4, so only `127.0.0.1` is reachable today; the isolated peer predicate also
accepts `::1` for a future same-server IPv6 binding. Other Tori LAN functions
keep their existing access behavior. A local browser with the correct cookie may discover only its own
session metadata at `GET /api/terminal/sessions`.

The same Tori HTTP listener handles `GET /api/terminal/ws/{session_id}`; there
is no additional port. Strict Host, Origin, cookie, and owner checks occur
before the WebSocket upgrade. An owner requests a 30-second attach ticket at
`POST /api/terminal/attach-ticket` with the existing Origin/CSRF gate. Only
SHA-256 ticket digests are retained. The ticket is bound to session ID and
owner and consumed atomically by the first masked WebSocket message. It is not
placed in the URL or access log. No output is sent until successful attach.
Knowledge of the session ID alone is insufficient. An expired, replayed,
wrong-owner, or wrong-session ticket fails.

`GET /api/terminal/availability` gives a remote browser only a local-only
availability result, never session metadata. The direct-peer check also gates
`/api/terminal/request`, `/api/terminal/decide`, session listing, attach-ticket
issuance, and WebSocket upgrade. All WebSocket controls, including input,
resize, takeover, and signals, exist only after that gated upgrade and a
one-use ticket. Existing Host, Origin, CSRF, cookie, and owner checks remain.
The local HTML CSP permits a WebSocket only to its validated same-host address;
ordinary LAN CSP is unchanged. No policy-management route is published in
Slice 3, so remote clients cannot list or mutate terminal rules through HTTP.

The browser request route accepts exact command, absolute cwd, and scope. It
creates a normalized Slice 1 request and evaluates the **one** policy authority.
BLACKLIST returns an explanation and no run path. WHITELIST immediately issues
an exact one-use grant and launches, since the local human deliberately
submitted the request. DEFAULT_ASK and ALWAYS_ASK return a 60-second,
owner-bound, one-use approval proposal. The UI shows exact command, cwd,
scope, policy, rule, and reason; Approve Once re-evaluates policy, issues the
bounded grant, and calls the broker. Proposal tokens are retained only as
digests in memory. The broker independently requires an application-minted
local-web authority object bound to the same browser owner before consuming
the grant. No Discord, Remote Chat, scheduled/background, Night Owl, Research,
MCP, webhook, model output, or generic LAN path can mint that authority or
launch a PTY. **Origin permission and command policy are separate:** a
whitelist only removes command-specific approval for an otherwise authorized
local interaction. The former in-process general-command action and runner
are retired: direct internal invocation fails before subprocess creation.

Protocol version 1 uses JSON text control frames and binary PTY data frames.
The first client message is `{"v":1,"type":"attach","ticket":"..."}`.
The server responds with `ready` session metadata, bounded binary scrollback,
then live binary output and `exit` metadata. Client controls are `resize`
(`rows`,`columns`), `take_control`, `release_control`, `interrupt`, `terminate`,
and `force_kill`; the server sends `state`, `error`, or `superseded` as needed.
Ping/pong is supported. Frame size is capped at 16 KiB; human input frames
are capped at 4 KiB with a bounded PTY write wait. A valid same-owner
reconnect supersedes the old attachment. Only the current attachment can hold
human keyboard authority. Disconnect or supersession revokes that authority,
while the command continues. Reconnect requires a fresh ticket and begins in
observation mode. Browser binary input is accepted only after explicit Take
Control; there is no model-driven stdin route. Slice 4 adds Private Input;
the transport keeps output bytes separate from control messages and receipts.

Durable metadata lives in the version-2
`runtime/supervised_terminal/tori_terminal_receipts.db` SQLite store. It records
session/request/grant/owner digests, scope, cwd, start/end times, exit code,
termination reason, and lifecycle state. It stores no raw command text,
ticket, keystrokes, or terminal bytes. The store is included in verified SQLite
backup/restore and canonical runtime schema inspection. An unavailable audit
store prevents a new launch. The existing policy/grant store remains the sole
execution authorization authority; the receipt store grants nothing.

## Slice 3 local terminal interface

The conversation view contains a bottom drawer with open, minimize, restore,
expand, and collapse controls, an owned-session selector, scope and lifecycle
status, a terminal viewport, and distinct interrupt/terminate/force-kill
actions. Force Kill requires a deliberate UI confirmation. The locally bundled
MIT `@xterm/xterm` 6.0.0 and `@xterm/addon-fit` 0.11.0 assets are served on
Tori's existing port; no CDN, npm runtime, addon-attach, daemon, or new port is
involved. Fit computes bounded rows/columns on container resize and sends the
existing JSON resize control. xterm consumes binary PTY bytes; Tori's client
handles JSON lifecycle/control frames. Browser keyboard bytes are sent only
after the server acknowledges Take Control. Release Control, disconnect, or
supersession revokes the lease. The browser cannot send model-originated input.

Refresh or disconnect leaves the backend process alive. The browser discovers
only its own sessions, obtains a fresh ticket, and reconnects in observation
mode. On `ready` it resets the visual viewport and replays the broker's bounded
snapshot before ordered live frames, avoiding duplicate rendered output
without persisting transcripts. The user must Take Control again. A remote LAN
browser sees a local-only message; the terminal form and metadata stay hidden.
The layout remains responsive without enabling mobile LAN authority. The UI exposes a server-acknowledged Private Input state. No terminal
keystrokes are inserted into model context or durable logs.

Native-host acceptance with `scripts/validate-terminal-pty-host.py` passed:
PROJECT_SANDBOX PTY allocation, foreground job control, human input, resize,
SIGINT handler, Bubblewrap filesystem/runtime isolation, secret exclusion, and
reap. The nested Codex sandbox itself cannot create user namespaces; the
disposable probe succeeded when run in a namespace-capable host context.
Real-browser acceptance also verified approved command launch, observation,
human takeover/input, refresh with retained scrollback and revoked control,
and interrupt/exit presentation. Temporary fixture stores were outside
canonical runtime.

Receipts capture lifecycle metadata, immutable conversation/turn binding, and private interval count. Model-visible output is captured separately in memory, sanitized, bounded, and explicitly labeled untrusted evidence. Durable raw terminal transcripts are off by default.

After Tori launches an approved command, the browser may observe output, while human keyboard input remains disabled until Take Control. Human input then travels browser -> broker -> PTY without model mediation. Releasing control returns to observation mode. Tori has no model-driven arbitrary interactive stdin.

Private Input is a user-selected state: human keystrokes bypass model context and durable logs/receipts, and output remains visible to the human. The first activation permanently locks model capture for that process, including after the keyboard/UI state exits. A durable receipt records only interval count, with no bytes. Echo-off/password detection may assist, but cannot be the security boundary.

## Slice 4 conversation and Private Input design

The local browser supplies no conversation identifier for a launch. The server
binds the current archived conversation ID and a fresh turn/request ID to the
launch proposal, grant owner digest, broker session, and metadata-only receipt.
For a manual browser request when no archived conversation is active, the server
instead binds a distinct process-local scope derived from the verified browser
owner; it does not create an archive chat or a model-result origin. That scope
still passes through exact policy evaluation, approval, one-use grant, and the
same PTY broker. A new browser owner or process cannot assume it, and a later
real chat cannot adopt its sessions or read their output as model context.
Switching chats does not retarget a running session. Discovery, attachment,
ticket issuance, and read-only results require both the original browser
session and the currently selected conversation. A remote connector, worker,
LAN peer, or model text cannot mint the required loopback authority. A
WHITELIST match removes only the command-specific approval; it cannot supply
an authorized origin.

The HTTP result is typed `untrusted_execution_output` and read-only. The PTY
produces merged output, so the result makes no false stdout/stderr distinction.
The broker has a separate, non-durable 64 KiB model capture with approximately
16 KiB head and 48 KiB tail plus an omission marker. It decodes invalid UTF-8
safely, strips ANSI/OSC/terminal controls, and redacts common secret assignment
shapes as a secondary defense. An eligible completed result enters only its
originating local browser conversation. A short command result is given once
to the model during the current operation as explicitly untrusted evidence;
the model's follow-up has no action handler and cannot chain execution. If
follow-up synthesis is unusable, the typed bounded result is presented. A
long-running command returns a typed pending result and can later be read
through the owner- and conversation-bound read-only endpoint. A later ordinary
turn can consume a completed pending result once; provider failure leaves it
eligible. There is no autonomous polling or PTY write path for the model.
When a completed terminal result is supplied as untrusted context in a turn,
that provider response has no command-proposal handler. The model can discuss
the result, but cannot turn its contents into a new execution in that same
response. A subsequent local user turn can request another command through
the normal origin, policy, approval, and grant chain.
An explicitly worded new local user command defers a previous unacknowledged
terminal result so the new command can be proposed without receiving that
untrusted result as model instructions. The result remains eligible for a later
question. The server supplies its trusted working directory when available;
Gemma is instructed to propose directly and leave confirmation to policy UI.
A stream's validated visible assistant content (excluding any well-formed
leading reasoning) alone reaches the same strict whole-JSON-envelope parser.
For an explicitly requested first command in a new chat, a valid model
envelope is held only in process memory. A provider-free origin archives the
original user request and one fixed, internal terminal-proposal event. That
event is not visible assistant prose, model history, or a completed model turn.
Only after verification does the application invoke local policy, create an
approval token if needed, or consume a whitelist grant and launch. Failure to
archive creates no command, grant or usable proposal. On a short exited result,
the application foreground coordinator admits one result continuation using
bounded sanitized PTY output as explicitly untrusted evidence. The terminal
action handler is disabled, so even command-shaped output cannot authorize a
second run; the real model response completes the original user turn. Private
Input capture lock prohibits synthesis, and long-running or failed synthesis
leaves the result available for a later explicit user turn.

For local web turns, provider-neutral text adapters may return one exact whole
JSON envelope, `tori_terminal_proposal_v1`, containing only command, absolute
cwd, and scope. The application parses it only as the direct assistant response
to the current trusted local request. It is never recognized from user text,
retrieval, PTY output, remote turns, or a second model synthesis response.
The request then enters the same policy/approval/grant/broker path as browser
`/run`. The browser alone receives an approval proposal token; it is omitted
from model-facing text. An unauthorized proposal is rejected as internal
control data. This is a structured proposal interface, not unrestricted shell
or arbitrary interactive stdin authority.

Private Input is an explicit WebSocket state transition. Entry requires the
same local owner attachment, active human control, and running process; the UI
shows the state only after the server's state frame. Human bytes still go to
the PTY, but are never logged or stored. PTY bytes read while private continue
to the human viewport and bounded reconnect scrollback but do not enter model
capture. Disconnect revokes keyboard control while preserving blackout;
reconnect starts observation-only with Private Input still active. Only a new
human-control lease can end the keyboard/UI state. A receipt increments a count
without storing bytes. The first activation also sets a process-lifetime
`model_capture_locked` state; leaving Private Input, disconnecting, and
reconnecting never clear it. Subsequent PTY output, including delayed echoes
of previously entered secrets, remains human-visible but never enters model
capture. Only a new process starts with fresh public capture. Earlier output
is not retroactively removed, so the human should activate Private Input
before entering sensitive material.

The Settings policy editor exposes exact user rules and Default Ask. Create,
update, and removal require loopback, the browser session, Origin, and CSRF.
The policy service enforces Always Ask conflicts independently of the UI.
The `/run` HTTP path uses the same four outcomes and exact one-use grant. The
CLI `/run`, in-process general-command action, and old general runner are
retired. Specialized fixed-purpose subprocess adapters retain their narrower
contracts and are not generalized command authorities.

## Persistence, backup, and failure recovery

Policy rules and grant state live in one versioned SQLite store under `runtime/supervised_terminal/`. It is created only by an explicit policy mutation or grant issuance, not by read-only evaluation. A new store starts at schema 1, so there is no pre-existing schema to migrate in place. Backup treats the new database as SQLite, uses a consistent SQLite snapshot, and restore carries it with the runtime tree. Read-only canonical inspection recognizes the schema. Tests use isolated temporary roots. Unknown existing files, symlinks, corrupt stores, or unsupported versions are preserved and fail closed. A policy read failure cannot be treated as DEFAULT_ASK with an approval shortcut.

Execution failures leave honest receipts and never return a grant to pending. A broker crash/restart cannot infer success from a process ID; it must reconcile known session ownership and mark uncertain results as interrupted/unknown. Output never authorizes its own follow-up command.

## Planned slices

1. **Slice 1 (complete):** architecture, exact policy CRUD/evaluation, conservative high-risk rules, durable one-use grants, backup recognition, compatibility mapping, and tests.
2. **Slice 2 (complete):** PTY/session broker and same-server session-bound WebSocket, grant consumption at the single spawn boundary, reconnect and process ownership.
3. **Slice 3 (complete):** direct-loopback execution origin, local xterm.js drawer/expanded view, browser proposal/approval, resize, interrupt/terminate/kill, and atomic human takeover.
4. **Slice 4 (complete):** structured local-turn proposal/approval, conversation-bound results, process-lifetime Private Input capture lock, bounded model-visible output, policy UI, and receipt binding.
5. **Slice 5 (complete):** adversarial policy/origin/session/Private Input review, native sandbox PTY acceptance, real-browser UI acceptance with disposable stores, and closeout fixes.

## Slice 5 closeout observations

The audit added an adversarial exact-match corpus for shell operators,
redirection, substitution, newlines, quoted metacharacters, shell and
interpreter forms, and changed arguments. Existing tests also exercise grant
replay, expiry, owner/cwd/scope bindings, conflicting and malformed policy
rows, WebSocket tickets, owner and conversation isolation, process-group
lifecycle, and receipt/backup integrity. A delayed fake secret and a
transformed version remained in the human PTY view while the process-lifetime
capture lock kept them out of model results and durable test stores.

The real browser audit found that streamed model command proposals included a
`terminal_request` completion field that the frontend's strict parser had not
recognized. The parser now validates that field for each policy outcome, so
approval prompts reach the browser. On reload, the session selector chooses
the newest running owned session before historical completed sessions; human
keyboard control still starts revoked. Local browser acceptance used a
disposable provider fixture and temporary stores, leaving canonical runtime
untouched. The native host probe passed the unmodified Bubblewrap isolation,
PTY job control, resize, SIGINT, and reap checks.

V1 remains loopback-only with no account login or protected remote transport.
The browser owner cookie binds a session, not a named human. Terminal processes
do not survive backend restart. Parent-death signaling, PTY hangup, and
Bubblewrap reduce hard-crash orphans but cannot guarantee cleanup of detached
descendants; a future cgroup supervisor would be required. Raw transcripts,
human keystrokes, attach tickets, and reusable grants are not durable backup
content. No alternate listener or model PTY-input path exists.

Before any remote-terminal mode, design strong device/account authentication
and cryptographically protected transport such as HTTPS/WSS; a simple LAN
toggle is not sufficient. The loopback browser `/run` and structured model proposal paths use four-state policy: WHITELIST has no command-specific confirmation, ALWAYS_ASK requires one every time, BLACKLIST denies, and DEFAULT_ASK requests one. Origin authorization is checked separately for every launch.
