# Server-backed queue: source-backed blocker and takeover contract

## Release boundary

This document preserves source evidence and a future review contract, not an
activation guide or an enforced release-wide queue denial. The shareable build
retains experimental DJ/refill and foreground queue editing. Those controls do
not implement this server-backed takeover design or establish durable ownership.
Read [queue-release.md](queue-release.md) for current behavior and limitations.

## Result

No server-backed repair was enabled or implemented. Existing guard refusal is
correct for this live context. Do not call native queue.removeItem, server removal,
reorder, playlist editing, queue clearing, shuffle, or account mutations to test
this conclusion on a user's queue. No live writes were made during this investigation.

Read-only CDP inspected function source and a fixed metadata projection only; no
cookies, credentials, opaque params values, config, or account tokens were read.
The shipped public script was downloaded without authentication:
`https://music.youtube.com/s/caa327f5/music_polymer_inlined_html.js`.
Minified names below describe this version, not stable supported public APIs.

## Exact findings

* A read-only inspection established serverQueuesEnabled=true, shuffle=false,
  repeat=NONE and a retained continuation. Pending requests were false at
  inspection. This is a snapshot, not proof of no races. Per-user listening,
  media position, volume, selection and opaque queue identifiers are omitted.
* Current and following renderers use navigation watchEndpoint.playlistId=`LM`,
  with playlistSetVideoId and playlistEditParams present. Their queue-add endpoint
  independently names backingQueuePlaylistId=`QP<transient-queue>`.
  Those identifiers are different authorities; a QP hint is not removal authority.
* Live queue exposes mangled `JSC$12915_serverQueueApi`, not `.serverQueueApi`.
  Runtime native `removeItem` calls its server removal and immediately dispatches
  local REMOVE_ITEM, without awaiting server completion. Removing current invokes
  the next-song path. Never use it as a transactional preserve-current adapter.
* `k0.removeItem -> Bob -> Dob` reads removal playlistId and playlistSetVideoId
  from **navigationEndpoint.watchEndpoint**, not the QP add target. `Bob` obtains
  renderer.playlistEditParams and constructs ACTION_REMOVE_VIDEO. `Eob` wraps
  `{actions:[action], params:playlistEditParams, playlistId}` in the shared
  playlistEditEndpoint request and executes response.actions through `Bx`.
  In the present fixture/live projection the emitted target is LM. This does not
  prove an actual unlike/library deletion would occur: opaque edit params might
  encode ephemeral behavior. It DOES mean ephemeral-only authority cannot be
  established from permitted evidence. Calling it to find out is unacceptable.
* Reorder `bob -> aob -> Eob` uses the same navigation playlistId and edit params,
  with ACTION_MOVE_VIDEO_AFTER and set-video predecessor. Same blocker.
* Add `zob -> j0.getRequest` calls `/music/get_queue`. The request builder inherits
  store.queue.queueContextParams; serializes queueInsertPosition, videoIds or a
  playlistId and params. It **does not serialize backingQueuePlaylistId**.
  `Aob/Jnb` passing a QP value is therefore no proof of isolated queue ownership.
  Native add executes onResponseReceivedCommands (`Bx`/`FT`) before returning;
  the UI `Mzb` then adds every returned queueDatas.content. The existing exact
  helper filters content and avoids command execution, but does not synchronize
  the old server authority. Do not replace it with blindly executing commands.
* Shuffle `P_.shuffle -> Cob -> qob -> Y_` calls `/next` with
  WATCH_NEXT_TYPE_MUSIC_SHUFFLE or MUSIC_UNSHUFFLE and retained queue context.
  Both on and off can replace local rows through RESET_SHUFFLE_ITEMS. The method
  captures currentItem before await. A delayed response after SET_INDEX uses that
  old captured item: serialized Python locks do not serialize natural transitions.
* Natural advance `D_` dispatches SET_INDEX against the current rows; if autoplay
  is enabled at the end it can promote preview and call Jnb for server add. Also,
  the queue's selected-index subscription can extend a retained continuation near
  the end, independent of assuming autoplay is off. Both must be addressed.
* Replacement exists internally: `Rmb -> S_ -> Bnb` resets context/continuation;
  `S_(queue,true)` keeps the current local row; Bnb/Nnb can filter selected row
  out of fetched additions. However the actual user-facing keep-current decision
  `Nhb` is narrowly a same-video **RD radio** watch endpoint (not RDPN).
  That generates recommendations, not an exact curated ephemeral takeover.
  Ordinary watch/playlist navigation may reload/start media. No supported exposed
  exact-list replacement with a no-reload/pause/time/volume guarantee was found.
  Do not synthesize an RD playlist or shadow serverQueuesEnabled=false.

## Concrete takeover design (review contract, not implemented/live-supported)

The supported ingredients are queueAddEndpoint `/music/get_queue`, watch endpoint
`/next`, and application queue replacement/reset actions. Their composition into a
strict preserve-current takeover is NOT yet supported by verified evidence. The
missing piece is a native ephemeral replacement/create operation whose response
binds all edit endpoints to the new transient queue without reloading current media.
A safe adapter must meet all of these criteria before activation:

1. Keep one singleton worker and control.lock. OFF revokes generation before any
   paid model launch, search/network submission or queue write. Persist a bounded
   renderer lease before submission and drain it on OFF. A request sent before OFF
   cannot be unsent; document that boundary. The current lease guards local ADD_ITEMS
   only, and is NOT sufficient for server calls which mutate before resolving.
2. Checkpoint reviewed full queue, current renderer/media identity, currentTime,
   paused, volume, generation, shuffle=false, repeat=NONE and pending requests.
   Capture deliberate additions by review, never absence from discovery history.
3. Obtain a **new native transient authority** using a shipped create/replace route
   with no LM/saved playlist target or inherited old queue context. Include current
   video plus reviewed retained/manual upcoming tracks and screened Basil tracks.
   QP prefix alone is insufficient: require native queue ownership binding and
   consistent navigation/edit endpoints. Reject mixed LM/QP/saved targets.
4. Prepare detached response metadata; allowlist commands and reject any library,
   like, saved-playlist, navigation, transport or unexpected queue command. Validate
   exact IDs/order and one current selection before adopting anything. Never execute
   arbitrary onResponseReceivedCommands/actions to discover what they do.
5. Adopt authority/context/continuation/shuffle endpoints coherently without changing
   the current media node/source or triggering selected-item subscriptions to load it.
   Keep currentTime advancing if playing, precisely unchanged if paused, unchanged
   pause and volume. If native replacement cannot do that, STOP: parent must offer
   a separately approved controlled reload/seek recovery with disclosed interruption,
   or defer takeover to an explicitly approved natural boundary. Neither is the
   strict preserve-current requirement, so neither is an automatic fallback.
6. Future appends/removals must update transient server and local state under the
   same authority/lease and recheck selected ID after every await. Remove only
   provenance-proven upcoming rows; a newly current recommendation is protected.
   Review manual actions; invalidate evidence on unknown replacement or reorder.
   Stop on ambiguity without retry, playlist rollback, or undoing committed history.
7. Verify delayed shuffle ON and OFF, transition during pending request, near-end
   continuation fetch, autoplay promotion, reload/restoration, manual append, pause,
   generation change, OFF/client timeout, and network failure in a disposable player
   first. Confirm no saved/library requests and stable media properties. Then parent
   obtains explicit activation/live-testing approval for the actual account.

## Safe actionable path today

Do not activate server cleanup or describe recommendation/history prevention as
installed. Parent can review these findings and request a disposable-account native
queue takeover experiment, instrumenting only allowlisted routes/metadata. An
LM-targeting edit is outside that experiment. This release refuses guard
activation and queue automation rather than treating diagnostic evidence as a
safe repair. Preserve current media and use read-only capabilities/transport.
There is no safe one-command activation for a server-backed cure at present.

## Executed tests and limitations

`engine/fixtures/server_queue_caa327f5.json` contains exact public shipped function
excerpts, not secret metadata. `test_server_queue_routes.mjs` executes those methods
inside an isolated VM with mocked successful I/O and a minimal Closure async runner:
LM removal target despite QP add hint; inherited add context/ignored backing ID;
real pending shuffle-off promise restoring deletion and losing exact local addition;
natural SET_INDEX into restored history; natural transition during delayed shuffle
restoring the old captured selection; guard refuses server removal/local cleanup.
The reducer and media object are fixtures, not real browser/audio execution; error,
cast and feature-flag paths are not covered by this Closure runner.

`test_server_authority_off.py` proves OFF blocks paid process launch before player
reads and denies background search/enqueue/control before network/effect entry.
Existing tests additionally execute a real isolated delayed renderer process after
actual OFF lease draining and kill/reap an owned dummy refill child; no paid calls.

All engine Python tests: 47 passed. Renderer/append/server characterization tests:
39 passed. No new production behavior was changed; these are characterization and
safety tests, not a RED/GREEN implementation of the blocked server repair. An initial
natural-transition fixture incorrectly left one row (shuffle skips server fetch
when length <=1); adding a retained row corrected that fixture, not production.
No service/session/player/server queue/library/profile write, commit or push.
