# Church Presenter Architecture

## Scope

Phase 2 is a native PySide6 desktop application for one operator, one broadcast
key/PDF/video output, one venue PDF/video output, and one application-wide
background-music player. Web streaming, camera capture, OBS, ATEM control,
device-specific audio routing, and service-order features remain outside scope.

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
media -> domain contract / Qt Multimedia adapter
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

Decoded video frames are distributed as `QImage` values to the same
`OutputSurface` instances. Controller Live, physical output, and Simulation do
not create additional decoders. Each channel has one prepared Preview decoder
and one Live decoder; TAKE swaps those prepared/live roles so the first frame is
already available and the prior Live can continue while a new Preview is cued.

`OutputSurface` performs a linear two-stage opacity fade for transitions among
BLACK, PDF, and VIDEO. Content readiness is validated before state commit. The
fade only paints existing frames and images; it does not use blur or allocate a
second video decoder.

## Media playback

`MediaPlaybackBackend` is the replaceable command/signal contract.
`QtMediaBackend` contains every `QMediaPlayer`, `QAudioOutput`, and `QVideoSink`
dependency. `MockMediaBackend` gives tests deterministic frames and playback
events without codecs or audio devices. A future libmpv implementation can
replace this adapter without changing `ApplicationState` or output widgets.
`AudioDeviceService` enumerates Qt audio outputs, persists an encoded device ID,
and resolves it for every video and background-music backend. An empty ID keeps
all audio on the operating system's current default output.

`VideoPlaybackManager` owns independent Broadcast/Venue prepared and Live
players plus runtime state. Immutable `Content.video(path)` descriptors are
copied by TAKE; rapidly changing position remains in runtime state. Preview
decode is muted and stops on its first real frame. Stop, Ended, or fatal Live
errors emit a channel event that Controller converts to BLACK.

`AudioPlaybackController` owns the global player and `AudioPlaylist`. Playlist
order, repeat behavior, three-second Previous policy, deleted-file status, and
video pause reason are domain/media state rather than widget state. Playlists
use atomic JSON writes and may store paths relative to the playlist directory.

## PDF pipeline

PDF discovery is separate from UI models. PyMuPDF renders pages in QRunnable
workers. Jobs are keyed by canonical path, modification time, page index, and
pixel size. A bounded LRU image cache avoids repeated work and naturally
invalidates when a file's modification time changes. Thumbnail requests are
issued lazily for visible/listed pages and may be cancelled by generation token.
Errors become user-visible item/channel errors and never terminate the app.
Thumbnail items use a static left-to-right grid and source-page ascending order.
Drag/drop and previously persisted custom permutations are intentionally ignored
so operator navigation and visual order cannot diverge.
The PDF library itself uses one fixed filename-descending order; removing runtime
sort controls keeps the operator's file positions stable between selections.
Two independent Preview target checkboxes replace the single-target combo. One
checked target prepares that channel, while two checked targets reuse the existing
atomic two-channel preparation path. The selected page and Live summary remain in
domain state rather than occupying a persistent text row below the thumbnails.

## Screens and simulation

`ScreenService` abstracts Qt screen enumeration and signals. `MockScreenService`
accepts injected virtual screens for CI and tests. Physical output is opened only
after the operator presses Start Outputs. Broadcast and venue cannot share a
physical screen. Simulation may use duplicate/injected screens and presents
resizable 16:9 windows backed by the same `OutputSurface`.

## Controller theme system

`ThemeManager` discovers JSON themes from the packaged `ui/themes` directory,
validates their common color, metric, spacing, and typography token schema, and
renders one shared `app.qss` template. Theme JSON is the visual-token source of
truth; Python widgets use semantic properties such as `primary`, `take`, and
`danger` instead of storing theme colors. A missing token, invalid value,
duplicate ID, malformed JSON, or unresolved QSS placeholder prevents that theme
from being applied. A missing or invalid saved selection falls back to Light
Professional without terminating the application.

Settings are loaded before the initial theme is applied. The selected theme ID is
persisted in `AppSettings.current_theme`, while the active `QPalette` is derived
from the same tokens to keep native Qt controls consistent with QSS. Theme changes
affect Controller chrome only: `ApplicationState`, Preview/Live content, and the
shared `OutputSurface` rendering contract remain unchanged. The Controller layout
uses 1920×1080 as its design baseline and layout/size policies rather than fixed
coordinates so it can scale down to its supported 800×600 minimum and across DPI
profiles.

The main workspace is a vertical `QSplitter`. Its upper child owns the four
Preview/Live monitors and linked TAKE controls; its lower child is a scroll area
containing the content tabs. The default 60:40 allocation protects monitoring
space, while operators can drag the divider and the serialized splitter state is
stored in `AppSettings.workspace_splitter_state`. `ResponsiveContentTabs` removes
the aggregate minimum height inherited from inactive tabs, so the lower workspace
fits its allocation without an outer scrollbar. Lists that contain actual data
retain their own local scrolling.

Controller density is derived automatically from the current window dimensions,
not from a user preference: widths below 1440 or heights at or below 900 use the
compact theme metrics. Compact mode also reduces PDF thumbnail geometry and video
panel chrome. Window resizing never hides or floats the worship-order dock; its
visibility and dock/floating state remain under explicit operator control.

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

libmpv, individual audio routing, transition variants, and ATEM commands remain
adapter extension points. Two different videos can play simultaneously; this
uses two decoders. Cueing replacement videos can temporarily use up to four
channel decoders total. Controller/Simulation/physical mirrors reuse decoded
frames and do not multiply that count.
