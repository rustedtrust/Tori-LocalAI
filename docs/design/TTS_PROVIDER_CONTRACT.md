# Tori Text-to-Speech Provider Contract

**Project:** Tori

**Document:** TTS Provider Contract

**Status:** Approved, implemented, and human accepted through Phase H.5 across Qwen and Kokoro

**Authority:** Subordinate to `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`, `docs/ARCHITECTURE_GOVERNANCE.md`, and `docs/TARGET_ARCHITECTURE.md`

## 1. Purpose

This document defines the future Tori-owned boundary between speech-output policy and replaceable text-to-speech implementations.

Tori may use Qwen3-TTS, Kokoro, Chatterbox, an OpenAI-compatible speech service, or another local or explicitly configured network service. Those technologies are adapters. They do not define Tori, own Conversation behavior, or receive authority. Replacing one conforming adapter with another must not require redesigning Conversation, speech-session coordination, permissions, or the browser audio path.

This is a capability-specific contract, not a generic plugin framework. It does not select the next provider, authorize an integration, add a dependency, define STT, or approve a runtime migration.

The first implementation layer establishes the provider-neutral request, audio, identity, validation, status, and error values in `tori.tts_provider`; moves the current Qwen HTTP behavior into an allowlisted compatibility adapter; and keeps `SpeechCoordinator` responsible for segmentation, ordering, cancellation, and canonical audio validation. Phase H.2 adds an explicitly configured Kokoro adapter. Phases H.4A, H.4B, and H.5 add canonical revision-safe profiles, Settings management, a bounded legacy compatibility seed, and runtime profile selection. Provider and voice discovery remain deferred.

## 2. Governing principles

The boundary follows these rules:

- Tori owns identity, speech policy, user intent, configuration authority, provider selection, interruption, and truthful failure presentation.
- A TTS provider performs bounded synthesis and returns audio or a typed failure. It has no identity, judgment, permission, or action authority.
- Speech is presentation derived from already-approved visible text. Audio is never canonical conversation truth.
- Provider output cannot grant permissions, trigger actions, change settings, write memory, mutate Projects or tasks, or alter the transcript.
- Configuration changes are explicit, user-controlled, validated, and revision-safe.
- No provider is added, enabled, selected, probed, or contacted automatically.
- Local and self-hosted providers are preferred. Any external transmission requires an explicitly configured provider and an honest indication of its network boundary.
- A provider failure must leave the text response and canonical archive successful and usable.
- Provider-specific fields and protocol quirks remain inside the adapter that needs them.

## 3. Scope

This contract covers:

- provider and profile identity;
- configuration and connection validation;
- model and voice discovery where supported;
- availability and capability status;
- streaming synthesis;
- canonical audio exchange expectations;
- cancellation and cleanup;
- safe errors;
- profile selection; and
- migration from the current Qwen-specific construction path.

It does not cover:

- speech-to-text or microphone capture;
- wake phrases or continuous listening;
- conversational turn-taking redesign;
- audio persistence or voice cloning policy;
- automatic provider installation or discovery;
- arbitrary remote credentials or secret storage;
- a generic capability registry, event bus, or plugin loader; or
- selection of Qwen3-TTS, Kokoro, Chatterbox, or any other engine as the preferred implementation.

## 4. Ownership boundary

### 4.1 Tori-owned responsibilities

Tori owns:

- whether speech output is administrator-permitted, user-enabled, and effective;
- which saved TTS profile is selected;
- when visible assistant text may be spoken;
- speakable-text normalization and exclusion of hidden reasoning, controls, source URLs, and rejected output;
- segmentation, ordering, queuing, backpressure, session lifetime, and one-active-session policy;
- manual replay, automatic speech, Stop Speaking, supersession, and cancellation semantics;
- request identifiers and correlation without exposing transcript contents in logs;
- validation of text, profile fields, endpoint boundaries, model and voice identifiers, audio limits, and provider results;
- the canonical internal audio format accepted from an adapter;
- same-origin delivery to clients and browser playback behavior;
- bounded timeouts, response-size limits, and safe error mapping;
- authoritative profile persistence, revision conflicts, enablement, deletion, and selection;
- truthful availability presentation; and
- all permission, security, privacy, and audit policy.

Tori decides why and whether synthesis occurs. A provider never makes that decision.

### 4.2 Provider-owned responsibilities

A provider adapter owns only the implementation details required to synthesize speech:

- translating a validated Tori request into its native request;
- mapping Tori model and voice identifiers to supported provider identifiers;
- authenticating to its configured endpoint through an approved credential mechanism, if later authorized;
- performing bounded connection and response handling;
- decoding or normalizing native audio into the contract format when the adapter can do so without leaking provider details;
- yielding ordered audio frames promptly;
- closing transport resources on completion, cancellation, or failure;
- reporting supported discovery and streaming features honestly; and
- translating native failures into typed, safe Tori provider errors.

An adapter must not inspect unrelated state, select another provider, silently fall back, persist audio, modify canonical data, or interpret audio as instructions.

### 4.3 Client-owned responsibilities

The web client remains a replaceable presentation client. It may display profile/status data supplied by Tori, request a permitted profile change, receive Tori's same-origin audio stream, and play or stop that stream. It does not validate canonical configuration, contact provider endpoints directly, store authoritative profiles, or decide provider fallback.

Voice and provider selection belong primarily in Settings. Conversation may retain compact Auto Voice, Speak, and contextual Stop controls, but it should not become a provider-management surface.

## 5. Contract model

The implementation should use a narrow application-owned port. Names below are normative concepts; exact Python names may be refined during implementation.

```python
class TextToSpeechProvider(Protocol):
    def capabilities(self) -> TTSProviderCapabilities: ...
    def validate_configuration(self) -> TTSConfigurationValidation: ...
    def availability(self) -> TTSAvailability: ...
    def list_models(self) -> tuple[TTSModelDescriptor, ...] | None: ...
    def list_voices(self, *, model: str | None) -> tuple[TTSVoiceDescriptor, ...] | None: ...
    def stream(self, request: TTSSynthesisRequest) -> Iterator[TTSAudioChunk]: ...
```

This is not a reflective plugin API. Tori constructs an adapter from an allowlisted provider type through explicit application wiring. Adding a provider means adding one conforming adapter and its contract tests, then making that type deliberately available. Importing arbitrary user code or discovering executable modules is outside the contract.

### 5.1 Synthesis request

`TTSSynthesisRequest` contains only bounded synthesis inputs:

- opaque request identifier;
- normalized visible text;
- selected model identifier, or `None` when the provider has no model choice;
- selected voice identifier;
- requested Tori audio format;
- optional portable generation controls only after their shared meaning is proven; and
- a Tori-controlled deadline or cancellation context.

It must not contain permissions, action tokens, system prompts, hidden reasoning, full conversation history, memory, Project context, credentials, or browser state.

The adapter must either honor a supplied portable field or return a clear unsupported-configuration failure. It must not silently ignore a field that can materially change output.

### 5.2 Audio chunk

`TTSAudioChunk` contains:

- ordered audio bytes;
- the declared audio format, either on the first chunk or through an immutable stream descriptor established before audio; and
- optional provider-neutral timing metadata only if later needed and validated.

It contains no executable instruction, authority result, transcript mutation, or provider-defined UI payload. Unknown metadata is rejected rather than forwarded.

### 5.3 Capability description

`TTSProviderCapabilities` truthfully declares:

- native streaming support;
- model discovery support;
- voice discovery support;
- whether a model is required;
- supported canonical output formats;
- supported portable generation controls; and
- bounded adapter/version information useful for diagnostics.

Capability description is not availability. A provider may support streaming while its configured endpoint is currently offline.

## 6. Profile model

TTS profiles prevent repeated configuration entry and provide an explicit replacement boundary. The design should follow the useful patterns of the existing LLM provider profiles—stable identity, human display name, explicit enablement, revision-safe mutation, safe validation, and authoritative server-side state—without reusing their LLM-specific schema or pretending the domains are identical.

A canonical `TTSProfile` should conceptually contain:

- `identifier`: stable opaque Tori-owned identifier;
- `display_name`: user-facing profile name;
- `provider_type`: allowlisted adapter type such as `openai_compatible_tts` or another explicit adapter identifier;
- `endpoint`: normalized API root or service location when applicable;
- `model`: selected model identifier or `None`;
- `voice`: selected voice identifier;
- `enabled`: whether the profile may be selected or contacted;
- `connect_timeout_seconds` and `read_timeout_seconds` within Tori limits;
- `authentication`: an allowlisted mode, with any future secret referenced through a separately approved secret boundary rather than stored in UI state;
- `provider_options`: a bounded, adapter-scoped structure only for options that cannot be portable;
- `revision`: monotonic optimistic-concurrency revision;
- `created_at` and `updated_at`; and
- optionally cached discovery metadata with an explicit observation time, never presented as current health.

The active TTS profile identifier is separate canonical Tori configuration. Selecting a profile does not delete or rewrite another profile. A disabled, missing, invalid, or stale selected profile makes speech unavailable honestly; Tori does not silently select another profile.

Profile creation, editing, enablement, deletion, and selection require explicit user actions. Mutations use expected revisions so multiple clients converge through authoritative refresh rather than overwriting each other. Deleting an active profile must require selecting another valid profile or explicitly disabling speech first.

This contract alone did not authorize a profile store. The separately approved TTS Profiles Design and H.4/H.5 implementation now provide the dedicated schema and bounded compatibility initialization path.

## 7. Configuration and validation

Validation occurs at distinct layers:

1. **Shape validation:** types, lengths, allowlisted provider type, identifiers, timeouts, option keys, and forbidden control characters.
2. **Endpoint policy validation:** allowed schemes, host/address boundary, port, path, authentication mode, redirects, and credential handling.
3. **Adapter configuration validation:** required model/voice fields and provider-specific combinations, without network contact where possible.
4. **Explicit connection validation:** a user-requested bounded probe or discovery call that reports observed availability without saving configuration automatically.
5. **Selection validation:** the selected profile exists, is enabled, passes stored validation, and supports the selected model/voice combination.

Saving valid configuration and proving current reachability are separate operations. An offline local provider may still be a valid saved profile. Conversely, a reachable endpoint is not valid merely because it responds.

The initial implementation should retain Tori's current numeric IPv4 loopback/RFC1918 LAN restriction unless a separate security design explicitly authorizes a broader endpoint boundary. A future external provider requires HTTPS, explicit user configuration, deliberate credential handling, and clear disclosure that speech text leaves the local machine.

Validation never installs a service, scans the network, follows arbitrary redirects, discovers providers automatically, or turns on speech.

## 8. Availability and discovery

Tori exposes status with separate, non-misleading dimensions:

- **configured:** profile fields are complete and valid;
- **enabled:** user permits this profile to be selected;
- **selected:** this is the active profile;
- **reachable:** the last explicit or bounded operational check reached the service;
- **available:** the profile is configured, enabled, selected where relevant, reachable, and supports its selected model/voice;
- **degraded:** synthesis may work but discovery or another nonessential function failed; and
- **unknown:** no current check has been made.

Status includes a safe reason code and observation time. It does not expose raw response bodies, credentials, internal paths, transcript text, or network diagnostics unsuitable for the user.

Model and voice discovery is optional. `None` means unsupported; an empty tuple means supported but no entries were returned. Discovery results are untrusted input: Tori bounds count and text length, validates identifiers, removes control characters, and never treats returned names or metadata as instructions. Discovery is initiated only by an explicit Settings action or a narrowly justified bounded refresh; it is not an automatic LAN scan.

## 9. Streaming contract

Streaming exists to preserve fast, low-latency speech while text generation continues.

For each synthesis request:

1. Tori validates and segments visible text.
2. The coordinator submits ordered segments to the selected adapter.
3. The adapter begins yielding canonical audio as soon as useful audio is available; it must not buffer the entire result when it declares native streaming.
4. Chunks are yielded in playback order and exactly once.
5. Tori applies bounded backpressure and response-size limits.
6. Stop or supersession closes the active iterator and underlying transport promptly.
7. Completion means the adapter reached a clean terminal end. An empty, truncated, malformed, or late stream is a failure.

An adapter that lacks native streaming may be supported only if it declares that fact. Tori may expose higher latency honestly and stream a completed bounded result to the client in chunks, but must not label the provider as native streaming or block foreground text completion.

There is no automatic cross-provider retry. Such fallback could transmit text to an unselected service, change voice unexpectedly, conceal failure, and violate user control. A later explicit fallback policy would require its own reviewed design.

## 10. Audio format expectations

The initial canonical internal format should preserve the proven current path:

- signed 16-bit little-endian PCM;
- mono;
- 24,000 Hz sample rate;
- frame-aligned, nonempty byte chunks; and
- an overall Tori-owned size limit.

The audio descriptor is immutable for one stream and is delivered before audio bytes. A stream cannot change encoding, sample rate, channel count, or sample width partway through.

Adapters whose native service can return this format should request it directly. An adapter whose native format differs must normalize it behind the provider boundary through a deliberately approved, bounded implementation. The browser must not learn provider-specific codecs or endpoints. Supporting another canonical format later requires an explicit versioned extension and client compatibility plan; it must not be inferred from a misleading content type.

All audio is untrusted presentation data. Tori validates declared content type, content length where present, actual cumulative bytes, frame alignment, timeouts, and clean completion. Audio remains transient and is not archived or used as canonical input.

## 11. Cancellation and lifecycle

The existing one-active-speech-session behavior remains Tori policy:

- starting a new session supersedes the old session;
- Stop Speaking affects speech, not model generation or the transcript;
- cancellation clears queued text and closes active adapter/transport resources;
- session identifiers are opaque, bounded, short-lived, and single-consumer;
- cancelled or expired audio cannot be replayed as current speech; and
- provider cleanup must run on success, failure, disconnect, cancellation, and iterator close.

The provider may observe a cancellation signal only to stop work. It gains no authority from that signal and may not turn cancellation into another request.

## 12. Error contract

Provider adapters map native failures into safe categories such as:

- `invalid_configuration`;
- `authentication_failed`;
- `provider_unreachable`;
- `provider_timeout`;
- `model_unavailable`;
- `voice_unavailable`;
- `unsupported_feature`;
- `rate_limited`;
- `invalid_response`;
- `stream_interrupted`;
- `response_too_large`; and
- `cancelled`.

Errors may carry a safe retryability indication and bounded diagnostic code for logs. Raw provider bodies, credentials, URLs containing secrets, transcript text, and stack details do not cross the public boundary.

Tori maps these failures to calm, truthful presentation. It never reports successful speech when audio failed. Speech failure does not roll back or contaminate a successful text response, archive write, memory workflow, or other capability. Retries are bounded and only allowed when policy explicitly considers the operation safe; no retry may switch providers implicitly.

## 13. Security and privacy

- A profile grants permission only to synthesize through its validated endpoint. It grants no file, command, browser, memory, Project, task, or network authority beyond that connection.
- Tori sends only the minimum normalized visible segment needed for speech. It does not send history, hidden controls, reasoning, sources, or unrelated state.
- External or nonlocal profiles require explicit creation and selection with clear data-boundary disclosure.
- Endpoint validation must prevent SSRF, unsafe schemes, embedded credentials, ambiguous hosts, uncontrolled redirects, query/fragment injection, and access outside the approved network policy.
- Authentication configuration is allowlisted. Secrets must not be returned to the browser, written to logs, embedded in profile display documents, or accepted as arbitrary headers.
- Provider responses are untrusted bytes and bounded metadata. They cannot create profiles, select models or voices, grant permissions, invoke actions, or write canonical state.
- Profile mutations are CSRF-protected, same-origin, revision-safe application operations when exposed through the web client.
- Availability checks are bounded and user-controlled; Tori performs no automatic provider addition, network scanning, or speculative external connection.
- Audio and temporary session state remain memory-only unless a separate user-approved recording feature is designed in the future.

## 14. Current architecture assessment

### 14.1 Existing code that can remain

The following current responsibilities already align with the contract and should generally remain Tori-owned:

- `TextToSpeechProvider` as the seed of a narrow provider port;
- `SpeechSegmenter` and natural-boundary incremental segmentation;
- `normalize_speakable_text()` and the exclusion of Markdown machinery, URLs, sources, private control markers, and hidden provider content;
- bounded text, queue, session, lifetime, and response limits;
- `SpeechCoordinator` ownership of sessions, ordering, supersession, cancellation, and cleanup;
- manual replay and automatic speech initiating the same coordinator path;
- speech enablement as administrator permission plus user preference plus effective state;
- speech failure remaining secondary to foreground conversation success;
- same-origin Tori-proxied audio rather than direct browser-to-provider access;
- browser-native playback and the current start/audio/complete/stopped/error event lifecycle; and
- transient audio with no archive or browser persistence.

These components may need signature changes to carry an audio descriptor, selected profile, model, or voice, but their policy ownership is correct.

### 14.2 Responsibilities moved behind the contract

The following implementation details are now isolated or replaced:

- `QwenTTSProvider` as the only constructible adapter;
- the hard-coded Qwen endpoint, host, port, request path, request model, payload, accepted content types, and transport validation;
- `build_tts()` branching directly on the string `qwen`;
- `Settings` fields that represent one global provider/endpoint/voice rather than a selected saved TTS profile;
- fixed voice ownership in `SpeechCoordinator` rather than a Tori-selected profile/request;
- fixed module-level audio constants where a validated stream descriptor should express the contract;
- Qwen-specific availability being inferred from construction rather than reported as configured/enabled/reachable/available dimensions; and
- any future model, voice, or provider discovery logic, which belongs in adapters behind bounded Tori validation.

The Qwen adapter remains the compatibility adapter around existing behavior, not the definition of the interface.

### 14.3 Existing architecture to borrow, not merge

The LLM provider/profile system demonstrates useful patterns:

- stable profile identifiers and human display names;
- explicit implementation type and endpoint;
- validated local/LAN network boundaries;
- allowlisted authentication modes;
- explicit enablement;
- revision-safe create, update, enable/disable, and delete;
- authoritative server-side merging and refresh; and
- client presentation that does not own provider authority.

TTS should follow those patterns through a TTS-specific application service, profile type, adapter factory, and contract-test suite. It should not add TTS fields to the LLM profile table, reuse model-context semantics, or create a universal provider database merely for code reuse.

### 14.4 Preserved boundaries

This design does not authorize changes to:

- Conversation streaming, transcript rendering, or archive semantics;
- Auto Voice, Speak, Stop Speaking, or browser audio UX;
- current administrator/user speech enablement behavior;
- the current same-origin web speech event protocol;
- STT or microphone behavior;
- audio persistence;
- identity, system prompts, memory, Projects, tasks, permissions, or M23/M24 behavior;
- unrelated canonical runtime data or schemas;
- Conversation layout or browser audio protocol; or
- legacy TTS configuration, which remains untouched while the one-time canonical compatibility profile preserves its effective provider, endpoint, voice, and timeouts.

## 15. Conformance and testing strategy

Completion must prove the boundary, not only one provider.

A reusable provider contract suite should verify that every adapter:

- reports capabilities and unsupported discovery honestly;
- rejects invalid configuration without network contact;
- sends only validated request fields;
- yields ordered, nonempty, frame-aligned audio within bounds;
- preserves one immutable audio descriptor;
- closes resources on success, error, cancellation, and consumer disconnect;
- maps transport, timeout, status, malformed, empty, truncated, and oversized responses safely;
- never returns executable authority or provider-defined UI instructions;
- does not persist text or audio; and
- does not silently fall back or ignore material unsupported settings.

Application tests should use at least two fake conforming adapters to prove profile selection and replacement without changing coordinator or client behavior. The retained Qwen compatibility adapter receives protocol-specific tests. A second real adapter is desirable proof during a later provider implementation, but is not required to write the contract.

Security tests should cover endpoint and redirect attacks, embedded credentials, discovery-response bounds, revision conflicts, disabled profiles, stale selection, external-provider disclosure, secret redaction, cancellation races, and runtime preservation.

## 16. Future migration path

Migration should proceed in bounded stages:

1. **Strengthen the port without behavior change.** Introduce request, audio-format, capability, availability, and typed-error values. Adapt the current Qwen implementation and prove parity with existing streaming, cancellation, and browser tests.
2. **Separate construction from core policy.** Add an allowlisted TTS adapter factory and move Qwen transport/path/payload knowledge wholly into its adapter.
3. **Define TTS profile application semantics.** Specify authoritative selection, revision-safe mutations, deletion rules, and failure behavior. Decide persistence only with explicit schema/migration authorization; do not mutate canonical runtime during implementation.
4. **Add server-side profile/status APIs.** Keep endpoint contact and validation behind Tori. Preserve the current speech enablement and same-origin audio APIs.
5. **Expose profiles in Settings.** Make provider, endpoint, model, and voice discoverable and easy to switch without moving authority into the browser. Keep Conversation controls compact.
6. **Prove replacement.** Implement or wrap a second provider selected after fresh open-source evaluation and run the shared contract suite. Qwen3-TTS, Kokoro, Chatterbox, and OpenAI-compatible services are candidates, not preselected outcomes.
7. **Consider broader network providers separately.** Add remote HTTPS and credential support only after a dedicated privacy/security review and explicit user-control design.

At every stage, the current text response remains independent of TTS success and no initialization or selection action contacts a provider. The Phase H.5 compatibility seed applies only to an absent store, never rewrites existing canonical or legacy configuration, and preserves rollback without changing Conversation data.

## 17. Completion criteria for a future implementation

The capability boundary is complete only when:

- Tori owns profiles, selection, consent, speech policy, and failure presentation;
- at least one existing adapter preserves current low-latency streaming behavior;
- provider-specific details do not leak into Conversation, the browser, or unrelated core code;
- voice/provider switching is available through authoritative Settings workflows;
- availability and discovery are truthful and bounded;
- cancellation and transient-audio guarantees remain intact;
- contract tests demonstrate provider substitution;
- no provider output can alter authority or canonical state; and
- replacing the engine requires configuration/profile selection or one conforming adapter rather than a redesign.

## 18. Recommended next steps

Human acceptance verified Qwen3 TTS, Kokoro, canonical profile management, and
immediate provider switching through the common contract. A Kokoro voice metadata
change may require one Settings refresh to become visible; synthesis selection still
changes immediately, so this is an accepted minor presentation note rather than a
provider-boundary defect.

1. Treat connection testing, discovery, credentials, external providers, or another schema migration as separately reviewed work.

No broader provider access, discovery, credential storage, plugin framework, or external connection is authorized by this document.
