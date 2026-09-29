# Security Center V1

**Status:** V1 implemented and accepted for closeout. Security Center is an awareness and
conversation workspace, not a security product or local monitoring system.

## Boundary

`/security` shows **external threat intelligence** retained in Night Owl's
existing versioned findings, source attributions, and `new` / `seen` (Reviewed) /
`dismissed` lifecycle. A future **local security alert** would be an event from
an independently operated endpoint, LAN, IDS, AV, or SIEM system with source
system/event/asset/severity/time/evidence identity. V1 defines this type only:
there is no producer, alert store, sensor, webhook, poller, listener, inbound
alert API, or connected security product. “No systems connected” conveys no
claim about safety, attacks, vulnerabilities, or compromise.

## Research and evidence

The default-Off Night Owl grant now offers Security as a seventh category.
Enabling it in Settings explicitly replaces the Night Owl grant. On-demand
and existing Scheduled Work runs still process **all enabled categories**.
Three fixed search queries look for individual CISA KEV-addition alerts, Ubuntu notices and NVIDIA product
security; only narrowly allowlisted primary CISA, Ubuntu, NVIDIA and Mozilla
advisory URL forms may be fetched. Discovery titles and snippets cannot become
findings. The separate Security branch fetches at most three admitted primary
pages per run with no redirects, a 512 KB body / 6,000-character text cap per page and Night Owl's
existing source policies, grants, run budgets, deduplication and receipts.
NVIDIA bulletins hosted on the vendor's `nvidia.custhelp.com` answer service
are admitted only at exact bulletin answer-ID paths. One candidate per fixed
discovery angle is considered before a second from any one angle.
Live isolated acceptance confirmed dated CISA KEV-addition alerts and Ubuntu
Security Notice pages with this normal Night Owl path. The local SearXNG
backend also returned generic pages on repeated queries, so zero findings in
a run is not a claim that no applicable advisories exist. A legitimate NVIDIA
bulletin URL was discovered intermittently. A bounded inspection through the
same source-retrieval port received HTTP 403 from the vendor; V1 retains the
fail-closed no-redirect/no-authentication boundary rather than claiming NVIDIA
bulletin coverage on that evidence.
Corroborated GitHub research in the other categories remains unchanged.

Only primary-source text with an explicit CVE, or a relevant CISA campaign
advisory, can create a Security finding. Application-authored title and summary,
validated CVE identifiers, a fingerprint of the cited evidence window, publisher/source URL, observation
timestamps, run association and the matched watch family are stored; raw pages,
scripts, search snippets and instructions are not. A CVE found in the retrieved
CISA KEV catalog, or in a CISA alert explicitly stating that it was added to
KEV near the CVE, can be labeled a KEV listing; this describes exploitation in
the wild, **not** exploitation locally. A partial or unavailable source never
becomes positive evidence. `Relevant` requires both KEV evidence and an
Environment Watch family match; `Watch` requires a family match; `General` has
neither. This is a deliberately narrow initial funnel, not exhaustive CVE
coverage or a guarantee of timely detection. Published dates and installed
versions are not inferred; observation timestamps describe Tori's research.
Selected catalog findings are keyed by their leading cited CVE rather than
collapsing every page update into one finding; unrelated page changes do not
reopen a reviewed CVE.
For a multi-CVE advisory V1 retains only the leading cited CVE in its brief;
the linked primary advisory is the place to inspect other CVEs and products.
This prevents a watch-family match near one CVE from being asserted for every
entry in the same page.

## Environment Watch and presentation

Environment Watch is a static, bounded list of research interests: Ubuntu /
Kubuntu, Linux kernel, NVIDIA/CUDA, OpenSSH, Firefox, Python and Ollama/local AI.
This list is **not** a verified installed-software inventory. Source/publisher
and product phrases in the retrieved primary evidence support a relevance
match, but no host package, version, service, port or LAN inspection occurs.
The Security Briefing shows high-interest, watch and recent findings, the last
Security-category Night Owl run and a link to Night Owl settings. Run Night Owl
research uses the same existing on-demand run authority. The evidence view
contains only text and links to admitted HTTPS source forms; external links
open separately with `noopener noreferrer`. Dismiss and Review use Night Owl's
revision-bound review endpoint. Capability Growth promotion of Security
intelligence is disallowed: advisory source text is not operational evidence.

The existing Home attention card shows one compact Security row only for new
KEV-listed findings also matching Environment Watch, linking to Security. It
does not display a permanent sensor status. Companion Initiative's generic
Night Owl attention cohort excludes Security to avoid treating unrelated
Security Watch findings as proactive check-ins.

“Discuss with Tori” accepts one displayed, current finding ID/revision and
prepares a single bounded in-memory context packet. It contains only that
finding's canonical summary, watch matches, CVEs, observed times and primary
source references; no raw HTML, unrelated history or model interpretation.
The next conversation turn consumes the packet and disables the model terminal
proposal handler for that response, regardless of terminal whitelist state.
The packet clears after the turn or a chat change; the browser does not submit
automatically. Research data remains untrusted and cannot install, execute,
grant authority, patch, change firewall configuration or remediate anything.
Any later user-requested command is independently governed by Supervised
Terminal and its normal human/policy gates.

## Persistence and future integration

No schema migration or Security-specific copy of findings is needed. Night Owl
continues to own grants, runs, evidence, revisions, backups and retention.
Future alert integration requires a separately authorized design for source
identity, authentication, evidence retrieval, deduplication and trust; the
internal `SecurityAlert` type does not provide ingestion authority.
