# Source-aware Worship Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the source path or URL for every file-backed worship-order cue and restore it with a per-cue fallback to the active source when a saved local file is unavailable.

**Architecture:** Extend `Content` and `CueReference` with subtitle provenance and generic persisted path/URL fields, then write schema version 4 while keeping versions 1–3 readable. Resolve both channels into immutable `Content` snapshots before changing either Preview; the source panels are navigation aids rather than the source of truth.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, JSON, PySide6/Qt Widgets, pytest, pytest-qt

## Global Constraints

- Store absolute paths for PDF, local video, praise plan, and Bible plan cues.
- Store the original URL for YouTube video cues.
- Use an existing saved path before the active source; use the active source only when the saved path is absent or missing.
- Resolve fallback independently for Broadcast and Venue so the channels may use different files.
- Do not change either Preview unless both cues resolve successfully.
- Write worship-order schema version 4 and continue reading versions 1, 2, and 3.
- Do not stage or modify the pre-existing `.DS_Store` changes.

---

### Task 1: Source-aware cue reference model

**Files:**
- Modify: `src/church_presenter/domain/models.py:90-385`
- Test: `tests/unit/test_settings.py`

**Interfaces:**
- Produces: `Content.subtitle(..., source_path: Path | None = None) -> Content`
- Produces: `Content.subtitle_path: Path | None`
- Produces: `CueReference.path: Path | None`
- Produces: `CueReference.url: str`
- Produces: `CueReference.from_content(content: Content) -> CueReference`
- Produces: `CueReference.to_content() -> Content`

- [ ] **Step 1: Write failing round-trip tests for every source-bearing cue**

Add parameterized cases that convert `Content` to `CueReference`, serialize it, deserialize it, and convert it back:

```python
@pytest.mark.parametrize(
    ("content", "expected_path", "expected_url"),
    [
        (Content.pdf(Path("/media/slides.pdf"), 4), Path("/media/slides.pdf"), ""),
        (Content.video(Path("/media/clip.mp4")), Path("/media/clip.mp4"), ""),
        (Content.youtube_video("https://youtu.be/example"), None, "https://youtu.be/example"),
        (
            Content.subtitle(
                "Verse",
                2,
                SubtitleStyle(),
                "#00FF00",
                source="praise",
                reference="song-1:verse-1",
                source_path=Path("/plans/praise.json"),
            ),
            Path("/plans/praise.json"),
            "",
        ),
    ],
)
def test_cue_reference_retains_source(content, expected_path, expected_url) -> None:
    restored = CueReference.from_dict(CueReference.from_content(content).to_dict())
    assert restored.path == expected_path
    assert restored.url == expected_url
    assert CueReference.from_content(restored.to_content()) == restored
```

- [ ] **Step 2: Run the focused model test and verify the RED state**

Run: `.venv/bin/pytest -q tests/unit/test_settings.py::test_cue_reference_retains_source`

Expected: failure because `source_path`, `path`, and `url` do not exist.

- [ ] **Step 3: Add the source fields and lossless conversion**

Add `subtitle_path` to `Content`, serialize it as `subtitle_path`, accept `source_path` in the subtitle constructor, and preserve it in `as_preset_reference()`. Add `path` and `url` to `CueReference`; derive the path from `subtitle_path`, `pdf_path`, or `video_path` according to kind, and derive the URL from `video_url`.

`CueReference.to_dict()` writes `path` only when non-null and `url` only when non-empty. `from_dict()` accepts omitted fields. `to_content()` restores the appropriate kind-specific field:

```python
if self.kind is ContentType.PDF_PAGE:
    return Content(kind=self.kind, pdf_path=self.path, pdf_page=self.position)
if self.kind is ContentType.VIDEO:
    return Content(kind=self.kind, video_path=self.path, video_url=self.url)
```

- [ ] **Step 4: Run the focused test and the existing model/settings tests**

Run: `.venv/bin/pytest -q tests/unit/test_settings.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the domain model**

```bash
git add src/church_presenter/domain/models.py tests/unit/test_settings.py
git commit -m "feat: persist worship cue sources"
```

---

### Task 2: Schema version 4 with legacy loading

**Files:**
- Modify: `src/church_presenter/services/settings_service.py:96-175`
- Modify: `tests/unit/test_settings.py`

**Interfaces:**
- Consumes: `PreviewPreset.to_preset_dict() -> dict[str, Any]`
- Produces: `SettingsService._preview_presets_payload(...)` with `version == 4`
- Produces: `SettingsService._preview_presets_from_payload(...)` accepting versions `{1, 2, 3, 4}`

- [ ] **Step 1: Write failing v4 and compatibility tests**

Assert that a saved file has version 4 and exact source keys, then load it and compare presets. Keep separate fixtures for v1 full-content, v2 positional references, and v3 semantic subtitle references:

```python
def test_worship_order_v4_round_trip_retains_sources(tmp_path: Path) -> None:
    path = tmp_path / "service.json"
    service = SettingsService(tmp_path)
    preset = PreviewPreset(
        "Opening",
        Content.pdf(tmp_path / "broadcast.pdf", 2),
        Content.youtube_video("https://www.youtube.com/watch?v=abcdefghijk"),
    )
    service.save_preview_preset_file(path, [preset])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 4
    assert payload["presets"][0]["broadcast"]["path"] == str(tmp_path / "broadcast.pdf")
    assert payload["presets"][0]["venue"]["url"].startswith("https://")
    assert service.load_preview_preset_file(path) == [preset.as_file_independent()]
```

- [ ] **Step 2: Run new and legacy tests and verify the RED state**

Run: `.venv/bin/pytest -q tests/unit/test_settings.py -k 'worship_order or preview_preset'`

Expected: the v4 assertion fails because the writer emits version 3.

- [ ] **Step 3: Advance the writer and extend the reader**

Change the version dispatch to `if version in {2, 3, 4}` and emit version 4. Keep the v1 migration through `PreviewPreset.from_dict(...).as_file_independent()` so legacy paths survive the new conversion. Keep the version-2 files under `sample_assets/` unchanged as explicit legacy-loading examples.

- [ ] **Step 4: Run all settings tests**

Run: `.venv/bin/pytest -q tests/unit/test_settings.py`

Expected: all tests pass, including legacy fixtures.

- [ ] **Step 5: Commit schema v4**

```bash
git add src/church_presenter/services/settings_service.py tests/unit/test_settings.py
git commit -m "feat: write worship order schema v4"
```

---

### Task 3: Praise and Bible plan provenance

**Files:**
- Modify: `src/church_presenter/ui/panels/subtitle_panel.py`
- Modify: `src/church_presenter/ui/panels/bible_panel.py`
- Modify: `tests/gui/test_subtitle_source_panels.py`

**Interfaces:**
- Consumes: `Content.subtitle(..., source_path: Path | None = None)`
- Produces: praise and Bible `Content.subtitle_path == panel.plan_path`
- Produces: existing `load_plan_path(path: Path, warn: bool = True) -> bool`

- [ ] **Step 1: Add failing panel provenance tests**

Load a saved praise plan and Bible plan, request a real content row, and assert `subtitle_path` equals the resolved plan path:

```python
def test_praise_and_bible_content_retains_plan_path(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    praise_path = tmp_path / "praise.json"
    bible_path = tmp_path / "bible.json"
    _save_praise_plan(praise_path)
    _save_bible_plan(bible_path)
    assert window.subtitle_panel.load_plan_path(praise_path, warn=False)
    assert window.bible_panel.load_plan_path(bible_path, warn=False)
    assert window.subtitle_panel.content_for_reference("song-1:verse-1", 0).subtitle_path == praise_path.resolve()
    assert window.bible_panel.content_for_reference("John 3:16", 0).subtitle_path == bible_path.resolve()
```

- [ ] **Step 2: Run the focused test and verify the RED state**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/gui/test_subtitle_source_panels.py::test_praise_and_bible_content_retains_plan_path`

Expected: failure because panel-created content has no subtitle plan path.

- [ ] **Step 3: Pass each panel's resolved `plan_path` into `Content.subtitle`**

Update only the content construction sites. Do not change semantic references, card indexes, styles, labels, or navigation.

- [ ] **Step 4: Run the subtitle-source panel suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/gui/test_subtitle_source_panels.py`

Expected: all tests pass.

- [ ] **Step 5: Commit subtitle provenance**

```bash
git add src/church_presenter/ui/panels/subtitle_panel.py src/church_presenter/ui/panels/bible_panel.py tests/gui/test_subtitle_source_panels.py
git commit -m "feat: retain subtitle plan provenance"
```

---

### Task 4: Atomic source-aware preset resolution

**Files:**
- Modify: `src/church_presenter/ui/controller_window.py:1013-1375`
- Modify: `src/church_presenter/ui/panels/pdf_panel.py`
- Modify: `src/church_presenter/ui/panels/video_panel.py`
- Modify: `tests/gui/test_controller.py`

**Interfaces:**
- Produces: `ControllerWindow._available_path(saved: Path | None, active: Path | None) -> Path | None`
- Produces: `ControllerWindow._resolve_preview_preset(preset: PreviewPreset) -> tuple[dict[ChannelRole, Content] | None, str]`
- Produces: `PdfPanel.select_path(path: Path, page: int = 1) -> bool`
- Produces: `VideoPanel.select_source(source: Path | str) -> bool`

- [ ] **Step 1: Write failing resolution tests**

Add controller tests for these independent cases:

```python
def test_preset_uses_saved_pdf_paths_per_channel(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    broadcast_pdf = _write_pdf(tmp_path / "broadcast.pdf", pages=3)
    venue_pdf = _write_pdf(tmp_path / "venue.pdf", pages=4)
    window.preview_presets = [
        PreviewPreset("Split", Content.pdf(broadcast_pdf, 2), Content.pdf(venue_pdf, 4))
    ]
    assert window.apply_preview_preset("Split")
    assert window.state.broadcast.preview_content == Content.pdf(broadcast_pdf, 2)
    assert window.state.venue.preview_content == Content.pdf(venue_pdf, 4)


def test_missing_saved_pdf_falls_back_to_active_pdf(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    active = _write_pdf(tmp_path / "active.pdf", pages=2)
    window.pdf_panel.select_path(active)
    window.preview_presets = [
        PreviewPreset("Fallback", Content.pdf(tmp_path / "missing.pdf", 2), Content.black())
    ]
    assert window.apply_preview_preset("Fallback")
    assert window.state.broadcast.preview_content == Content.pdf(active, 2)


def test_failed_second_cue_preserves_both_previews(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    before = (window.state.broadcast.preview_content, window.state.venue.preview_content)
    window.preview_presets = [
        PreviewPreset("Invalid", Content.black(), Content.pdf(tmp_path / "missing.pdf", 999))
    ]
    assert not window.apply_preview_preset("Invalid")
    assert (window.state.broadcast.preview_content, window.state.venue.preview_content) == before
```

Add parallel cases for a saved YouTube URL, saved local video, saved praise plan, saved Bible plan, and missing-path fallback to each active panel source.

- [ ] **Step 2: Run the focused controller tests and verify the RED state**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/gui/test_controller.py -k 'saved_pdf_paths or missing_saved or saved_youtube or saved_praise or saved_bible or preserves_both'`

Expected: saved sources are ignored because resolution uses only active panels.

- [ ] **Step 3: Resolve source-aware snapshots before mutating state**

For each cue, choose an existing saved local path or fall back to the current active source. Build PDF and video `Content` directly from the selected source. For subtitles, load the selected plan only after the other cue's path/page validation succeeds, then call the correct panel's semantic `content_for_reference` method. Collect both results in a temporary dictionary and return an error before `state.set_preview(...)` is called if any resolver fails.

Keep `save_preview_preset` and `update_preview_preset` using `as_preset_reference()`, which now strips rendered text/styles but retains path/URL provenance.

- [ ] **Step 4: Add optional panel navigation helpers**

`PdfPanel.select_path` accepts a valid PDF even if it is outside the currently scanned folder, sets the page after loading, and returns `False` without changing selection for an invalid file. `VideoPanel.select_source` selects an existing list item or creates/selects the same transient representation used by drag-and-drop. Synchronize at most the first resolved source per panel after both contents resolve.

- [ ] **Step 5: Run focused and full controller suites**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/gui/test_controller.py tests/gui/test_subtitle_source_panels.py tests/gui/test_media_panels.py`

Expected: all tests pass.

- [ ] **Step 6: Commit source-aware application**

```bash
git add src/church_presenter/ui/controller_window.py src/church_presenter/ui/panels/pdf_panel.py src/church_presenter/ui/panels/video_panel.py tests/gui/test_controller.py
git commit -m "feat: restore worship cue sources"
```

---

### Task 5: User documentation and verification

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Documents: schema v4 source priority and legacy fallback behavior

- [ ] **Step 1: Update operator documentation**

Explain that newly saved worship orders retain source paths/URLs, moved or deleted local sources use the current active source, and no media is copied into the JSON file. Add schema v4 and per-cue resolution to the architecture document.

- [ ] **Step 2: Run formatting, types, and the non-network suite**

Run:

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m 'not media_integration'
```

Expected: every command exits 0.

- [ ] **Step 3: Commit documentation and verification fixes**

```bash
git add docs/user-guide.md docs/architecture.md
git commit -m "docs: explain source-aware worship orders"
```
