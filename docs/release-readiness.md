# Release readiness and acceptance limits

## What the portable candidate establishes

- An offline installer works in an independent empty HOME and a prefix containing
  spaces, with no credentials, model/player startup, profile installation or
  service activation. It refuses overwrite and emits an inactive exact-prefix
  web service plus public TOML configuration.
- UI and `/api/health` serve without Pear/Hermes accounts. Missing backend state
  returns a bounded explanatory error, not a traceback; transport is disabled
  when disconnected and the UI points to `basil-coda doctor`.
- Doctor distinguishes source installed, dependency/configuration-file presence,
  unverified login and live acceptance not performed. Optional loopback GET
  probes do not authenticate, run models or mutate playback. Reachable fake
  endpoints in tests are explicitly **not live integration success**.
- Config resolves user HOME/state/profile/executable paths without a fixed
  account; TOML plus environment precedence is tested. Nonloopback REST/CDP
  values are rejected before any connection. Player launch is an explicit
  command with a single executable argv and fixed loopback/data-isolation flags;
  tests exercise it with a clearly labelled fake executable only.
- HTTP Host/Origin/request-header/body/static-path protections remain covered by
  the HTTP suite. Headless Chromium checks use a local fixture API, not Pear.
- Original code has an MIT license; extracted upstream characterization excerpts
  have a separate third-party notice and are excluded from runtime installation.
  This is not a legal clearance to redistribute those excerpts in a source archive.

Proof logs belong outside the product sources. During candidate preparation,
bootstrap/path/security tests were written before implementation and failed;
the missing-prerequisite UI assertion also failed in real headless Chromium
before the explanatory UI change, then passed. Full source-baseline engine,
web/history/volume, optional household and Node suites are regression gates,
not proof of live external access. The parent integration/review must rerun the
suites after combining queue and portability changes and record exact results
in its external release report.

## Integrated portability boundary

The engine now consumes the same resolved configuration before binding state,
executable/profile/unit and REST/CDP endpoints. Its nonsecret Node bridge reads
that shared TOML/environment resolver; standalone Node helpers also require
`python3` (Python 3.11+) on PATH. Player HTTP requests refuse proxies/redirects,
client IDs and paths are validated, and returned CDP WebSocket URLs must name the
same literal loopback authority. The retained worker primitive propagates resolved
configuration explicitly through systemd-run. Explicit DJ ON can launch the
existing worker/model; setup and serving cannot. Synthetic tests of argv do not
establish live worker acceptance.

Existing installations must explicitly retain their old state directory in public
configuration; no credentials/state are migrated. This release is prepared in a
separate worktree, not deployed over the existing listening session.

## Queue workflow: capability gated, no invented fix

Read [server-queue authority](server-queue-authority.md) and
[queue guard](queue-guard.md). Local-only ADD_ITEMS/deletion may diverge from
server-owned playlist/history context; asynchronous shuffle responses can restore
removed rows or lose local additions. Autoplay=false alone is not ownership.

Queue capabilities are exposed in snapshots and checked before web ON/edit
handlers. DJ ON/OFF, bounded automatic refill and the original queue editing
controls are enabled experimentally without an extra opt-in. Existing stale queue,
readback, OFF/pause, generation and reservation protections remain. Capability
booleans mean feature availability, not real login or integration acceptance.
No durable server-queue adapter, server-backed deletion/reorder, invisible reload,
quiet re-login or automatic repair has been implemented. The linked investigation
and guard contracts are design/research requirements, not a blanket release denial.
Do not create a second worker, force flags or retry ambiguous appends for a demo.

## Manual prerequisites and remaining real acceptance

The following are not established by bootstrap, fake endpoints or a source merge:

- Independently installed/supported Pear build; loopback REST/CDP sockets;
  dedicated target; own client enrollment, valid auth and manual YouTube login.
- Independently installed Hermes with selected provider credentials, working
  model access, adapted DJ skill/SOUL, reviewed CLI/Desktop tool restrictions and
  correct profile/state paths. Profiles are not OS sandboxes.
- Read-only authenticated player state/queue agrees with live renderer; worker
  unit refers to the chosen singleton/config and no unintended worker exists.
- Separately authorized real bounded model conversation and player control with
  pre/post queue, current selection, pause and volume readback. No audible-output
  claim from an HTTP 200. No silent player launch or navigation/reload guarantee.
- Real queue mutation/recovery only when the installed engine admits that exact
  mode/version; unsupported modes must fail closed. Reliable unattended management
  and durable server-queue persistence remain unverified.
- Optional household/Signal identity policy and actual message delivery, if
  deliberately enabled. No Signal integration is installed by default.

Do not copy old credentials, browser data, accounts or private histories to make
a fresh-user test pass. Do not include proof logs, scratch artifacts, cookies,
state, private settings or credentials in a source archive. No public publication
or live deployment is part of this candidate preparation.
