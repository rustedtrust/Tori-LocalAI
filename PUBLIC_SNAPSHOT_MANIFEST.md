# Public snapshot manifest — initial public preview

Source: tracked `v0.9.0` export only, independently sanitized. This manifest defines the separate public source snapshot. `scripts/create-clean-portable-archive` must use this inclusion policy rather than `git archive` or a wholesale worktree copy.

## Keep public (reviewed for the candidate)

- Root: `.gitignore`, `README.md`, `CHANGELOG.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `SECURITY.md`, `CONTRIBUTING.md`, `install.sh`, `start-tori.sh`, `requirements.txt`, the explicit `PUBLIC_SNAPSHOT_FILES.txt` list and this manifest.
- Product source: `src/tori/`, including the web assets, after origin and path review.
- Public tests: `tests/` after fixture sanitization. These are synthetic tests, not test-run data.
- Deployment: `deploy/portable/`, `deploy/radicale/`, `deploy/system/`, and the tracked source and instructions in `deploy/voice/` (no virtual environment or model assets).
- Support scripts: the tracked `scripts/` programs, subject to candidate-only archive-builder and restore changes.
- Founding documents: `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`; retain intact pending any separately approved foundational change.
- Public product documentation: `docs/README.md`, `docs/ARCHITECTURE_GOVERNANCE.md`, `docs/CAPABILITY_GROWTH_V1_ARCHITECTURE.md`, `docs/COMPANION_INITIATIVE_V1_ARCHITECTURE.md`, `docs/COMPANION_INITIATIVE_V2_ARCHITECTURE.md`, `docs/CONVERSATION_BEHAVIOR_CONTRACT.md`, `docs/DELEGATED_WORK_V1_ARCHITECTURE.md`, `docs/FINAL_STATE.md`, `docs/FINANCE_V1_CONTRACT.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/MCP_V1_ARCHITECTURE.md`, `docs/NIGHT_OWL_V1_ARCHITECTURE.md`, `docs/PLANNING_CALDAV_CONTRACT.md`, `docs/PROJECTS_CONTINUITY_V1_ARCHITECTURE.md`, `docs/REMOTE_CHAT_V1_CONTRACT.md`, `docs/RESEARCH_WORKER_V1_ARCHITECTURE.md`, `docs/SECURITY_CENTER_V1.md`, `docs/SKILLS_V1_ARCHITECTURE.md`, `docs/SUPERVISED_TERMINAL_V1_ARCHITECTURE.md`, `docs/TARGET_ARCHITECTURE.md`, `docs/USER_GUIDE.md`, `docs/VOICE_INPUT_V1_ARCHITECTURE.md`, the three `docs/design/*_CONTRACT.md` provider contracts, and `docs/design/TTS_PROFILES_DESIGN.md`.
- Dated technology reviews (not private acceptance artifacts): `docs/research/DEEP_RESEARCH_TECHNOLOGY_AUDIT_2026-08.md`, `docs/research/DEEP_RESEARCH_V1_CONTRACT.md`, `docs/research/REMOTE_CHAT_DISCORD_SDK_REVIEW_2026-09-08.md`, `docs/research/REMOTE_CHAT_ECOSYSTEM_REVIEW_2026-09-04.md`, and `docs/research/TARGET_ARCHITECTURE_DRAFT_2026-08.md`. Review for privacy before packaging.

## Sanitized publication boundary

`README.md`, `CHANGELOG.md`, `docs/README.md`, `docs/USER_GUIDE.md`, `docs/FINAL_STATE.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/RESEARCH_WORKER_V1_ARCHITECTURE.md`, public absolute-path references in other contracts, and owner-correlated locations/endpoints in `tests/` were reviewed for the initial public snapshot. Public Restore must retain exact origin/source-history verification; installation-root portability must not be regressed by replacing paths blindly.

## Exclude from the initial public snapshot

- Private acceptance/evaluation records: `docs/VISUAL_REFRESH_V1_REVIEW.md`, `docs/REALTIME_STT_POC_RESULTS.md`, `docs/RESEARCH_WORKER_V1_ACCEPTANCE_2026-09-21.md`, `docs/RESEARCH_WORKER_V1_GAP_AUDIT.md`, `docs/MILESTONE_21_LIVE_ACCEPTANCE.md`, `docs/MILESTONE_7_CONVERSATION_EVALUATION.md`, `docs/PERSONALITY_INTERACTION_V1_EVALUATION.md`.
- Internal governance/reporting material: `AGENTS.md`, `docs/DEVELOPMENT_WORKFLOW.md`, `docs/CODEX_FINAL_REPORT_TEMPLATE.md`.
- Private metadata/data and generated material: `.git/`, `runtime/`, root `tori.toml`, `.env*`, `.venv/` (any depth), `models/`, `artifacts/`, `backups/`, external user/Finance/Knowledge/Planning data, logs, caches, screenshots, databases and sidecars. The private backup is never an input.

## Bundled third-party material with retained notices

`src/tori/web_assets/vendor/xterm/` includes both complete upstream MIT license files; `deploy/voice/NOTICE.md` retains upstream interface provenance and full MIT notice. `THIRD_PARTY_NOTICES.md` indexes those retained notices. Declared Python dependencies, external Research code, Voice models, and environments are **not** bundled in this file list; their separate distribution and license review is not implied by this source snapshot.

The maintained packaging allowlist must enumerate the public documentation above explicitly and fail closed on unknown files or excluded categories. Exclusion is not permission to break public links; update referring documentation in the candidate.

The reviewed file-by-file inclusion list is `PUBLIC_SNAPSHOT_FILES.txt`. The source ZIP deliberately has no Git metadata and removes references to reachable private commits; the separate public Git repository must have new history. Automatic Restore is pinned in both components to exactly `https://github.com/rustedtrust/Tori-LocalAI.git` and also requires verified `origin/main` ancestry; a caller-provided remote cannot change that default. GitHub Private Vulnerability Reporting must be enabled and verified before publication; no personal security contact address is published.
