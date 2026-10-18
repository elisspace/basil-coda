# Third-party notices and distribution boundaries

## Original Basil Coda

Original Basil Coda code and documentation are MIT licensed, copyright (c) 2026
Eli Gaultney. The MIT grant does **not** relicense third-party excerpts, upstream
applications, account content, artwork, recordings or trademarks.

## Excluded vendor-code characterization material

Proprietary Google/YouTube JavaScript excerpts and the optional characterization
test that depends on them are **not included in this public repository or its
history**. Specifically, `engine/fixtures/server_queue_caa327f5.json` and
`engine/test_server_queue_routes.mjs` are excluded. No permission to relicense or
redistribute Google's source is claimed. The public test suite runs without
these excerpts.

The album metadata fixture contains public track/album metadata for compatibility
tests, not recordings, artwork, lyrics or extracted vendor application code.
Basil's MIT license does not grant rights over third-party music or other content.

## External applications (not bundled)

- Pear Desktop: https://github.com/pear-devs/pear-desktop — maintained by its
  upstream contributors. Acquire it separately and consult its own license,
  notices and release/install requirements.
- Hermes Agent: https://github.com/NousResearch/hermes-agent — Nous Research and
  upstream contributors. Acquire/configure it separately; authoritative docs:
  https://hermes-agent.nousresearch.com/docs/
- Python, Node.js and optional Chromium are independently installed tools with
  their own licenses. The installer neither bundles nor downloads them.

No Pear/Hermes binaries/source checkout, browser profiles, cookies, credentials,
private history, model credentials, or music is included by Basil's installer.
Music and artwork displayed from YouTube Music remain third-party content and
subject to the relevant account/service terms. Household/Signal adapters in the
source are optional examples, not upstream Signal software or identity data.
