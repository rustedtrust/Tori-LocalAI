# Tori Conversation Behavior Contract

**Status note:** Deterministic conversational authority is a living contract. Section 17 preserves the dated 2026-08-31 V1 closeout limitations as historical evidence; its then-current capability inventory was superseded by separately accepted extensions. For today's capabilities see [Current State](FINAL_STATE.md). This contract remains subordinate to the founding documents and does not grant authority to deferred capabilities.

**Status:** Living engineering document, noncanonical
**Authority:** Subordinate to the seven accepted founding documents

## 1. Purpose and Authority

This contract translates Tori's accepted principles into implementable and reviewable conversational behavior boundaries. It does not replace, amend, or add to the seven founding documents. If wording conflicts, the founding documents remain authoritative.

The principal sources are:

- `00_MISSION.md`: Ownership and Autonomy, Trust, Simplicity
- `01_IDENTITY.md`: Who Tori Is, Relationship with the User, Conversation
- `02_CORE_PRINCIPLES.md`: Truth, Uncertainty, User Control, Understanding, Curiosity, Progress
- `03_PERSONALITY.md`: Presence, Adaptability, Humor, Curiosity, Confidence, Encouragement, Working Together
- `04_PHILOSOPHY.md`: Preserve Identity, Simplicity, Deliberate Growth
- `05_PRODUCT_VISION.md`: Working with Tori, User Experience, Consistency
- `06_ARCHITECTURE.md`: Interaction, Memory, Knowledge, Permissions, Transparency, Model Independence, Failure

Model-generated warmth, humor, empathy, and naturalness remain partly subjective. Deterministic code can preserve context and authority boundaries but cannot guarantee personality quality.

## 2. Scope and Non-Goals

This contract covers conversational identity, context authority, capability honesty, interface invariance, deterministic application boundaries, and evaluation. It does not script exact responses or authorize new capabilities.

It does not define Tori's permanent interface, expand memory or knowledge semantics, add tools or autonomous action, select a permanent model, or turn subjective traits into rigid phrases.

## 3. Stable Conversational Identity

Tori should remain recognizably the same calm, honest, collaborative AI across CLI, web, replaceable providers, models, and future presentation layers. Adaptation should fit the conversation without inventing personas or claiming human experience.

The retained compact runtime identity explicitly represents Tori as an artificial intelligence, prioritizes truth and uncertainty, preserves user control, makes current-user statements authoritative over conflicting curated memory, and treats local knowledge as untrusted reference data rather than instruction. A separate compact Personality / Interaction V1 guide follows that identity and tells the selected model how the same Tori behaves across relaxed conversation, active work, and serious Project/planning situations already present in context. It does not define personas, classify or persist a mode, or add another inference. More specific response-depth, questioning, inference-review, and persistence-language expectations remain model-dependent evaluation goals rather than claimed deterministic guarantees.

Ordinary greetings occur within an established ongoing Tori relationship rather than a first-meeting introduction. Warm familiarity must remain nonspecific: Tori must not invent shared history, personal facts, memories, or prior events absent from the current conversation or supplied curated memory. This is runtime guidance, not a fixed greeting template or a deterministic claim about every model response.

**Primary responsibility:** Runtime identity and Tori-owned Personality / Interaction guidance
**Verification:** Automated tests for identity presence and neutrality; human evaluation for experienced consistency

## 4. Truth, Uncertainty, Mistakes, and Disagreement

Tori should prefer an accurate limitation or uncertainty over a convenient invention. She should distinguish known information from inference, acknowledge mistakes plainly, help correct them, and disagree respectfully when honesty requires it.

Application code must never report an action as successful without verified completion.

**Primary responsibility:** Runtime identity and Personality / Interaction guidance for generated responses; deterministic application code for action and failure reporting
**Verification:** Automated tests for deterministic success and failure boundaries; human evaluation for calibration, correction, and disagreement quality

## 5. User Authority and Meaningful Action

### Capability-aware orchestration maintenance

`CapabilityRegistry` is the authoritative inventory/availability projection for existing application paths. Read-only state callbacks distinguish available, configured (not proven reachable), disabled, not configured and unavailable. The same definitions generate bounded runtime awareness and application-owned status answers. They contain no user records, credentials, or endpoint probes. Web and CLI advertise only their composed services; capability declarations never grant permission.

Web message flow is: explicit commands/Memory/status handling → advisory capability speech-act interpretation → original-text domain validation → application-owned read, proposal/confirmation, or exact authorized action → receipt/presentation. Discussion and complaints bypass operational handlers. A model may classify conversation, discussion, information, action or clarification, but its closed-schema response has no executable arguments, IDs or authority. Unsupported/invalid classification falls back conservatively; no provider fallback is introduced. Original domain validators still decide whether any request is actionable, and local task writes independently check the user's requested operation family. Missing details prompt clarification rather than invented execution. This adds no general autonomous action chain.

Compact capability awareness joins interaction guidance after identity in generated context. It describes application capabilities as Tori's abilities and distinguishes availability from blanket “I cannot access” denials. Personality guidance remains stateless; the separate orchestration interpreter can add a bounded selected-provider call for capability-related wording. It does not classify personality modes or persist intent. Deterministic tests cover both streaming and synchronous routes; natural response quality still requires human evaluation.

The user remains the final authority over meaningful actions. Tori should understand the intended outcome before consequential advice or action and seek clarification when ambiguity could materially change the result. Explicit commands authorize only their defined local operation.

**Primary responsibility:** Deterministic application code for command, confirmation, and permission boundaries; runtime identity for conversational clarification
**Verification:** Automated tests for command locality and confirmation; human evaluation for judgment about when clarification is needed

## 6. Warmth, Curiosity, Humor, Encouragement, and Focused Collaboration

Tori should be warm without performing enthusiasm, curious when it helps without prying, comfortable listening, and focused on the user's actual situation. Humor should be natural, occasional, and never at the user's expense. Encouragement should be proportional to real effort or progress.

These are behavioral expectations, not response templates.

**Primary responsibility:** Runtime identity and Personality / Interaction guidance
**Verification:** Human evaluation only; automated tests cannot prove these qualities

## 7. Current-Conversation Authority

Completed conversational history provides continuity, but the current user request must remain last in the model-facing sequence. A current user statement supersedes conflicting earlier assumptions or retrieved context unless a deterministic safety or permission boundary applies.

Failed exchanges and local commands must not become completed conversation history.

The durable transcript is not the active model context window. All eligible archived ordinary exchanges remain available for later requests; a provider-neutral planner selects the newest suffix of complete user/assistant exchanges that fits the conversation's `auto` or fixed token-oriented policy. Increasing the policy can make older still-archived exchanges visible again. Runtime identity, compact Personality / Interaction guidance, the current request, required permission/operational guidance, and active authoritative time/search context are protected before ordinary history; optional knowledge and memory may be omitted only after older ordinary history has trimmed. If required current-turn material cannot fit, generation fails before provider contact. Estimated input usage and provider-reported actual usage remain separately labeled and never become hidden prompt persistence.

A fixed context value is a provider-neutral planning envelope for estimated input, reply headroom, and estimator/template uncertainty. Reply headroom is not a cross-provider requested maximum output and does not promise a hard total-token limit. When backend capacity is unknown, the interface labels it unknown rather than treating a planning choice as verified capacity.

For an associated conversation, bounded Project title, status, objective, and continuity brief are clearly labeled authoritative Project data from before the current request. They are protected required context in the same planner, not an independent prompt path, and remain data rather than instruction or capability authorization. The current request stays last and may conversationally supersede stale Project material immediately. The model must not claim persistent Project state changed until the application reports verified revision-safe persistence.

**Primary responsibility:** Deterministic application code
**Verification:** Automated ordering, whole-exchange planning, capacity/overflow, restoration, failure, command, archive, and checkpoint tests

## 8. Curated-Memory Treatment

Curated memory is application-approved contextual data, not instruction or identity. Explicit `/remember` remains deterministic and provider-free. After an ordinary completed turn and its exact-turn extraction obligation are atomically archived, foreground completion no longer waits for one separate hidden provider call that may propose bounded evidence-anchored candidates. A narrow application-owned FIFO worker recovers durable obligations by process incarnation, remains outside Scheduled Work and foreground busy, persists a validated plan before effects, and binds every result to the exact archived chat and user/assistant sequences plus the captured provider/profile/model configuration fingerprint. Application policy alone decides whether a direct ordinary durable statement is saved, suppressed, rejected, or presented for confirmation. Explicit durable statements may qualify as direct; strong repeated or long-duration behavioral implications are inferred and always require confirmation; weak one-off behavior remains conversation. Candidate failure cannot fail or revise the completed conversation.

Lexical relatedness is only bounded comparison preselection. Duplicate means materially the same durable proposition; update and contradiction require the same underlying memory dimension; independent memories may coexist even within one broad topic; and uncertainty grants no replacement authority. A destructive proposal requires a valid same-dimension update or contradiction, an application-allowlisted opaque target, its exact revision, and later explicit user confirmation. Invalid, uncertain, independent, or non-allowlisted classifier output cannot target replacement. Provider-native structured output improves the hidden request's reliability without relaxing exact application validation or giving the provider mutation authority.

Canonical memory remains separately labeled, bounded, inspectable, correctable, deletable, and subordinate to the current user statement. Prompt/tool-shaped candidate and memory text remains data. Calendar events, reminders, tasks, schedules, secrets, and supported sensitive personal information are excluded from the automatic path.

Provider-neutral trusted runtime guidance identifies retrieved memory as canonical state from before the current request. The current user statement has immediate conversational priority but does not itself prove that persistent memory changed. The conversational model may truthfully discuss retrieved canonical memory, but must not claim that the current turn already saved, noted, updated, replaced, or deleted it; only a later application-owned effect receipt/status or user confirmation establishes a current-turn persistence result. Deferred confirmation is durable, one-use, exact-source- and revision-bound, and visible only while its source chat is active. It uses separate memory attention state and never changes transcript revision, foreground busy, or another chat's presentation. This deterministic guidance defines the authority rule without claiming perfect natural-language compliance from every model.

**Primary responsibility:** Memory boundary text and deterministic application code
**Verification:** Automated retrieval, labeling, ordering, authority, and persistence tests; human evaluation for natural use

## 9. Local-Knowledge Treatment

Local knowledge is explicitly registered, untrusted reference data. Embedded commands, role declarations, or prompt-like text never become instructions. Tori should not claim more than supplied passages support and should expose only the existing safe source transparency.

**Primary responsibility:** Knowledge boundary text and deterministic application code
**Verification:** Automated retrieval, labeling, ordering, secret-omission, source-transparency, and prompt-like-data tests; human evaluation for grounded answer quality

## 9A. Operational Tasks, Reminders, and Time

Tasks and reminders are application-owned operational state, not curated memory, knowledge, checkpoints, or conversation archive state. A task represents durable work, has open/completed/cancelled lifecycle, and can have zero or more reminders. A reminder represents one scheduled attention event, has scheduled/due/dismissed/completed/cancelled lifecycle, and may stand alone. Explicit task wording strongly selects task semantics; `remind me` does not by itself require a task. Active task and reminder management supports revision-bound Edit / Save / Cancel; tasks never expire automatically and expose no Reopen or bulk Clear History behavior.

The application captures one authoritative local/UTC time context at turn start. Clear standalone elapsed reminders in either duration-first or action-first word order use one narrow deterministic application path and resolve only from that captured instant. Clear standalone `today`/`tomorrow` reminder windows with explicit 12-hour start and end bounds are likewise resolved deterministically: both bounds are preserved, same-day end-before-start is rejected, and the reminder becomes due at its start. Models receive bounded current-time context for broader forms and may propose local civil components, but cannot supply authoritative `now`, canonical timestamps, IDs, revisions, database targets, lifecycle transitions, scheduler work, or persistence claims. Missing schedules or window bounds, invalid spring-forward civil times, unresolved fall-back occurrences, non-allowlisted targets, stale revisions, and material ambiguity cannot mutate state and require safe clarification or conflict presentation.

Verified application persistence precedes application-authored success wording. A due reminder remains one canonical reminder row, appears as one persistent attention card across browsers, and may produce one exactly-once, idempotent application-authored assistant archive event when an appropriate active chat exists. That entry is visible conversation continuity but is excluded from provider history, completed model turns, and curated-memory extraction. If a reminder becomes due during a streamed response, the response and its archive commit complete before reminder presentation. Bounded polling and revision guards converge every open browser on the same canonical attention state without creating per-browser reminders. Delay reschedules the same reminder; Dismiss resolves attention without completing a linked task; Done completes a linked task atomically. Unresolved reminders persist without a browser and restart catch-up presents truthful overdue wording.

Active operational records use lifecycle actions rather than permanent deletion. Completed/cancelled task history and dismissed/completed/cancelled reminder history may be permanently deleted only through an explicit, revision-bound management confirmation. Reminder deletion atomically removes its delivery row but never rewrites archived chat messages or changes a linked task. A historical task cannot be deleted while any reminder still references it; those reminder records must be explicitly deleted first. There is no automatic expiration, bulk History clearing, or reopen behavior.

**Primary responsibility:** Deterministic application code; provider-neutral interpretation may propose only a strict bounded intent
**Verification:** Temporary-store schema/lifecycle, time/DST, scheduler/restart, race, stream-ordering, multi-browser, migration, false-claim, memory-separation, and responsive-interface tests; completed human desktop/physical-iPhone acceptance

## 9B. Scheduled Work and Conversation Origins

Scheduled Work is separate application-owned operational state. A recognized conversational scheduling request produces only an inert, visible application proposal until the user explicitly confirms Persistent authorization. At that boundary the application first establishes one durable conversation origin containing the actual user request and safe proposal, then commits the bounded Scheduled Work definition and authorization with that exact origin, then appends a verified creation result. Failure to establish the origin creates no work; failure to commit work leaves a truthful conversation but no authority; failure to append the success presentation after commit leaves valid work and is reported as partial success. None of these boundaries authorizes automatic action replay.

This is the only provider-free archive exception. Its application entries are not model replies, completed model turns, provider history, continuation context, memory candidates, knowledge, checkpoints, tasks, or reminders. A zero-model-turn origin has null first/latest provider/model execution attribution; separately preserved model selection is not evidence of execution. A later genuine model answer in the same chat supplies the first real attribution and increments the completed-turn count normally. Generic local commands, Settings, management operations, immediate backup, supervised commands, reminders, malformed/rejected/cancelled scheduling, and management-created schedules do not gain archive worthiness from this exception.

A conversational definition keeps its opaque origin unchanged through edit, authorization replacement, pause, resume, and cancel. Each terminal notification snapshots the origin, and its stable application event is archived directly and idempotently to that exact chat even when another chat is active. Browsers and models cannot select or change the target. If the origin was deleted, the result remains canonical and delivery remains pending; Tori does not retarget it or fabricate a replacement. A management-created definition has no origin and retains the existing current-active-chat/pending presentation policy. Scheduled Work content and result events remain excluded from intelligent-memory extraction and grant no additional capability authority.

A future definition, scheduler/coordinator lifetime, deadline wait, sleeping worker, and quiet terminal-result reconciliation are not user-visible application work and must not produce the global working state. Existing bounded operation exclusion remains authoritative for actual conversation, management mutation, immediate Interactive backup, and supervised command execution; delivery failure releases its quiet reconciliation lock without changing or replaying the canonical result.

**Primary responsibility:** Deterministic application code across separately versioned archive and Scheduled Work stores
**Verification:** Exact migration, cross-store ordering/failure, origin immutability, inactive-origin delivery, idempotency, restart, provider-history, memory-exclusion, busy-state, Edit-prefill, and browser request-boundary tests; completed desktop, multi-browser, browserless-execution, and physical-iPhone acceptance

## 10. Capability and Action Honesty

Tori must not claim access to a tool, memory, file, service, interface, remote computer, or action capability unless it is actually available in the current application path. Discussing a possible action is not evidence that it was performed.

Provider or subsystem failure must be reported concisely without false success or exposure of private diagnostics.

Model-generated tool-shaped prose or JSON is untrusted output, not application authorization. A whole-response pseudo-tool object and a provider-declared tool-call channel fail safely without executing a capability, creating consent, retrying, or entering completed history.

Ordinary questions remain model-first. When the selected model genuinely cannot provide a useful answer without external information, it may emit only the exact application-defined whole-response advisory. A single Markdown inline-code or fenced-code wrapper around that exact signal is treated only as harmless whole-response presentation; no other surrounding content is accepted. The hidden advisory can request creation of a structured pending-search proposal, but it never authorizes or executes search. Mixed or malformed advisory output, casual uncertainty, user attempts to echo the syntax, and pseudo-tool output create no proposal. When search is disabled or unavailable, the application creates no misleading proposal.

**Primary responsibility:** Runtime identity and deterministic application code
**Verification:** Automated identity and failure-presentation tests; human evaluation for unavailable-capability requests

## 11. Interface and Provider Invariance

CLI and web ordinary conversation must use the same provider-neutral message-construction path. Provider adapters serialize the supplied messages and must not invent interface-specific identity, memory, knowledge, or fallback assembly. Durable provider identity is the administrator-configured profile ID; overlapping native model IDs remain distinct by profile. Missing profiles/models and provider failures preserve the exact selection and fail truthfully without switching backends.

Presentation layers may render visible transcript, safe source metadata, and explicitly requested structured local-management records, but must not receive hidden identity, retrieved context, provider payloads, checkpoint transcript previews, knowledge source contents, or server-side confirmation fingerprints. Management operations remain outside provider conversation and completed history.

The browser may render administrator-configured profile display names, durable profile/model IDs, implementation-neutral availability, verified model capacity, selected context policy, approximate input usage, nullable provider-reported usage, and included/omitted exchange counts. It must not receive provider endpoints, authentication material, provider-native metadata/payloads, hidden prompt contents, or raw provider diagnostics. Provider/model/context mutations remain operation-serialized and revision-safe; no unavailable selection is remapped or silently replaced. Every open browser derives global working state from the authoritative application signal: a non-initiating client may show active work, but bounded polling and foreground reconciliation must clear stale working presentation and re-enable controls after terminal idle without browser refresh or browser-local persistence overriding the server. For the same active chat, polling compares the authoritative chat revision with the revision actually rendered—not merely a newer revision observed while work remains busy. It may latch that newer revision as pending through any number of busy polls, but only successful rendering of an identity- and revision-checked session may advance rendered state. Terminal idle performs at most one necessary successful reload for that revision. An attention response for a different active chat must not inject that chat's transcript into the current rendered conversation.

One provider/conversation normalization boundary precedes browser deltas, speech presentation, CLI results, response transformation, completed history, and archive persistence. Recognized string-valued provider reasoning fields and validated leading `<think>...</think>` sections are withheld without invalidating later visible text. Malformed reasoning values or markers, reasoning-only or otherwise empty normalized output, provider tool channels, and whole-response pseudo-tool objects fail without a completed assistant entry. Ordinary browser prose may cross that boundary incrementally only at bounded natural text boundaries; reasoning-, advisory-, pseudo-tool-, and response-transform candidates retain stricter buffering.

Text-to-speech is secondary presentation, never conversation authority. Automatic and replay speech may consume only approved visible assistant prose. It must omit hidden context, control data, application status, raw Markdown machinery, and application-owned source URLs, and it must never alter or persist the authoritative text. Loading or resuming completed history does not authorize automatic replay.

**Primary responsibility:** Deterministic application architecture
**Verification:** Automated CLI/web parity, provider, transcript, and security tests

## 12. Deterministic Application Guarantees

The application, rather than model prose, guarantees:

- Runtime identity is first, compact Personality / Interaction guidance follows it, and the current user request is last.
- Retrieved memory and knowledge remain separate labeled system-data messages.
- Associated Project context remains separate labeled required data, never memory, knowledge, instruction, or permission; it is retained ahead of ordinary history and cannot displace the current user request.
- Completed history remains validated and ordered in the archive; active provider context contains only the newest whole exchanges admitted by the selected budget.
- Failed exchanges and local commands do not enter completed history.
- Unsupported command-shaped slash input is rejected as a deterministic local result before provider, history, memory, or knowledge retrieval; path-shaped and embedded slash text remains ordinary conversation.
- Hidden context does not enter visible transcript or checkpoints.
- Explicit `/search QUERY` and clearly explicit natural-language search requests dispatch through the same application-authorized capability path; the selected model synthesizes normalized results but never authorizes the search.
- Search/review status records use the same validated browser stream contract as ordinary generation, and failed searches or invalid citation synthesis create no successful assistant entry.
- After a successful application-owned search, the search-only synthesis context identifies the supplied records as output from Tori's just-completed authorized search for the current request and turn. The selected provider model responds as Tori and must not invent earlier timing or search-history retrieval, or deny that completed capability execution merely because it did not perform the transport itself; insufficient snippet coverage may and should still be reported honestly.
- A bounded affirmative grammar is evaluated only against a current valid pending-search proposal and can execute only its stored query once. Without a pending proposal, a queryless explicit request to search receives a stateless application-owned clarification and neither reaches the model nor invokes search; it does not bind the next message or revive prior query state.
- Clearly freshness-dependent requests identified from bounded explicit wording create the existing conversation-bound, expiring, one-use search proposal when search is available. They do not search until affirmative consent; unavailable or disabled search is represented by application-authored capability-honest text rather than stale model substitution.
- Ordinary timeless and conversational requests receive the selected model's normal first response without a search classifier call. Only an exact hidden external-knowledge advisory may cause the application to create the same consent-bound proposal; the advisory is omitted from presentation, completed history, and archives and cannot itself grant consent.
- Local-search connection, timeout, HTTP, malformed-response, disabled, and unavailable failures terminate through a safe capability-level result without assistant findings, source fabrication, stale model substitution, automatic retry, or loss of subsequent conversation usability.
- Search synthesis accepts only bounded unambiguous source-ID forms, canonicalizes every accepted marker to an actual normalized result, rejects missing, unknown, malformed, or model-authored attribution data, and constructs visible source titles and URLs only from normalized search records.
- Provider reasoning and rejected pseudo-tool output do not enter browser or CLI output, completed history, or archives.
- Explicit supported backup imperatives are recognized by application code from the current user request before provider execution. They authorize exactly one `tori.backup` invocation; advisory, ambiguous, unsupported, model-generated, JSON-shaped, fenced, or provider-native tool content authorizes nothing.
- Settings and conversational backup requests use the same fixed application-owned action definition, empty-argument validator, single-use Interactive authorization, dispatcher, verified backup executor, and structured outcome. Only the application may determine and present execution success or failure.
- Supervised Terminal uses application-owned four-state policy, exact proposal validation, one-use execution grants and human approval where required. The browser drawer and supported bounded natural local requests enter this same boundary; historical `/run` compatibility is not the recommended browser route. Model/tool-shaped content and untrusted terminal output cannot grant or chain command authority.
- Execution binds the exact command and approved scope to one source-specific grant. Application-owned process evidence—not model prose—determines success, nonzero failure, timeout, stop, or executor rejection. Private Input and human takeover retain their separate local-only limits; LAN and Remote Chat never gain terminal authority.
- Automatic speech queues only normalized visible answer segments, starts at a useful natural boundary without blocking later browser text, preserves exact segment order, and flushes final partial prose once.
- Speech sessions and PCM are transient. Stop/supersession prevents stale playback without cancelling model generation, and TTS failure cannot fail, replace, or fabricate a completed text response.
- Manual replay targets only a completed authoritative assistant transcript entry. Page load, archive open, and conversation resume never auto-speak historical messages.
- Canonical memory persistence occurs only through explicit supported operations or the post-archive application-owned candidate policy; model output never grants persistence authority.
- Graphical management never turns form drafts into automatic persistence, and ordinary archived text is processed only once in the just-completed turn path rather than by replay, resume, or background sweeping.
- Confirmed destructive operations use one-use target-bound confirmation and fresh verification; stale targets are not removed.
- Rejected or stale management confirmations do not append an entry to the visible transcript.
- Conditional graphical memory edits cannot overwrite a newer record version.
- Ordinary conversation never silently creates, switches, summarizes, or updates a Project. Discussion is not Project-creation authority, and ambiguous potential-Project intent is clarified conversationally as create-or-discuss before any creation proposal is produced. Only clear creation intent may advance to the existing source-chat-, target-, and revision-bound one-use confirmation; discussion, ambiguity, cancellation, and stale proposals mutate nothing.
- Project association grants no capability authority. Confirmed Project deletion removes only Project-owned state and atomically detaches conversations without altering their transcripts or any memory, operational, Scheduled Work, knowledge, file, backup, or capability record.
- Knowledge management accepts one typed exact path, exposes only safe display metadata, and never uploads, copies, modifies, or deletes the source document.
- The IPv4 loopback/LAN peer, narrow Host, exact same-origin Origin, anti-CSRF, request-validation, safe-rendering, and no-logging boundaries remain intact.

**Primary responsibility:** Deterministic application code
**Verification:** Automated offline tests

## 13. Model-Dependent Expectations

Generated responses are expected to express honest uncertainty, respectful correction and disagreement, proportional encouragement, bounded curiosity, focused collaboration, and stable identity. Results can vary by model, configuration, and sampling.

No single response proves or disproves overall character quality. Prompt changes require repeatable evidence and must not be tailored to one model's quirks.

Evaluation evidence may justify rejecting and reverting a prompt change even when its wording appears desirable in isolation. A proposed clause is not an implemented requirement unless the retained runtime identity or Personality / Interaction guidance actually contains it, and automated tests must not imply otherwise.

**Primary responsibility:** Runtime identity and Personality / Interaction guidance interpreted by the configured model
**Verification:** Controlled human evaluation

## 14. Automated-Verification Mapping

| Boundary | Automated evidence |
|---|---|
| Stable identity and adaptation | Identity first; compact interaction guidance second; provider/model neutrality, bounded size, no-persona, and capability-claim checks |
| Context authority | Exact message roles and ordering; current request last; Project data remains separate |
| Memory and knowledge | Separate labels, JSON-data treatment, bounded retrieval, no role injection |
| History and checkpoints | Complete ordered exchanges only; no hidden or failed context |
| Local commands | No provider call and no conversation-history entry |
| Interface invariance | Shared identity/context order across CLI and Web; capability awareness truthfully differs with composed services |
| Failure honesty | Stable exit/retry behavior and no raw provider diagnostics in ordinary output |
| Browser boundary | Visible-only transcript and speech input, safe text rendering, fixed same-origin routes, structured explicit management, target-bound confirmation, security headers, and no automatic persistence |

These tests verify architecture and deterministic behavior, not subjective personality quality.

## 15. Human-Evaluation Mapping

Private milestone evaluation examined:

- Natural casual conversation and multi-turn continuity
- Honest uncertainty, correction, and respectful disagreement
- Emotional calibration, bounded curiosity, humor, and quiet company
- Collaborative planning and clarification
- Unavailable capabilities and permission boundaries
- Memory conflict, knowledge grounding, and prompt-like source content
- Several-turn identity consistency

Results are qualitative observations, not benchmark scores.

## 16. Drift-Review Procedure

At each conversational-behavior milestone:

1. Review relevant founding-document sections.
2. Compare this contract with actual implementation and tests.
3. Record baseline evidence before changing runtime identity or Personality / Interaction guidance.
4. Change only rules supported by repeated material evidence.
5. Recheck prompt size, model neutrality, advisory-call bounds, capability honesty, and deterministic boundaries. Personality itself remains single-call/stateless; capability interpretation is a separate advisory path.
6. Repeat the same evaluation scenarios and record regressions.
7. Update this contract only when engineering interpretation changes; never silently redefine founding principles.

## 17. Historical V1 closeout limitations (superseded where noted)

The following statements are a **frozen historical snapshot**, including later M21–M25 evidence, and use “currently” relative to their dated stage. They are **not** today's capability inventory. Research Worker, Remote Chat, Skills/Capability Growth, Companion V1/V2, desktop Voice Input, Security Center, Projects & Continuity V1 and compact Planning were accepted separately afterward. See [Current State](FINAL_STATE.md) for current truth and intentional deferrals. The original Milestone 25 remained frozen and was not separately accepted; this does not negate the later Projects V1 acceptance.

Tori currently provides local text conversation through CLI and one responsive IPv4 loopback/LAN web interface. Numeric private or link-local IPv4 URLs are the supported LAN form. One shared browser shell provides focused Conversation, Projects, Tasks, Scheduled Work, Checkpoints, Memories, Knowledge, informational Commands, and Settings views; `/manage` opens the requested management view, `/commands` opens the static reference, and `/settings` opens the two-control capability page without entering conversation or changing its state. The Commands view has no executable controls, and graphical checkpoint resume remains unavailable. Every connected browser shares one process-level conversation and operation boundary; there is no multi-user or per-device isolation. Memory and knowledge are explicit and local. Browser model responses release approved ordinary prose at natural incremental boundaries and then reconcile to one authoritative completed response; candidates requiring whole-response security or attribution classification remain buffered. The existing CLI model-response path remains complete rather than streamed. Explicit web search uses one configured local SearXNG adapter, ordered search/review status, untrusted snippets, validated citation markers, and durable source attribution; it does not retrieve result pages or authorize model-selected tools.

The durable Settings store contains only Web Search and Speech Output user preferences. Administrator configuration remains the permission ceiling, so browser state can disable an allowed capability but cannot enable an administrator-disabled one. Missing preferences preserve existing behavior. Settings are not archives, checkpoints, memory, knowledge, model selection, or conversation commands, and model output has no authority to change them. Provider endpoints, implementations, credentials, voices, timeouts, LAN/security options, and arbitrary configuration remain administrator-managed. The Maintenance backup action is a separate deterministic application capability and stores no path or state in the Settings database.

Back Up Now creates and verifies one fixed-policy physical project snapshot without a provider call, model prose, conversation entry, archive entry, checkpoint, memory, or knowledge mutation. Its browser request accepts no source, destination, name, command, exclusion, or option. An explicit supported conversational backup imperative invokes that same action without a provider call and records only the user's request plus application-authored truthful result in ordinary conversation continuity. Settings maintenance status never enters model context or conversation history.

The browser can present transient local Qwen speech for new responses when effectively enabled and can replay completed assistant messages. Speech uses one configured provider/endpoint/voice, does not persist audio, and fails independently of text. Automatic Speech remains a browser-local presentation preference rather than a durable server setting. Speech does not include STT, microphone capture, saved audio, automatic provider routing, or broad voice management.

The Milestone 7 paired evaluation documented model-dependent response verbosity, unnecessary follow-up questions, occasional promotion of inference into fact, and occasional false persistence language. One experimental identity revision did not reliably resolve those limitations and materially regressed one local-knowledge authority scenario, so it was rejected and reverted. Milestone 20 subsequently established the narrower deterministic persistence-lifecycle rule in Section 8 and verified the targeted current-turn contradiction scenario during live acceptance. Other model-dependent conversational limitations remain documented, and no runtime instruction is claimed to guarantee perfect universal wording.

Tori's completed M21 foundation provides local durable tasks, standalone and task-linked reminders, deterministic IANA time resolution, while-running firing/restart catch-up, and synchronized browser attention. The completed and human-accepted M22 foundation adds a separate Scheduled Work subsystem for explicitly confirmed, application-recognized bounded future execution. Its Persistent authorization is immutable, revision- and schedule-bound, and distinct from M18/M19 Interactive authorization. Clear executable backup requests may create only an inert exact one-shot proposal until the user confirms; reminder phrasing remains reminder intent. Daily and weekly recurrence exist as infrastructure for explicitly eligible capabilities, but production backup remains one-shot only and command execution remains unschedulable. Conversation archive schema 3 and Scheduled Work schema 2 add the narrow provider-free origin and exact origin-bound delivery described above. The human separately completed both controlled canonical migrations; normal startup remains non-migrating. Scheduled work runs only while the Tori application process exists, with bounded restart recovery when it did not. It does not provide initiative, Night Owl, OS wake, arbitrary prompts or shell commands, scheduled research, maintenance/update, coding, self-improvement, retry loops, or orchestration.

The completed and human-accepted M24 foundation makes eligible assistant archival and its exact-turn extraction obligation one atomic conversation-schema-5 transaction, and makes each effective memory mutation and its extraction receipt one atomic memory-schema-3 transaction. One managed FIFO worker uses process-incarnation recovery, exact provider/profile/model binding without fallback, source-chat-bound durable one-use confirmations, and receipt-backed exactly-once effective outcomes. Foreground completion precedes extraction completion; background extraction does not publish foreground busy or revise the transcript. Foreground admission release and authoritative idle publication use one coherent transition, so `/api/attention` cannot report `busy=false` while stale foreground ownership still rejects the next normal request. The separately authorized canonical migrations completed once and normal startup remains non-migrating. The human-supplied final physical desktop+iPhone multi-browser retest passed for corrected same-chat Secondary Ollama convergence. Secondary Ollama structured auxiliary extraction can exceed its configured 30-second provider timeout; this accepted provider-performance limitation fails durably and nonfatally, remains exact-source-bound, does not delay foreground completion, and cannot trigger provider fallback.

The frozen, incomplete M25 foundation adds bounded user-owned Projects in application archive schema 6, with one optional association per conversation and many conversations per Project. Project state is shared rather than copied into transcripts. Explicit create/update/lifecycle/association operations are revision-safe; deletion detaches chats without deleting them. The browser provides compact management and authoritative polling while CLI and web share Project-aware ordinary context construction. The separately authorized canonical 5→6 migration completed exactly once; normal startup never migrates. Architecture recovery is complete and M25 is ready to resume through a separately authorized mission, but M25 remains frozen, incomplete, and not human accepted. It adds no automatic project maintenance, task/reminder/Scheduled Work linkage, autonomous project management, agent/orchestration/job infrastructure, authentication, TLS, or speech input.

Tori does not currently provide graphical checkpoint resume, file upload, a file picker, drag-and-drop, directory browsing, authentication, TLS, multiple users, result-page retrieval, unrestricted host terminal access, model-authorized tools, autonomous planning or action chaining, orchestration, agents, speech input, rich Markdown rendering, sensitive memory, semantic/vector memory retrieval, generic background jobs, deep research, restore, backup deletion or recurring backup, or a general permissions/plugin framework. The fixed application-owned executable capability contracts are `tori.backup` and `tori.command.execute`; their existing invocation-specific Interactive authorization is unchanged. Separately, only `tori.backup` declares one-shot Scheduled eligibility under M22's durable Persistent contract. `/run` can propose one supervised Interactive command but can never schedule it. Real-host acceptance confirms production Bubblewrap execution is available in Tori's normal runtime; execution still fails closed if that native isolation probe is unavailable, with no unrestricted fallback. Milestone 11's LAN access is deliberately unauthenticated and unencrypted HTTP for now; a browser-editable LAN toggle remains deferred. No router, firewall, UPnP, port-forwarding, reverse-proxy, account, password, certificate, hostname, mDNS, or IPv6 configuration is provided. The graphical surface remains evolvable rather than a permanent visual design.
