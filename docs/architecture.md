# Church Presenter Architecture

## Scope

Phase 2 is a native PySide6 desktop application for one operator, one broadcast
key/PDF/video output, one venue PDF/video output, and one application-wide
background-music player. Background music accepts local files and public single-video
YouTube URLs. YouTube video output, downloads, playlist import, authentication, other
web streaming, camera capture, OBS, ATEM control, and device-specific mpv routing remain
outside scope.

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
media -> domain contract / Qt Multimedia, yt-dlp, and libmpv adapters
remote server thread -> validated protocol -> Qt queued signal -> Controller widgets
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

Linked subtitle/PDF navigation can optionally queue an automatic `take_both()`.
The queue snapshots both new Preview descriptors and commits only after both channel
readiness flags become true. A render error, disabled option, disabled linked mode,
or any later Preview change cancels the queue, preserving both previous Live values.

BLACK is the initial and shutdown-safe content. Screen removal also moves the
affected live channel to BLACK while leaving the application running. Operator-selected
chroma blanks use a separate `SOLID_COLOR` snapshot, so choosing a color never weakens
the BLACK shutdown fallback or bypasses Preview/TAKE.

## Rendering

`OutputSurface` is the only content display widget. Controller mirrors,
simulation windows, and full-screen output windows all embed this widget.
`SubtitleRenderer` paints normalized style coordinates, outline, shadow,
background, padding, alignment, and line spacing with QPainter. PDF pages use a
shared contain calculation and black letterboxing. No simulation-only image or
renderer exists.

The prepared first video frame is converted once to `QImage` for thumbnails and
paused Preview. During Live playback, native `QVideoFrame` values are distributed
to the `QVideoWidget` sink embedded in each `OutputSurface`; the normal path does
not convert every frame to a CPU image or repaint it through the parent widget.
Controller Live, physical output, and Simulation do not create additional
decoders. Each channel has one prepared Preview decoder and one Live decoder;
TAKE swaps those prepared/live roles so the first frame is already available and
the prior Live can continue while a new Preview is cued.

`OutputSurface` performs a fixed 250ms linear two-stage opacity fade for transitions among
BLACK, SOLID_COLOR, PDF, and VIDEO. Content readiness is validated before state commit. The
fade only paints existing frames and images; it does not use blur or allocate a
second video decoder. When leaving native Live video, the surface freezes one
frame to an image for the short fade and then clears the native sink.

## Media playback

`MediaPlaybackBackend` is the replaceable local-media command/signal contract.
`QtMediaBackend` contains every `QMediaPlayer`, `QAudioOutput`, and `QVideoSink`
dependency. `MockMediaBackend` gives tests deterministic frames and playback
events without codecs or audio devices. A future libmpv video implementation can
replace the video adapter without changing `ApplicationState` or output widgets.
`AudioDeviceService` enumerates Qt audio outputs, persists an encoded device ID,
and resolves it for every video and background-music backend. An empty ID keeps
all audio on the operating system's current default output.

`VideoPlaybackManager` owns independent Broadcast/Venue prepared and Live
players plus runtime state. Immutable `Content.video(path)` descriptors are
copied by TAKE; rapidly changing position remains in runtime state. Preview
decode is muted and stops on its first real frame. Stop, Ended, or fatal Live
errors emit a channel event that Controller converts to BLACK.

`AudioPlaybackController` owns the global player and `AudioPlaylist`. It sends every
transport command through `AudioBackendRouter`; UI code never branches on source type.
`AudioPanel` treats the selected audio folder as the playlist source of truth. A background
scan produces sorted local items, then `PlaylistService` appends entries from the fixed
`youtube_url.json` file when it exists. URL additions, removals, and fallback changes are
atomically written to that file without a save dialog. The compact transport panel is placed
to the right of the folder playlist. It shows the current track, playback state, and transport
controls; the active track is painted with the theme accent in the left list and detailed
operational notices use the Controller status bar.
The router sends local files to the existing `QtMediaBackend` and YouTube sources to
`MpvAudioBackend`. `YtDlpResolver` validates the public single-video URL and resolves
metadata or an ephemeral best-audio URL in a bounded worker pool. `MpvAudioBackend`
initializes libmpv off the UI thread, disables video, normalizes position/duration/status
signals, forwards yt-dlp's HTTP headers and request-size hint, and detects preparation and
buffering timeouts. On Windows it registers bundled libmpv directories before importing
python-mpv. It best-effort maps Qt output IDs/descriptions to libmpv device names and falls
back to the system default when names cannot be matched. A Qt timer mirrors core libmpv
properties as a macOS-safe fallback when python-mpv's native event callbacks are not
delivered. The backend releases its player on source switch or shutdown.

```text
AudioPanel -> AudioPlaybackController -> AudioBackendRouter
                                      -> QtMediaBackend (local Path)
                                      -> MpvAudioBackend -> yt-dlp -> ephemeral URL
```

If streaming preparation or playback fails, the router prepares the configured local
fallback and emits an explicit fallback event before playback continues. If no usable
fallback exists, only that item becomes ERROR; local music and video remain available.
Playlist order, repeat behavior, three-second Previous policy, availability, fallback
status, and video pause reason are domain/media state rather than widget state.

The folder-scoped `youtube_url.json` schema stores only original URLs and optional portable
fallback paths; it never stores the expiring resolved stream URL. The former version-1/2
playlist reader remains for data compatibility but is no longer exposed by the Controller UI.

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

The video library similarly exposes no runtime sorting controls. It always sorts
by modification time descending so newly added service media appears first.

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
visibility is always restored and it has no close action. Left/right docking and
floating remain available.

## Local remote mirroring

`RemoteNetworkService` owns a daemon Python thread with an independent asyncio
event loop and an `aiohttp` HTTP/WebSocket server. It binds to `0.0.0.0` and tries
ports 8765 through 8790. LAN addresses come only from Qt's active
`QNetworkInterface` entries: non-loopback, non-link-local IPv4 addresses are
accepted and RFC1918 private addresses are preferred. No external address probe,
cloud relay, UPnP, or port forwarding is used.

The browser receives the packaged, build-free HTML/CSS/JavaScript client after a
`secrets.token_urlsafe(32)` URL token is validated. HTTP exchanges the token for
an HttpOnly, SameSite session cookie; WebSocket handshakes require that session
or the current token. Restart and stop invalidate both token and sessions. The
server exposes only the client assets, frame stream, and bounded input protocol.
Each client owns a one-frame asyncio queue, so slow clients drop stale frames and
cannot grow memory or block other clients. The browser mirrors that backpressure:
at most one JPEG decode runs while one replaceable latest frame waits. A newer
arrival replaces that waiting frame, preventing Safari's asynchronous bitmap
decodes from building an ever-older display queue. Coarse-pointer devices cap the
canvas backing store at 1024 pixels wide while retaining the original frame size
for CSS layout and coordinate inversion. This reduces mobile draw and canvas
memory cost without changing WebSocket metadata or Qt input coordinates.

`FrameCaptureService` runs exclusively on the Qt GUI thread. While clients exist,
an 8 FPS timer grabs the Controller or the currently active application dialog,
excluding the remote-connection dialog itself. Frames are capped at 1280 pixels
wide and encoded as quality-72 JPEG. Native `QVideoWidget` pixels may be absent
from `QWidget.grab()`. The remote capture therefore composites each surface's
already-prepared first-frame `QImage` into the native video rectangle and labels
it as a remote still frame. It deliberately never calls `QVideoFrame.toImage()`
during capture: Windows hardware-decoded frames can otherwise force repeated
GPU-to-CPU readback on the GUI thread. The Controller chrome remains at 8 FPS,
while video motion is omitted in favor of responsive controls. Remote clients
never allocate another decoder.

The aiohttp thread only validates JSON, rate-limits it, and emits Qt signals.
`RemoteInputDispatcher` receives those queued signals in the GUI thread, maps
normalized coordinates to the latest captured widget and its `childAt()` target,
then sends standard mouse, wheel, and key events through Qt. Consequently the
Controller's existing application event filter, focus-area shortcuts, Preview
readiness, atomic TAKE BOTH, and single `ApplicationState` remain authoritative.
The remote layer neither reads application files nor copies presentation state.

The browser owns an explicit remote-view transform independently of browser page
zoom. The canvas keeps its Controller-frame pixel dimensions and applies a
top-left-origin CSS `translate3d(...) scale(...)` transform. `zoom` is clamped
from the current fit scale through 4×; pan is clamped to the transformed frame
bounds. A pointer at viewport position `(px, py)` is mapped back with
`((px - left) / scale, (py - top) / scale)`, divided by the original frame width
and height, and clamped to `[0, 1]` before the existing WebSocket protocol sees
it. This keeps Qt targeting independent of zoom and pan.

Pointer Events maintain separate one-touch and two-touch states. One touch emits
the existing pointer protocol. A second touch cancels the pending one-touch
gesture and starts local pinch/pan without emitting its moves to the server.
Pinch midpoint anchoring keeps the content below the fingers stable, and a short
post-pinch guard suppresses synthetic click/double-click events. Resize,
orientation, frame-size, and fullscreen changes recompute fit scale while
preserving the normalized content point that occupied the previous viewport
center. Double tap toggles a 2× anchored view and fit; the header reset returns
zoom and pan to fit.

## Persistence and recovery

`SettingsService` stores versioned JSON in the platformdirs user config folder.
It writes a temporary file, fsyncs it, and atomically replaces the target. Invalid
JSON is renamed with a `.corrupt-<timestamp>` suffix and defaults are returned
with a non-fatal warning. Subtitle presets use the same policy in a separate JSON
file. User-edited subtitles remain in memory until Save and are always written
as UTF-8 without a BOM; blank source lines are intentionally omitted on load and
save. Opening or reloading a TXT file uses an explicit Yes/No/Cancel decision:
Yes saves first, No discards memory changes and continues, and Cancel aborts the
load.

## Shutdown

The Controller first asks about unsaved subtitle edits; folder playlist URL changes are already
saved immediately. It then sets both live
channels to BLACK, processes pending paint events, closes physical/simulation
outputs, stops remote capture/server with a bounded thread join, persists
settings, and accepts shutdown. Exceptions are logged to a
rotating file while the best-effort BLACK/close sequence continues.

## Extension points

Individual mpv audio routing, authenticated providers, transition variants, and ATEM
commands remain adapter extension points. Two different videos can play simultaneously; this
uses two decoders. Cueing replacement videos can temporarily use up to four
channel decoders total. Controller/Simulation/physical mirrors reuse decoded
frames and do not multiply that count.
