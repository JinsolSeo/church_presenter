---
title: Select the composite tab before using reparented tool widgets
date: 2026-08-03
category: ui-bugs
module: controller-tabs
problem_type: ui_bug
component: frontend
symptoms:
  - "QTabWidget.setCurrentWidget(child) no longer activates a tool after the tool is moved inside a composite tab page"
  - "Current-tab-dependent style refresh logic silently takes the wrong branch"
  - "GUI geometry assertions read zero or stale coordinates for hidden child widgets"
root_cause: wrong_api
resolution_type: code_fix
severity: medium
tags:
  - qt-widgets
  - qtabwidget
  - composite-panel
  - gui-testing
  - settings-compatibility
---

# Select the composite tab before using reparented tool widgets

## Problem

Combining two direct `QTabWidget` pages into one composite page changes which widgets the tab owns. Existing code and tests can still hold references to the original tool widgets, but those widgets are now descendants of the composite page and are no longer valid arguments to `QTabWidget.setCurrentWidget()`.

This can fail quietly. The requested child widget remains usable as an object, while the active tab, visibility, geometry, and any logic based on `currentWidget()` remain unchanged.

## Symptoms

- A test calls `tabs.setCurrentWidget(tool_panel)`, but the previous tab remains active.
- Style or navigation logic that checks the active tab does not refresh the tool's prepared content.
- Hidden child widgets report unusable coordinates or button spacing even though their layout is correct when visible.
- Saved identifiers for the removed direct tabs no longer restore a visible page.

## What Didn't Work

- Keeping the old `setCurrentWidget(tool_panel)` calls after reparenting. `QTabWidget` only selects widgets added as its direct pages.
- Verifying the composite layout while another tab is active. Equal stretch factors can be inspected while hidden, but user-visible positions and sizes require the composite page to be shown and Qt events to be processed.
- Updating only the tab construction. Active-tab branches and persisted stable tab identifiers are separate consumers of the old page identity.

## Solution

Add the composite widget itself as the direct tab page while retaining direct controller references to the nested tools for signals and feature behavior:

```python
self.misc_panel = MiscPanel(self.instant_panel, self.black_panel)
self.tabs.addTab(self.misc_panel, "기타")
```

Any logic that means “the instant tool's containing tab is active” must compare against the composite page:

```python
from_instant = self.tabs.currentWidget() is self.misc_panel
```

Tests must also select the composite page before interacting with or measuring a nested tool:

```python
window.tabs.setCurrentWidget(window.misc_panel)
QApplication.processEvents()

window.instant_panel.preview_current()
```

Keep focus ancestry checks against the nested tool when the distinction between the left and right sections matters. A focused descendant still satisfies `tool_panel.isAncestorOf(focus)` even though the tool is not a direct tab page.

Finally, map persisted identifiers for removed pages to the new stable composite identifier before tab lookup:

```python
source_id = settings.panel_layout.removeprefix("tab:")
if source_id in {"instant", "black"}:
    source_id = "misc"
```

## Why This Works

It separates two identities that were previously the same:

- The composite page is the unit of tab selection, visibility, ordering, and persistence.
- Each nested tool remains the unit of signals, focus ancestry, content preparation, and TAKE behavior.

Using the correct identity at each boundary preserves existing feature objects without asking `QTabWidget` to select a non-page descendant.

## Prevention

- When reparenting a direct tab page, search for `setCurrentWidget`, `currentWidget`, `indexOf`, saved tab identifiers, and geometry tests that reference the old page.
- Test both the composite page contract and the original nested tool behavior.
- Select and show the composite page before asserting child coordinates or size relationships.
- Add a compatibility test for each removed persisted tab identifier.

## Related Issues

- The implementation is covered by `tests/gui/test_subtitle_source_panels.py`, including composite selection, equal-width layout, legacy identifier restoration, and instant-style refresh.
