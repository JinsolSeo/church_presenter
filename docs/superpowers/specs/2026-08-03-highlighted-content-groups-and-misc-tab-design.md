# Highlighted Content Groups and Misc Tab Design

## Goal

Make praise songs and Bible passage groups easier to scan, and consolidate the small instant-text and blank-screen tools into one secondary tab without changing their behavior.

## User Experience

### Praise plan

Each existing non-selectable song header remains in the praise cue list. Its text, such as `곡 제목 · Verse 1 → Chorus`, uses the active theme's accent color and a bold font. Cue rows keep their existing normal, Preview, Live, and Live + Preview presentation.

### Bible plan

Each existing non-selectable passage-range header remains in the Bible cue list. Its text, such as `창세기 1:1 – 1:5`, uses the same theme accent color and bold font. Verse rows and their selection behavior remain unchanged.

### Misc tab

The separate `즉석` and `빈 화면` tabs are removed. A new `기타` tab is placed last, after `음악`, so the final tab order is:

`찬양 · 성경 · PDF · 영상 · 음악 · 기타`

The `기타` tab contains two equal-width regions:

- Left: `즉석 문구`, containing the existing instant-text panel.
- Right: `빈 화면`, containing the existing blank-screen panel.

Both regions retain all current controls and behavior. Existing panel objects remain available to the controller so signal wiring, state updates, style editing, Preview, TAKE, Send to Both, and TAKE BOTH behavior do not change.

## Architecture

The praise and Bible panels continue to create ordinary `QListWidgetItem` header rows. When a header is created, the panel applies a theme-provided header color and bold font. The theme value is supplied through a small panel API so a runtime theme change refreshes existing headers without introducing a custom item delegate or embedded header widgets.

A focused composite widget owns the `기타` layout. It accepts or contains the existing `InstantPanel` and `BlackPanel`, adds descriptive section headings, and places the two regions in a horizontal layout with equal stretch factors. The controller adds only this composite widget to the tab bar while retaining direct references to `instant_panel` and `black_panel`.

## Data and Signal Flow

No domain data or persisted settings format changes.

- Praise and Bible data continue to rebuild their respective cue lists as before.
- Theme application passes the current accent color to both source panels and refreshes header styling.
- Instant-text signals continue to connect through the existing `instant_panel` reference.
- Blank-screen signals continue to connect through the existing `black_panel` reference.
- The composite `기타` widget is layout-only and does not reinterpret content or relay signals.

## Error Handling

This change introduces no new file or network operations. Invalid theme color values continue to be handled by Qt's existing color behavior, consistent with other theme-derived colors in the application. Existing panel validation and status messages remain unchanged.

## Testing

Automated GUI tests will verify:

1. Praise song headers use the theme accent color, are bold, remain non-selectable, and cue-row styling is unchanged.
2. Bible range headers use the theme accent color, are bold, and remain non-selectable.
3. Changing themes updates both types of existing headers.
4. The tab labels and order are exactly `찬양`, `성경`, `PDF`, `영상`, `음악`, `기타`.
5. The `기타` tab contains the existing instant-text panel on the left and blank-screen panel on the right with equal layout stretch.
6. Existing signal-driven Preview and TAKE behavior remains covered by the current controller and panel test suite.

Implementation will follow test-driven development: add a focused failing GUI test for each behavior, verify the expected failure, make the smallest production change, and rerun both focused and full relevant test suites.

## Non-goals

- Redesigning praise or Bible cue rows.
- Changing theme definitions or adding a new user-configurable color.
- Changing instant-text or blank-screen functionality.
- Adding new persistence fields or migrating existing settings.
- Making the 1:1 split user-adjustable.
