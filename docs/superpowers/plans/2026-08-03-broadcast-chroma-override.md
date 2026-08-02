# Broadcast Chroma Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `크로마키` check box that visually forces only Broadcast Live to fixed green while preserving and updating the underlying Live content for immediate reveal when cleared.

**Architecture:** Keep `ApplicationState` authoritative for Preview and underlying Live content. Resolve a separate effective Broadcast Live content at the Controller output boundary, and use it consistently for the Controller monitor, simulator/physical output, TAKE refreshes, and output startup.

**Tech Stack:** Python 3.11+, PySide6/Qt Widgets, pytest, pytest-qt

## Global Constraints

- The control label is exactly `크로마키` and the color is fixed to `#00FF00`.
- Only Broadcast Live visual output and the Controller `송출 LIVE` monitor are overridden.
- Broadcast Preview, Venue Preview, Venue Live, and all underlying `ApplicationState` content remain state-driven.
- TAKE and TAKE BOTH continue updating underlying Live while the visual override stays green.
- Clearing the check reveals the latest underlying Broadcast Live content.
- The override does not pause, mute, restart, or otherwise control media.
- The override is not persisted and starts unchecked on every application launch.
- Do not stage or modify the pre-existing `.DS_Store` changes.

---

### Task 1: Effective Broadcast Live override

**Files:**
- Modify: `src/church_presenter/ui/controller_window.py:80-100,454-495,883-897,1976-2030,2072-2105`
- Test: `tests/gui/test_controller.py`

**Interfaces:**
- Produces: `BROADCAST_CHROMA_CONTENT: Content`
- Produces: `ControllerWindow.sync_chroma_check: QCheckBox`
- Produces: `ControllerWindow._effective_live_content(role: ChannelRole) -> Content`
- Produces: `ControllerWindow._broadcast_chroma_toggled(enabled: bool) -> None`
- Consumes: existing `ControllerWindow._push_live`, `_refresh_channel`, `start_outputs`, `take`, and `take_both`

- [x] **Step 1: Write failing GUI tests for activation, latest-TAKE reveal, and TAKE BOTH isolation**

Add three tests using the real Controller and simulation output:

```python
def test_broadcast_chroma_override_only_replaces_broadcast_displays(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    broadcast_live = Content.subtitle("현재 송출", 0, SubtitleStyle(), "#00FF00")
    venue_live = Content.solid_color("#0000FF")
    broadcast_preview = Content.subtitle("다음 송출", 1, SubtitleStyle(), "#00FF00")
    venue_preview = Content.black()
    window.state.broadcast.live_content = broadcast_live
    window.state.venue.live_content = venue_live
    window.state.set_preview(ChannelRole.BROADCAST, broadcast_preview)
    window.state.set_preview(ChannelRole.VENUE, venue_preview)
    window._refresh_all()

    assert window.sync_chroma_check.text() == "크로마키"
    assert window.sync_chroma_check.objectName() == "BroadcastChromaCheck"
    assert not window.sync_chroma_check.isChecked()
    qtbot.mouseClick(window.sync_chroma_check, Qt.MouseButton.LeftButton)

    green = Content.solid_color("#00FF00")
    assert window.state.broadcast.live_content == broadcast_live
    assert window.state.venue.live_content == venue_live
    assert window.state.broadcast.preview_content == broadcast_preview
    assert window.state.venue.preview_content == venue_preview
    assert window.broadcast_live.surface.target_content == green
    assert window.venue_live.surface.target_content == venue_live

    assert window.start_outputs()
    assert window.broadcast_simulator is not None
    assert window.venue_simulator is not None
    assert window.broadcast_simulator.surface.target_content == green
    assert window.venue_simulator.surface.target_content == venue_live


def test_broadcast_chroma_override_reveals_latest_take_when_cleared(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    first = Content.subtitle("첫 화면", 0, SubtitleStyle(), "#00FF00")
    latest = Content.subtitle("새 화면", 1, SubtitleStyle(), "#00FF00")
    window.set_preview(ChannelRole.BROADCAST, first)
    assert window.take(ChannelRole.BROADCAST)
    window.sync_chroma_check.setChecked(True)

    window.set_preview(ChannelRole.BROADCAST, latest)
    assert window.take(ChannelRole.BROADCAST)

    green = Content.solid_color("#00FF00")
    assert window.state.broadcast.live_content == latest
    assert window.broadcast_live.surface.target_content == green
    assert window.broadcast_simulator is not None
    assert window.broadcast_simulator.surface.target_content == green

    window.sync_chroma_check.setChecked(False)

    assert window.broadcast_live.surface.target_content == latest
    assert window.broadcast_simulator.surface.target_content == latest
    assert "최신 송출 Live" in window.status.text()


def test_take_both_keeps_only_broadcast_visually_overridden(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    broadcast = Content.subtitle("찬양", 0, SubtitleStyle(), "#00FF00")
    venue = Content.solid_color("#0000FF")
    window.set_preview(ChannelRole.BROADCAST, broadcast)
    window.set_preview(ChannelRole.VENUE, venue)
    window.sync_content_check.setChecked(True)
    window.sync_auto_take_check.setChecked(True)
    window.sync_chroma_check.setChecked(True)

    assert window.take_both()

    assert window.sync_content_check.isChecked()
    assert window.sync_auto_take_check.isChecked()
    assert window.state.broadcast.live_content == broadcast
    assert window.state.venue.live_content == venue
    assert window.broadcast_live.surface.target_content == Content.solid_color("#00FF00")
    assert window.venue_live.surface.target_content == venue
    assert window.broadcast_simulator is not None
    assert window.venue_simulator is not None
    assert window.broadcast_simulator.surface.target_content == Content.solid_color("#00FF00")
    assert window.venue_simulator.surface.target_content == venue
```

The production mutations these tests catch are missing or wrong green output, state mutation, Preview/Venue contamination, lost TAKE updates, stale-content restoration, output startup bypassing the override, or coupling the new check box to the existing linked controls.

- [x] **Step 2: Run the focused tests and verify the RED state**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest -q \
  tests/gui/test_controller.py::test_broadcast_chroma_override_only_replaces_broadcast_displays \
  tests/gui/test_controller.py::test_broadcast_chroma_override_reveals_latest_take_when_cleared \
  tests/gui/test_controller.py::test_take_both_keeps_only_broadcast_visually_overridden
```

Expected: all three tests fail because `sync_chroma_check` and the effective-content output path do not exist.

- [x] **Step 3: Add the check box and effective-content resolver**

Add the immutable module-level content constant:

```python
BROADCAST_CHROMA_CONTENT = Content.solid_color("#00FF00")
```

Create the check box with no settings-backed initial value:

```python
self.sync_chroma_check = QCheckBox("크로마키")
self.sync_chroma_check.setObjectName("BroadcastChromaCheck")
self.sync_chroma_check.setToolTip(
    "송출 화면과 송출 LIVE를 크로마키 그린으로 가립니다. "
    "해제하면 가장 최근에 TAKE한 송출 Live를 표시합니다."
)
sync_widgets = (
    self.sync_auto_take_check,
    self.sync_chroma_check,
    self.sync_previous_button,
    self.sync_next_button,
    self.sync_take_button,
)
```

Connect it in `_connect_signals`:

```python
self.sync_chroma_check.toggled.connect(self._broadcast_chroma_toggled)
```

Add the resolver and toggle handler:

```python
def _effective_live_content(self, role: ChannelRole) -> Content:
    if role is ChannelRole.BROADCAST and self.sync_chroma_check.isChecked():
        return BROADCAST_CHROMA_CONTENT
    return self.state.channel(role).live_content

def _broadcast_chroma_toggled(self, enabled: bool) -> None:
    self._push_live(ChannelRole.BROADCAST)
    self.status.setText(
        "송출 화면을 크로마키 그린으로 전환했습니다."
        if enabled
        else "크로마키 해제 · 최신 송출 Live를 복원했습니다."
    )
```

- [x] **Step 4: Route every Broadcast visual publication through the resolver**

Use `_effective_live_content(ChannelRole.BROADCAST)` when initializing Broadcast output in both simulation and physical branches of `start_outputs`.

In `_push_live`, replace direct channel Live lookup with:

```python
content = self._effective_live_content(role)
```

In `_refresh_channel`, keep Preview state-driven but resolve Broadcast Live:

```python
if role is ChannelRole.BROADCAST:
    self.broadcast_preview.set_content(channel.preview_content)
    self.broadcast_live.set_content(self._effective_live_content(role))
```

Do not change `take`, `take_both`, media transport, state mutation, Venue rendering, or Preview rendering. Existing calls to `_push_live` and `_refresh_channel` then preserve green automatically while their underlying state transitions proceed.

- [x] **Step 5: Run focused and adjacent linked-control tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest -q \
  tests/gui/test_controller.py::test_broadcast_chroma_override_only_replaces_broadcast_displays \
  tests/gui/test_controller.py::test_broadcast_chroma_override_reveals_latest_take_when_cleared \
  tests/gui/test_controller.py::test_take_both_keeps_only_broadcast_visually_overridden \
  tests/gui/test_controller.py::test_sync_checkbox_uses_one_indicator_and_compact_label \
  tests/gui/test_controller.py::test_linked_auto_take_moves_live_with_page_and_arrow_keys
```

Expected: all selected tests pass.

- [x] **Step 6: Commit the behavior**

```bash
git add src/church_presenter/ui/controller_window.py tests/gui/test_controller.py
git commit -m "feat: 송출 크로마키 오버라이드 추가"
```

---

### Task 2: Operator documentation and whole-change verification

**Files:**
- Modify: `docs/user-guide.md:140-165`
- Modify: `docs/superpowers/plans/2026-08-03-broadcast-chroma-override.md`
- Test: `tests/gui/test_controller.py`

**Interfaces:**
- Consumes: `ControllerWindow.sync_chroma_check` behavior from Task 1
- Produces: operator-facing explanation of temporary Broadcast green output and latest-Live reveal

- [x] **Step 1: Update the linked-control user guide**

Add this behavior after the existing `바로 Live` explanation:

```markdown
`크로마키`를 체크하면 실제 송출 화면과 Controller의 `송출 LIVE`만 그린
(`#00FF00`)으로 가립니다. 송출 Preview와 현장 화면은 바뀌지 않으며, 체크된 동안에도
찬양, 성경, PDF, 영상을 계속 TAKE할 수 있습니다. 이때 내부 송출 Live는 최신 콘텐츠로
갱신되지만 화면은 계속 그린을 유지합니다. 체크를 해제하면 가장 최근에 TAKE한 송출
Live가 즉시 표시됩니다. 이 상태는 앱을 다시 시작할 때 저장되지 않습니다.
```

- [x] **Step 2: Run the complete affected GUI module**

```bash
QT_QPA_PLATFORM=offscreen pytest -q tests/gui/test_controller.py
```

Expected: zero failures.

- [x] **Step 3: Run the full non-media suite**

```bash
QT_QPA_PLATFORM=offscreen pytest -q -m 'not media_integration'
```

Expected: zero failures; network-dependent media integration tests remain deselected or skipped according to their existing markers.

- [x] **Step 4: Verify formatting and scope**

```bash
git diff --check
git status --short
git diff --stat 598f143..HEAD
```

Expected: no whitespace errors; only the planned source, tests, guide, and implementation plan are in feature scope; `.DS_Store` remains unstaged.

- [x] **Step 5: Commit the guide and implementation plan**

```bash
git add docs/user-guide.md docs/superpowers/plans/2026-08-03-broadcast-chroma-override.md
git commit -m "docs: 송출 크로마키 사용법 기록"
```
