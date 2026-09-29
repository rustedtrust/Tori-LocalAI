# Voice recognition runtime

This is Tori's local, replaceable RealtimeSTT integration for desktop-local
Voice Input. The normal browser UI owns permission, client-local microphone
selection, local Ready buffering, and explicit PTT; it does not use the PoC
directory. The main Tori environment imports only standard-library domain/IPC
code.

Fresh clones include this bridge and the pinned direct requirements, but not
the Python 3.12 recognition environment or model snapshots. The core installer
does not advertise `--with-voice`: reviewed immutable model/ONNX asset identities,
redistribution notices and GPU/CUDA compatibility validation are still needed
before a complete optional installer path can be claimed. These packages and
assets can consume substantial disk and GPU memory and require explicit owner
preparation, never a core-install or Voice On side effect.

Verified Tori backups include `models/voice/`, and whole-runtime Restore recovers
that exact verified asset tree. `deploy/voice/.venv` is intentionally excluded
from the backup and is not moved into the activated restore, even on the same
machine. Reprepare this separate environment and verify CUDA/model readiness
before turning Voice Input On after restore; Restore never downloads packages.

## Separate operator preparation

Provisioning is a separate operator action, not part of Voice Input enablement.
Use a native Linux project-local environment at `deploy/voice/.venv`, Python 3.12,
and this directory's pinned requirements. Use owner-controlled directories and
files, a restrictive umask (077), and no globally installed packages or services.
The interpreter is the fixed `bin/python` venv entry; browser/model inputs cannot
select it or supply commands. The isolated environment needs CUDA-compatible
CTranslate2/faster-whisper and the host's existing NVIDIA driver. If their library
loader needs local CUDA libraries, provision them in that environment's `lib`.
The pinned environment installs RealtimeSTT 1.1.2 with its narrow
`faster-whisper`/CTranslate2 and `silero-onnx-cpu` extras, plus websockets 16.0.
Tori never installs them or changes the driver/library configuration.

Prepare local, complete CTranslate2 model snapshots at
`models/voice/small.en` and `models/voice/tiny.en`, including `model.bin`,
`config.json`, `tokenizer.json`, `vocabulary.txt`, and any additional
snapshot vocabulary assets. Use the corresponding Systran faster-whisper English
models. `preprocessor_config.json` is not part of these official snapshots and
is not required. Remove Hugging Face downloader `.cache` metadata from inside
each production snapshot directory; Tori validates the complete asset tree and
does not treat downloader state as a model asset. Prepare the compatible Silero
ONNX VAD asset as
`models/voice/silero_vad.onnx`. Retain upstream/dependency/model licenses in the
prepared installation and verify its resolved package versions and CUDA support.
RealtimeSTT and Whisper/faster-whisper use MIT licenses; Silero's model/dependency
notices must also accompany the prepared assets. No assets are bundled here.

Optional **operator-only** local `tori.toml` configuration:

```toml
[voice_input]
environment_root = "/absolute/path/to/Tori/deploy/voice/.venv"
model_root = "/absolute/path/to/Tori/models/voice"
port = 8013
readiness_seconds = 90.0
shutdown_seconds = 5.0
```

Absent settings leave the backend unconfigured and Off. Physical microphone
identity remains a browser-local preference and Voice Input never restores On
after a browser or Tori restart. Missing assets, unsupported versions,
GPU/model errors, or occupied loopback
ports fail truthfully. Each configured asset root and its parent directory chain
must pass Tori's owner/trust and group/world-write checks; shared writable asset
parents are rejected. Repair prerequisites separately, then explicitly retry.

## Ownership and privacy

Explicit controller acquisition starts the fixed `runtime.py --bridge` in an
owned Linux session. Its worker binds only `127.0.0.1`; the browser never connects
to it. A fresh secret authenticates the bridge before private recognition commands.
Both models are loaded/warmed once, with one bounded inference scheduler.
Readiness requires model usability and an authenticated matching profile/epoch.
The profile is tiny.en/small.en CUDA int8_float16; energy 100, pre-roll 0.50 s,
trailing silence 0.80 s. Native manual recording retains the held turn regardless
of VAD pauses; energy guards empty/no-signal finals, not action authority.
`stop → wait_audio → transcribe` finalizes without recorder shutdown or silence
injection. Empty releases skip `wait_audio`, which would otherwise re-arm the
native recorder when no frames were queued, and produce reusable no-speech.
Native recording IDs fence late realtime observations.

Off/release, event-stream disconnect, expired heartbeat, or failure revokes the
lease first, closes the session, and stops only owned processes using Linux pidfd
identity checks. Graceful shutdown is bounded; forced cleanup follows only if
needed. Failed cleanup remains unavailable/Stopping rather than claiming Off.
No automatic restart occurs. Fresh Tori startup is Off.

Audio, intermediate text, and final candidates remain transient. The browser
forwards PCM only during an authorized PTT turn. A current, fenced nonempty final
may be claimed exactly once and then enters Tori's ordinary Conversation stream;
only that accepted normal user turn uses the existing archive rules. Recorder file
logging is disabled; library stdout/stderr is discarded. Last-recognition
convenience buffers are cleared each turn. Runtime caches/temp files are confined
to a newly created disposable `/tmp/tori-voice-*` directory removed after
confirmed shutdown; canonical `runtime/` and user data are never runtime scratch
space. Offline model flags, absolute model paths, and local raw-ONNX VAD prevent
download-on-start.

## Developer transport and smoke checks

The existing same-origin Tori Web server exposes sanitized GET
`/api/voice-input/status`. Local-host-only, CSRF-protected POST operations are
`acquire`, `release`, `heartbeat`, `begin`, `audio`, `finalize`, `cancel`, `clear`,
`admit`, and `events` under `/api/voice-input/`. These are Tori concepts, not the
engine's WebSocket contract. `admit` contains only the current fenced segment and
final-event identity plus the browser's bounded Auto voice choice; it cannot
supply arbitrary transcript text. JSON controls
are at most 4096 bytes; audio is binary POST
PCM signed 16-bit little-endian mono at 44.1/48 kHz, at most 32768 bytes/chunk,
with a bounded `X-Tori-Voice-Binding` JSON header. Every mutation carries epoch,
lease, lease generation and expected revision; audio adds turn ID/sequence,
finalize adds turn ID/last acknowledged sequence. POST `events` yields bounded
NDJSON with session/turn/segment/revision identity. One controller/event reader,
five-second heartbeat expiry, ten-second final timeout, 60-second utterance cap,
one-second native audio backlog, and 128 queued events apply. Backpressure is an
explicit rejection, never an unbounded queue. Clear is presentation-only.

After prerequisites are prepared, run `scripts/verify-voice-runtime` with the two
absolute roots. It uses only synthetic silence, checks ten reusable turns, and
always stops owned resources. It does not install/download or capture audio.
Physical transcription and GPU acceptance remain separate from fixture tests.
