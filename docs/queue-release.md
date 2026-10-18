# Experimental DJ and queue behavior

## Available controls

The shareable source enables the existing DJ ON/OFF, automatic refill, exact
track/album append and foreground queue controls. No extra enable flag is needed.
These require a separately configured, signed-in dedicated Pear player and a
configured Hermes DJ profile. Installation and serving the page do not start
management, music, a model or a player.

- DJ ON uses the existing singleton worker and saved or explicit musical brief.
  OFF revokes management and drains the existing bounded renderer lease without
  pausing audio. Combined Stop also pauses through the separate transport helper.
- Foreground reorder/remove preserves stale-ID/index checks, upcoming-only scope,
  mutation serialization and bounded exact-order readback. No automatic retries
  follow an ambiguous write. The UI retains these controls, plus discovery filters,
  play/pause/next and volume.
- Background checks run every 300 seconds. In track mode, below five upcoming
  tracks the worker makes one bounded refill toward eight; album mode admits one
  complete official album. OFF, pause, generation, screening, reservation, expiry
  and readback checks remain in the existing helpers. No second worker is added.
- Likes, library, saved-playlist editing and server takeover are not supported.
  Endpoint validation, loopback restrictions and helper whitelists remain in force.

## Limits, not a server-queue fix

Local Redux edits can diverge from YouTube's server-owned queue. A later response
can restore removed rows or discard additions. Autoplay=false and immediate
readback are not durable ownership. Existing append/order checks do not implement
server/local synchronization, quiet reload, recommendation prevention or automatic
recovery. Do not force authority flags, edit saved playlists, erase reservations,
clear/reload a queue or retry uncertain writes merely to demonstrate success.

[Server queue authority](server-queue-authority.md) and
[queue guard](queue-guard.md) preserve investigation/design material. Their future
acceptance requirements are not blanket restrictions enforced by this build and
are not claims that a reviewed durable server-backed adapter now exists.

## Capability contract

`python3 engine/djctl.py capabilities` reads the dedicated renderer projection.
Snapshots use `djctl.queue_capabilities(live)` without a redundant renderer read.
Version 1 reports `release_mode="experimental"`; `ready`, `exact_append`, `refill`,
`queue_edit`, `queue_mutation_ready`, `automatic_refill_ready` and `transport` are
true; `server_takeover` is false. `server_queues_enabled` is boolean or null.
The reason describes the persistence limitation. These booleans describe available
code paths, not player availability, sign-in, worker health or real queue acceptance.
Unknown authority is not converted into a verified local-only queue.

The web server checks corresponding capabilities before DJ ON/edit; the UI disables
only disconnected, unavailable or invalid/boundary actions, not experimental
features globally. OFF remains available for saved ON intent. Session status
reports management intent/readiness; a saved ON flag does not prove a running worker.
Doctor reports experimental feature availability separately from
`automatic_dj_ready=false`, `login="unverified"` and live acceptance not performed.

## Portable isolation and verification

Set fresh `HOME`, `BASIL_STATE_DIR` and `TMPDIR` before imports and remove inherited
`BASIL_*`, `HERMES_*` and `PYTHONPATH` for independent-user tests. Helpers execute
from installed/source `engine/`, never mutable state. Keep credentials, private
sessions, histories, browser data and test logs out of source distributions.
Resolved executable/profile/unit and loopback endpoint configuration is propagated
to the singleton worker; setup never activates it.

Mock API/renderer, frontend and household fixtures exercise wiring, bounded
mutations and readback only. They do not establish real login, audible playback,
paid model access, Signal delivery, durable queue persistence or clean-machine
player integration. Record current suite results outside product sources; old
investigation test counts are historical, not current release acceptance.
