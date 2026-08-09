# Cross-platform Qt Music Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play local and YouTube playlist items through Qt Multimedia on both macOS and Windows, eliminating the separate libmpv runtime required only by YouTube music.

**Architecture:** Keep one audio-only `QtMediaBackend` for local files and configure a second audio-only instance to resolve YouTube URLs through `YouTubeWorkerService.request_video_stream`. Route both through the existing `AudioBackendRouter`, preserving all controller and playlist contracts while removing the libmpv adapter and dependency.

**Tech Stack:** Python 3.11+, PySide6 Qt Multimedia, yt-dlp, pytest, pytest-qt

## Global Constraints

- Local music and YouTube music must both use `QMediaPlayer` plus `QAudioOutput`.
- YouTube music must request the same progressive stream type used by the working YouTube video backend.
- The YouTube music backend must not create a video sink.
- Keep `AudioPlaybackController`, playlist, fade, fallback-file, volume, mute, position, duration, and state behavior compatible.
- Remove the production `python-mpv` and native libmpv requirement.
- Diagnostics must expose Qt state, media capabilities, output device, and YouTube resolution state.
- Do not stage or modify the pre-existing `.DS_Store` changes.

---

### Task 1: Audio-only Qt YouTube stream backend

**Files:**
- Modify: `src/church_presenter/media/qt_media_backend.py`
- Modify: `tests/unit/test_media.py`

**Interfaces:**
- Produces: `QtMediaBackend(video: bool, *, streaming: bool = False, audio_device_resolver: Callable[[str], QAudioDevice | None] | None = None, youtube_worker: YouTubeWorkerService | None = None)`
- Consumes: `YouTubeWorkerService.request_video_stream(request_id: str, url: str) -> bool`
- Preserves: `MediaPlaybackBackend.load(path: Path | str) -> None`

- [ ] **Step 1: Write failing Qt streaming tests**

Use a fake worker and fake/real `QMediaPlayer` signal harness to prove URL loading is asynchronous and audio-only:

```python
def test_audio_only_qt_backend_resolves_youtube_progressive_stream(qtbot) -> None:
    worker = FakeYouTubeWorker()
    backend = QtMediaBackend(video=False, streaming=True, youtube_worker=worker)
    assert backend.video_sink is None
    backend.load("https://www.youtube.com/watch?v=abcdefghijk")
    request_id, source = worker.video_requests[-1]
    assert source.endswith("abcdefghijk")
    metadata = YouTubeMetadata("Title", 60_000, "abcdefghijk", source)
    worker.resolved.emit(request_id, ResolvedYouTubeStream("https://cdn/stream", metadata))
    assert backend.path == source
    assert backend.player.source() == QUrl("https://cdn/stream")
```

Add a stale-result test: load URL A, load URL B, emit A's result, and assert A never reaches `player.setSource`.

- [ ] **Step 2: Run the focused tests and verify the RED state**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/unit/test_media.py -k 'audio_only_qt_backend'`

Expected: constructor failure because the `streaming` option and injected worker are unavailable.

- [ ] **Step 3: Generalize YouTube resolution without changing video behavior**

Create a worker when `video or streaming` is true, or use the injected worker. Keep `request_video_stream` for both. Change YouTube-specific error text from “영상 backend” to “미디어 backend” so it is accurate for audio. Preserve generation and request-ID cancellation logic.

- [ ] **Step 4: Expand `diagnostic()`**

Append `has_audio`, `has_video`, Qt error enum/name, audio device description, volume, mute, original source, and `youtube_pending`. Guard capability calls with `getattr` so supported PySide6 versions remain safe:

```python
device = self.audio_output.device()
description = device.description() if not device.isNull() else "system-default"
has_audio = bool(self.player.hasAudio()) if hasattr(self.player, "hasAudio") else False
```

- [ ] **Step 5: Run Qt media unit tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/unit/test_media.py`

Expected: all tests pass.

- [ ] **Step 6: Commit the reusable Qt stream path**

```bash
git add src/church_presenter/media/qt_media_backend.py tests/unit/test_media.py
git commit -m "feat: stream YouTube audio through Qt"
```

---

### Task 2: Route YouTube playlist items to Qt

**Files:**
- Modify: `src/church_presenter/media/audio_router.py`
- Modify: `src/church_presenter/media/audio_controller.py`
- Modify: `src/church_presenter/ui/controller_window.py:240-285`
- Modify: `tests/unit/test_youtube_audio.py`
- Modify: `tests/gui/test_controller.py`

**Interfaces:**
- Produces: `AudioBackendRouter(local_backend: MediaPlaybackBackend, youtube_backend: MediaPlaybackBackend)`
- Produces: `AudioPlaybackController(..., streaming_backend: MediaPlaybackBackend | None = None)`
- Consumes: `QtMediaBackend(video=False, streaming=True, audio_device_resolver=...)`

- [ ] **Step 1: Write failing composition and routing tests**

Assert that the production controller creates two distinct Qt backends, the YouTube one has streaming enabled and no video sink, and a YouTube playlist item routes its string URL to that backend. Keep the existing local-path and local-fallback assertions.

```python
def test_controller_uses_qt_for_local_and_youtube_music(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    assert isinstance(window.audio_controller.router.local_backend, QtMediaBackend)
    assert isinstance(window.audio_controller.router.youtube_backend, QtMediaBackend)
    assert window.audio_controller.router.youtube_backend.video_sink is None
```

- [ ] **Step 2: Run the focused tests and verify the RED state**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/unit/test_youtube_audio.py tests/gui/test_controller.py -k 'uses_qt_for_local_and_youtube or routes_youtube'`

Expected: the production YouTube backend is `MpvAudioBackend`.

- [ ] **Step 3: Broaden router typing to the common media contract**

Change the router's YouTube backend and active backend annotations to `MediaPlaybackBackend`. Remove the `StreamingAudioBackend` import and type-ignore on `load`; both local and streaming Qt instances accept `Path | str`. Preserve fallback routing and signal forwarding exactly.

- [ ] **Step 4: Inject the streaming Qt backend in both construction paths**

Remove the `MpvAudioBackend` imports. `AudioPlaybackController` defaults to `QtMediaBackend(video=False, streaming=True)` when a streaming backend is not injected. `ControllerWindow` supplies an instance with the same audio-device resolver used by local music:

```python
streaming_backend=QtMediaBackend(
    video=False,
    streaming=True,
    audio_device_resolver=self.audio_output_manager.resolve_device,
)
```

- [ ] **Step 5: Run audio controller and GUI regression suites**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/unit/test_youtube_audio.py tests/gui/test_controller.py tests/gui/test_media_panels.py`

Expected: all tests pass.

- [ ] **Step 6: Commit the production switch**

```bash
git add src/church_presenter/media/audio_router.py src/church_presenter/media/audio_controller.py src/church_presenter/ui/controller_window.py tests/unit/test_youtube_audio.py tests/gui/test_controller.py
git commit -m "fix: use Qt for YouTube music on Windows"
```

---

### Task 3: Remove libmpv dependencies and obsolete adapter tests

**Files:**
- Delete: `src/church_presenter/media/mpv_audio_backend.py`
- Modify: `tests/unit/test_youtube_audio.py`
- Modify: `tests/integration/test_youtube_streaming.py`
- Modify: `pyproject.toml`
- Modify: `src/church_presenter/services/feature_update_service.py`
- Modify: `src/church_presenter/ui/panels/video_panel.py`
- Modify: `tests/unit/test_feature_update_service.py`

**Interfaces:**
- Produces: `UPDATE_REQUIREMENTS == ("yt-dlp[default]",)`
- Produces: network integration coverage for `QtMediaBackend(video=False, streaming=True)`

- [ ] **Step 1: Write failing dependency-updater assertions**

Assert the updater command includes `yt-dlp[default]` and excludes `python-mpv`, and assert the UI description mentions yt-dlp/EJS plus an application restart but no libmpv DLL.

- [ ] **Step 2: Run updater tests and verify the RED state**

Run: `.venv/bin/pytest -q tests/unit/test_feature_update_service.py`

Expected: failure because `python-mpv<2` is still in `UPDATE_REQUIREMENTS`.

- [ ] **Step 3: Remove the obsolete runtime path**

Remove `python-mpv` from project dependencies, updater requirements, result reporting, and UI copy. Delete the production adapter and remove only the libmpv-specific fixtures and tests from `test_youtube_audio.py`; retain its playlist, router, fallback, metadata, and controller coverage. Remove the `mpv_integration` pytest marker.

- [ ] **Step 4: Replace native-mpv integration coverage**

Keep the existing public YouTube URL gate, but instantiate `QtMediaBackend(video=False, streaming=True)`, wait for `READY`, `PLAYING`, or a diagnostic failure, and verify position advances when `CHURCH_PRESENTER_MEDIA_INTEGRATION=1`. The test must create a `QApplication` through `qtbot` and always close the backend.

- [ ] **Step 5: Run dependency, import, and integration-collection checks**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_feature_update_service.py
.venv/bin/pytest --collect-only -q tests/integration/test_youtube_streaming.py
rg -n 'MpvAudioBackend|python-mpv|mpv_integration' src tests pyproject.toml
```

Expected: tests pass and the search returns no production/test/config references.

- [ ] **Step 6: Commit dependency removal**

```bash
git add pyproject.toml src/church_presenter/media/mpv_audio_backend.py src/church_presenter/services/feature_update_service.py src/church_presenter/ui/panels/video_panel.py tests/unit/test_youtube_audio.py tests/unit/test_feature_update_service.py tests/integration/test_youtube_streaming.py
git commit -m "refactor: remove libmpv music backend"
```

---

### Task 4: Cross-platform media documentation and final verification

**Files:**
- Modify: `docs/media-playback.md`
- Modify: `docs/windows-media-test.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/architecture.md`
- Modify: `docs/session-handoff.md`

**Interfaces:**
- Documents: Qt-only local/YouTube music path, yt-dlp updater boundary, and Windows validation checklist

- [ ] **Step 1: Replace current libmpv operator guidance**

Document the shared Qt audio path, remove `mpv-2.dll`, bitness, libmpv device mapping, and python-mpv update instructions, and retain yt-dlp/EJS/Deno guidance. In the Windows checklist, require successful local music, YouTube resolution, Qt `hasAudio`, output-device description, position advancement, mute/volume, fallback file, and clean shutdown.

- [ ] **Step 2: Run static checks and the full non-network suite**

Run:

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m 'not media_integration'
```

Expected: every command exits 0.

- [ ] **Step 3: Run the opt-in media integration test when network is available**

Run: `CHURCH_PRESENTER_MEDIA_INTEGRATION=1 .venv/bin/pytest -q tests/integration/test_youtube_streaming.py`

Expected: pass, or a clearly recorded external network/Qt codec limitation without weakening unit coverage.

- [ ] **Step 4: Commit documentation and verification fixes**

```bash
git add docs/media-playback.md docs/windows-media-test.md docs/user-guide.md docs/architecture.md docs/session-handoff.md
git commit -m "docs: document Qt music playback"
```
