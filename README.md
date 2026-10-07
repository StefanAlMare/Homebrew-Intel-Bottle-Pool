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

Homebrew Intel Bottle Pool turns every configured Intel Mac into an equal peer.
Any Mac can authenticate, reuse an existing compatible artifact, or obtain/build
a missing one locally, validate it, and publish it to the private central pool.
The new artifact then becomes available to every other compatible Mac. The next
artifact may be contributed by a different Mac, so work and reuse flow in both
directions across the whole fleet.

This project does **not** replace Homebrew and is **not affiliated with, endorsed
by, or maintained by Homebrew**. It coordinates the normal Homebrew CLI and adds
a private reuse layer for trusted machines.

## How it works

```text
┌─────────────────────┐   authenticate / fetch / publish   ┌──────────────────────┐
│ Intel Mac 1         │ ⇄─────────────────────────────────⇄ │ Private bottle pool  │
│ package A producer  │                                     │ NAS / server + disk  │
└─────────────────────┘                                     │                      │
┌─────────────────────┐   authenticate / fetch / publish   │ - manifests + blobs  │
│ Intel Mac 2         │ ⇄─────────────────────────────────⇄ │ - SHA-256 validation │
│ package A consumer  │                                     │ - leases + versions  │
│ package B producer  │                                     │ - durable storage    │
└─────────────────────┘                                     │                      │
┌─────────────────────┐   authenticate / fetch / publish   │ No compilation here  │
│ Intel Mac 3         │ ⇄─────────────────────────────────⇄ │                      │
│ Cask/adapter update │                                     └──────────────────────┘
└─────────────────────┘
          ⋮                          ⇅
┌─────────────────────┐   authenticate / fetch / publish
│ Intel Mac N         │ ⇄─────────────────────────────────⇄
│ any compatible work │
└─────────────────────┘
```

There are no permanent builder and consumer roles. Every configured Mac follows
the same peer workflow:

1. Authenticate to the private pool and describe the required compatibility
   context.
2. Look up the package, Cask download, or configured external adapter artifact.
3. On a compatible hit, download, verify, and use it.
4. On a miss, obtain the build lease when online, then acquire an official bottle
   when suitable or compile locally, validate/test the result, and place it in the
   durable local spool.
5. Publish or sync the validated artifact to the pool. It immediately becomes a
   candidate for every other compatible Mac.
6. Repeat independently: Mac 2 may publish another formula, Mac 3 may refresh a
   Cask or external adapter, and Mac N may contribute the next missing artifact.

The central host authenticates peers, coordinates online leases, verifies and
versions uploads, and stores or serves files. It never assigns a Mac a fixed role
and never compiles Homebrew packages. Compilation stays on whichever Mac first
needs and successfully claims the missing compatible artifact. If Macs are
offline from the pool, more than one may build the same item; their durable local
spools preserve the results until synchronization can resolve them safely.

The pool server can run on a NAS, TrueNAS system, Linux server, home server, or
another always-on host with persistent storage and reliable connectivity. The
backend uses Python's standard library and requires no third-party Python package.

## Release 0.3.3

Release 0.3.3 is recovery-focused. At launch, whenever the menu opens, and every
10 seconds, the app reconciles its UI cache with the real schema-1 backend job.
An `idle`, `resolved`, or terminal job with zero failures and zero remaining
steps becomes **Healthy** and immediately unlocks normal actions. A stale
`pending-run.json`, a resolved `job.json`, a cold launch, or a reboot can no
longer leave the menu stuck on Paused/Stopped.

The menu-bar application provides:

- first-run **Setup** with Server URL, pasted Token or Token File, optional CA,
  and **Test Connection**;
- **Update & Upgrade** for the coordinated Homebrew workflow;
- **Install…** with Auto, Formula, and Cask selection;
- **Sync now** for queued offline results;
- **Repair / Install Dependency…** while a job is paused, stopped, needs action,
  or is otherwise idle; it preserves the queue, repairs through the pool-aware
  formula flow, and runs `brew missing` plus `brew linkage --test`;
- **Repair Pool State…** to reconcile the GUI or explicitly discard pending
  work without deleting installed formulae, completed bottles, configuration,
  token, or spool;
- an always-available **Maintenance Console…** with explicit command input,
  live stdout/stderr, in-session command history, Stop Command, exit code, and
  shortcuts for `brew doctor`, `brew outdated`, `brew missing`, and
  `brew linkage --test`;
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

Before a formula is accepted as current or built/published, its topological
runtime dependencies are now installed or updated first. This specifically
prevents a dependent build such as `coreutils` from reaching publication with an
outdated dependency such as `openssl@3`. Retry revalidates formula and dependency
context before publication.

Maintenance commands are never inferred from logs and never run automatically.
They receive closed stdin, secrets are not placed in command arguments by the
app, and modifying commands share the same exclusive Homebrew lock as normal
jobs. Read-only diagnostics use a shared lock and cannot overlap a writer.
Potentially destructive commands require confirmation. A leading `sudo` is
removed and routed to the native macOS authorization dialog; the application
does not read or store the password. The console is for Homebrew and pool
recovery, not for modifying the signed/notarized application bundle; code fixes
arrive only through a later signed release.

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

### Old versions are replaced, not accumulated

The active pool keeps **only the newest valid artifact in each compatibility
slot**. A slot is the exact combination of artifact kind/name, platform, and
compatibility variant. When a newer upgrade for that same slot is committed:

1. the server verifies the complete new upload and its SHA-256;
2. it stores the new blob durably;
3. it atomically points the slot manifest to the new version;
4. it deletes every older blob in that slot.

This means repeated upgrades do not leave every historical version in the active
pool consuming storage. Different macOS/prefix/ABI variants are different slots,
so the newest artifact for each still remains available. A download already in
progress can finish from its open file handle even when the old filename is
removed; new lookups receive the new version.

Local spool entries are also deleted after the server confirms that they were
published, already existed, or were superseded by a newer version. Failed,
offline, busy, or conflicting entries are retained for review so work is not
lost. Incomplete temporary uploads and unreferenced blobs are cleaned during
normal completion or server restart.

Two boundaries are intentional:

- NAS/ZFS snapshots and external backups may retain deleted historical blocks;
  their space use follows the NAS retention policy, not the active pool.
- The project does not run `brew cleanup` automatically on client Macs. Old
  Homebrew kegs/download caches follow Homebrew's own policy and can be cleaned
  separately after the operator confirms the upgrade works.

The bearer token grants access to the whole private pool; this release does not
implement per-artifact ACLs. SHA-256 protects integrity, not upstream authorship.
Only use the pool among machines and operators you trust.

## Validation and checksums

Release 0.3.3 passed 104 automated tests, isolated real-Homebrew formula/Cask smoke
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
