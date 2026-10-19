# Basil Coda · The Elsewhere

A local listening room for YouTube Music, hosted by Basil Coda: an eight-armed
record collector with a conservatory education and no genre allegiance.
Python 3.11+ and Node 22+; no frontend build, pip/npm packages or bundled player.
Linux is the supported management platform (systemd user services).

**Free and open-source under the [MIT License](LICENSE).** Use it, change it,
share it, sell it, or build it into your own projects—including commercial and
closed-source projects. Just keep the copyright and license notice.

## Start without accounts

From any checkout path:

```sh
python3 -B basil.py doctor
python3 -B basil.py serve --port 8847
# Open http://127.0.0.1:8847
```

The interface and `/api/health` work without Pear or Hermes. Missing prerequisites
are reported, not treated as authenticated/live integration success. Serving the
page **never opens the player, starts music, starts management, or calls a model**.
Doctor is read-only; `doctor --probe` optionally GETs the configured loopback
Pear schema and CDP target listing without authentication. Even reachable
endpoints are not proof of login, valid credentials, safe queue capabilities or
audible playback.

For an offline independent-prefix install:

```sh
python3 -B scripts/setup.py install --prefix "$HOME/.local"
"$HOME/.local/bin/basil-coda" doctor
"$HOME/.local/bin/basil-coda" serve
```

The installer copies original sources and public configuration only, refuses to
overwrite an installation, generates but does not activate a user service,
and installs no Hermes profiles or Signal integrations. It does not download
anything, copy credentials, launch Pear, invoke a model or enable systemd units.
See [installation](docs/installation.md) for configuration and external setup.

## DJ and queue controls

Automatic DJing and queue editing are experimental; YouTube may override queue changes.

DJ ON/OFF, discovery filters, queue reorder/remove and explicit transport controls
are available with a configured player and Hermes profile. DJ ON enables the
singleton manager without opening the player or starting/resuming music; OFF
leaves playback alone. See [queue behavior and limits](docs/queue-release.md).

Musical direction is **ongoing until explicitly replaced**, including requests
worded "today". The latest genre, mood and track/album format survive refills,
pause, OFF/ON and worker restarts; neither generic hits nor old preferences are
fallbacks. Foreground assistants merge additive feedback into the complete saved
brief and mirror it in private preferences. For a direct update without enabling
management or touching playback/queue:

```sh
python3 engine/dj_session.py direction --brief 'Gentle beach folk' --queue-mode album
python3 engine/dj_session.py status
```

`start` without a brief reuses the saved direction and format. An explicit new
brief or mode also takes effect when already ON, without launching a second worker.
`direction` keeps ON/OFF unchanged and revokes stale refill admission; existing
queued music remains. An optional generation-scoped queue guard must be explicitly
re-armed after a direction change; it is not silently reauthorized. Omitted format
is retained unless the brief explicitly
requests full/whole/complete albums or a track mix. No date-based expiry exists.

Audio comes from the separate desktop player, not from the webpage. Web/REST/CDP
must stay on loopback. Host/Origin/custom-header protections are not multi-user
authentication. A restricted Hermes DJ profile is **not an OS sandbox**; only a
trusted local user should operate this app. No generic shell/API proxy is exposed.
Account/library/likes/saved-playlist changes require separate authorization.

## Public source versus private state

- `web/`, `server.py`, `history.py`, `volume.py`: room and observed listening ledger.
- `engine/`: narrow player controller, DOM readback, discovery and management.
- `portable_config.py`, `basil.py`, `diagnostics.py`, `scripts/setup.py`: portable
  configuration, explicit commands, offline install and read-only diagnostics.
- `hermes/dj/`: **reference** persona/skill, not an automatically installed profile.
- `integrations/together/`: optional personal household Signal example; not part
  of the installer payload, not a general multi-user auth implementation. It
  requires independently reviewed identity/group/policy configuration.
- `deploy/`: non-activating user-service example.

State defaults to `~/.local/share/basil-coda/state`; player data to
`~/.local/share/basil-coda/player`. Never put credentials, sessions, listening
ledgers, chat, preferences or cookies in source/distributions. An existing
installation can explicitly set its old state path; **no migration or symlink
changes happen automatically**. Back up private state separately.

## Verification

Use isolated state before importing engine modules:

```sh
export BASIL_STATE_DIR="$(mktemp -d "${TMPDIR:-$HOME/.cache}/basil-tests.XXXXXX")"
python3 -B -m unittest discover -s engine -v
python3 -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s integrations/together/household-dj -v
node --check web/app.js
node tests/test_frontend.mjs
node tests/test_history.mjs
node --test engine/test_*.mjs
python3 -B tests/test_frontend_browser.py
```

Browser checks use local mock APIs and installed Chromium only, no real player.
They do not establish external login, audible output or real model/Signal success.
This public repository excludes the proprietary vendor-code characterization
fixture and its dependent optional test. The tests above run without those
excerpts. No vendor binary or account state is bundled.
See [release-readiness](docs/release-readiness.md) for acceptance limits.

## License and external boundaries

All original Basil Coda code and documentation in this repository are released
under the [MIT License](LICENSE), copyright Eli Gaultney. No copyleft or
source-disclosure requirement is imposed on your modifications or applications.
The software is provided as-is, without warranty; see the license for details.

[Pear Desktop](https://github.com/pear-devs/pear-desktop) and
[Hermes Agent](https://github.com/NousResearch/hermes-agent) are separate upstream
projects with their own authors, licenses, releases and notices. They are not
vendored, relicensed or downloaded by this installer. Inspect their upstream
licenses before redistributing their binaries/source. YouTube Music, music,
artwork and accounts remain subject to their respective owners' terms. Proprietary
YouTube function excerpts are not included in this public repository; see
[third-party notices](THIRD_PARTY_NOTICES.md). Model subscriptions, streaming access,
network access and manual sign-in are external prerequisites, not included.
