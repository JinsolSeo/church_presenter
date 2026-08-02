---
title: Narrow widened media-source unions at consumer boundaries
date: 2026-08-02
category: architecture-patterns
module: media_playback
problem_type: architecture_pattern
component: backend
severity: medium
applies_when:
  - A shared backend interface supports multiple source representations
  - A router or facade intentionally exposes a narrower consumer-specific type
  - A downstream consumer may only receive one member of a shared union
related_components: [integration, testing_framework]
tags: [python-typing, union-types, adapter-boundary, media-playback, mypy]
---

# Narrow widened media-source unions at consumer boundaries

## Context

The shared media backend accepts both local files and original network URLs through
`MediaSource = Path | str` and reports the same stable source identity from its `path`
property (`src/church_presenter/media/base.py:9`, `src/church_presenter/media/base.py:26`,
`src/church_presenter/media/base.py:72`). That broad contract is required by video:
`VideoPlaybackManager` cues both variants and normalizes them differently
(`src/church_presenter/media/video_manager.py:67`,
`src/church_presenter/media/video_manager.py:474`).

The widening does not mean every consumer should widen. `AudioBackendRouter.path`
represents only an active local-audio file and deliberately promises `Path | None`.
Returning its backend's widened property directly would produce a `Path | str | None`
versus `Path | None` mypy incompatibility. Treating every string as a path
would also erase the distinction between a remote URL and a filesystem location.

## Guidance

Keep the union at the lowest shared abstraction that genuinely supports every source
kind. At each source-specific API, preserve the narrower semantic contract and narrow
the shared value explicitly:

```python
@property
def path(self) -> Path | None:
    source = self.local_backend.path if self._active is self.local_backend else None
    return source if isinstance(source, Path) else None
```

This is the boundary implemented by `AudioBackendRouter`
(`src/church_presenter/media/audio_router.py:135`). Prefer a runtime guard, a source
discriminant, or a validated converter over `cast()`: a cast silences the checker but
does not prevent an unexpected URL string from escaping through a local-path API.

Use this recurrence guard whenever a shared protocol gains a variant:

1. Audit every adapter, facade, state object, and return property that forwards the
   widened value.
2. Retain the union in consumers that support every member.
3. Narrow at consumers whose public contract is intentionally smaller.
4. Run mypy and tests that cover both supported variants and the narrowed-away variant.

## Why This Matters

The shared interface describes everything an implementation may legally expose. A
consumer-facing adapter describes what its callers may rely on. Those contracts are
related, but they need not be identical.

Here the Qt video backend must preserve a URL string as its stable identity while it
plays a separately resolved stream (`src/church_presenter/media/qt_media_backend.py:193`,
`src/church_presenter/media/qt_media_backend.py:214`). Video therefore retains the full
union. The audio router should not force all local-path callers to handle URLs that its
`path` property never intends to expose. Local narrowing keeps both APIs honest and
prevents a capability added for one source type from weakening unrelated callers.

## When to Apply

- A protocol or base class gains a union because one implementation accepts a new
  source representation.
- An adapter, router, facade, or compatibility layer retains a narrower domain meaning.
- Static checking reports that a broad upstream return type cannot satisfy a narrow
  downstream contract.
- A migration introduces remote and local variants without requiring every established
  caller to understand both.

Do not narrow when the downstream component truly supports all variants.
`VideoPlaybackManager`, for example, should keep `MediaSource` because its cue and
activation APIs operate on both paths and URLs
(`src/church_presenter/media/video_manager.py:67`,
`src/church_presenter/media/video_manager.py:89`).

## Examples

Returning the widened backend value directly leaks the union:

```python
# Incorrect: local_backend.path is Path | str | None.
@property
def path(self) -> Path | None:
    return self.local_backend.path if self._active is self.local_backend else None
```

Widening the adapter merely to make the error disappear loses useful semantics:

```python
# Compiles, but every caller now handles URLs even though this API is local-only.
@property
def path(self) -> MediaSource | None:
    return self.local_backend.path if self._active is self.local_backend else None
```

Keep the explicit `isinstance(source, Path)` boundary and pair it with behavior checks:

```python
router.prepare(local_item)
assert router.path == local_item.path

router.prepare(youtube_item)
assert router.path is None
```

The behavior test protects the runtime meaning; mypy protects the public type from a
future union leak.

## Related

- [Architecture overview](../../architecture.md)
- [Media playback policy](../../media-playback.md)
