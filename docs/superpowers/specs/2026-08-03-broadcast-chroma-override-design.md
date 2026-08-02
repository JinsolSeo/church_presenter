# Broadcast Chroma Override Design

## Goal

Add a compact control that temporarily replaces the Broadcast visual output with fixed chroma green while operators continue preparing and taking any supported content underneath it. Turning the control off reveals the latest Broadcast Live content.

## User Experience

The `연동 제어` bar gains one check box named `크로마키`, placed with the existing `동시 진행` and `바로 Live` controls.

When `크로마키` is checked:

- The external Broadcast output displays solid green `#00FF00`.
- The Controller's `송출 LIVE` monitor displays the same solid green.
- Broadcast Preview, Venue Preview, and Venue Live remain unchanged.
- The operator may continue to prepare and TAKE praise, Bible, PDF, video, or other supported content.
- Every TAKE updates the underlying Broadcast Live state, but the effective Broadcast display remains green.

When `크로마키` is unchecked, the external Broadcast output and Controller `송출 LIVE` monitor immediately display the current underlying Broadcast Live content. If no TAKE occurred while green was active, this is the content that was visible immediately before activation. If one or more TAKE operations occurred, this is the most recently taken content.

The control is independent of `동시 진행` and `바로 Live`. Toggling it does not enable, disable, or otherwise alter those controls.

## State Model

The chroma check box represents a temporary visual output override, not a new `ApplicationState` content transition.

The Controller owns an in-memory Boolean indicating whether the Broadcast chroma override is active. A single effective-content helper resolves what visual content should be pushed or shown:

- Broadcast + override enabled → `Content.solid_color("#00FF00")`
- Every other case → the channel's underlying `live_content`

The underlying Broadcast `live_content` continues to change through the existing TAKE flow. No previous-content snapshot is needed because the state itself remains the restoration target.

The override is intentionally not persisted. Every application start begins with the check box cleared and follows the existing safe startup output behavior.

## Output and Monitor Flow

All paths that visually publish or refresh Broadcast Live use the effective-content helper. This includes:

- Toggling the new check box.
- Ordinary Broadcast TAKE.
- TAKE BOTH.
- Starting or reconnecting the Broadcast output while the override is active.
- Refreshing the Controller `송출 LIVE` monitor.

Venue output and both Preview paths continue to use their existing state content directly.

The override changes only the rendered visual content. Existing media preparation, video transport, audio routing, subtitle live markers, PDF live markers, validation, and state transitions continue unchanged. A playing video can therefore continue behind the green output and will be visible at its current playback state when the override is removed.

## UI Feedback

The check box label is `크로마키`. Its tooltip explains that it forces only the Broadcast visual output and `송출 LIVE` monitor to chroma green, and that clearing it reveals the latest taken content.

The status bar reports activation and deactivation in concise Korean text. Activation reports that Broadcast is temporarily green. Deactivation reports that the latest Broadcast Live content has been restored.

## Error and Lifecycle Handling

If no external Broadcast window is running, the Controller monitor still changes to green. Starting the output later must publish green immediately while the check remains active.

Closing or restarting the application does not preserve the override. The existing shutdown and startup BLACK safety behavior remains authoritative.

Because the override uses immutable `Content` values and does not mutate Preview or Live state, no rollback path is required. A failed underlying TAKE continues to preserve the previous Live state under the green override according to existing behavior.

## Testing

Automated GUI tests will verify:

1. `연동 제어` contains an unchecked `크로마키` check box with a stable object name and concise tooltip.
2. Checking it leaves Broadcast Live state unchanged while the external Broadcast target and Controller `송출 LIVE` show `#00FF00`.
3. Broadcast Preview, Venue Preview, and Venue Live remain unchanged.
4. A Broadcast TAKE while the override is active updates underlying Live but keeps both effective Broadcast displays green.
5. Clearing the check reveals the most recently taken Broadcast Live content.
6. TAKE BOTH follows the same rule: underlying Broadcast and Venue Live update, only Broadcast remains visually overridden.
7. Starting or refreshing an output while checked applies the override.
8. Existing linked-navigation, media, TAKE, and shutdown tests continue to pass.

Implementation will follow test-driven development: each new behavior is first captured by a failing GUI test, the expected failure is observed, and the smallest production change is made before focused and full regression verification.

## Non-goals

- Choosing or persisting a chroma color.
- Applying the override to Venue output or any Preview.
- Pausing, muting, restarting, or otherwise controlling media behind the override.
- Reusing the currently selected preset from the `빈 화면` tool.
- Persisting the check box state across application launches.
- Replacing the existing `빈 화면` controls.
