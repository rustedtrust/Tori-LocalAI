# Tori V1 User Guide

**Applies to:** The accepted capabilities at the [Gate 4 entry checkpoint](FINAL_STATE.md), following the original V1 closeout and subsequent accepted extensions.

## 1. What Tori is

Tori is a local-first AI companion with a command-line interface and a responsive web interface. Conversation is the main interface. Her accepted workspaces include Chat, Projects & Continuity, compact Planning, Security Center, Skills & MCP, Settings and supervised local Terminal. Optional integrations and current boundaries are summarized in the [current-state checkpoint](FINAL_STATE.md).

Tori does not make consequential changes merely because a model suggested them. Durable or host-changing operations use application-owned proposals and confirmation. When a provider or capability is unavailable, Tori reports that limitation; she does not silently claim success or switch models.

## 2. Requirements and first setup

Tori supports Linux with Python 3.11 or newer. The portable installer targets Debian/Ubuntu-family Linux. The web client needs a modern browser. Ordinary model conversation needs a separately configured, running provider; the generic example profile points to Ollama at `http://127.0.0.1:11434`, but installing Tori does not install Ollama or its model. The declared environment includes the Planning, Finance, Discord and reviewed MCP Time Python adapters; enabling their integrations is separate.

Clone [Tori-LocalAI](https://github.com/rustedtrust/Tori-LocalAI) or extract a reviewed portable ZIP into the intended writable installation directory. Backups default to a sibling `<installation-name>_backups` directory; optional integrations are configured separately.

On a new Debian/Ubuntu machine, install Git, Python 3.11 or newer, and the matching `python3-venv` package first. To get the public Git checkout:

```bash
git clone https://github.com/rustedtrust/Tori-LocalAI.git Tori
cd Tori
./install.sh --non-interactive
```

For an already obtained and reviewed source tree:

```bash
cd /path/to/Tori
./install.sh --non-interactive
```

The reviewed source distribution supplies application source; it does not include this computer's runtime, settings, conversations, models, or credentials. Moving existing user data requires a separately verified private backup and deliberate recovery.

From a fresh extracted tree with no `runtime/` directory:

```bash
chmod +x install.sh
./install.sh
```

The installer checks Linux/Python/venv prerequisites, creates or safely reuses `.venv`, installs `requirements.txt`, runs `pip check`, validates configuration, and checks Tori import and CLI help. It removes inherited `PYTHONHOME` and `PYTHONPATH` from interpreter/dependency setup so these do not supply another project's packages. If root `tori.toml` is absent, it validates the generic [`deploy/portable/tori.toml`](../deploy/portable/tori.toml) and publishes a private exact copy without overwriting a raced-in file. Existing safe regular configuration is preserved byte-for-byte; symlinks/non-regular destinations are refused. If Python/venv is missing, an interactive run offers the exact minimal Debian package command for confirmation before sudo. It never upgrades the system. Use unattended setup with:

```bash
./install.sh --non-interactive
```

Non-interactive mode never invokes sudo or an external optional installer. Interactive mode asks only when a missing **core** Python prerequisite needs privileged installation; neither mode asks about providers or external APIs. Unsupported `--with-voice` / `--with-research` flags fail before changing anything, rather than claiming partial provisioning.

To verify a fresh Git checkout after installation and before starting Tori, run `./scripts/verify-milestone` from the checkout. It requires Git metadata and the installed `.venv`; a portable ZIP has no Git metadata and cannot run this Git-specific gate. The offline gate checks imports, tests, JavaScript syntax, founding documents, and runtime preservation; install Node.js so a `node` executable is on `PATH` for the JavaScript checks. An absent `runtime/` is accepted and remains absent after the gate.

**Core:** Python environment, declared adapters, committed Web/static assets and a generic local configuration. Application stores and schema initialize on first start. Radicale and MCP Time Python packages are included, but their runtime service/tool settings are not enabled. The existing Radicale user-service template uses an owner-local collection path and loopback endpoint; service installation/start and any Planning data migration require a separate deliberate owner action. MCP Time also requires exact approved executable/Bubblewrap paths and hashes; it never uses another MCP checkout.

**Optional Tori components:** Tori's Voice bridge is committed, but its separate Python 3.12 environment and verified `tiny.en`, `small.en` and Silero ONNX assets are not installed; follow [`deploy/voice/README.md`](../deploy/voice/README.md) and enable only after verification. Research Worker is unavailable on a fresh clone: its accepted external wrapper includes a copied upstream package and a large environment whose redistributable, integrity-checked source has not been established. Do not copy or guess an external project directory. Neither component currently has a complete safe `install.sh` flag.

**External integrations configured later:** model servers/weights (Ollama, LM Studio and other compatible providers) through **Settings → Models**; external TTS and Search through Settings; Discord credentials through its private configuration; OpenCode 1.18.31 and Bubblewrap through their separate installation/bootstrap; external Finance workbook root and Knowledge source files through their explicit workflows. The bounded Ollama service-control helper remains a separate privileged owner operation using committed templates, not part of the core installer. No provider/account/API onboarding occurs during install.

The installer does not create `runtime/` or pre-populate chats, memory, Finance, Knowledge, Projects, Scheduled Work, reminders, logs, or backups. Normal Tori first use initializes supported stores. Finance remains inert until an external absolute data root is configured and `/finance initialize` is explicitly confirmed. For a clean-install acceptance run, isolate `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME` and the clone's working directory before launching: a normal installation intentionally uses the current owner's XDG configuration when started.

Manual core setup remains available if needed:

```bash
python3 --version
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Install or configure Ollama separately, make the selected model available, then check it:

```bash
ollama list
curl -s http://127.0.0.1:11434/api/version
```

The generic template enables only loopback Ollama. Search, speech output, Planning, Finance, and Coding Work start disabled. This is intentional: a fresh checkout contains no machine's root `tori.toml`, runtime databases, credentials, or user data. Tori creates the local configuration during installation and the application stores it needs on first use; Finance creates nothing until its external data root is configured and initialization is confirmed.

There is no installer-driven upgrade, migration, merge, or full uninstall. If `runtime/` exists, `install.sh` stops before creating or changing `.venv`. For an unused pre-start extraction, remove the extracted project directory manually. Once Tori has runtime/user data, preserve it and use verified backups plus deliberate maintenance procedures; never replace or merge it with a fresh ZIP.

No Tori installer path detects GPUs or installs NVIDIA/AMD/Intel drivers, CUDA, ROCm, model-specific packages, or model weights. Model performance and compatibility belong to the chosen provider's own installation process. Tori also creates no application or Radicale system service. Persistent services remain an explicit owner operation documented by the relevant upstream/Tori operational material.

## 3. Starting and stopping Tori

Start Tori from any current working directory by invoking the helper at the extracted project path:

```bash
/path/to/Tori/start-tori.sh
```

From the project root, the same command is `./start-tori.sh`. The helper resolves its own repository root, checks that `.venv/bin/python` is executable, clears inherited `PYTHONHOME`, sets `PYTHONPATH` to that repository's `src`, and replaces itself with `.venv/bin/python -m tori --web`. It creates no service or log and leaves Ctrl+C connected directly to Tori. If `.venv` is missing, it stops with guidance to run `./install.sh`.

Open `http://127.0.0.1:8765/`. Use `Ctrl+C` in the terminal for a clean shutdown. The browser has no shutdown or self-restart control.

For the CLI:

```bash
PYTHONPATH=src .venv/bin/python -m tori
```

Use `/exit`, `/quit`, or `Ctrl+C`. A one-request smoke test is:

```bash
PYTHONPATH=src .venv/bin/python -m tori "Reply with one short sentence."
```

Use `--web-port 9876` to select another port. `--help` shows the complete terminal option list.

## 4. Conversation and chat history

Tori receives a compact, current inventory of her application capabilities with every generated conversation turn. “Can you use OpenCode?” returns actual configured/readiness state; disabled Search remains a known capability, not a claim that Tori has no search integration. Configured does not guarantee an external server is reachable.

Talking about work is not an instruction to create it. “Too much to do then wait and unpredictable lol,” “What do you need to create a reminder?” and “Reminders aren't working” stay conversational. A supported request such as “Remind me today at 7 PM to look into a fishing trip” enters the existing reminder workflow (CalDAV proposal/confirmation when configured). If “Remember to take out the trash at 8 PM” is missing only its day, Tori asks for `today` or `tomorrow`; an immediate `tonight` reply also means today and resolves that bounded clarification without a model call. Other incomplete requests still require the missing description/date/time, and Tori does not invent details. “Can you create a plan on my calendar?” asks for the calendar details instead of denying the existing Planning integration.

“How much RAM is in use?” and “Can you tell me how much system RAM is in use?” read actual host information. “Use OpenCode to audit /absolute/workspace” can propose a bounded read-only review when Coding Work is ready; it still requires confirmation. Budget discussion can use Finance's existing workbook/calculations, not arbitrary spreadsheet creation. Exact commands, capability validation, and confirmation remain application-owned; model classification cannot execute anything. Unrecognized phrasing may still need clarification. No model can guarantee flawless intent interpretation.

Send a message in Conversation or type it at the CLI prompt. Browser responses stream as temporary plain text and become authoritative only after the complete response is archived. Failed or empty provider responses do not create a false completed assistant turn.

Successful normal turns are archived automatically in `runtime/conversations/tori_conversations.db`. A normal restart resumes the active chat. Recent Chats can open, rename, or explicitly delete an archived chat; associated Project badges show the current Project title without waiting for the full Projects workspace. New chat starts a separate durable conversation and takes you to Chat with the composer focused, including when started from Home or Settings. All connected browsers share one process-level active conversation and operation state.

Checkpoints are separate, explicit snapshots:

```text
/save
/save Optional display name
```

```bash
PYTHONPATH=src .venv/bin/python -m tori --list-checkpoints
PYTHONPATH=src .venv/bin/python -m tori --resume CHECKPOINT_ID
PYTHONPATH=src .venv/bin/python -m tori --remove-checkpoint CHECKPOINT_ID
```

Archive controls are:

```bash
PYTHONPATH=src .venv/bin/python -m tori --list-chats
PYTHONPATH=src .venv/bin/python -m tori --resume-chat CHAT_ID
PYTHONPATH=src .venv/bin/python -m tori --remove-chat CHAT_ID
PYTHONPATH=src .venv/bin/python -m tori --new-chat
```

A checkpoint is saved transcript context; curated memory is selected long-term context. Neither is local Knowledge.

## 5. Models and providers

The portable default is one Ollama profile. Tori also implements local/LAN OpenAI-compatible profiles. Settings → Model Providers manages local profiles and write-only bearer values; stored tokens are never returned to the browser. Provider endpoints are restricted to numeric loopback or private IPv4 addresses with explicit ports. Public/cloud providers and automatic model download are not implemented.

The Conversation `Change` control selects a configured profile, model, and context policy for future requests. An explicit provider/model selection is also retained as Tori's non-secret last-used application preference, so a later fresh start without an active chat restores it; a clean installation retains the configured default. Selection persists with the active chat. Existing assistant turns retain the provider/model attribution that generated them. An unavailable saved provider or model stays selected and fails clearly—there is no silent fallback or preference rewrite.

Checkpoints remain preserved as dormant compatibility data and terminal options, but are no longer shown as a normal Web workspace or navigation destination.

CLI equivalents include:

```bash
PYTHONPATH=src .venv/bin/python -m tori --list-models
PYTHONPATH=src .venv/bin/python -m tori --model MODEL
PYTHONPATH=src .venv/bin/python -m tori --context auto
PYTHONPATH=src .venv/bin/python -m tori --context fixed:32768
```

Context pressure is an estimate unless the provider reports validated usage. A fixed policy is a planning envelope, not a guaranteed provider-level total-token limit.

## 6. Personality and interaction behavior

Every model request receives Tori's stable identity plus compact, provider-neutral interaction guidance. Tori should be warmer and more conversational in relaxed exchanges, focused during active work, and concrete in serious Project, planning, troubleshooting, or tradeoff discussions. There are no selectable personas, mood modes, autonomous personality changes, or personality database.

## 7. Curated memory

Curated memory stores approved facts that may help future conversations. It is not a transcript and does not copy all chat content.

Explicit commands are:

```text
/remember TEXT
/memories
/update-memory MEMORY_ID NEW_TEXT
/forget MEMORY_ID
```

Forgetting requires exact confirmation. The Manage → Memories workspace provides create, edit, and confirmed removal controls, with newest memories first. You can also say “Create a memory that I like root beer,” “Remember that I prefer Fahrenheit for weather,” or “Can you remember that I use Firefox?” These clear directives save through the same Memory policy as `/remember` and return a verified receipt; they do not ask a model to pretend to save anything. A timed “Remember to …” request stays in the reminder path, and an ambiguous request is clarified without saving either a memory or a reminder. Tori retrieves at most a small bounded set of lexically relevant memories for a request. The current user statement always outranks an old memory.

Tori also performs asynchronous candidate extraction after eligible completed turns. Automatic low-risk results and proposed changes remain governed by the memory contract; proposals are source-chat-bound and require confirmation when necessary. The worker does not delay transcript commitment, silently switch providers, or become Scheduled Work.

Memory is local in `runtime/memory/tori_memory.db`. Recognizable credentials, private keys, payment-card numbers, SSNs, and clearly labeled sensitive material are best-effort rejected, but memory is not a password manager or complete secret scanner.

## 8. Local knowledge

Knowledge registrations point to exact external `.txt` or `.md` files; Tori does not copy the source document into runtime.

```text
/add-knowledge /absolute/path/to/notes.md
/knowledge
/remove-knowledge SOURCE_ID
```

Manage → Knowledge provides the same registration and confirmed removal workflow. Sources must be regular UTF-8 files, no larger than 1 MiB, and remain at the registered path. Tori reads bounded relevant passages at request time, labels them as untrusted data, and shows source filename/span information. Removing a registration does not change or delete the source file. Directories, uploads, PDF ingestion, crawling, vector indexing, and semantic RAG are not implemented.

## 9. Web search

If Tori offers to search for a current-information question, “Yes, please” continues that original query through the existing expiring, conversation-bound one-use consent. No retrieval results and failure of the selected model to synthesize retrieved sources are different outcomes: the former produces an application-owned no-results notice; the latter explicitly says retrieval completed but synthesis failed. Neither silently falls back to an unsupported model-only answer.

Web Search is an optional local SearXNG integration. Configure `tori.toml` with a SearXNG instance on an allowed numeric loopback/private IPv4 endpoint:

```toml
[search]
enabled = true
endpoint = "http://127.0.0.1:8080"
result_limit = 5
timeout_seconds = 8
```

Settings → Search can enable or disable the configured search capability. It does not choose arbitrary endpoints.

Ask naturally, for example, `search the web for the current Python release notes`, or use:

```text
/search current Python release notes
```

For a request that appears to need current external facts, Tori may propose a search. Reply with a clear `yes please`, `sure`, or `go ahead`; a rejection or topic change clears the proposal. Proposals do not survive restart. Explicit URLs can be retrieved only through the bounded public-source path.

Search uses Tori-owned SearXNG categories, not model-selected engines: ordinary web requests use `general`; clear weather/forecast requests use `weather`; explicit news requests use `news`; and clear Linux/software/computing requests use the deployed `it` category. Uncertain requests stay in `general`. A direct weather question such as “What's the weather in Exampleville Illinois?” offers the normal Search-consent choice even without the word `today`. Tori separates `current`, `today`, `tonight`, or `tomorrow` from the requested place, sends only the canonical location (for example, `Exampleville, IL`) to the specialized service, and retains the requested period through consent and synthesis. It uses current conditions for `current` and bounded hourly forecast evidence for the other periods in the structured source's validated timezone. If no authoritative location is present, a request such as “weather for tonight” receives `What location should I check?`; supplying the location restores the original request but does not authorize a search, so Tori then asks the normal Search-consent question. A versioned technical query gets at most one deterministic `it` → `general` retry when `it` does not return enough records matching both its requested subject and version. Tori never sends a model-selected engine, bang, or category to SearXNG. A weather response may be a structured SearXNG service record rather than a webpage; Tori accepts it only when the returned location matches the requested place. A shortened forecast location is usable only when an exact state-qualified nearby structured record anchors it. Matching weather engines are represented as one visible source with bounded internal engine provenance, rather than duplicate source rows. Tori labels structured-service evidence and cites the configured SearXNG service rather than inventing a weather-provider link.

Search results are current-turn, untrusted evidence. Tori supplies snippet, bounded retrieved-page, or explicitly labeled structured-service evidence to the selected model and presents application-owned source links. A snippet-only source means Tori did not open the linked page. If a local model omits inline source markers, Tori still labels the result with the exact retrieved source records; it does not invent claim-to-source mappings. Invented, unknown, or malformed source references remain rejected. Results are not automatically saved as Knowledge or Memory.

If you explicitly save a Fahrenheit weather preference in curated Memory, Tori applies it only to the presentation of a validated structured-weather answer: explicit Celsius measurements, bounded numeric ranges, and common qualitative Celsius decades in the answer are converted deterministically to Fahrenheit while the SearXNG evidence and its provenance remain unchanged. Without that saved preference, Tori retains the provider's reported unit.

If Search is disabled or SearXNG is unreachable, Tori reports that the backend is unavailable. It separately reports malformed backend results, no usable results, selected-provider synthesis failures, and invalid provider source references. Current-news searches rank bounded date-bearing records and exclude records that are clearly stale; one malformed third-party news item is ignored rather than treated as evidence. Tori does not silently present an ungrounded model-only answer as a successful search. Search sends the query and bounded retrieval requests to the configured SearXNG/public sites, so it is not offline even though Tori and SearXNG may be locally hosted.

## 10. Finance and Budgeting

Finance V1 is a local, informational budgeting notebook. It is not bank connectivity, payment execution, tax/accounting software, investment advice, or an autonomous decision maker.

### Enable and initialize

Choose a user-owned absolute directory outside the project and outside `runtime/`:

```toml
[finance]
enabled = true
currency = "USD"
data_root = "/absolute/path/to/Tori Finance"
```

Restart Tori, then enter:

```text
/finance initialize
```

Review and confirm the exact proposal. Initialization creates:

```text
Tori Finance/
├── tori_finance.xlsx
└── imports/
    ├── incoming/
    └── processed/
```

The workbook is authoritative and has `Transactions`, `Merchant Rules`, `Bills`, `Debts`, `Budget`, `Goals`, and rebuildable `Summary` sheets. It is meant to be readable and editable with ordinary spreadsheet software. Tori validates its contract rather than guessing around malformed cells. Friendly labels such as `Citi Card`, `Car Loan`, `Rent`, and `Electric` are appropriate; do not put account numbers or credentials in labels.

### Import statements

Supported imports are CSV and XML OFX/QFX. CSV uses the implemented bounded column/sign mapping; inspect the preview carefully. Legacy non-XML OFX/QFX and arbitrary PDF layouts fail closed.

Place a file in `imports/incoming/`, then use only its filename:

```text
/finance import statement.csv | Citi Card
```

Nothing is imported during preview. Unknown merchants, conflicts, and possible duplicates enter a transient review:

```text
/finance review
/finance review 3 | McDonald's | Dining / Fast Food
/finance review 4 | exclude
/finance review rule 3 | contains | MCDONALD | McDonald's | Dining / Fast Food
/finance review propose
/finance review cancel
```

A reviewed reusable rule becomes durable only with final confirmation. Confirmed import normalizes source facts into signed transaction semantics, writes and verifies the workbook atomically, and then moves that exact source to `imports/processed/`. Cancelled or failed imports leave the source in `incoming/`. Tori detects committed and same-batch duplicates and flags possible mirrored transfers instead of silently double-counting.

To update Finance, edit valid source sheets in the workbook or import a later statement, close the spreadsheet so Tori can read it consistently, then ask again. Re-imported source IDs are detected as duplicates. Tori has no conversational `reset Finance` or delete-workbook command. Make a backup before manual structural edits; removing or replacing the Finance data root is a manual user data operation outside Tori.

### Questions Tori calculates deterministically

Examples using fictional data:

- `How much did I spend on fast food this month?`
- `What are my biggest spending categories this month?`
- `What bills are due in the next seven days?`
- `What's my average Electric bill?`
- `What are my current credit-card and loan balances?`
- `Which debt has the highest APR?`
- `How much discretionary money do I have left?`
- `Can I afford a $75 purchase this month?`
- `If I pay an extra $100 a month toward Car Loan, what happens?`
- `What changed in my spending over the last three months?`

Finance answers use `Decimal` calculations and current workbook facts. Bills support fixed/variable expected cost, next due date, common frequencies, linked-payment rolling averages, and upcoming obligations. Debts store friendly name, type, balance, APR, minimum/target payment, due date, priority, and balance-as-of date. Balances older than 31 days are flagged as stale. Budgets track monthly expected income, starting funds, essential/discretionary/savings/debt targets, and reserve buffer. Goals support savings and debt-payoff progress. Missing or unlinked facts produce conditional answers rather than invented certainty.

The workbook and statement files stay under the selected Finance root, not canonical Tori runtime. Ordinary Finance questions and results still appear in the conversation archive. Tori stores no bank credentials and cannot move money.

## 11. Planning, tasks, reminders, and scheduled work

### Planning / CalDAV workspace

When configured, Planning's compact desktop utility rail/mobile sheet shows Today, seven-day Upcoming, open/due/overdue/completed Tasks, and a nearby-day Calendar agenda from current CalDAV data. It is a working projection, not a full month/week calendar. The committed Radicale service template binds to `127.0.0.1:5232`; credentials, if used, come from an environment reference rather than `tori.toml`. Its collections remain outside Tori's normal backup/restore scope.

Natural examples include:

- `Add a task to renew the registration tomorrow at 6 p.m.`
- `Remind me tomorrow at 9 a.m. to call the mechanic.`
- `Schedule an appointment Friday at 2 p.m.`
- `What do I have today?`
- `Show my overdue tasks.`
- `Move the appointment to Monday at 3 p.m.`
- `Mark renew the registration done.`
- `Cancel the appointment.`

Reads use fresh CalDAV truth. Creates, edits, completion, and deletion produce a review and require confirmation. Supported recurrence includes bounded daily/weekly/every-N-day/every-N-week/named-weekday rules and finite count/until dates. Calendar event reminders use DISPLAY alarms; the Reminder Bridge derives delivery entries without creating a second planning authority. Full month/week grids, attendees, recurrence exceptions, and broad free-form time interpretation are not implemented.

Current reminders are created conversationally and managed in **Reminders & legacy tasks**. Existing legacy task records remain manageable for compatibility; creating new legacy task records is not the primary workflow. The **Upcoming** rail section continues to show dated reminders and Scheduled Work.

### Scheduled Work

The Scheduled Work engine supports durable one-shot/recurring schedule semantics, pause/resume/cancel/history, occurrence recovery, and attention delivery, but only registered capabilities may be scheduled. The normal user-facing persistent capability is a one-shot verified Tori backup; recurring backup is deliberately rejected because retention/pruning is absent. Planning reminders are system-derived one-shot work.

Example:

```text
Schedule a Tori backup tomorrow at 8 p.m.
```

Review the exact time, missed-run policy, and capability, then confirm. Use Manage → Scheduled Work to view active/paused/completed definitions and runs, edit supported entries, pause, resume, cancel, or confirm permanent deletion of resolved history.

Scheduled work runs only while the Tori application process exists. If Tori was stopped, startup recovery applies the stored missed-run policy; it cannot wake a sleeping/stopped host. Results appear through Tori's application attention/delivery state and are archived idempotently.

## 12. Projects & Continuity V1

The earlier Milestone 25 was frozen without human acceptance. Projects & Continuity V1 is its separately completed and manually live-accepted workspace. The Projects navigation and Project Home are available, and existing Project records remain preserved.

Ask explicitly to create a Project. If your wording could mean either ordinary discussion or durable Project creation, Tori asks which you mean. A clear create answer still leads only to a formal proposal; confirm it to create the record. To avoid creation, say `Let's discuss this without creating a Project.`

Projects shows a compact Project Home with objective/status, explicit phase/current focus/checkpoint, deterministic Where We Are, current lightweight Plan, open Questions, active Decisions with historical supersession, metadata-only associated conversations, and separate read-only Legacy Continuity. **New Project Chat** starts a fresh associated conversation without saving an empty chat. Opening an existing associated conversation follows the normal archive flow. Project Home reads do not create structured records or change the Project revision. Existing creation, edit, lifecycle, association, and confirmed deletion controls remain revision-safe. Deleting a Project detaches chats and removes its own structured records and explicit links; it does not delete transcripts or source-owned capability records. In a Project-associated conversation, Context details show the exact persisted Stable/Working/Historical Project context receipt for a completed model turn; material not loaded is identified rather than silently reconstructed.

Related Work lists bounded metadata from Research, Coding Work, and Attention records already associated by their own source systems. To link an existing Night Owl finding, Scheduled Work definition, or Knowledge source, choose its human-readable **Source** and **Item** in Project links, review the confirmation, and select **Link**. The source-owned stable ID is retained internally and reverified with that source before saving. Scheduled Work also labels this value **Definition ID** in its run details. **Unlink** removes only the Project relationship, not the finding, schedule, or Knowledge registration. An unreadable source is labeled as a partial view; a missing target remains a visible link until you remove it. Recent activity is a current-record projection, not a complete event log. The right-side Attention & review rail shows concise title/source/state while Review opens full details in the owning surface; Later and Dismiss remain available. Project links and context grant no search, execution, scheduling, file, network, credential, Git, commit, push, or deploy authority.

## 13. System information and service controls

Tori recognizes bounded deterministic requests for disk/storage, LAN IPv4, RAM, CPU, GPU/VRAM, uptime, Ollama status, Radicale/Planning status, and Tori health. Examples: `How much RAM is available?`, `How much disk space is free?`, or `Is Ollama running?` These reads do not need web search or model generation. On desktop, At a glance also shows compact one-row CPU, RAM, GPU, and optional VRAM values. A fixed local `nvidia-smi` probe supplies per-GPU utilization and VRAM when available. GPU telemetry may truthfully say unavailable; it does not require sudo and does not affect chat or Search.

Tori can also open allowlisted desktop applications (Brave, Dolphin, a terminal, and LM Studio) and existing directories through fixed executable vectors. This is not arbitrary desktop control.

Starting, stopping, or restarting Ollama or Radicale requires a one-use confirmation. Radicale uses a fixed user service. Ollama uses only the root-owned fixed `/usr/local/libexec/tori-ollama-service` helper and the three exact actions from the sudoers installation template. Replace `@TORI_USER@` during installation and validate with `visudo`; do not install the template verbatim. There is no arbitrary `sudo`, service/unit selection, or Tori self-restart. Missing helpers/privileges fail clearly.

## 14. Delegated Work, OpenCode, and Supervised Terminal

On a browser connected directly through host IPv4 loopback, open **Supervised Terminal** in Chat to submit an exact command. Tori shows the four-state policy decision; commands needing approval require a one-use grant before execution. The xterm drawer shows bounded output and permits human keyboard takeover/release, reconnect to a running session, and interrupt/stop. **Private Input** prevents subsequent model capture for this process. Natural local requests may propose an exact command through the same policy and approval boundary; terminal output is untrusted and cannot authorize another command. Terminal is unavailable to LAN and Remote Chat clients. The old `/run` input is retained only for compatibility; use the supervised drawer or a clear local request, not the Commands page, for current browser operation. Native Bubblewrap isolation must pass or execution fails closed.

The optional Delegated Work integration can send one explicitly confirmed coding objective for one existing absolute workspace to OpenCode 1.18.31 through a Tori-owned supervisor, once its exact-version offline bootstrap is prepared. Coding Work remains the internal durable domain; OpenCode is the replaceable worker, not Tori. A recognizable request includes a coding action, code/file/project subject, and exactly one absolute directory, for example:

```text
Fix the tests in /absolute/path/to/workspace. Done when: the focused tests pass.
```

The proposal shows objective, workspace, acceptance criteria when supplied,
read/modify/sandbox authority, and limits. Delegated Work cannot prepare a
missing workspace, access unrelated paths, write authoritative Git control
state, use general network/credentials, commit, push, release, deploy, publish,
or use GitHub. A normal bounded OpenCode turn becomes **Completed** only after
ACP reports `end_turn`, Tori stops the owned worker, and the strict private
snapshot import succeeds. An explicit request for authority outside the
approved bounds may remain **Waiting** with an actionable reason; it is not
treated as success.

After authorization, you may navigate away or reconnect. The canonical record
belongs to Tori. In ordinary Conversation, try:

```text
How is that fix going?
What did OpenCode change?
Did the tests pass?
Stop that coding job.
Continue that work and fix the remaining test.
```

Status and stop prefer work originating in the current chat. Tori refuses to
guess if multiple active items are ambiguous. A related follow-up is a new
proposal with fresh authorization and a durable link to the prior work; prior
authority is not reused, and Tori does not claim that a closed OpenCode session
resumed.

The Workspace card lists **Active**, **Needs attention**, and **Recent** work.
Its receipt shows objective, workspace, acceptance assessment, changed files,
structured verification, recent activity, result/failure, related work, and
Stop when valid. “Reported complete; not independently proven in full” means
the worker finished and Tori retained evidence, but the evidence does not prove
every acceptance criterion. Raw ACP/process logs are diagnostic data, not the
normal user experience. Pause/resume, autonomous coding, package acquisition,
and generic jobs are not implemented. The portable default omits
`[coding_work]`; configure it only on a host with the required OpenCode and
Bubblewrap installation.

## 15. Capability Growth and Skills Review

Open **Skills & MCP** and find **Capability Growth** to review Tori's current
application-owned capability inventory, open findings, known-good baselines,
recommendations, history, and recent Skills Reviews. This Improvement Journal
is Tori-owned operational evidence; it is not curated Memory and contains no
saved conversation transcript.

You can run a general review from the page or say a clear request such as:

```text
Run a Skills Review.
Look for useful Skills we don't have yet.
What capabilities are you missing?
Find a Skill for Excel files.
Is there a Skill for this?
Find something useful for Discord.
Look for image-generation Skills.
```

A general review considers FIX (regressions and failures), IMPROVE (friction
and workarounds), and EXPAND (useful missing capabilities). A directed request
searches only its topic. “Is there a Skill for this?” is intentionally too
ambiguous on its own, so Tori asks which capability you mean.

The clear local request authorizes only that one bounded read-only review. Tori
may search skills.sh and statically inspect a small number of public GitHub
candidates at immutable commits through quarantine. Catalog claims remain
untrusted, downloaded scripts do not execute, and transient research files are
not journal state. Remote Chat cannot run a review.

Recommendations say whether a capability is ready now, needs Skill lifecycle or
permission approval, needs an application adapter, needs MCP/external
integration, requires unsupported execution, duplicates current capability, or
is not recommended. **Accept** records your advisory disposition only. It does
not install or enable anything. Installation, enablement, permission grants, and
integrations remain separate explicit workflows. **Dismiss** suppresses the same
unchanged suggestion for a cooldown rather than creating a permanent ban.

Finding controls are revision-safe: use **Monitor** while watching a pattern and
**Resolve** only after the underlying behavior is actually addressed. Repeated
verified successes consolidate into a baseline such as “17 successes, 0 recent
failures” instead of filling the journal with duplicate rows. A later verified
failure can be recognized as a regression without erasing that baseline.
Success-only evidence does not create an IMPROVE recommendation. During a general
review, an open evidence recommendation no longer supported by current policy
moves to **obsolete** history; a regression FIX supersedes the matching
lower-priority failure FIX while preserving the failure evidence. Legitimately
empty discovery completes as “no new candidates”; handled discovery or
inspection faults are reported as partial, with inspection attempts and
successful inspections shown separately.

Capability Growth does not install, enable, disable, update, grant, execute,
edit Tori's code/configuration/prompts, change Memory or identity, create an
agent, or perform background research. Night Owl owns its separate bounded
research lifecycle and can submit only an explicit advisory promotion into
Capability Growth; Capability Growth remains authoritative for recommendation
review and never treats external research as operational evidence. MCP
administration expansion and agents remain deferred.

## 16. Remote Chat (Discord)

Remote Chat's Discord implementation is complete, physically human accepted,
and default-off.
It supports one official bot, one owner, plain-text one-to-one DMs, normal Tori
conversation/context, consent-bound Search, and bounded upcoming-reminder reads.
It does not support guild conversation, group DMs, other users, slash/general commands,
attachments, reactions, embeds, voice, administration, local proposal
confirmation, execution, mutations, Finance, Projects, Knowledge contents,
Skills Review, Capability Growth research, Coding Work, MCP, or agents.

### Minimal Discord setup

1. In the Discord Developer Portal, create one application and use its official
   bot user. Turn **Public Bot** off. Never use a Discord user token or self-bot.
2. Configure only **Guild Install** for this V1 bot and install it with the
   `bot` OAuth2 scope into one private test server controlled by the owner. Do
   not grant guild permissions merely for convenience. Tori requires the bot to
   be installed in exactly this one server so startup can prove the configured
   installation identity; guild messages are still rejected.
3. Leave every privileged Gateway intent off. Tori requests only Discord's
   standard **Direct Messages** intent; Discord provides content in DMs with the
   app without the privileged Message Content intent.
4. With Discord Developer Mode enabled, copy the numeric Application ID, bot
   User ID, private test-server/Guild ID, and owner User ID. Open a direct
   one-to-one DM with the bot. The DM channel ID is optional during initial
   configuration; Tori binds the first verified owner DM durably. Supplying it
   up front is stricter.
5. From the Tori installation directory, configure only those exact IDs. Choose a stable
   local connector label such as `discord-owner-dm`:

```bash
./scripts/tori-remote-chat configure-identity \
  --connector-id discord-owner-dm \
  --application-id APPLICATION_ID \
  --bot-user-id BOT_USER_ID \
  --installation-id PRIVATE_GUILD_ID \
  --owner-user-id OWNER_USER_ID
./scripts/tori-remote-chat set-token
./scripts/tori-remote-chat permit
./start-tori.sh
```

`set-token` prompts twice without echo. There is no token command-line argument,
read-back, Web form, archive entry, Memory entry, normal runtime copy, log value,
or backup copy. The private connector record lives under the user's XDG config
directory (normally `~/.config/tori/remote-chat`) rather than Git or `runtime/`.
Discord remains an external service and receives accepted owner DM/reply text
and communication metadata.

Use the local CLI for truthful redacted state:

```bash
./scripts/tori-remote-chat status
./scripts/tori-remote-chat disable
./scripts/tori-remote-chat kill
./scripts/tori-remote-chat revoke
./scripts/tori-remote-chat clear-token
```

After Tori starts, enable the session from **Settings → Remote Chat** on direct host IPv4 loopback, or run `./scripts/tori-remote-chat enable` locally after startup. Saved permission or a pre-start CLI enable is not session enablement; each new process begins Off. `runtime_state` distinguishes `disabled`, `configured_disconnected`,
`connecting`, `connected_ready`, `authentication_configuration_error`,
`runtime_error`, and `stopping`. A disabled/cleared/revoked/rotated generation
cannot authorize a later send. After changing IDs or replacing the token,
explicitly permit/enable as needed and restart Tori. Startup/authentication
failure disables Discord work but leaves local Web Tori available.

**Settings → Remote Chat** shows `Not configured`, `Disabled`, `Connecting`,
`Connected`, or `Error` without returning the token or complete Discord
identities. A browser connected directly through IPv4 loopback on the Tori host
may turn the current Remote Chat session On or Off. Every new Tori process starts
Discord Off, even when its saved local enablement was on during an earlier
process. Off stops the active connector and fences old replies. Re-enabling
creates a clean lifecycle; delayed work from the previous generation cannot be
delivered. On requires the existing CLI-configured identities, token, and
administrator permission. If the connector was not composed at startup, Settings
reports that a restart is required after enablement. LAN browsers may view this
sanitized status, but the control is read-only: `Remote Chat can only be changed
from this computer.`
Credentials, identities, and administrator permission remain CLI-only.

The server terminal also emits concise operational events for major Web and
Remote lifecycle changes, turn admission/completion/failure, actual
provider/model calls, Search consent/execution, Remote delivery outcomes,
reminders, and Scheduled Work. These events deliberately omit prompt and reply
text, Search queries, complete Discord identities, tokens, credentials, Memory,
Knowledge, Finance data, and authorization payloads. Retrieval and synthesis
are distinct visible lifecycle events. An affirmative Search continuation is
authorization only: synthesis answers the validated original request with the
retrieved evidence, rather than treating `Yes, please.` as the question. A
Search service timeout returns a safe unavailable reply to the DM after
consuming that one-use consent; send a fresh weather/Search request to retry.

Use **Settings → Advanced → Operator Activity Log** to turn normal activity
events On or Off. The preference is durable and defaults to On. Off does not
hide startup failures, fatal failures, serious runtime errors, or sanitized
tracebacks; it is not a debug or transcript log.

The verified owner may send the exact DM command `Terminate Discord connection
now`. Tori durably turns Remote Chat enablement off, advances the existing
delivery/admission generation fence, and disconnects Discord. For safety, the
fence may prevent a final acknowledgement from being sent. The disabled state
survives restart and cannot re-enable itself; enable again locally via Settings
or CLI. Similar wording, guild/group messages, other users, Web conversation,
and model output cannot invoke this operation.

### Recorded human acceptance

Remote Chat V1 is complete and physically human accepted. The recorded
acceptance scope covered: default-off startup; secure
configuration and enablement; sanitized loopback Settings Off/On plus read-only
LAN status; `Hello Tori` through the normal provider; a
context-retaining follow-up; one consent-approved Search; an upcoming-reminder
read; one prohibited action refused with no side effect; restart
reconnect/continuity; disable preventing new DM work/replies; and unaffected
local Web conversation. This checklist remains useful for operational rechecks;
current session-explicit startup requires fresh local enablement before reconnecting.
Automated tests already cover replay, identity attacks,
chunk boundaries, fault ordering, fencing, backup, and shutdown, so exhaustive
manual fault injection is not required.

## 17. Backups

Settings → Maintenance lists published backup metadata and can create a fully verified backup immediately. A natural `Back up Tori` request invokes the same bounded backup action. Normal backups are written beneath sibling `<installation-name>_backups` as directories containing a `project/` payload and manifest. The backup service inventories, copies, verifies, checks source stability, coordinates Coding Work, Remote Chat, Skills, and the Capability Growth journal under their consistency guards, and reports failure rather than publishing an unverified result. Remote Chat's non-secret ledger and dedicated archive are included; its XDG credential/configuration directory and bot token are excluded. Whole-runtime restore preserves and validates the journal; skills.sh results and quarantine/download state are not durable learning. After page refresh, even a backup verified at creation is listed as **not rechecked**: its payload has not been freshly rehashed merely to show the list.

Normal backups include the project and canonical runtime, so they may contain conversations, memory, settings, tasks, and other user data. Rebuildable Python virtual environments named `.venv` are excluded wherever they occur in the project tree, including `deploy/voice/.venv`; adjacent deployment files and Voice model assets under `models/voice/` remain included. Voice model assets are recoverable from the verified backup, but the separate Voice Python environment is not: even on the same machine, restore does not carry `deploy/voice/.venv` through activation. Prepare that environment separately before using Voice Input again. Radicale data under `%h/.local/share/tori/radicale/collections`, the external Finance root, and registered Knowledge source files are outside restore scope and require separate user backups.

**Restore Backup** is an explicit local Maintenance action. Automatic Restore requires a Git checkout whose origin is exactly `https://github.com/rustedtrust/Tori-LocalAI.git` and whose selected backup source commit belongs to its trusted `origin/main` history. The history-free ZIP cannot supply that source-history requirement. `Eligible for verification` means structural publication metadata is valid and the recorded source commit belongs to Tori's fixed public source history; it does **not** certify that the current payload matches its manifest. `Legacy/manual recovery` identifies a backup whose source history cannot be activated automatically; `Invalid` and `Incomplete` entries cannot be selected. Confirmation is one-use and states the boundaries before proceeding. Tori then creates and verifies a new safety backup, fully reverifies the selected backup (including hashes and SQLite integrity), blocks new durable work, stages the exact trusted source, selected Tori-owned runtime and verified `models/voice/` assets outside the live directory, reverifies the selected backup again before handoff, and exits. Only the explicit Voice asset root is recovered from ignored project files; generated browser/review artifacts are not activated. Unsafe links, permissions or a collision with trusted source stop restoration before activation. A failed selected verification stops before staging or activation. A fixed copied helper waits for shutdown and performs a same-filesystem rename swap. It preserves the current root `tori.toml` byte-for-byte, never imports backup `.git`, backup `tori.toml`, or backup `.venv`, and restores Skills disabled where existing restore policy requires fresh local revalidation and enablement. Restore does not download or install Voice dependencies.

After activation the helper restarts Tori and checks the local process, Web endpoint, and runtime initialization without using a model/provider. A structural startup failure triggers one automatic attempt to restore and restart the pre-restore installation. Failure evidence and the new verified safety backup are retained. Restore V1 has no selective-file mode, configuration restore, backup retention, or pruning. It also refuses a source rollback whose pinned dependencies differ from the current verified environment rather than activating a half-compatible installation.

The portable ZIP builder follows the explicit [`public snapshot manifest`](../PUBLIC_SNAPSHOT_MANIFEST.md), includes only reviewed source and the generic [`deploy/portable/tori.toml`](../deploy/portable/tori.toml) at its root, and refuses unexpected or private files. It never reads live installation configuration or runtime. Use `scripts/create-clean-portable-archive` only for a clean installation copy, not for disaster recovery. The root [MIT license](../LICENSE) and retained [third-party notices](../THIRD_PARTY_NOTICES.md) accompany the ZIP.

## 18. Settings

Useful Settings sections include provider/profile management, TTS profiles, explicit desktop-local Voice Input, configured Web Search enablement, Memory navigation, Schedule & Tasks navigation, verified backups, and capability status. Provider profiles are managed in **Models**. **Model Settings** is only a bridge to the implemented conversation-scoped model and context controls; the planned richer standalone Model Settings workspace was not completed. The reviewed MCP Time server is configured in per-machine `tori.toml`; **Skills & MCP** exposes its status and approved inventory but V1 has no arbitrary server or tool-approval UI. Generalized capability administration and appearance preferences remain unavailable. Tori's identity/system prompt is not editable.

**Settings → Night Owl** controls default-Off bounded public research. Select
one or more of the seven fixed categories before turning Night Owl On. This grants
only category-limited Night Owl research through its fixed query templates and
approved public sources; it does not grant normal interactive Search consent or
allow custom queries, prompts, or URLs. Use **Run Night Owl Now** for one bounded
run, or choose On demand only, Nightly, or Weekly. Nightly suggests 02:00 local
time and Weekly suggests Sunday 02:00. Scheduled research uses local civil time,
skips a run missed while Tori is stopped, and does not catch up at startup.
Quiet Hours suppress proactive interruption, not an explicitly scheduled
research run.

The same panel reports running/last/next status and lists compact findings with
source attribution. Source-derived project details, risks, and unknowns are
separate from any section labeled **Model-assisted interpretation**. Use **Mark
reviewed** or **Dismiss** to manage review state. Dismiss removes the item from
the active review list immediately while preserving its history; it cannot be
reviewed or promoted again unless a meaningful source change creates a new
reviewable version. While a run is active, Workspace shows a compact Night Owl
background-research activity item and whether its trigger was on-demand or
scheduled; it never exposes raw queries or retrieved content. A meaningful
later source change may surface a new version. **Promote as EXPAND** creates only an advisory
Capability Growth recommendation; IMPROVE appears only for a compatible open
operational-friction link, and external research cannot create FIX or
`CapabilityEvidence`. Promotion never installs, clones, enables, executes, or
configures anything.

Each enabled category receives three fixed discovery angles. The bounded depth
scales with the category count (up to 21 searches, 84 considered results, and
28 reserved GitHub fetches when all seven are enabled), rather than spending a full-category allowance on a smaller
selection. Each category has its own 12-result consideration ceiling; Skills
catalog candidates use their separate Skills budget. **Last Run Details** shows
only safe counters: elapsed time, used/allowed budgets, GitHub-hosted results,
canonical repository leads, queued and corroborated repositories, truthful
Skills catalog request/candidate outcomes, rejection/failure/budget-skip counts,
terminal reasons, and concise per-category coverage. It
never displays query text, source URLs, snippets, page bodies, or authorization
internals.

Ask “What did Night Owl find?” or “Show me the latest Night Owl findings” to
summarize already-stored findings with attribution. This does not start a run or
turn arbitrary Conversation text into research. **Settings → Proactive
Companion → Night Owl findings** is a separate default-Off permission to offer a
short findings-available check-in. The Proactive Companion master switch, Quiet
Hours, recent-activity suppression, 24-hour cooldown, rolling caps, pause, and
one-unresolved-check-in rules still govern it. No Night Owl check-in speaks
automatically or sends through Discord.

Each finding card begins with **What it is**, a short source-derived explanation
of the project. Select **Details** to expand stored version, risk, unknown,
source, and optional model-interpretation material; this never fetches the
Internet. Ask about a named stored project for more detail, or say **Run Night
Owl** to start the same bounded configured review as the Settings button. Adding
a topic, URL, or custom query to that command is refused: it does not expand
Night Owl’s research scope. Numbered or punctuated references such as “Tell me
more about: 5. owner/project” also read the matching stored finding rather than
starting Search. When a previously stored project is rediscovered unchanged,
Night Owl may improve its source-derived display description without treating
that presentation refresh as a new finding version. If the same project is
successfully reassessed and no longer meets the current relevance policy, it
leaves active review while its historical record remains preserved.

**Security** (`/security`) is a small external threat-intelligence workspace.
Select **Security intelligence** under Settings → Night Owl and enable Night Owl
before using its research action; the existing run still covers every enabled
category. Security lists primary-source advisories, observed dates, CVEs where
present, evidence links, and a conservative Environment Watch match. Details,
Review, Dismiss, and Discuss with Tori act on the selected Night Owl finding.
Discuss prepares one bounded context packet for the next conversational turn;
you decide whether to send the suggested message. Security research is
advisory only and never executes vendor commands. Home may show one compact
attention row for new, relevant CISA KEV intelligence; otherwise it shows no
Security status card. The watch list is research metadata, not a verified
software inventory or vulnerability scan. **Connected Security Systems: No
systems connected** means Tori has no local-alert sources: it does not mean
there were no attacks. See [Security Center V1](SECURITY_CENTER_V1.md).

**Settings → Proactive Companion** controls the physically accepted optional
local Conversation check-ins. The master switch and Morning, Resume work, and Long silence types
all start Off. You can set the morning and quiet-hour windows in Tori's shown
application timezone, pause all check-ins for one day or one week, resume early,
or turn the feature off again. Fixed protections include a 15-minute
recent-activity suppression, a 24-hour global cooldown, and caps of three
check-ins per seven days and eight per 30 days.

The V2 **Attention** card in Workspace records meaningful Tori-owned changes
even when they should not interrupt. It groups **Needs Attention**, **Worth
Reviewing**, and a bounded **Recently Resolved** history. Initial sources are
Research, Delegated/Coding Work, Night Owl, and failed/interrupted or genuinely
missed Scheduled Work. Routine successful schedules are omitted. An exact
active-Project relationship may explain why an item matters, but it never
changes the Project or grants authority.

Use **Review** to mark the item reviewed and move toward its authoritative
source surface, **Later** to defer it for one day, or **Dismiss** to suppress
that unchanged material. These choices survive restart. Timestamp-only source
refreshes do not resurrect an item; a genuinely changed result, outcome,
failure, decision requirement, or Night Owl version may make it eligible again.
Ask **What needs my attention?**, **What changed while I was away?**, **Anything
worth reviewing?**, or **Remind me about that later.** Recognition is bounded,
not a general natural-language task system.

While Tori's Web process is running, application-owned policy checks eligibility
at a bounded interval. The Tori tab may be hidden, unfocused, minimized, or
disconnected; browser state is a presentation/return signal, not a reason to
invent initiative or meaningful activity. A safe
existing active Conversation is still required, and busy or uncertain runtime
state suppresses delivery. An already-open Conversation detects the authoritative
archive revision and renders the check-in automatically; clients that return
later load the same event. Multiple tabs share one archived event and converge
without creating copies. **Dismiss** resolves the current check-in without
deleting its truthful archive history or adding a user message; the adjacent
pause actions resolve that exact check-in and apply the same durable global
pause. Switching, opening, or creating Conversations does not resolve or move
the check-in: its controls disappear while another chat is selected and return
when its still-unresolved target chat is reopened. Unrelated meaningful activity
may reset future silence timing without acknowledging the check-in. A check-in never starts
Search, Coding Work, Planning, Projects, Discord, or another action, and it
never plays automatically through Auto voice. You may use its ordinary manual
**Speak** control; playback does not dismiss or acknowledge the check-in, and
its Dismiss/Pause controls remain available afterward. A real reply still
follows all normal authorization and confirmation rules.

Meaningful attention can accumulate during quiet hours and remains available in
Workspace afterward. A Morning or return brief contains at most three
unsurfaced meaningful items, distinguishes action from review, and is omitted
when nothing changed. It still requires the existing master/type opt-ins and
delivery protections. V2 does not use an elapsed Long Silence timer by itself
as a reason to speak.

Voice Input starts **Off** after every browser or Tori restart. Use the compact **Voice input: Off / Ready** control beside the composer for everyday enable/disable, then grant browser microphone permission when explicitly requested. Select the desired microphone and hold/toggle preference in **Settings → Voice**; the device choice belongs only to that browser. While **Ready**, the browser may keep its selected microphone open locally for prompt capture, but it sends no PCM or transcript to Tori. Hold or toggle push-to-talk changes the state to **Listening** and sends only that bounded utterance; partial text is transient and the nonempty final text enters the same normal Conversation path as typed input.

When **Auto voice** is On, Tori speaks the completed response and Voice Input returns to Ready afterward. Starting PTT while Tori is speaking stops playback immediately. A PTT press alone does not cancel generation: only a valid nonempty final utterance may cancel the exact still-active response before normal admission. Empty, cancelled, or failed PTT preserves useful generation, and a response that completed before that fence remains in the archive normally. Turning Voice Input Off releases browser tracks, clears local audio buffers, releases the recognition lease, and stops Tori's owned recognition runtime and GPU allocation. Wake phrase and passive speech activation are not available.

Voice profiles use one OpenAI-compatible local protocol rather than a vendor selector. Enter a profile name, an approved numeric loopback/private-LAN HTTP endpoint (for example `http://192.168.1.50:8000/v1`), optional model, voice, and timeouts. Tori sends the bounded standard speech request to `/audio/speech` and accepts validated 24 kHz mono WAV output for browser playback. Saving validates configuration only; it does not connect to or select the profile. Existing legacy profiles remain available without being rewritten.

Local bearer tokens are stored server-side in owner-private settings storage and are write-only in the browser. Disabling a profile or capability does not rewrite historical chats or silently migrate selections.

## 18a. Research Worker

When the administrator has configured the hardened local worker, ask for a
substantial objective beginning with **Research**, **Deep research**, or
**Investigate**. Tori presents the exact objective, public-web-only disclosure,
private-data denial, network boundary, and resource limits before anything
starts. Confirming creates one supervised durable Research Job; cancelling the
proposal starts no worker.

Research is distinct from ordinary Search and Night Owl. It may make multiple
unauthenticated GitHub and Hugging Face discovery requests, fetch selected public
pages, prefer official sources,
identify evidence gaps, synthesize a report, and validate material claims. It
does not receive conversation history, Memory, Knowledge, Project notes, local
files, credentials, or browser cookies. A Project association is organization,
not authority. It cannot automatically start Coding Work or change a Project.

Ask **How is the research going?**, **What has the research found so far?**, or
**Stop the research** in the originating conversation. Workspace shows durable
phase, progress, source/primary-source counts, validation summary, report, and
exact source links without raw worker chatter. `completed_with_limits` means a
useful bounded result reached at least one limit; it is not displayed as full
completion. Restarted in-flight work becomes `interrupted` and is not silently
resumed.

Research Worker V1 completed production-worker, isolation, cancellation, restart,
and physical browser acceptance on 2026-09-21. On the accepted host its
`[research]` settings point to a separately prepared external GPT Researcher
wrapper, Python environment, and supervisor. `install.sh` does not install this
wrapper. The PoC contains separate wrapper modules plus a copy of GPT Researcher
at `6f998577d547b1e54ec662dac63583aa11e3b84b`. The inspected upstream
LICENSE is Apache-2.0, while its package metadata declares MIT; resolve this
conflict before redistribution or automatic Research Worker provisioning. The
PoC lacks upstream license material, and its dependency lock lists versions
without artifact hashes.
A reviewed source/provenance/notice/lock build and portable wrapper source must
precede installer support. Do not copy the external working folder or another
research project's venv into a new installation. Research is unavailable until
separately provisioned; removing or unmounting the accepted wrapper disables
Research, not core chat. See the [deployment checkpoint](FINAL_STATE.md#deployment-data-and-recovery-boundaries).

## 18b. MCP Time

When the administrator has enabled the exact reviewed `[mcp.time]` profile in
the per-machine `tori.toml`, ask naturally: **Use MCP Time to get the current
time in America/Chicago**. Tori performs one local read without sending the
request to the selected model. The timezone must be a valid IANA name such as
`UTC`, `America/Chicago`, or `Europe/London`.

Open **Skills & MCP** to see whether MCP Time is configured, enabled, running,
and ready; the negotiated protocol/server version; network/filesystem posture;
discovered and permitted tool counts; schema drift; and the last error. The
official server advertises two tools, but V1 permits only `get_current_time`.
`convert_time` and any newly advertised tool remain unavailable until a future
reviewed scope explicitly approves them.

MCP Time is local stdio, account-free, and network-denied. Tori validates the
server executable, Bubblewrap executable, package and implementation versions,
protocol, tool schema, request, and result on every startup/use boundary. A
changed identity or schema fails closed. Stop Tori with `Ctrl+C` to stop its
owned server. V1 does not install servers automatically and has no remote URL,
marketplace, credentialed server, write/destructive tool, or generic MCP
administration workflow. See `MCP_V1_ARCHITECTURE.md` for the reviewed profile
and configuration semantics.

## 19. Mobile and LAN use

Web mode listens on all IPv4 interfaces and prints usable numeric LAN URLs. Open one from another browser on the same trusted LAN. The responsive UI uses mobile navigation/history and utility sheets; portrait phone use was historically accepted. Landscape phone conversation visibility is a known limitation.

LAN mode is unencrypted HTTP with no login. Every allowed LAN client shares the same Tori process, active chat, and authority surface. Do not expose port 8765 through router forwarding, a public interface, VPN sharing, or an untrusted LAN. Tori does not configure TLS, firewall rules, UPnP, authentication, hostnames, mDNS, or reverse proxies.

## 20. Privacy and data locations

Canonical application data is Git-ignored beneath `runtime/`, including conversations, checkpoints, curated memory, the separate Capability Growth Improvement Journal, Night Owl grants/runs/compact findings, provider settings, Skills, scheduled work, legacy tasks/reminders, TTS profiles, settings, Projects (inside the conversation archive), Coding Work state, and durable Research jobs/reports/source provenance. Night Owl and Research backups do not retain fetched page bodies. Knowledge source documents remain at their registered external paths. Finance lives only at its configured external root. Planning/Radicale lives under `%h/.local/share/tori/radicale/collections`. Normal backups live in the sibling `<installation-name>_backups` directory. Owner-private provider tokens and Remote Chat configuration under `~/.config/tori/`, and installed bounded host helpers, require separate recovery attention; normal restore does not import them.

Conversation text is not written to normal application logs, but archives intentionally contain completed conversation. Search queries and selected public URLs leave the host through the configured search/retrieval path. Local model/OpenAI-compatible profiles receive assembled conversation context according to their configured endpoint.

Never copy `runtime/`, external Finance/Knowledge/Planning data, `.env`, credentials, `.venv`, or the per-machine root `tori.toml` into source distribution. The archive script exports committed source into external temporary staging and publishes only the generic portable template there for this reason. Root `tori.toml` remains local configuration on each machine.

## 21. Troubleshooting and maintenance

- **Import error for `openpyxl` or `caldav`:** activate/use `.venv` and install `requirements.txt`.
- **Provider unavailable:** verify the exact selected profile endpoint and model. Tori will not fall back automatically.
- **Search unavailable:** confirm `[search] enabled = true`, a numeric local/private endpoint, SearXNG JSON support, and network reachability.
- **Finance unavailable:** confirm Finance is enabled, `data_root` is absolute/outside the project, initialization was confirmed, and the workbook is closed and structurally valid.
- **Planning unavailable:** check `systemctl --user status tori-radicale.service --no-pager`, configured collection URLs, and any credential environment variable.
- **Scheduled item did not wake the machine:** Tori cannot wake or start the host; restart Tori and review the missed-run result.
- **Coding Work unavailable:** verify the configured exact OpenCode version, executable, Bubblewrap, runtime root, provider upstream, and readiness diagnostics. Isolation failure has no unrestricted fallback. OpenCode **1.18.31 is intentionally pinned**; installing a different CLI version reports `opencode_wrong_version` and does not silently broaden compatibility. An older 1.18.21 offline-bootstrap receipt is not valid for 1.18.31: separately review and explicitly prepare matching bootstrap material before expecting full readiness. This version-contract update alone does not establish live ACP/provider/sandbox compatibility. Tori disables OpenCode auto-update in its managed processes but cannot prevent an external manual CLI update.
- **Research unavailable:** verify the explicit `[research]` paths, hardened wrapper entrypoint, local Ollama models, Bubblewrap/user-namespace support, mounted secondary drive, and configured SearXNG endpoint. Research uses unauthenticated GitHub/Hugging Face primary discovery and a tightly relayed SearXNG secondary path; it does not use cloud/search APIs or unrestricted-network fallback. If every approved provider fails, Tori returns a truthful limited result rather than model-memory research.
- **MCP Time unavailable:** inspect **Skills & MCP** for the exact last error. Verify the reviewed package and SDK versions, executable and Bubblewrap paths/hashes, `mcp-time` implementation version, approved schema digest, and Linux user-namespace support. Do not bypass a drift error or substitute an unrestricted process; update approval only through a separately reviewed change.
- **Unsafe Coding Work state / backup not published:** a backup now reports `backup_unsafe` when Coding Work private-state validation fails. It does not skip that state or publish an unverified backup. New snapshot output is finalized only after its owned writers stop, and terminal success is not published before that finalization; orderly shutdown waits for this step. Existing unsafe files, a hard application/host interruption before finalization, or an unsafe import require a separately reviewed repair. Do not recursively chmod/delete runtime or clear work history. An explicitly waiting OpenCode worker or pending finalization still blocks backup until safely quiescent.
- **Backup maintenance returns `backup_in_progress`:** keep the terminal used for the normal owner `./start-tori.sh` launch open and inspect its private `tori.operator` error line `backup.maintenance.failed` immediately after a failed attempt. `stage` distinguishes overall entry, individual `guard_enter`/`guard_exit`, backup `body`, and completion; `guard` is a fixed subsystem identifier, `error_type` is the exception class, and `message` is an allowlisted safe label or `redacted`. If cleanup also fails, `final_stage` and `final_error_type` identify that masking failure. The browser, model, Discord, and Research receive none of these diagnostics. Tori does not persist a separate operator log: console visibility lasts only as long as the operator's terminal or privately managed console capture. An exit failure can occur after a verified backup was published; inspect the existing catalog before any separately approved follow-up. Do not retry until green, clear locks, or treat the generic response as proof of a specific guard failure.
- **LAN browser cannot connect:** use a printed numeric private IPv4 URL, ensure both devices are on the same trusted LAN, and check host firewall policy manually.
- **Corrupt/unsupported runtime store:** stop and preserve it. Tori fails closed and normal startup does not perform an unapproved migration. The archive reader retains an explicitly enumerated compatibility path for legitimate application-event metadata written by Tori's retired experimental Deep Research workflow; it does not accept arbitrary event types or write new retired events.
- **Improvement Journal unavailable or full:** preserve the owner-private file and inspect the reported error. Tori does not repair an unsafe/corrupt store or discard active findings to make room. Do not edit, copy live, chmod, or delete canonical journal state as routine cleanup.

For maintenance, stop Tori with `Ctrl+C`, create and verify a normal backup before deliberate runtime work, keep Finance/Radicale backups separate, and run `./scripts/verify-milestone` after repository changes. Do not copy a live SQLite database without the application backup workflow merely because its main file appears idle.

## 22. Commands

Open **Commands** in the browser for a reference to supported slash commands and
their graphical equivalents. Natural-language requests are the usual way to
work with Tori. `/search`, Memory, Knowledge and Finance slash commands remain
usable where listed above. Supervised Terminal uses its own local drawer and
approval flow; the browser Commands page does not advertise `/run` as a normal
command. `/exit` and `/quit` stop an interactive CLI session, not the Web server.

## 23. Known V1 limitations

- No LAN authentication, TLS, multi-user isolation, IPv6, or safe Internet exposure.
- No cloud/public model provider product, automatic routing/fallback, or model download/management.
- Voice Input V1 is physically accepted for desktop/local-host push-to-talk with manual PTT barge-in. There is no wake phrase, passive activation, hands-free follow-up listening, mobile/LAN microphone capture, far-field guarantee, or raw-audio retention. TTS remains output-only; normal Voice profiles are protocol-oriented and use Tori's bounded OpenAI-compatible local speech contract. Existing legacy Qwen/Kokoro profiles remain readable through their retained adapters.
- Research Worker V1 is complete and physically accepted. It has one hardened GPT Researcher implementation, unauthenticated GitHub/Hugging Face primary discovery, bounded SearXNG secondary discovery, local Ollama/embeddings, no browser-login research, no private Tori context, no automatic Night Owl launch, no Research-to-Coding chain, no cloud fallback, and no worker resume after restart. Night Owl remains human-accepted and independently bounded to its fixed categories. MCP V1 is limited to the one reviewed account-free local Time server and one read tool. Agent Plugins, automatic Skill updates/creation, general agents, durable MCP credentials, MCP writes/additional transports, arbitrary servers, and a generic plugin registry remain absent.
- Knowledge is exact-file `.txt`/`.md` retrieval, not folder ingestion, PDF ingestion, embeddings, or crawling.
- Tori does not directly generate images. She can discuss image generation and Night Owl may research image-generation tools, but researching a tool is not generating an image. Direct integration is deferred.
- Finance has no bank connection, money movement, automatic statement watching, legacy OFX/QFX, arbitrary PDF parsing, full accounting, or automatic reset/delete workflow.
- Planning lacks full calendar grids, attendees, broad natural-language time interpretation, and recurrence exceptions.
- Scheduled Work cannot wake a stopped/sleeping host; recurring verified backups are intentionally unavailable.
- Projects & Continuity V1 is complete and manually live-accepted; the earlier Milestone 25 checkpoint remains a distinct frozen, incomplete, and unaccepted historical Project foundation. Projects provide bounded continuity, context, and organization, not autonomous workspaces or capability authority.
- Coding Work has one OpenCode adapter and strict existing-workspace/sandbox boundaries; no Git commit/push or general network authority.
- Backup retention and pruning remain manual; Restore V1 is whole-runtime only and preserves current machine configuration.
- The full V1 closeout was not comprehensively re-tested on every physical device. Recorded feature-specific acceptance, including later explicit physical-iPhone acceptance where stated, remains valid within its documented scope.
