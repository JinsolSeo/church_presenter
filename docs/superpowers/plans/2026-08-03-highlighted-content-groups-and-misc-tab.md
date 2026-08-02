# Highlighted Content Groups and Misc Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Highlight praise-song and Bible-range headers with the active theme and replace the separate instant-text and blank-screen tabs with one equal-width `기타` tab.

**Architecture:** Keep the existing `QListWidgetItem` header rows and give each source panel a small theme API that applies an accent foreground and bold font to header items. Add a layout-only `MiscPanel` that hosts the existing `InstantPanel` and `BlackPanel` instances side by side, while the controller retains direct references and signal wiring.

**Tech Stack:** Python 3.11+, PySide6/Qt Widgets, pytest, pytest-qt

## Global Constraints

- The final tab order is exactly `찬양 · 성경 · PDF · 영상 · 음악 · 기타`.
- The `기타` tab uses a fixed 1:1 left/right layout: instant text on the left and blank screen on the right.
- Existing Preview, Live, TAKE, Send to Both, TAKE BOTH, style editing, keyboard handling, and persistence behavior must remain intact.
- Use the active theme's existing `colors.accent`; do not add a theme field or settings migration.
- Do not stage or modify the pre-existing `.DS_Store` changes.

---

### Task 1: Theme-aware praise and Bible group headers

**Files:**
- Modify: `src/church_presenter/ui/panels/subtitle_panel.py:45-205,356-401`
- Modify: `src/church_presenter/ui/panels/bible_panel.py:1-220,410-457`
- Modify: `src/church_presenter/ui/controller_window.py:795-805`
- Test: `tests/gui/test_subtitle_source_panels.py`

**Interfaces:**
- Consumes: `ThemeManager.current_value("colors", "accent") -> object`
- Produces: `SubtitlePanel.set_group_header_color(color: str) -> None`
- Produces: `BiblePanel.set_group_header_color(color: str) -> None`

- [x] **Step 1: Write focused failing tests for both header types**

Add two tests that build real plan rows, switch the live controller theme, and inspect the existing header items:

```python
from PySide6.QtGui import QColor


def test_praise_song_headers_follow_active_theme(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.subtitle_panel
    assert panel.load_song_paths([SAMPLE_SONG])
    panel.add_selected_sections()

    window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark_modern"))

    header = panel.plan_list.item(0)
    assert header.data(Qt.ItemDataRole.UserRole) == ("entry", 0)
    assert header.foreground().color() == QColor(
        str(window.theme_manager.current_value("colors", "accent"))
    )
    assert header.font().bold()
    assert not bool(header.flags() & Qt.ItemFlag.ItemIsSelectable)
    panel.is_modified = False


def test_bible_range_headers_follow_active_theme(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel
    qtbot.mouseClick(panel.add_after_button, Qt.MouseButton.LeftButton)

    window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark_modern"))

    header = panel.plan_list.item(0)
    assert header.data(Qt.ItemDataRole.UserRole) == ("range", 0)
    assert header.foreground().color() == QColor(
        str(window.theme_manager.current_value("colors", "accent"))
    )
    assert header.font().bold()
    assert not bool(header.flags() & Qt.ItemFlag.ItemIsSelectable)
```

The production mutations these tests catch are a missing accent brush, a non-bold header, a theme update that only affects newly created rows, or an accidentally selectable group header.

- [x] **Step 2: Run the two tests and verify the RED state**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest -q \
  tests/gui/test_subtitle_source_panels.py::test_praise_song_headers_follow_active_theme \
  tests/gui/test_subtitle_source_panels.py::test_bible_range_headers_follow_active_theme
```

Expected: both tests fail because header items still use their default foreground and normal font.

- [x] **Step 3: Add the minimal theme APIs and style headers**

In each panel, store the accent color, style new headers during `_rebuild`, and restyle existing headers when the theme changes:

```python
def set_group_header_color(self, color: str) -> None:
    self._group_header_color = QColor(color)
    for row in range(self.plan_list.count()):
        item = self.plan_list.item(row)
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and data and data[0] in {"entry", "range"}:
            self._style_group_header(item)

def _style_group_header(self, item: QListWidgetItem) -> None:
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    item.setForeground(self._group_header_color)
```

Use only the applicable discriminator in each panel (`entry` for praise, `range` for Bible). Initialize `_group_header_color` to a valid `QColor`, import `QColor` in `bible_panel.py`, and call `_style_group_header(header)` before adding each header.

Extend `ControllerWindow._apply_subtitle_card_theme()` without changing cue-card colors:

```python
accent = str(self.theme_manager.current_value("colors", "accent"))
self.subtitle_panel.set_group_header_color(accent)
self.bible_panel.set_group_header_color(accent)
```

- [x] **Step 4: Run the focused tests and relevant existing theme test**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest -q \
  tests/gui/test_subtitle_source_panels.py::test_praise_song_headers_follow_active_theme \
  tests/gui/test_subtitle_source_panels.py::test_bible_range_headers_follow_active_theme \
  tests/gui/test_controller.py::test_all_themes_subtitle_cards_use_only_live_and_preview_highlights
```

Expected: all selected tests pass, including all parameterized theme cases.

- [x] **Step 5: Commit the header behavior**

```bash
git add src/church_presenter/ui/panels/subtitle_panel.py \
  src/church_presenter/ui/panels/bible_panel.py \
  src/church_presenter/ui/controller_window.py \
  tests/gui/test_subtitle_source_panels.py
git commit -m "feat: 찬양과 성경 그룹 제목 강조"
```

---

### Task 2: Consolidated equal-width Misc tab

**Files:**
- Create: `src/church_presenter/ui/panels/misc_panel.py`
- Modify: `src/church_presenter/domain/models.py:700-706`
- Modify: `src/church_presenter/ui/controller_window.py:65-75,543-605,913-937,1710-1720`
- Test: `tests/gui/test_subtitle_source_panels.py`
- Test: `tests/gui/test_controller.py`

**Interfaces:**
- Consumes: `MiscPanel(instant_panel: InstantPanel, black_panel: BlackPanel, parent: QWidget | None = None)`
- Produces: `MiscPanel.instant_panel`, `MiscPanel.black_panel`, `MiscPanel.instant_section`, and `MiscPanel.blank_section`
- Produces: controller references `misc_panel`, `instant_panel`, and `black_panel`

- [x] **Step 1: Replace the old tab-shape assertions with a failing Misc-tab behavior test**

Update the existing flat-tabs test and add real layout/persistence assertions:

```python
def test_content_tabs_end_with_equal_width_misc_tools(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    QApplication.processEvents()

    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "찬양", "성경", "PDF", "영상", "음악", "기타"
    ]
    assert window.tabs.currentWidget() is window.subtitle_panel
    assert window.tabs.indexOf(window.instant_panel) == -1
    assert window.tabs.indexOf(window.black_panel) == -1
    assert window.tabs.indexOf(window.misc_panel) == 5

    layout = window.misc_panel.layout()
    assert layout is not None
    assert layout.stretch(0) == layout.stretch(1) == 1
    assert window.instant_panel.parentWidget() is window.misc_panel.instant_section
    assert window.black_panel.parentWidget() is window.misc_panel.blank_section
    assert window.instant_panel.mapTo(window.misc_panel, QPoint(0, 0)).x() < (
        window.black_panel.mapTo(window.misc_panel, QPoint(0, 0)).x()
    )


@pytest.mark.parametrize("legacy_source", ["instant", "black"])
def test_legacy_tool_tab_settings_restore_misc_tab(
    qtbot, tmp_path: Path, legacy_source: str
) -> None:
    window = _window(qtbot, tmp_path)
    window.settings.panel_layout = f"tab:{legacy_source}"

    window._restore_panel_layout()

    assert window.tabs.currentWidget() is window.misc_panel
```

Also update existing tests that select or locate the old direct pages to use `window.misc_panel`; keep all interactions and assertions against `window.instant_panel` or `window.black_panel` so they still prove the real tools work after reparenting.

The production mutations these tests catch are separate old tabs returning, wrong tab order, unequal stretch, reversed tools, new replacement tool instances, or loss of legacy tab restoration.

- [x] **Step 2: Run focused tests and verify the RED state**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest -q \
  tests/gui/test_subtitle_source_panels.py::test_content_tabs_end_with_equal_width_misc_tools \
  tests/gui/test_subtitle_source_panels.py::test_legacy_tool_tab_settings_restore_misc_tab \
  tests/gui/test_controller.py::test_blank_screen_presets_prepare_preview_before_take
```

Expected: the new Misc-tab tests fail because `misc_panel` does not exist and the old tabs are still present. The blank-screen behavior test remains a regression guard after its tab lookup is updated.

- [x] **Step 3: Create the layout-only composite panel**

Create `misc_panel.py` with a small section factory and no signal relaying:

```python
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from church_presenter.ui.panels.black_panel import BlackPanel
from church_presenter.ui.panels.instant_panel import InstantPanel


class MiscPanel(QWidget):
    def __init__(
        self,
        instant_panel: InstantPanel,
        black_panel: BlackPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.instant_panel = instant_panel
        self.black_panel = black_panel
        layout = QHBoxLayout(self)
        self.instant_section = self._section("즉석 문구", instant_panel)
        self.blank_section = self._section("빈 화면", black_panel)
        layout.addWidget(self.instant_section, 1)
        layout.addWidget(self.blank_section, 1)

    @staticmethod
    def _section(title: str, panel: QWidget) -> QFrame:
        section = QFrame()
        section.setObjectName("MiscSection")
        section_layout = QVBoxLayout(section)
        heading = QLabel(title)
        heading.setProperty("role", "sectionTitle")
        section_layout.addWidget(heading)
        section_layout.addWidget(panel, 1)
        return section
```

- [x] **Step 4: Integrate the composite without changing tool signal wiring**

Construct `BlackPanel` next to `InstantPanel`, then create `self.misc_panel = MiscPanel(self.instant_panel, self.black_panel)`. Add content/media tabs in the exact final order and give the composite `ContentSource_misc`; do not add the contained panels directly to `QTabWidget`.

Update `open_source_style_settings` so the old current-tab check recognizes the composite:

```python
from_instant = self.tabs.currentWidget() is self.misc_panel
```

In `_restore_panel_layout`, normalize the two old stable identifiers before matching:

```python
source_id = self.settings.panel_layout.removeprefix("tab:")
if source_id in {"instant", "black"}:
    source_id = "misc"
```

Keep `_connect_signals`, `_keyboard_area`, content navigation, and direct `instant_panel`/`black_panel` calls unchanged because child-focus ancestry still identifies the original panels.

Change the default for new settings so the reduced `기타` tool tab does not open first:

```python
panel_layout: str = "tab:praise"
```

- [x] **Step 5: Run the focused Misc and behavior regressions**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest -q \
  tests/gui/test_subtitle_source_panels.py::test_content_tabs_end_with_equal_width_misc_tools \
  tests/gui/test_subtitle_source_panels.py::test_legacy_tool_tab_settings_restore_misc_tab \
  tests/gui/test_subtitle_source_panels.py::test_instant_text_navigation_previews_then_requires_explicit_take \
  tests/gui/test_subtitle_source_panels.py::test_returning_from_instant_restores_prepared_preview_but_keeps_live \
  tests/gui/test_controller.py::test_blank_screen_presets_prepare_preview_before_take
```

Expected: all selected tests pass and continue to interact with the original tool instances.

- [x] **Step 6: Commit the consolidated tab**

```bash
git add src/church_presenter/domain/models.py \
  src/church_presenter/ui/panels/misc_panel.py \
  src/church_presenter/ui/controller_window.py \
  tests/gui/test_subtitle_source_panels.py \
  tests/gui/test_controller.py
git commit -m "feat: 즉석과 빈 화면을 기타 탭으로 통합"
```

---

### Task 3: Whole-change verification and documentation commit

**Files:**
- Test: `tests/gui/test_subtitle_source_panels.py`
- Test: `tests/gui/test_controller.py`
- Modify: `docs/superpowers/plans/2026-08-03-highlighted-content-groups-and-misc-tab.md`

**Interfaces:**
- Consumes: all production behavior from Tasks 1 and 2
- Produces: a clean relevant GUI suite and a committed implementation plan

- [x] **Step 1: Run the complete affected GUI modules**

```bash
QT_QPA_PLATFORM=offscreen pytest -q \
  tests/gui/test_subtitle_source_panels.py \
  tests/gui/test_controller.py
```

Expected: zero failures.

- [x] **Step 2: Run the full non-media test suite**

```bash
QT_QPA_PLATFORM=offscreen pytest -q -m 'not media_integration'
```

Expected: zero failures.

- [x] **Step 3: Check formatting and scope**

```bash
git diff --check
git status --short
git diff --stat b61d1c1..HEAD
```

Expected: no whitespace errors; only the planned source, test, and documentation files are part of the feature commits; `.DS_Store` remains unstaged.

- [x] **Step 4: Commit the implementation plan**

```bash
git add docs/superpowers/plans/2026-08-03-highlighted-content-groups-and-misc-tab.md
git commit -m "docs: 목록 강조와 기타 탭 구현 계획"
```
