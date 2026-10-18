# Queue authority and retained guard research

This document records queue-guard research and future acceptance requirements,
not a blanket prohibition enforced by the release. Existing DJ/refill and queue
controls remain available experimentally. Local-only guard protections below do
not establish durable server ownership or a new automatic server repair. See
[queue-release.md](queue-release.md) for current behavior.

Further read-only server-route investigation and source-backed race tests:
[Server queue authority and takeover contract](server-queue-authority.md).
The live LM navigation target differs from the QP add hint; server removal uses
LM and opaque edit params, so ephemeral-only safety remains unestablished.

## Findings from read-only inspection

Current YTM's `music_polymer_inlined_html.js` reducer has separate `items` and
`automixItems`. `ADD_AUTOMIX_ITEMS` populates preview, not playable queue.
`SHIFT_AUTOPLAY_ITEMS` promotes preview into the playable queue. No reservation,
library flag, title familiarity or absent library flag proves this provenance.

The live queue service (`#queue.queue`) reports `serverQueuesEnabled=true`.
`P_.prototype.shuffle` toggles shuffle, calls its serverQueueApi.shuffle(), then
replaces local items using `RESET_SHUFFLE_ITEMS` with the server response and
current item. This happens when toggling **off** as well as on. The reducer
preserves the current item if present, and recalculates its selected index.

Pear's installed enqueue handler gets `/music/get_queue` then inserts every
`queueDatas.content` into local Redux. The existing exact append helper filters
that response to one requested item. Pear's remove handler and exact append
both dispatch local Redux actions; neither updates the server-backed queue.
Consequently a later server shuffle response can restore local deletions and
lose local additions. That is distinct from automix or new recommendations.
No `originalOrder` cache was established by inspection; do not invent a cache
patch, clear historical rows, or claim autoplay=false means exclusive ownership.

`GET /api/v1/shuffle` reports `{state: boolean|null}`. The documented POST is
"Shuffle the queue", not an idempotent set-false operation. Do not issue it as an
assumed harmless shuffle-off setter. `GET repeat-mode` reports NONE/ALL/ONE.
`player_dom.mjs status` now reports renderer shuffle/repeat, server queue authority
and selectedItemIndex in addition to existing media fields, without writes.

## Local guard design and protections (not server-repair acceptance)

* Exact append refuses shuffle true/unknown before fetch and immediately before
  ADD_ITEMS, including a shuffle change during a delayed fetch. It never toggles
  shuffle, changes transport, or promises server queue synchronization.
* `queue_guard.mjs` installs an **observation-only** Redux dispatch wrapper after
  bounded admission and exact snapshot verification. It records at most eight
  bounded queue-change observations (max 512 unique rows).
* Deletion proof requires an observed tail `SHIFT_AUTOPLAY_ITEMS` whose exact
  object identities were in the pre-action automix preview. Preview-only rows,
  direct ADD_ITEMS, manual additions, preexisting unknown/history/library rows,
  reservations and server shuffle replacements are never deletion proof.
* Cleanup only removes proven **upcoming** rows, at most 100, descending indices.
  It verifies exact retained order, current selection and unchanged media time,
  paused state and volume after each synchronous removal. Selected/history rows
  stay. Clones/replacements/generation changes discard evidence conservatively.
* Destructive cleanup additionally requires `serverQueuesEnabled === false`,
  shuffle false and repeat NONE. True/unknown server authority is observation
  only. **The live installation currently fails this safety gate. Do not enable
  server-backed destructive cleanup or force its flag false.**
* `queue_guard.py` serializes checks with control.lock, requires ON and an
  explicitly armed matching generation, respects pause, persists the existing
  eight-second renderer lease before submission, and verifies REST readback.
  OFF uses the existing lock/lease draining path. Detached observers cannot
  mutate queue, even after OFF or a client timeout.
* Unknown deviations from a reviewed baseline are flagged, not auto-deleted or
  auto-adopted. Opted-in worker checks run in the existing 300-second loop;
  queue_guard_warning blocks refill/model work while review is needed. No second
  worker, search, model call or automatic player start is introduced.

## Guard scope

Guard arm/check is an existing helper surface, not installation-time activation
or proof of safe server-backed cleanup. Its local-only authority, generation and
readback guards still apply. OFF and disarm do not change playback or the queue.
Do not coerce `serverQueuesEnabled`, reload, navigate, toggle shuffle, clear or
edit saved playlists as an automatic fallback. Experimental queue controls are
not an implementation of the future server adapter described here.

## Verification

RED evidence: shuffle race/unknown tests initially failed with missing expected
rejection; server-authority cleanup regression initially removed a row unsafely;
Python OFF/generation/readback/worker guards failed against the no-op baseline.
GREEN: engine 45 Python tests; renderer/append 33 Node tests; web 40 Python tests;
household four Python tests; frontend/history Node tests and web syntax check.
All engine fixtures use isolated state, mocking renderer/session APIs; additional
threaded test proves OFF's control lock serializes against in-flight maintenance.
Existing real detached-renderer append/OFF expiry tests also pass.

The original guard investigation made no live writes. Release verification is
isolated; current release scope and test limitations are in queue-release.md.

## Still unresolved

A safe server-backed repair needs explicit supported ephemeral queue editing
that updates **both** server authority and local Redux, followed by delayed
shuffle-off/natural-transition verification. Direct local deletion is insufficient.
The current internal serverQueueApi exposes removal/reordering paths, but binding
those to only the ephemeral backing queue (never saved library playlists),
handling response commands and preventing stale concurrent mutations requires
further inspection and separately approved integration tests. This candidate
therefore refuses that repair rather than hiding uncertainty behind auto-cleanup.
