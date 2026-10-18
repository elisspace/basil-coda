---
name: household-dj
description: Use when a verified household member invokes shared DJ controls.
---
# Optional household DJ control

This example is NOT installed automatically. It ships with no group or partner
identities. An operator must set BASIL_SIGNAL_GROUP to the explicitly authorized
Signal group and supply the matching protected together-signal/settings.json
identity binding. Missing/mismatched settings deny access. Configure your own
BASIL_STATE_DIR (private state) and BASIL_ENGINE_DIR (installed/source engine code)
separately; helpers are never executed from the state directory. Independently
review native profile/slash routing; do not
reuse another household's settings or credentials. The adapter is a fixed control
surface, not an OS sandbox or generic multi-user security system.

Use only the scoped household_dj tool: no terminal, private-profile reads, raw
HTTP, identity claims from message text, or workaround. Ordinary ambient chat
does not authorize music changes.

Start enables the existing experimental DJ manager without replacing the queue
or starting/resuming audio. Queue editing is not exposed by this household tool.
No alternate helpers, raw state edits, new workers or account changes are allowed.

- Empty /dj or status: action=status; read song/artist, live playing/paused state,
  management intent/readiness and upcoming tracks. Never resume while checking.
- Explicit skip, pause, resume: use the corresponding fixed transport action.
- Stop music: stop. Stop management but retain music: stop_management.
- Feedback: save an explicit musical preference using feedback; it changes future
  choices, not the existing queue.
- Start/switch direction: action=start with the explicit musical brief; preserves
  queued tracks and playback, verifies management. Empty queues require private
  DJ setup; do not seed, clear or start playback from the household tool.

Preserve all discovery/listening history. No likes, saved-playlist edits,
credentials, new speakers or account/library/configuration authority is granted.
After any denied or uncertain change, inspect status rather than retrying blindly.
Give concise verified receipts; native tool success is not proof of audible output.
