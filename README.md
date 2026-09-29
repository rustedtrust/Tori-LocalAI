# Tori

> **Technology changes. Character endures.**

Tori is a local-first AI companion for Linux. Conversation is her main interface; models and integrations are replaceable, while identity, continuity, privacy, honest failure, and human control remain Tori-owned. She does not treat model suggestions or retrieved content as permission to act.

**Release status:** `v0.9.0-public.1` is an **early public preview** derived
from a sanitized private testing checkpoint. The runtime reports
`0.9.0-public.1`; the matching public Git tag has a `v` prefix. This is not
a production-ready or v1.0 release. Tori is an independent project, not an
official OpenAI product.

## What works today

- Responsive Web chat and CLI with automatic conversation archives, explicit checkpoints, per-chat provider/model/context selection, curated Memory, and live retrieval from registered individual `.txt`/`.md` Knowledge files.
- Consent-bound Web Search via SearXNG; separately authorized, durable public-web Research Worker jobs; and default-Off, category-limited Night Owl advisory research.
- Projects & Continuity, a compact Planning/CalDAV workspace, tasks and reminders, and bounded Scheduled Work. Companion check-ins and attention are opt-in and suggestion-only.
- Skills lifecycle and advisory Capability Growth; a reviewed, read-only local MCP Time tool; confirmed Delegated Work through OpenCode; and local-only Supervised Terminal with policy, approval, and human takeover.
- Desktop push-to-talk Voice Input, optional local TTS playback, and default-Off, owner-private Discord Remote Chat with restricted capabilities.
- Security Center (external advisory intelligence, not a vulnerability scanner); deterministic Finance/Budgeting over an external workbook (no bank connections or payments); bounded host reads and confirmed fixed service controls; verified backup and whole-runtime Restore. Automatic Restore requires a Git installation whose `origin` exactly matches the approved public repository and whose selected backup source is in its trusted `origin/main` history; the history-free ZIP is for fresh installs, not automatic Restore.

Capabilities depend on their configured providers and local readiness. Tori does **not** directly generate images: she can discuss image generation or use Night Owl to research relevant tools, but research is not image creation. See the [current-state checkpoint](docs/FINAL_STATE.md) for boundaries, deferrals, external dependencies, and closeout-gate status; see the [User Guide](docs/USER_GUIDE.md) for actual usage.

## Install and start

On Debian/Ubuntu-family Linux, use Python 3.11+, the matching `python3-venv`, and a reviewed source checkout or portable ZIP. Git is needed for Git-checkout development and source-history Restore; Node.js is needed for frontend verification. Install into a writable absolute directory; Tori derives its runtime location and sibling backup destination from that installation. To obtain the public Git source:

```bash
git clone https://github.com/rustedtrust/Tori-LocalAI.git Tori
cd Tori
```

In that source directory (or the directory containing the reviewed ZIP contents):

```bash
./install.sh --non-interactive
./start-tori.sh
```

Open `http://127.0.0.1:8765/` and stop with `Ctrl+C`. The installer creates a project-local environment and a missing generic `tori.toml` from [`deploy/portable/tori.toml`](deploy/portable/tori.toml); it preserves existing configuration and refuses an existing `runtime/`. Installation fetches the declared Python packages but **does not** install a model, model weights, or connect a provider. Configure a separately running Ollama, LM Studio, or another supported endpoint later through Settings. Provider failures do not trigger a silent cloud fallback. Hardware requirements beyond Linux/Python depend on the selected model and optional integrations.

Research Worker needs a separately prepared external wrapper; its upstream
implementation is not bundled. Voice Input needs a separate Python 3.12
environment, compatible local GPU/CUDA support and separately obtained model
assets; neither weights nor that environment are bundled. SearXNG, TTS servers,
Discord, OpenCode, and Radicale services also require separate setup. See the
[User Guide](docs/USER_GUIDE.md#2-requirements-and-first-setup) for their
boundaries. A fresh installation creates empty application state on first use:
it contains **no** existing chats, memory, Finance or Knowledge data, models,
Discord credentials, or private backups.

The [User Guide](docs/USER_GUIDE.md#2-requirements-and-first-setup) covers optional setup, privacy, recovery, and troubleshooting. In an installed Git checkout, `./scripts/verify-milestone` runs the offline repository gate (including Node.js syntax checks); it needs both Git metadata and the installed `.venv`. A portable ZIP deliberately has no Git metadata. Nothing in fresh source restores user data: existing data needs a verified backup and deliberate recovery. Automatic Restore only accepts source commits in the trusted public repository history; external Finance, Planning, and Knowledge data need separate recovery.

## Privacy and security

Tori keeps its canonical chats and settings in local, ignored `runtime/` stores.
This public source distribution intentionally includes **no personal user dataset**,
runtime database, production configuration, or private development Git history;
that is a reviewed packaging boundary, not a guarantee about third-party
integrations. You choose any external providers and credentials you configure;
their services have their own privacy policies. The Web server may be available
to other devices on your LAN, with no general-purpose login or TLS; use only on
a trusted network and never expose it to the Internet.

Do not include secrets, conversation excerpts, private logs, or personal
screenshots in public issues. See [SECURITY.md](SECURITY.md) for GitHub's
private vulnerability reporting route and [CONTRIBUTING.md](CONTRIBUTING.md) for
contribution guidance. Tori's Security Center is an advisory information
feature, not a SIEM, IDS, EDR, or security scanner.

## Documentation

- [User Guide](docs/USER_GUIDE.md): daily operation, Settings, Commands, and backup/restore.
- [Current state](docs/FINAL_STATE.md): authoritative implementation checkpoint, boundaries, deferrals, and next closeout gates.
- [Documentation map](docs/README.md): architecture, contracts, acceptance, and historical research.
- [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md): implementation history and current boundaries.
- [Founding documents](docs/00_MISSION.md) through [architecture](docs/06_ARCHITECTURE.md): protected product definition; [architecture governance](docs/ARCHITECTURE_GOVERNANCE.md) and [target architecture](docs/TARGET_ARCHITECTURE.md) guide approved changes.

Tori is standard-library-first with narrow pinned production adapters. Changes to capabilities and authority require deliberate scope and review; historical designs are not standing implementation authorization.

## Licensing

Tori-owned source is licensed under [MIT](LICENSE). Bundled third-party
frontend assets retain their own full MIT license notices; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Separately installed Python
dependencies, Voice models, and the external Research Worker are not contained
in the source ZIP and retain their own terms.
