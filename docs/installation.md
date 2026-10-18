# Installation and configuration

## Supported bootstrap

Python >=3.11 runs the HTTP server/installer with only the standard library.
Node >=22 supplies native WebSocket for the external player bridge. Linux with
systemd user services is required for timed management; UI/doctor can be used
without systemd, Pear or Hermes. No npm/pip install or build is required.

```sh
python3 -B scripts/setup.py install --prefix "$HOME/.local"
"$HOME/.local/bin/basil-coda" doctor
"$HOME/.local/bin/basil-coda" serve --port 8847
```

Use an absolute prefix without backslashes or control characters; unsupported
prefixes are rejected before installation. Spaces, dollar signs and percent signs
are supported. The prefix contains
`bin/basil-coda`, `share/basil-coda/`, `etc/basil-coda/config.toml`, and the
**inactive** generated `share/basil-coda.service`. Existing destinations are not
overwritten. Upgrades should use a new empty prefix, review config changes,
then explicitly switch the chosen service; private state is never removed or
migrated by installation. To uninstall, remove only the installed paths after
backing up configuration; state/player data are separate and are not removed.

No dependency downloads, credentials, Hermes profile activation, player launch,
model requests, service enablement, playback or household integration occur.
`doctor` reports missing dependencies as JSON with exit 0 when diagnostics ran;
a configuration error exits nonzero. Inspect `configured`, not just exit status.
The source-only `hermes/dj` files are reference material only. The installer omits
Hermes profile references, household adapters and test/vendor fixtures from its runtime payload.

## Configuration

`BASIL_CONFIG=/absolute/path/config.toml` selects a TOML file. The installed
launcher selects its generated config by default. Every field has a `BASIL_`
environment override (uppercase field name). CLI `serve --port` chooses the web
port; bind address is deliberately fixed at `127.0.0.1`.

Example public config (replace paths yourself; **no secrets**):

```toml
[basil]
state_dir = "/home/YOUR_USER/.local/share/basil-coda/state"
hermes_home = "/home/YOUR_USER/.hermes"
hermes_profile = "dj"
hermes_bin = "/home/YOUR_USER/.local/bin/hermes"
player_executable = "/home/YOUR_USER/Apps/pear-desktop/AppRun"
player_data_dir = "/home/YOUR_USER/.local/share/basil-coda/player"
rest_url = "http://127.0.0.1:26538"
cdp_url = "http://127.0.0.1:26539"
worker_unit = "hermes-dj-session"
```

Without overrides, state/player/Hermes paths derive from the invoking user's
HOME, `hermes_bin` is `hermes` on PATH, and the player executable is unset.
`~` is expanded for directory paths, not within executable names. Executables
are one argv element, not shell fragments; use absolute paths for services.
The custom Hermes home is its base containing `profiles/NAME`; profile names
allow only letters, digits, `_` and `-`. Do not point a new install at someone
else's HOME or state. Existing users must explicitly configure their previous
state directory if retaining it; there is no automatic credential/state copy.
Unset stale `BASIL_*` variables before independent-HOME tests: an inherited
`BASIL_STATE_DIR` can intentionally override the safe default.

REST/CDP URLs accept only `http://127.0.0.1:PORT`, no remote hosts, credentials,
paths, query or fragment. Configure Pear to match and independently verify
socket binding with your OS tools. Do not reverse-proxy or tunnel these ports;
CDP can execute code in the authenticated renderer. Host/Origin/header checks
on the web app are not a remote-authentication solution.

The server and standalone Python/Node engine helpers share this TOML/environment
resolver. Endpoint values remain loopback-only; configured executable/profile/unit
values are propagated to helpers. Node helpers also need Python 3.11+ as `python3`
on PATH. DJ ON/refill and queue editing are available with the existing helper
guards; experimental availability is not real login or durable queue acceptance.

## External prerequisites: manual, separately authorized

1. Install Pear Desktop from its upstream project, review its license/install
   requirements and choose a dedicated data directory. No Pear binary or
   AppImage is included here. Configure its API plugin to bind REST only to
   `127.0.0.1` and the chosen port. Refer to that installed build's `/doc` for
   authentication/enrollment; API behavior varies by version.
2. Set `player_executable`. **Only when you intend to open the player**, run
   `basil-coda player`. It passes a dedicated `--user-data-dir` and loopback CDP
   address/port. Launch/navigation can start media; this is not a silent login
   command. Complete YouTube Music sign-in yourself inside the dedicated player.
   Never export/copy browser cookies or another user's player data into a release.
3. Enroll a client using that Pear build's documented consent flow. Basil expects
   a private `player-client.json` in `state_dir`, containing a `client_id` issued
   to your own dedicated player. Protect it and the directory with user-only
   permissions. Do not invent an ID or copy one from another installation. There
   is deliberately no automatic enrollment or account login in the installer.
4. Install Hermes separately following the authoritative
   [installation docs](https://hermes-agent.nousresearch.com/docs/getting-started/installation).
   Create/configure a dedicated named profile using the current
   [profile documentation](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)
   and [security guidance](https://hermes-agent.nousresearch.com/docs/user-guide/security).
   Choose/configure a model provider and credentials through Hermes itself.
   Review and adapt the reference SOUL/skill to your actual checkout/state/helper
   paths and musical preferences **before** copying them into your chosen profile.
   The reference describes the experimental controls; it is not an automatically
   installed or configured profile.
5. Restrict the chosen profile's CLI and Desktop tools; read back configuration.
   A persona/prompt alone is not enforcement, and profile isolation is not an OS
   sandbox. Web chat is for a trusted local user and can invoke the profile's
   configured tools. No model or gateway is started during bootstrap verification.
6. Run `basil-coda doctor`, optionally `doctor --probe`. Check the real player's
   read-only state and engine capabilities. Separately authorize a bounded real
   model/music test only after confirming account, queue ownership, pause and
   volume. Unverified login is not a successful installation test of integrations.

There is no complete one-click account provisioning flow. Until manually
configured, the interface serves and controls fail unavailable with guidance.
The optional `integrations/together` adapter is disabled/not installed by default;
it is a reviewed sample requiring your own group/identity/policy setup, not
permission to use the original household's identities or private settings.

## Optional web service (never management auto-start)

After reviewing the generated unit, paths and dependency PATH under your user
manager, you may explicitly install/enable the **web only** service:

```sh
mkdir -p "$HOME/.config/systemd/user"
cp "$HOME/.local/share/basil-coda.service" "$HOME/.config/systemd/user/basil-coda.service"
systemctl --user daemon-reload
systemctl --user enable --now basil-coda.service
```

These commands are opt-in and are not run by setup. A nondefault prefix's unit
uses its exact launcher path and quoted/escaped values. Check configured absolute
Hermes path and Node visibility in the service environment. The web unit serves
UI/history observations only; it does not launch Pear, start playback or enable
DJ management. Use the explicit DJ ON/OFF control for the existing singleton
worker; do not add a management timer or second worker. Worker argv code is
fixture-tested with resolved configuration, not live management acceptance.
