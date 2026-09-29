# Tori TTS Profiles Design

**Project:** Tori

**Document:** TTS Profiles Design

**Status:** Approved and implemented through Phase H.5; human acceptance passed

**Implementation status:** The Phase H.4A source tree contains an explicitly
initialized, revision-safe TTS profile repository, a separate revision-safe active
selection document, a Tori-owned application service, and bounded same-origin APIs.
Phase H.4B adds a Settings-owned Voice/TTS client for canonical list, create,
edit, delete, and selection commands with explicit revision-conflict handling.
Phase H.5 adds an atomic first-start compatibility seed, profile-backed runtime
provider resolution, selection/edit cancellation, and truthful operational status.
The seed preserves the validated legacy configuration as one selected canonical
profile without rewriting it; every later start treats existing canonical profile
state as authoritative and never re-projects or silently falls back to legacy.

**Authority:** Subordinate to `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`, `docs/ARCHITECTURE_GOVERNANCE.md`, `docs/TARGET_ARCHITECTURE.md`, and `docs/design/TTS_PROVIDER_CONTRACT.md`

## 1. Purpose

This document defines the future Tori-owned profile and selection boundary for text-to-speech providers.

The provider contract already separates Tori's speech policy from replaceable synthesis adapters. Profiles add durable, user-controlled configuration around that boundary so a user can save several valid speech configurations, choose one deliberately, and change providers, models, or voices without rewriting Conversation or repeatedly entering connection details.

A profile is canonical Tori configuration. It identifies one allowed adapter configuration and the model and voice Tori should request through it. A profile does not become an authority-bearing capability, does not define Tori's identity, and does not grant its provider access beyond the speech text Tori explicitly submits for synthesis.

This design preserves these invariants:

- Tori owns configuration, selection, consent, lifecycle, and failure policy.
- Providers perform synthesis only.
- The user explicitly controls saved profiles and the selected profile.
- Provider selection never changes silently.
- Provider failure never causes silent fallback or contaminates a successful text response.
- Voice and provider management belong primarily in Settings rather than Conversation.

Normal current profiles are protocol-oriented: they use Tori's bounded
OpenAI-compatible local speech request and do not expose a vendor selector.
The profile retains endpoint, optional model, voice, timeouts, and enablement;
the adapter sends a standard speech request and validates WAV output before it
reaches Tori's existing playback boundary. Persisted Qwen/Kokoro records remain
legacy adapter records where their raw-PCM/streaming contracts differ, rather
than being silently reinterpreted or deleted.

### 1.1 Non-goals

This document does not authorize or design:

- initialization or migration beyond the bounded Phase H.5 compatibility seed;
- unrelated runtime data creation or conversion;
- implementation beyond the separately approved Phase H.5 lifecycle;
- a generic plugin, registry, marketplace, or executable-extension system;
- automatic provider discovery, installation, or LAN scanning;
- automatic model or voice discovery;
- automatic cross-provider retry or fallback;
- speech-to-text, wake phrases, voice cloning, microphone capture, or audio recording;
- browser-owned profiles or browser-to-provider connections;
- external-provider credentials or general Internet endpoint support;
- changes to Conversation, transcript, memory, Project, task, or permission semantics; or
- selection of one speech technology as part of Tori's identity.

## 2. Ownership boundary

### 2.1 Tori-owned responsibilities

Tori owns:

- the canonical set of TTS profiles;
- stable profile identifiers and user-facing names;
- the allowlist of supported provider types;
- profile shape, endpoint-policy, model, voice, timeout, and option validation;
- profile creation, editing, enablement, disablement, and deletion workflows;
- the selected profile identifier and its revision;
- administrator permission, user speech preference, and effective speech availability;
- explicit connection tests and truthful availability observations;
- the adapter composition root and profile-to-adapter construction;
- switching, cancellation, concurrency, and no-silent-fallback rules;
- the minimum visible text sent for synthesis;
- canonical audio validation, cumulative limits, playback coordination, and safe errors;
- persistence, revisions, audit-safe metadata, and multi-client convergence; and
- all privacy, permission, disclosure, and credential policy.

The selected profile tells Tori which approved adapter configuration may receive a synthesis request. It grants no broader authority.

### 2.2 Provider-owned responsibilities

A provider adapter owns only:

- translation from the provider-neutral synthesis request to its native protocol;
- provider-specific endpoint paths, headers, payloads, model aliases, and voice identifiers;
- native transport and authentication behavior that Tori has explicitly authorized;
- conversion to Tori's canonical audio contract;
- transport-resource cleanup; and
- safe translation of native failures and capability information.

An adapter does not create, select, edit, enable, disable, or delete profiles. It does not persist configuration, choose fallback providers, interpret provider output as instructions, or mutate Tori state.

### 2.3 Client-owned responsibilities

A frontend may present profile documents supplied by Tori and submit explicit profile or selection commands. It owns form interaction and display only.

The client does not:

- persist authoritative profiles;
- decide which provider types or endpoint forms are allowed;
- contact provider endpoints directly;
- retain provider credentials;
- infer availability from browser reachability;
- resolve revision conflicts locally; or
- substitute another profile after failure.

## 3. TTS profile concept

A `TTSProfile` is a stable, named Tori document describing one configured synthesis path. It binds:

- one allowlisted provider type;
- one validated endpoint or local service location when that provider requires one;
- an optional provider model selection;
- one voice selection;
- bounded transport settings; and
- explicit enablement.

Profiles are separate from the selected-profile state. Saving or editing a profile does not select it. Selecting a profile does not rewrite the profile. This separation prevents incidental edits from changing active speech behavior and permits several configurations to coexist.

Profiles are also separate from:

- administrator permission to use speech;
- the user's speech-output preference;
- the browser's device-local automatic-playback preference;
- transient provider availability;
- active speech sessions; and
- Conversation or archive state.

The effective ability to speak is derived from all required conditions, conceptually:

```text
administrator permitted
AND user speech preference enabled
AND selected profile exists
AND selected profile enabled
AND selected profile validates
AND its adapter can be constructed
AND the synthesis operation succeeds
```

Current reachability is deliberately not a durable profile field. It is an observed condition that may change without a canonical mutation.

## 4. Profile fields and boundaries

The canonical profile has the following conceptual fields. Phase H.4A defines
their initial exact Python and SQLite representation behind the same boundaries.

| Field | Meaning | Boundary |
| --- | --- | --- |
| `identifier` | Stable opaque Tori-owned profile ID | Immutable after creation; bounded and not derived from endpoint or display name |
| `display_name` | User-facing profile name | Required, bounded, normalized text; not an adapter identifier |
| `provider_type` | Explicit allowlisted adapter type | Required; immutable unless a deliberate replacement operation is designed |
| `endpoint` | Provider API root or service location | Required only when the adapter requires it; normalized and policy-validated by Tori |
| `model` | Selected provider model ID | Optional when the provider has no model choice; bounded opaque identifier |
| `voice` | Selected provider voice ID | Required for synthesis unless a future adapter contract explicitly proves otherwise |
| `enabled` | Whether Tori may select and contact this profile | Canonical user-controlled state; not inferred from reachability |
| `connect_timeout_seconds` | Bounded connection timeout | Tori-owned portable transport policy |
| `read_timeout_seconds` | Bounded stream timeout | Tori-owned portable transport policy |
| `authentication_mode` | Allowlisted authentication category | Defaults to `none`; no arbitrary headers or embedded credentials |
| `credential_reference` | Optional reference to a separately approved secret boundary | Never contains a returned secret and is absent until credential storage is designed |
| `provider_options` | Bounded adapter-scoped options | Optional; only explicitly allowlisted keys and values, never arbitrary executable configuration |
| `revision` | Monotonic optimistic-concurrency revision | Changes on every canonical mutation |
| `created_at` | Canonical creation time | Server-generated civilly unambiguous timestamp |
| `updated_at` | Canonical last-mutation time | Server-generated and revision-consistent |

### 4.1 Fields that are not part of the profile

The profile must not contain:

- Tori identity, personality, system prompts, relationship state, or founding rules;
- permissions for files, commands, memory, Projects, tasks, search, or other capabilities;
- Conversation history, hidden reasoning, sources, memory, or Project context;
- browser state or device identifiers;
- raw credentials, arbitrary HTTP headers, cookies, or bearer tokens;
- provider-returned UI documents or executable metadata;
- live connection objects or active stream state;
- canonical audio or generated recordings;
- automatic fallback chains; or
- unbounded provider-specific dictionaries.

### 4.2 Provider-neutral versus adapter-scoped values

Profile field names and lifecycle semantics remain provider-neutral. `provider_type`, `model`, and `voice` values are opaque identifiers interpreted by the selected adapter; their native spelling does not become core policy.

Portable settings may be added only after two or more adapters demonstrate the same stable meaning. Settings with provider-specific semantics remain under `provider_options`, use an adapter-owned allowlist, and must be rejected rather than silently ignored when unsupported.

The initial profile design should not add generation controls merely because one adapter exposes them.

## 5. Provider, model, and voice selection

### 5.1 Provider selection

The provider is selected indirectly by selecting a profile. Tori reads the selected canonical profile, validates its `provider_type`, and constructs exactly that allowlisted adapter. Arbitrary imports, reflection, module discovery, entry points, or downloaded provider code are forbidden.

Adding support for another provider requires:

1. one reviewed adapter satisfying the TTS provider contract;
2. an explicit composition-root allowlist entry;
3. adapter-specific configuration validation; and
4. shared conformance and security tests.

Existing profiles do not change when a new adapter becomes available.

### 5.2 Model selection

`model` is nullable because some providers expose one fixed synthesis model. When set, it is a bounded opaque identifier passed only to the selected adapter.

Tori must distinguish:

- model choice unsupported by this provider;
- model choice supported but no model selected;
- selected model syntactically invalid;
- selected model not currently available; and
- model availability unknown because no explicit check has occurred.

An adapter must reject unsupported or materially ignored model selections. Tori does not rewrite the stored model based on a provider response.

### 5.3 Voice selection

Voice is profile-scoped because voice identifiers and availability vary by provider and model. Switching profiles therefore switches the configured voice as part of one deliberate selection.

Voice selection belongs primarily in Settings. Conversation may expose compact playback controls, but it must not become the authoritative voice/profile editor.

Tori validates voice shape before saving. An adapter validates provider-specific compatibility when constructing or synthesizing. A missing or unavailable voice causes safe speech unavailability; it does not cause Tori to choose another voice automatically.

### 5.4 Discovery

Profile CRUD does not require discovery. Users may enter known model and voice identifiers explicitly.

Future model or voice discovery, if authorized, must be:

- initiated by an explicit user action;
- performed server-side through the selected adapter;
- bounded in time, count, and text size;
- treated as untrusted observed data;
- clearly timestamped;
- optional when the provider does not support it; and
- incapable of saving or selecting a value automatically.

No LAN scan, provider auto-addition, or background discovery follows from this design.

## 6. Switching behavior

Switching is an explicit canonical selection mutation, not a frontend preference.

The selection document conceptually contains:

- `selected_profile_identifier`, nullable only when speech has been explicitly left without a provider;
- `revision`;
- `updated_at`; and
- no copied endpoint, model, voice, or credential fields.

A switch request must include the expected current selection revision. Tori performs the operation in this order:

1. authenticate the same-origin caller and validate CSRF protection where applicable;
2. load the requested profile authoritatively;
3. verify its exact revision when the command is profile-revision-bound;
4. verify it is enabled and passes offline shape, endpoint, and adapter validation;
5. atomically update the selected-profile document using the expected selection revision;
6. cancel any active speech session and close its old adapter stream;
7. publish the new authoritative selection revision; and
8. use the newly selected profile only for later synthesis sessions.

No synthesis request is required merely to save or select a profile. An explicit connection test may occur before switching if the user requests it, but reachability is not silently probed and is not confused with valid configuration.

### 6.1 In-flight and queued speech

A successful profile switch cancels current and queued speech. It does not let already queued text cross from one provider to another, and it does not restart cancelled speech automatically. Text generation, transcript state, and archive completion remain unaffected.

If selection persistence fails, Tori leaves the old selection and speech session unchanged. If persistence succeeds but stream cleanup reports an error, the old session remains authoritatively cancelled and the new selection remains canonical; cleanup failure is reported safely and does not roll back into ambiguous dual selection.

### 6.2 Multi-client convergence

Clients render the selected profile and revisions supplied by Tori. A stale expected revision fails without overwriting a newer selection. Clients refresh from authoritative state rather than merging selection locally.

Profile edits similarly require the profile's expected revision. Editing an unselected profile does not alter selection. Editing a selected profile changes the configuration used for future speech only after the edit succeeds; active speech is cancelled when a selected profile's effective synthesis fields change.

### 6.3 Disablement and deletion

Tori must not leave a selected profile silently unusable through an incidental mutation.

- Disabling or deleting an unselected profile is allowed through the normal revision-safe workflow.
- Disabling or deleting the selected profile is rejected unless the same explicit operation either selects another valid enabled profile or explicitly disables speech/no-provider selection.
- Tori never chooses a replacement profile automatically.
- Deletion requires confirmation appropriate to existing Settings conventions and verifies the exact profile revision.

## 7. Failure and unavailable-provider behavior

The selected profile remains selected across ordinary provider failures. Failure does not rewrite configuration.

### 7.1 Configuration failures

If a selected profile is missing, disabled, corrupt, unsupported by the current build, or invalid under current endpoint policy:

- effective speech is unavailable;
- no provider is contacted;
- no alternative profile is selected;
- text conversation continues normally;
- Tori presents a safe reason and directs the user to Settings; and
- canonical profile data is not repaired or rewritten automatically.

### 7.2 Operational failures

Connection refusal, timeout, authentication failure, unavailable model or voice, malformed audio, oversized output, interrupted streaming, and provider status errors:

- terminate only the affected speech session;
- close adapter resources;
- update a derived availability observation with a safe reason code and observation time;
- preserve the selected profile;
- preserve completed text and canonical archive state; and
- never trigger cross-provider or cross-voice fallback.

A later synthesis request may try the same selected profile again under existing bounded policy. A successful clean request may restore its observed availability. Retry never implies provider switching.

### 7.3 Availability representation

Profile validity and provider availability are different:

- **configured** means the canonical profile passes offline validation;
- **enabled** means the user permits its use;
- **selected** means the selection document refers to it;
- **unknown** means no relevant current observation exists;
- **available** means a bounded operation most recently completed cleanly;
- **unavailable** means a bounded operation most recently failed; and
- **degraded** is reserved for a provider that can synthesize while an optional function is impaired.

Availability is derived, time-sensitive state. It should normally remain process-local or be stored only as a bounded cache with `observed_at`; it must never be presented as timeless canonical truth.

## 8. Security and permission rules

### 8.1 Explicit authority

Profile creation, mutation, selection, enablement, disablement, connection testing, and deletion are user-controlled application operations. Provider output cannot request or authorize any of them.

No profile may grant authority beyond speech synthesis through its validated endpoint. It grants no access to files, commands, accounts, memory, Projects, tasks, Search, model-provider configuration, or other network destinations.

### 8.2 Network boundary

Initial implementation should preserve the existing numeric IPv4 loopback/RFC1918 HTTP endpoint policy and provider-specific path restrictions. It must reject:

- hostnames and ambiguous numeric forms;
- public, multicast, link-local, unspecified, or IPv6 destinations unless separately designed;
- embedded usernames or passwords;
- fragments, query injection, and unapproved paths;
- redirects outside the validated endpoint; and
- arbitrary proxy or header configuration.

External HTTPS providers require a separate security and privacy design covering credentials, certificate validation, data-boundary disclosure, revocation, and explicit user authorization. This profile contract does not authorize them.

### 8.3 Credentials

No raw secret belongs in the profile document, frontend state, logs, errors, exports, or diagnostics. A future credential reference must resolve server-side through a separately approved secret store and be usable only by the selected adapter for the selected endpoint.

Profile reads returned to clients must redact or omit credential references when even the reference would disclose sensitive structure.

### 8.4 Data minimization

The selected provider receives only the normalized visible text segment and bounded synthesis fields required by the provider contract. It receives no hidden reasoning, system prompt, full history, memory, Project context, action token, permission document, or browser state.

Provider responses remain untrusted audio and bounded metadata. They cannot mutate profiles, selection, permissions, or any other canonical state.

### 8.5 Application security

The Phase H.4A web mutations use existing same-origin, CSRF, size, content-type,
busy-state, confirmation, and safe-error conventions. Profile and selection
mutations use expected revisions. Logs contain profile IDs and safe reason codes
only when necessary, never transcript text, secrets, or raw provider responses.

## 9. Storage recommendations

This document defines the semantics controlling the narrow schema implemented in
Phase H.4A and the non-destructive production initialization authorized in Phase
H.5.

### 9.1 Application boundary

The Phase H.4A `TTSProfileApplicationService` mediates:

- profile listing and retrieval;
- creation and revision-safe mutation;
- enablement, disablement, and deletion;
- selected-profile reads and revision-safe switching;
- offline profile validation through the allowlisted provider contract; and
- resolution of the one enabled, valid active profile without fallback.

The Phase H.5 `TTSProfileRuntime` projects that authoritative selection into an
allowlisted adapter and bounded process-local availability status.
`SpeechCoordinator` consumes only this provider-neutral source rather than querying
storage or understanding profile persistence. Explicit connection testing remains
deferred and has no implied mutation authority.

### 9.2 Repository boundary

The dedicated TTS profile repository exposes typed profile and selection
operations using SQLite and the Python standard library, consistent with Tori's
current local-first implementation. It does not reuse the LLM profile schema
merely because both domains use the word "profile."

The durable model should keep:

- profile documents and profile revisions;
- the selected-profile document and its independent revision; and
- any migration metadata required by an explicitly approved schema version.

Transient streams, audio, connection objects, and ordinary availability observations do not belong in canonical storage.

### 9.3 Transaction requirements

Storage must provide:

- atomic profile writes;
- monotonic revisions;
- expected-revision conflicts;
- referential validation for selected profile IDs;
- atomic combined select/disable or select/delete operations when authorized;
- bounded reads and deterministic ordering; and
- integrity checks and failure-safe rollback.

### 9.4 Migration and legacy configuration

The schema-1 repository and Phase H.5 initialization path are implemented with
these exact rules:

- only an absent TTS profile store is eligible for initialization;
- the already validated configured provider, endpoint, voice, and timeouts are
  atomically written as stable profile `configured-speech` and selected in the
  same transaction;
- no provider connection occurs during initialization;
- the legacy configuration remains untouched as rollback evidence;
- an existing profile store is never merged, rewritten, or re-seeded, even when
  legacy configuration later changes;
- existing canonical selection is the only normal runtime source;
- missing, invalid, disabled, unsupported, or corrupt canonical state fails
  honestly without legacy or cross-provider fallback; and
- tests use injected temporary stores and do not initialize canonical runtime.

This is a bounded compatibility seed, not a general migration mechanism. Any
future schema change, credential store, external-provider conversion, or repair
workflow still requires separate authorization.

## 10. Settings integration direction

Settings should provide a compact TTS Profiles workspace owned by the modular Settings view. It should show:

- profiles with display name, provider type, enabled state, and selected state;
- endpoint/network boundary without exposing secrets;
- selected model and voice;
- configured versus observed availability as separate information;
- the observation time and safe reason when unavailable;
- explicit Add, Edit, Test Connection, Enable/Disable, Select, and Delete actions as supported; and
- clear unavailable states when discovery or credentials are not implemented.

### 10.1 Editing workflow

Profile editing should use a dedicated bounded form rather than a giant miscellaneous Settings form. Provider type determines which adapter-scoped fields are visible, but Tori supplies the allowlist and validation rules. Changing provider type should normally create or replace a profile deliberately rather than reinterpret existing provider-specific fields silently.

Saving performs offline validation only. "Test Connection" is a separate explicit action and must not save, select, enable, or otherwise mutate the profile as a side effect.

### 10.2 Selection workflow

Selecting a profile should state the provider, model, voice, and whether speech text remains local or crosses an external boundary. Selection uses the displayed authoritative revision and refreshes after conflicts.

The UI must not offer an automatic fallback toggle under this design. It must not silently choose the first available profile when the selected one fails.

### 10.3 Conversation surface

Conversation retains only compact speech interaction controls such as Auto Voice, Speak, and contextual Stop. It may display the active voice/profile name compactly if useful, but management, endpoints, models, voices, and connection tests remain in Settings.

Mobile Settings must remain usable without transferring configuration authority to browser storage or contacting providers from the device.

## 11. Future expansion boundaries

The following require separate design and authorization:

- live multi-client Settings acceptance;
- model and voice discovery;
- provider capability descriptors beyond the currently proven port;
- external HTTPS providers and credentials;
- portable generation controls such as speed after shared semantics are proven;
- adapter-scoped advanced options;
- profile import/export with secret-safe handling;
- explicit fallback policy, if ever desired;
- voice cloning, uploaded voice assets, or generated voice profiles;
- STT profiles, which remain a separate capability; and
- audio recording, caching, or archival.

No future expansion may turn profiles into plugins, allow providers to add themselves, or let provider output modify canonical configuration.

## 12. Remaining implementation sequence

Phase H.4A completes the repository and APIs, Phase H.4B completes the modular
Settings client, and Phase H.5 completes canonical initialization and runtime
selection. Remaining work is deliberately bounded:

Human acceptance passed profile management, Qwen3 TTS, Kokoro, and immediate
provider switching. Changing a Kokoro voice may require a Settings refresh before
the new voice metadata is reflected; runtime provider switching remains immediate,
so this is an accepted minor presentation note rather than a capability defect.

1. Add explicit connection-test handling only if separately approved; it must have
   no mutation side effects.
2. Treat any later schema migration or broader network/credential support as a
   separate sensitive mission.

## 13. Design completion criteria

The complete profiles product workflow is complete only when tests prove:

- profile fields remain provider-neutral across at least two real adapters and a fake;
- create, edit, enable, disable, delete, and select operations are revision-safe;
- stale clients cannot overwrite newer profile or selection state;
- switching cancels old speech and never crosses queued text between providers;
- invalid, disabled, missing, corrupt, or unavailable selections fail honestly;
- no provider or voice fallback occurs silently;
- endpoint and credential boundaries fail closed;
- Settings is a client of authoritative application services;
- provider output cannot mutate profiles, permissions, or canonical state;
- text conversation remains independent from speech failure; and
- verification does not mutate canonical runtime unexpectedly.

## 14. Decision summary

TTS profiles are canonical, revisioned Tori configuration around the existing provider-neutral synthesis port. Profiles hold bounded provider, endpoint, model, voice, and transport choices; selection is a separate revisioned document; availability is derived; switching is explicit and cancels old speech; and failure never triggers fallback.

Phase H.4A implements the backend repository and APIs, Phase H.4B implements the
modular Settings client, and Phase H.5 implements the one-time compatibility seed
and canonical selection-backed `SpeechCoordinator` source. The browser never owns
state, selection never falls back, and each speech session snapshots one profile.
Provider discovery, credentials, arbitrary options, external endpoints, and future
schema migrations remain separate reviewed decisions.
