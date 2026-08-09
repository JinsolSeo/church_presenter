---
title: Suppress tab restore during monitor-driven control routing
date: 2026-08-09
category: architecture-patterns
module: controller_navigation
problem_type: architecture_pattern
component: frontend
severity: medium
applies_when:
  - A monitor click selects controls for an already-authoritative Preview state
  - A QTabWidget currentChanged handler restores Preview during ordinary tab navigation
  - Programmatic navigation must preserve Preview and Live while changing control focus
tags: [pyside6, qtabwidget, preview-routing, signal-suppression, focus-routing, state-safety]
---

# Suppress tab restore during monitor-driven control routing

## Context

A monitor click is a control-focus operation: it should expose the controls for the clicked
channel's current Preview without changing Preview or Live. That is unsafe if ordinary tab
selection has a useful state-restoration side effect.

In this controller, `QTabWidget.currentChanged` calls `_content_tab_changed`, which restores
the praise or Bible panel's remembered cursor (`src/church_presenter/ui/controller_window.py:612`
and `src/church_presenter/ui/controller_window.py:661`). Those restore paths emit a new Preview
request. A direct programmatic `setCurrentWidget()` can therefore identify the correct existing
Preview and immediately replace it with stale panel state.

Manual tab selection intentionally restores remembered Preview content, and keyboard navigation
intentionally follows focus (session history). The monitor handoff must preserve those contracts
while remaining state-neutral itself.

## Guidance

Separate ordinary user tab selection from programmatic tab selection performed only to route
control:

```python
def _select_monitor_control_tab(self, panel: QWidget) -> None:
    self._suppress_content_tab_restore = True
    try:
        self.tabs.setCurrentWidget(panel)
    finally:
        self._suppress_content_tab_restore = False

def _content_tab_changed(self, _index: int) -> None:
    if self._suppress_content_tab_restore:
        return
    # Preserve ordinary operator-driven restore behavior below.
```

Keep the guard scoped to the one programmatic tab transition and clear it in `finally`. Do not
block the tab widget's signals globally or remove the ordinary restore behavior. The implemented
guard is in `src/church_presenter/ui/controller_window.py:661` and
`src/church_presenter/ui/controller_window.py:2395`.

Resolve the destination from the clicked channel's `preview_content`, regardless of whether the
operator clicked that channel's Preview or Live monitor. The monitor lookup maps both surfaces to
the same channel role, while activation reads only Preview
(`src/church_presenter/ui/controller_window.py:2378` and
`src/church_presenter/ui/controller_window.py:2403`). Subtitle source metadata selects praise,
Bible, or instant controls; content kind selects PDF or video controls; blank and solid content
select the miscellaneous/blank controls.

For a control panel that can target either output, set its target to the clicked channel before
handing over focus. After selecting the tab, focus the content-specific navigation widget and
repeat the focus request on the next event-loop turn so the intended navigation widget retains
focus after mouse processing settles (`src/church_presenter/ui/controller_window.py:2431-2434`).
Existing focus-based routing then applies; the PDF regression test verifies that navigation
changes only the selected channel.

## Why This Matters

Preview and Live are authoritative presentation state, not visual labels. Each channel stores them
separately (`src/church_presenter/domain/state.py:14-16`), and TAKE copies validated Preview into Live
(`src/church_presenter/domain/state.py:64-72`). A focus-only click that rewrites Preview prepares the
wrong content for a later TAKE even when Live appears unchanged.

The failure is subtle because the UI ends on the expected tab. It is visible only when comparing
state before and after the click, or when the next navigation/TAKE uses the overwritten Preview.
The scoped guard preserves both behaviors: direct tab selection can restore remembered content,
while monitor-driven selection only changes the active controls.

## Prevention

- Assert Preview, Live, and readiness state before and after both Preview-monitor and Live-monitor
  clicks. The Broadcast Bible-Preview/PDF-Live case is covered at
  `tests/gui/test_controller.py:1018`.
- Give the destination panel a deliberately stale cursor and verify that monitor routing changes
  tab and focus without restoring that cursor (`tests/gui/test_controller.py:1075`).
- For PDF controls, enable the broader two-channel target first, click one channel, navigate, and
  assert that only the clicked channel's Preview changes
  (`tests/gui/test_controller.py:1090`).
- Cover the remaining video, instant-text, and BLACK mappings
  (`tests/gui/test_controller.py:1128`).
- Whenever programmatic selection uses a component whose normal selection handler mutates state,
  test the triggering action's state-neutral invariant rather than only the final visible page.

## When to Apply

Use this pattern when a programmatic action selects a tab, route, or mode only to expose controls,
the normal selection callback performs restoration or another mutation, and that mutation remains
desirable for direct user selection. The guard distinguishes the cause of selection; it should not
be broadened to TAKE, Preview preparation, navigation, or ordinary tab changes.

## Related

- `docs/superpowers/specs/2026-08-09-preview-monitor-control-routing-design.md`
- `docs/solutions/architecture-patterns/safety-transitions-must-bypass-temporary-output-overrides.md`
- `docs/solutions/ui-bugs/select-the-composite-tab-before-using-reparented-tool-widgets.md`
