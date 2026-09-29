# Security policy

## Supported releases

Tori is an early public preview derived from a private-testing checkpoint.
Security fixes are considered for the **latest public preview**; older previews
may not receive backports.
No response time, fix, or coordinated disclosure date is guaranteed.

## Private vulnerability reports

Use GitHub **Private Vulnerability Reporting** on
[`rustedtrust/Tori-LocalAI`](https://github.com/rustedtrust/Tori-LocalAI):
**Security → Advisories → Report a vulnerability**. GitHub Private
Vulnerability Reporting is enabled for this public repository. If the
reporting action is unavailable, do not put an unpatched vulnerability,
exploit, credential, or private user data in a public issue; no personal email
address is designated as an alternate security contact.

Include the affected public version/commit, reproduction steps using
synthetic data, expected versus observed behavior, impact and boundary, and
suggested remediation if known. Avoid real transcripts, credentials, database
copies, full private logs, and private endpoint details. The maintainer will
review reports as availability permits and may coordinate a fix and disclosure
with the reporter; there is no guaranteed timetable.

For ordinary non-sensitive bugs, use public issues without attaching private
runtime state. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Scope and deployment

Tori is local-first companion software, **not** a SIEM, IDS, EDR, vulnerability
scanner, or managed security service. Its Web service may be reachable on a
trusted LAN and does not provide general Internet-facing authentication or TLS;
do not expose it to untrusted networks. Optional model, Discord, search, voice,
research, and other external services have their own security and privacy
boundaries and must be configured separately by users.
