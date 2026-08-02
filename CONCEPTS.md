# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Media presentation

### Media Source

The stable operator-selected identity of playable media, either a local file or an original remote URL; temporary stream URLs resolved for playback do not replace this identity.

### YouTube Feature Refresh

The operator-triggered maintenance process that updates Python-side YouTube playback dependencies inside the project's application environment while leaving native runtimes external and asking the operator to restart before relying on the updated versions.

### Preview Cue

For video, a prepared Preview state with a decoded first frame that can be inspected without changing Live or starting operator-audible playback.

### TAKE

The explicit operation that commits ready Preview content to Live while preserving the previous Live content if validation or preparation fails.

For video, TAKE keeps the prepared first frame paused; playback begins only through the separate Play operation.
