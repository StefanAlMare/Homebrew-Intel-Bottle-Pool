# Homebrew Intel Bottle Pool

A private, shared bottle pool for people who still use Intel Macs.

Created and maintained by **StefanAlMare**, developed together with
**ChatGPT by OpenAI** for design, implementation, testing, documentation, and
release engineering.

> **Build once. Store once. Reuse across compatible Intel Macs.**

Homebrew no longer produces bottles for current Intel macOS configurations. As a
result, newer formulae increasingly need to be built locally from source. That is
an inconvenience on one Mac; across a fleet of Intel Macs it wastes CPU time,
energy, bandwidth, and often many minutes or hours by compiling the same software
again on every machine.

Homebrew Intel Bottle Pool lets one compatible Intel Mac build or obtain an
artifact once, validate it, and publish it to a private central pool. Other
compatible Macs can reuse that artifact instead of repeating the work.

This project does **not** replace Homebrew and is **not affiliated with, endorsed
by, or maintained by Homebrew**. It coordinates the normal Homebrew CLI and adds
a private reuse layer for trusted machines.

## How it works

```text
┌───────────────┐     authenticated HTTPS/VPN     ┌──────────────────────┐
│ Intel Mac A   │ ─── lookup / publish ─────────▶ │ Private bottle pool  │
│ build + test  │                                  │ NAS / server + disk  │
└───────────────┘                                  └──────────┬───────────┘
                                                              │ lookup
┌───────────────┐                                             │
│ Intel Mac B   │ ◀───────────────────────────────────────────┘
│ verify + use  │
└───────────────┘
```

There are no permanent builder and consumer roles. Every configured Mac can look
up compatible artifacts, publish newly validated artifacts, keep failed uploads
in a local spool, and retry them later. The central host stores and serves files;
Homebrew compilation stays on the Macs.

The pool server can run on a NAS, TrueNAS system, Linux server, home server, or
another always-on host with persistent storage and reliable connectivity. The
backend uses Python's standard library and requires no third-party Python package.

## Release 0.3.2

The menu-bar application provides:

- first-run **Setup** with Server URL, pasted Token or Token File, optional CA,
  and **Test Connection**;
- **Update & Upgrade** for the coordinated Homebrew workflow;
- **Install…** with Auto, Formula, and Cask selection;
- **Sync now** for queued offline results;
- **Settings…** for later configuration changes;
- user-controlled **Start at Login**;
- distinct **Healthy**, **Busy**, **Action Required**, and **Paused — Error**
  states, plus a stopped/paused state when a queue is preserved.

At the first technical error, the queue pauses before the next package. The app
can review errors, retry only failed work, resume remaining work, explicitly skip
failed work, or cancel the saved queue. While work is running, Stop is available
and Quit offers Stop & Quit. Decisions that cannot safely be automated appear as
Action Required.

The preflight step checks the Brew repository and installed taps. It repairs only
recognized official legacy URLs and unambiguous missing upstream configuration,
then uses fetch/prune and fast-forward-only updates. Dirty, detached, ahead, or
divergent repositories require review. Custom remotes and third-party tap URLs
are preserved.

## Compatibility

The application release is for **Intel x86_64 Macs** and has a macOS 12 deployment
target. The backend recognizes Big Sur, Monterey, Ventura, Sonoma, Sequoia, and
Tahoe contexts; the GUI requires Monterey or newer. The final release was tested
on one Intel Mac, not on every macOS version.

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

Download the DMG from the GitHub release, verify its checksum, open it, drag
`Homebrew Pool.app` to Applications, and launch it from Applications. The signed
release is notarized and stapled. Setup opens automatically on an unconfigured Mac.

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

Release 0.3.2 passed 94 automated tests, isolated real-Homebrew formula/Cask smoke
tests, native GUI workflow checks, strict code-signature checks, Apple
notarization, stapling, Gatekeeper assessment, and DMG verification. Details and
known limitations are in [VALIDATION.md](VALIDATION.md).

Verify downloaded release assets:

```sh
shasum -a 256 -c SHA256SUMS.txt
```

The checksum file in the release covers the public DMG, app ZIP, source ZIP,
QUICKSTART, and VALIDATION assets.

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

See [QUICKSTART.txt](QUICKSTART.txt), [VALIDATION.md](VALIDATION.md),
[INSTALLATION.md](INSTALLATION.md), [CHANGELOG.md](CHANGELOG.md), and
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
