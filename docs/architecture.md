# Church Presenter Architecture

## Scope

Phase 1 is a native PySide6 desktop application for one operator, one broadcast
key/PDF output, and one venue PDF output. Video, audio, web streaming, camera
capture, OBS, ATEM control, and service-order features are deliberately outside
this phase.

## Reference analysis

`JinsolSeo/subscripter` was reviewed as a behavioural reference only. Useful
ideas are UTF-8-SIG text loading, ignoring blank input lines, grouping adjacent
source lines, keyboard navigation, and displaying Qt screen geometry. Church
Presenter does not reuse its subprocess launcher, AppKit/tkinter platform split,
transparent desktop overlay, pixel-only placement, or output-owned subtitle
index. Those choices make Preview/Live coordination and cross-platform output
behaviour difficult to reason about.

## Layers and dependency direction

```text
ui -> application commands/state -> domain
ui -> rendering -> domain
ui -> services -> domain
services -> filesystem / Qt screen API / PyMuPDF
```

The domain package contains no Qt widgets. `ApplicationState` is the single
source of truth for each channel's preview and live content. Content is an
immutable value object, so TAKE copies a value rather than a widget or renderer
reference. UI widgets observe explicit state updates; they are not state stores.

## State and TAKE transactions

Broadcast and venue have separate `ChannelState` instances. Selecting a subtitle
card or PDF page changes only `preview_content`. `take(channel)` first validates
that preview and commits it to `live_content` only when ready. `take_both()`
validates both channels before changing either, preserving both old live values
on any failure. Venue validation rejects subtitle content.

BLACK is the initial and shutdown-safe content. Screen removal also moves the
affected live channel to BLACK while leaving the application running.

## Rendering

`OutputSurface` is the only content display widget. Controller mirrors,
simulation windows, and full-screen output windows all embed this widget.
`SubtitleRenderer` paints normalized style coordinates, outline, shadow,
background, padding, alignment, and line spacing with QPainter. PDF pages use a
shared contain calculation and black letterboxing. No simulation-only image or
renderer exists.

## PDF pipeline

PDF discovery is separate from UI models. PyMuPDF renders pages in QRunnable
workers. Jobs are keyed by canonical path, modification time, page index, and
pixel size. A bounded LRU image cache avoids repeated work and naturally
invalidates when a file's modification time changes. Thumbnail requests are
issued lazily for visible/listed pages and may be cancelled by generation token.
Errors become user-visible item/channel errors and never terminate the app.

## Screens and simulation

`ScreenService` abstracts Qt screen enumeration and signals. `MockScreenService`
accepts injected virtual screens for CI and tests. Physical output is opened only
after the operator presses Start Outputs. Broadcast and venue cannot share a
physical screen. Simulation may use duplicate/injected screens and presents
resizable 16:9 windows backed by the same `OutputSurface`.

## Persistence and recovery

`SettingsService` stores versioned JSON in the platformdirs user config folder.
It writes a temporary file, fsyncs it, and atomically replaces the target. Invalid
JSON is renamed with a `.corrupt-<timestamp>` suffix and defaults are returned
with a non-fatal warning. Subtitle presets use the same policy in a separate JSON
file. User-edited subtitles remain in memory until Save and are always written
as UTF-8 without a BOM; blank source lines are intentionally omitted on load and
save.

## Shutdown

The Controller first asks about unsaved subtitle edits. It then sets both live
channels to BLACK, processes pending paint events, closes physical/simulation
outputs, persists settings, and accepts shutdown. Exceptions are logged to a
rotating file while the best-effort BLACK/close sequence continues.

## Extension points

`ContentType.VIDEO`, future folder settings, and channel readiness are defined
without a Phase 2 playback implementation. Media backends and ATEM commands will
remain adapters around state changes rather than entering rendering or domain
models.

