# Homebrew Intel Bottle Pool

**Version 0.3.5 · Intel macOS client · private bottle pool**

> **Build once. Reuse safely across compatible Intel Macs.**

Homebrew Intel Bottle Pool helps your Intel Macs share software they have already
built or downloaded. When Homebrew has no compatible bottle, one Mac can compile
and validate the formula, save it to a private pool, and let matching Macs reuse
it. The pool reduces repeated builds, CPU use, bandwidth, and waiting time.

Each Mac can both build and consume bottles. The menu-bar app coordinates normal
Homebrew commands, keeps a persistent work queue, and stores validated results
locally when the server is offline. A NAS or private server stores the artifacts;
compilation stays on the Macs.

Created and maintained by **StefanAlMare**, developed together with
**ChatGPT by OpenAI** for design, implementation, testing, documentation, and
release engineering. This project is independent from Homebrew and is not
affiliated with or endorsed by Homebrew.

## How it works

![Homebrew Intel Bottle Pool 0.3.5: shared architecture, five client steps, and bounded recovery](docs/assets/how-it-works.png)

[Editable diagram](docs/assets/how-it-works.svg)

1. **Plan consistently.** Read the dependency graph declared for the current
   macOS platform. Identify dependencies from recipes in their installed kegs.
   Before a source build, synchronize clean taps and pin the local recipe state.
2. **Look for a compatible bottle.** Check the pool and verify its identity and
   checksum. If there is no match, use a compatible official bottle when available.
3. **Build only when needed.** Coordinate with other Macs through a lease, build
   from the pinned local recipes, and save evidence of the build inputs.
4. **Validate before sharing.** Check the generated bottle, run the formula test,
   compare runtime/build/test inputs, and verify runtime dependencies and linkage.
5. **Keep the result and share it.** Save validated artifacts to the durable local
   spool and upload when the pool is reachable. Other matching Macs can reuse them.

Compatibility includes the macOS context, Homebrew prefix and Cellar, formula
source, options, and installed dependency identity. Every client follows the same
protocol; the private server authenticates requests, coordinates leases, checks
hashes, and stores or serves files. It uses Python's standard library.

## What changed in 0.3.5

| Problem | Behavior in 0.3.5 |
| --- | --- |
| Dependency API metadata changes while the installed keg stays unchanged | Dependency identity uses the installed `.brew` recipe hash and version, so an API-only change leaves the variant stable. |
| `brew deps` switches from the old keg's runtime graph to the new keg's graph during an upgrade | Planning explicitly selects the platform's declared recipe graph. Runtime dependencies are checked separately after the build. |
| API and local recipes are mixed during a source build | Installation uses synchronized local recipes with API installation disabled; tap state is checked again before publication. |
| Tap synchronization repeats during a long operation | Local safety checks reuse the synchronized snapshot without another client fetch; the snapshot is refreshed after the explicit `brew update` step. |
| Build inputs genuinely change | Reject the first artifact, refresh the plan and lease once, repair necessary dependencies, and perform a safe rebuild. Repeated drift stops publication. |
| Retry unnecessarily compiles a completed build again | Reuse it only when its recorded runtime/build/test inputs, installed recipe, and exact keg identity still match. |
| Provenance is missing, linked, unreadable, or inconsistent | Stop with a useful diagnostic. An unverified bottle is not published. |
| The target recipe changes without a version/revision bump | Its source hash is part of the variant, so the changed recipe cannot collide with the previous artifact. |
| Two local builds with identical proven inputs produce different archive bytes | Keep the published winner only after verifying its exact runtime/build/test context and downloading it with SHA-256 validation. |
| Legacy queued bottles repeatedly conflict | Preserve them unchanged in `spool/quarantine` for review, without upload or relabeling. |
| A legacy bottle-ready keg has no build evidence | A verified rebuild may be required; old evidence is never assumed. |

The `gobject-introspection`, `harfbuzz → brotli`, and `node → googletest` failures informed these general
fixes. The implementation applies to formulae throughout the dependency graph.
Homebrew's removal of the `bottle` stanza when saving `.brew` recipes is accounted
for explicitly, preserving the other source bytes exactly.

Pool protocol, spool, and `job.json` remain **schema 1**. The new identity has a
separate variant namespace, including formulae without dependencies. Existing
configurations, tokens, queued steps, and legacy pool artifacts are preserved.
Older clients keep their own variants; a first build of a new variant may be needed.
Legacy queued Homebrew artifacts are retained in `spool/quarantine`; the active
spool can continue safely without deleting those originals.

See [RELEASE_NOTES.md](RELEASE_NOTES.md) for the complete 0.3.5 changes,
[CHANGELOG.md](CHANGELOG.md) for earlier versions, and [VALIDATION.md](VALIDATION.md)
for completed checks and the actual release status.

## App actions and recovery

- **Setup / Settings…**: configure the private server URL, token or token file,
  optional CA certificate, and test the connection before saving.
- **Update & Upgrade** and **Install…**: run the coordinated Homebrew workflow.
- **Sync now**: upload queued validated artifacts when connectivity returns.
- **Retry Failed**: execute failed steps only; **Resume**: continue saved remaining
  steps. A successful Retry leaves the remaining queue paused for Resume.
- **Stop**: preserve resumable state; **Review Errors**: inspect the failure.
- **Repair / Install Dependency…**: repair a dependency without replacing a saved
  queue, then check missing dependencies and linkage.
- **Repair Pool State…**: reconcile stale UI or explicitly cancel saved work.
- **Maintenance Console…**: run an explicit command with live output and its real
  exit status. Destructive commands require confirmation; macOS handles `sudo`.
- **Start at Login**: enable the status agent if desired. Upgrade is user-initiated.

A technical failure stops before the next package. Recovery is bounded to one
replan per package per execution. Unknown trust decisions, unsafe taps, missing
provenance, and repeated changes remain visible for review. The client preserves
the queue and validated artifacts. It does not infer maintenance commands from logs.

Preflight preserves dirty, detached, ahead, or divergent checkouts and arbitrary
third-party remotes. Only recognized official legacy URLs and unambiguous missing
upstream configuration are repaired automatically. Compiler tuning and custom
formula options need separately reviewed variants.

## Compatibility

The application release is for **Intel x86_64 Macs** and has a macOS 12 deployment
target. The backend recognizes Big Sur, Monterey, Ventura, Sonoma, Sequoia, and
Tahoe contexts; the GUI requires Monterey or newer. Validation has been performed
on one Intel Mac; see VALIDATION.md for the tested scope and release status.

Each client needs:

- an Intel x86_64 Mac;
- a backend-supported macOS release;
- Homebrew;
- Python 3.9 or newer;
- Apple Command Line Tools when a source build is required.

Bottle compatibility is not determined by CPU alone. The pool separates artifacts
by platform, macOS context, Homebrew prefix and Cellar, formula metadata, options,
and relevant dependency/ABI context. It does not force an incompatible bottle or
promise reuse across different prefixes or platform variants.

## Install the macOS app

Use the final assets from the [v0.3.5 release](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/tag/v0.3.5)
once it is published. Verify the checksums, open the DMG, drag `Homebrew Pool.app`
to Applications, and launch it there. Final publication requires Developer ID
signing, notarization, stapling, and container verification. A local development
bundle or branch alone is not a completed release.

Setup opens automatically on an unconfigured Mac. For an existing installation,
quit the app before replacing it and keep your existing configuration, token,
spool, and saved queue. No schema-1 server migration is needed. Review the saved
error before using Retry; Resume handles the remaining steps.

Enter these public example values only as a guide; replace them locally and never
commit the real values:

```text
Server URL: https://pool.example.internal
Token File: /run/secrets/pool.token
CA:         optional private CA certificate
```

Select **Test Connection**, then **Save & Finish**. A pasted token is copied to a
private file with mode `0600`. Existing configuration and adapter settings are
preserved. Administrator credentials, when needed, are handled by macOS
SecurityAgent; the app does not collect or store the password.

The lower-level user-local installer is also available from source:

```sh
./install-app.sh \
  --url https://pool.example.internal \
  --token-file /run/secrets/pool.token
```

It installs under the current user and does not use `sudo`, modify shell profiles,
or install Homebrew/Python automatically.

## Run the private server

Use a dedicated persistent directory such as `/srv/homebrew-pool`. Store the token
outside the repository, for example at `/run/secrets/pool.token`, readable only by
the service account.

```sh
python3 -m pool.server \
  --root /srv/homebrew-pool \
  --bind 127.0.0.1 --port 8765 \
  --token-file /run/secrets/pool.token
```

The loopback binding is suitable behind a private reverse proxy or VPN endpoint.
For direct access from a protected LAN, bind to the appropriate private interface
and provide TLS certificate/key options. `Dockerfile` and `compose.yaml` are
included for a small local container deployment.

Use **HTTPS**, a **VPN**, or a trusted private LAN. **Never expose plain HTTP plus
a bearer token directly to the Internet.** Remote HTTP is rejected unless the
client's explicit insecure-HTTP option is enabled, and that option is intended
only for an already protected private network.

The server account needs write access only to `/srv/homebrew-pool` and read access
to `/run/secrets/pool.token` plus any TLS material. Macs do not need SMB or SSH
access to the storage directory. Run one server process against a storage root;
do not place the active store on a remote SMB/NFS mount.

## CLI quick start

```sh
sh install.sh
export PATH="$HOME/.local/bin:$PATH"
brew-pool configure \
  --url https://pool.example.internal \
  --token-file /run/secrets/pool.token
brew-pool status
brew-pool upgrade
```

Useful commands:

```sh
brew-pool upgrade
brew-pool upgrade openssl@3
brew-pool upgrade --no-build
brew-pool install wget --type formula
brew-pool install firefox --type cask
brew-pool install package-name --type auto
brew-pool sync
brew-pool repair dependency openssl@3
brew-pool repair state
brew-pool repair state --cancel
brew-pool maintenance "brew doctor"
```

Formula flow is pool lookup, compatible official bottle when available, or local
source build with Homebrew; the result is bottled, checked, tested, spooled, and
published. Dependencies follow the same client. Deterministic Casks with fixed
version and SHA-256 can be cached and reused. Mutable `latest`/`no_check` Casks are
upstream-only and are not published.

## Storage, integrity, and recovery

The server verifies SHA-256 before an atomic manifest update. Per-artifact leases
reduce duplicate online builds. If the server is unavailable, complete results
remain in a durable local spool and `brew-pool sync` can publish them later. An
offline network partition can still cause two Macs to build the same artifact;
the pool avoids losing either result and refuses ambiguous same-version bytes.

The bearer token grants access to the whole private pool; this release does not
implement per-artifact ACLs. SHA-256 protects integrity, not upstream authorship.
Only use the pool among machines and operators you trust.

## Validation and checksums

See [VALIDATION.md](VALIDATION.md) for the actual checks completed for 0.3.5,
including limitations and the release gate. No notarization is implied by a
source checkout or development build.

Verify downloaded release assets:

```sh
shasum -a 256 -c SHA256SUMS.txt
```

Download all files listed in the checksum manifest into the same directory before
running the complete check. The manifest covers the DMG, app ZIP, source ZIP,
release documentation, and notarization evidence. See INSTALLATION.md if you
only downloaded the DMG.

## Local development

```sh
python3 -m unittest discover -s tests -v
python3 local_demo.py
./build-macos.sh
```

The normal build is local and ad-hoc signed for development. Release signing and
notarization require credentials already configured by the maintainer. Secrets,
Keychain data, notarization receipts, private configuration, build directories,
and logs are intentionally excluded from version control and source archives.

There are no GitHub Actions or hosted builds. This keeps GitHub resource use low
and ensures Homebrew compilation happens only where it is useful: on the Intel
Macs participating in the private pool.

Release preparation happens entirely on the local Intel Mac. Only verified final
sources and artifacts are uploaded. Publication also updates the default `stable`
branch, including this introduction and diagram, and marks v0.3.5 as the latest
release after its downloaded assets pass verification. `main` is never used.
See [RELEASING.md](RELEASING.md) for the ordered release gates.

See [QUICKSTART.txt](QUICKSTART.txt), [VALIDATION.md](VALIDATION.md),
[RELEASE_NOTES.md](RELEASE_NOTES.md), [INSTALLATION.md](INSTALLATION.md), [CHANGELOG.md](CHANGELOG.md), and
[LICENSE](LICENSE).

## Credits

- **StefanAlMare** — project creator, owner, requirements, product direction,
  infrastructure context, validation decisions, and release authorization.
- **ChatGPT by OpenAI** — collaborative implementation, debugging, testing,
  documentation, security review, and release preparation.

The project remains independent from Homebrew; neither contributor attribution
implies affiliation with or endorsement by Homebrew.

## License and source-code permission

Official, unmodified releases may be downloaded and used without charge for
lawful personal, educational, internal, or business operation of the Product.
This includes running the unmodified server and clients for their intended
private bottle-pool purpose.

The source is public for transparency, audit, and evaluation, but it is not an
open-source grant. Reusing, modifying, integrating, repackaging, redistributing,
or creating derivative work from the code requires prior explicit written
permission from **StefanAlMare**. See [LICENSE](LICENSE) for the complete terms.
