---
title: Update YouTube playback dependencies with the running virtual environment
date: 2026-08-03
category: tooling-decisions
module: feature_update_service
problem_type: tooling_decision
component: tooling
severity: medium
status: superseded
applies_when:
  - An installed desktop application updates YouTube playback dependencies from its UI
  - The application runs from a project-local virtual environment on Windows or macOS
  - Updated Python modules are already imported by the running application
tags:
  - youtube-playback
  - yt-dlp
  - yt-dlp-ejs
  - python-mpv
  - virtual-environment
  - cross-platform
  - dependency-update
  - application-restart
---

# Update YouTube playback dependencies with the running virtual environment

> Superseded on 2026-08-09. This document records the former libmpv-based audio path and
> must not be used as current setup guidance. YouTube music now uses the same audio-only
> Qt Multimedia progressive-stream path as YouTube video. The updater installs only
> `yt-dlp[default]`; `python-mpv`, native libmpv, and `mpv-2.dll` are no longer required.
> See [Media playback](../../media-playback.md) and the
> [Windows checklist](../../windows-media-test.md) for current instructions.

## Context

Per the operator report, YouTube music worked on Windows one week and failed the next. In the
diagnostic run recorded for this change, macOS extraction reported JavaScript-challenge warnings
even though some formats still resolved. That pattern can occur when the remote extractor contract
changes independently of the application release.

The H.264 `Late SEI` warning belonged to a different path: YouTube video uses Qt Multimedia,
whereas YouTube audio uses yt-dlp and the libmpv adapter
([`docs/media-playback.md:139`](../../media-playback.md#qt-multimedia-제한과-확장)). Updating
system FFmpeg therefore does not update the Qt media backend, and updating `python-mpv` alone does
not update the extractor, its EJS companion, or the separate Windows `mpv-2.dll` runtime.

Session history confirmed the operational requirement that the updater live in the Video tab and
manage the Python-side YouTube dependency set together. It did not establish that a system-Python
installer had previously been attempted, so this document treats that as a prevented failure mode,
not a historical event.

## Guidance

Run package updates with the interpreter already running the application. Never invoke a bare
`python`, `python3`, or `pip`, and do not construct a shell command. The updater verifies that
`sys.prefix` names the project `.venv`, returns `sys.executable`, and rejects global or differently
named environments ([`feature_update_service.py:30`](../../../src/church_presenter/services/feature_update_service.py)).

Pass the interpreter and arguments separately to `QProcess`:

```python
UPDATE_REQUIREMENTS = ("yt-dlp[default]", "python-mpv<2")

program = str(current_venv_python())
arguments = (
    "-m",
    "pip",
    "install",
    "--disable-pip-version-check",
    "--no-input",
    "--upgrade",
    *UPDATE_REQUIREMENTS,
)
```

The production service supplies these as the QProcess program and argument list, avoiding shell
lookup and quoting differences between macOS and Windows
([`feature_update_service.py:50`](../../../src/church_presenter/services/feature_update_service.py)).

Treat `yt-dlp[default]` and the supported `python-mpv` major as one Python compatibility unit. The
default yt-dlp extra installs a compatible `yt-dlp-ejs`, while `python-mpv<2` preserves the
application's declared compatibility range. The project declaration uses the same default extra and
`<2` major ceiling while also declaring minimum supported versions
([`pyproject.toml:18`](../../../pyproject.toml)).

Deno and native libmpv remain explicit external runtimes. The updater reports whether Deno is on
`PATH` but does not install it, and it does not replace `mpv-2.dll`
([`feature_update_service.py:137`](../../../src/church_presenter/services/feature_update_service.py)).
After a successful update, require an application restart because imported modules and loaded
native libraries are not replaced in the running process. The Video-tab confirmation and result
dialogs make this boundary visible
([`video_panel.py:289`](../../../src/church_presenter/ui/panels/video_panel.py)).

## Why This Matters

`sys.executable -m pip` guarantees that a successful update lands in the same environment from
which Church Presenter imported its media services. A system-level command could succeed while
changing a different interpreter. Supplying an argument list also gives both operating systems the
same execution structure without depending on a shell.

Updating the group together avoids a partial repair: yt-dlp performs extraction, yt-dlp-ejs
supports the JavaScript challenge path, and python-mpv binds Python to the separately installed
libmpv runtime. A successful pip exit still cannot prove that Deno exists or that Windows can load
the correct-bitness `mpv-2.dll`, so those limitations must remain visible to the operator.

## When to Apply

- A desktop UI offers self-service updates for Python packages supporting an externally changing
  integration.
- Multiple packages must move together while a native runtime remains outside Python packaging.
- The same project-local `.venv` layout is required on macOS and Windows.
- Imported modules or loaded native libraries make restart semantics necessary.

Command construction is cross-platform, but it is not a substitute for real-device validation. The
unit test uses a Windows-style Python executable under the `.venv` Scripts directory and asserts
the exact program and arguments
([`test_feature_update_service.py:15`](../../../tests/unit/test_feature_update_service.py));
Windows playback, DLL discovery, EJS execution, and post-update restart still require the hardware
checklist.

## Examples

Avoid partial or ambiguous commands:

```text
pip install --upgrade yt-dlp       # may target another interpreter and omits the EJS extra
pip install --upgrade python-mpv   # does not update yt-dlp/EJS or native mpv-2.dll
ffmpeg update                      # does not address YouTube extraction or Qt's bundled backend
```

Verification for the implementation included clean Ruff and mypy runs, the full non-media
regression suite, targeted updater and Video-panel tests after the final environment guard, and a
pip dry-run that selected `yt-dlp-ejs` through `yt-dlp[default]`. These checks validate dependency
resolution and regression safety; they do not claim Windows hardware verification.

## Related

- [Media playback](../../media-playback.md)
- [Windows media test checklist](../../windows-media-test.md)
- [Narrow widened media-source unions at consumer boundaries](../architecture-patterns/narrow-widened-media-source-unions-at-consumer-boundaries.md)
