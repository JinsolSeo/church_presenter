# Source-aware Worship Orders and Cross-platform Qt Music Design

## Goal

Make saved worship-order cues self-contained enough to reopen the PDF, local video, YouTube URL, praise plan, or Bible plan that produced each cue, while preserving the current active source as a fallback when a saved local file is unavailable. At the same time, remove the Windows-only YouTube-music dependency on libmpv by playing both local and YouTube music through Qt Multimedia.

## Worship-order behavior

Each cue reference records the source needed to reconstruct that cue:

- PDF: absolute PDF path and one-based page number.
- Local video: absolute media path.
- YouTube video: the original YouTube URL.
- Praise subtitle: absolute praise-plan path, semantic cue reference, and card index.
- Bible subtitle: absolute Bible-plan path, semantic verse reference, and card index.
- Black and solid-color cues: no external source.

Absolute paths are intentional. Worship-order files are also copied into the application-data safety location, where a path relative to the original order file would have a different base directory.

When a worship order is selected, an existing saved local path wins over the active panel source. If the saved path is absent or no longer exists, that cue resolves from the currently active PDF, video, praise plan, or Bible plan. A saved YouTube URL is used directly because it is not a local-file existence check. This fallback is per cue, so a preset may legitimately use different PDFs or videos for Broadcast and Venue.

The two Preview channels are changed only after both cue references have resolved successfully. Invalid pages, invalid semantic subtitle references, unreadable plans, and unsupported media sources keep both current Preview values intact and produce the existing user-facing resolution error. Source panels may be synchronized to the first successfully resolved source of their type for navigation, but panel selection is not the source of truth for the resolved `Content` objects.

## Persistence model

Worship-order JSON advances from schema version 3 to version 4. `CueReference` gains optional `path` and `url` fields. `Content` gains an optional subtitle-plan path so the existing preview-to-reference conversion can retain praise and Bible provenance.

Version 4 writes source-aware references. Versions 1, 2, and 3 remain readable:

- Version 1 full-content entries migrate through the normal cue-reference conversion and retain any legacy paths that are present.
- Versions 2 and 3 have no source path fields, so they resolve exactly as before against the active sources.
- Unknown future versions continue to be rejected.

Missing optional fields deserialize to `None` or an empty string. Paths are serialized as strings and reconstructed as `Path` values by the domain model.

## Music architecture

Local music remains on an audio-only `QtMediaBackend`. YouTube music receives a second audio-only `QtMediaBackend` configured for streaming. That backend asks the existing `YouTubeWorkerService` for the same progressive audio/video stream variant already used by the working YouTube video path, supplies the resolved stream URL to `QMediaPlayer`, and attaches only `QAudioOutput`; no video sink is created.

`AudioBackendRouter` keeps the public playback interface unchanged. It routes local `Path` sources to the local Qt backend and YouTube `str` sources to the streaming Qt backend. `AudioPlaybackController`, the playlist panel, fade behavior, volume, mute, position, duration, and state signals therefore keep their existing contracts.

The production path no longer constructs `MpvAudioBackend`, and `python-mpv` is removed from application dependencies and the in-app dependency updater. The old adapter is removed once its Qt replacement and regression tests pass, preventing an unused native runtime requirement from remaining in the supported architecture.

## Diagnostics

Qt playback errors must contain enough platform evidence to distinguish stream resolution from device or codec failures. The diagnostic snapshot includes:

- backend name and Qt media backend selection;
- media status, playback state, error code, and error string;
- current position and duration;
- `hasAudio` and `hasVideo` when Qt exposes them;
- selected audio-output device description, mute state, and volume;
- original YouTube source and whether stream resolution completed.

These values are included in debug logging and the existing media-error reporting path without showing routine internal details during successful playback.

## Testing

Implementation follows test-driven development.

Persistence tests cover version 4 round trips for every path/URL-bearing cue and continued loading of versions 1–3. Controller tests cover existing saved paths, missing-path fallback, different Broadcast/Venue files, YouTube URL restoration, praise and Bible plan restoration, and all-or-nothing Preview updates on resolution failure.

Media tests cover router selection, an audio-only Qt streaming backend requesting a progressive stream, delayed play until resolution, volume/mute/state forwarding, stale-result rejection, and useful diagnostics. Existing local-audio Qt tests remain regression coverage. A network-marked integration test verifies YouTube resolution plus Qt media loading where the environment permits it.

The final verification runs the focused unit and GUI suites, the full non-network suite, Ruff, and mypy. This macOS development environment cannot prove the physical Windows audio-device path, so the Windows checklist must still be run on a Windows machine; the automated tests specifically remove the prior libmpv/DLL dependency and exercise the common Qt code path.

## Non-goals

- Bundling worship media into one archive.
- Copying or relocating user media files.
- Searching the disk for moved files.
- Supporting non-YouTube streaming providers.
- Replacing Qt Multimedia for local media or video playback.
- Changing playlist editing, fade timing, or output-device selection UX.
