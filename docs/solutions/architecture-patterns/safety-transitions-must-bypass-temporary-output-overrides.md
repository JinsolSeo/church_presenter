---
title: Safety transitions must bypass temporary output overrides
date: 2026-08-03
category: architecture-patterns
module: Controller output publication
problem_type: architecture_pattern
component: frontend
severity: high
applies_when:
  - A temporary visual override masks authoritative Live content
  - Shutdown or disconnect must publish a safety frame before closing outputs
tags: [output-override, safety-black, lifecycle, broadcast]
---

# Safety transitions must bypass temporary output overrides

## Context

The Broadcast chroma feature correctly kept authoritative Live state separate from the
effective content shown on output. That same resolver was initially reused during shutdown,
so an enabled chroma override converted the intended safety BLACK publication back to green
immediately before the output windows closed.

## Guidance

Use an effective-content resolver for ordinary display refreshes, TAKE operations, and output
startup, but define terminal safety transitions as higher priority than temporary overrides.
Before the existing shutdown sequence runs, disable the override without emitting normal UI
side effects:

```python
chroma_signals_blocked = self.sync_chroma_check.blockSignals(True)
self.sync_chroma_check.setChecked(False)
self.sync_chroma_check.blockSignals(chroma_signals_blocked)
self.state.black_all()
self._refresh_all()
self._push_live(ChannelRole.BROADCAST)
self._push_live(ChannelRole.VENUE)
```

## Why This Matters

Keeping state and presentation separate is not sufficient by itself. An override resolver is
also a priority policy. If every publication path uses it blindly, a low-priority operator
effect can defeat a higher-priority lifecycle invariant such as BLACK-before-close.

## When to Apply

- A visual mask, privacy screen, chroma frame, freeze frame, or maintenance overlay is applied
  at the output boundary.
- Shutdown, device disconnect, emergency blanking, or another terminal transition has a
  mandatory output state.

## Examples

Add a regression test that observes the target content immediately before `safe_close()`, not
only after closing. Output windows may paint BLACK inside `safe_close()`, which can hide an
incorrect pre-close publication and leave the required event-flush ordering untested.

## Related

- `docs/superpowers/specs/2026-08-03-broadcast-chroma-override-design.md`
