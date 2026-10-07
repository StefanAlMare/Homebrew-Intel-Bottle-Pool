# Validation — Homebrew Intel Bottle Pool 0.3.3

Validation date: 7 October 2026.

## Release result

The final application is `0.3.3` build `33`, Intel `x86_64`, with a macOS 12
deployment target. It was signed with Developer ID Application certificate
SHA-1 `9FEDAF606F7CB05FC9FB2DB6B31C5F518BD78724`, Team ID `YWVVK7QZ6X`, Hardened
Runtime and an Apple timestamp.

Apple Notary accepted both final submissions:

- app receipt: `a801dacc-4a0c-48ff-8830-3f944533175d`;
- DMG receipt: `11347a9a-7ea3-42f4-9879-7b9ca2a32133`.

The app and DMG were stapled successfully. `stapler validate` and Gatekeeper
assessment passed for both, with `source=Notarized Developer ID`. Apple logs
reported `issues: null`.

## Automated and native workflow validation

All **104 automated tests** passed on the final source. Coverage includes:

- server schema 1, authentication, leases, atomic publication, SHA-256,
  fencing, offline spool and protocol compatibility;
- formula/Cask installation, local and official bottles, dependency contexts,
  date versions, warning filtering, external `root_url`, Intel PATH and safe
  fetch + fast-forward-only remote repair;
- durable queue pause/retry/resume/resolve/cancel, Action Required, Stop/Quit and
  process-group cleanup;
- stale GUI state versus authoritative backend `idle/resolved`, including a
  stopped cache with zero failures and zero remaining work;
- runtime dependency traversal before the dependent formula's current/build
  shortcut, paused-queue-preserving dependency repair, `brew missing` and
  `brew linkage --test` revalidation;
- maintenance command classification, destructive-command confirmation, closed
  stdin, shared/exclusive locking, exit path and permanent recovery controls;
- app metadata, version `0.3.3` build `33`, embedded client, signature checks and
  installer preservation of the existing configuration.

The compiled GUI workflow passed these isolated checks:

- cold launch with `pending-run.json` saying Stopped while backend has no
  `job.json` and reports idle;
- immediate clearing of the stale UI cache and unlocking of Update & Upgrade,
  Install and Sync;
- pause on first error, persistent failed count, retry only failures, resume
  remaining work, controlled Stop of a detached child and subsequent resume;
- Quit availability and complete fixture/config isolation.

The opt-in real Homebrew smoke test also passed in a disposable prefix. It built
and tested a small C formula, published a bottle, uninstalled it, then reinstalled
and tested it from the pool with source builds disabled. A deterministic Cask
was published, removed, its upstream archive hidden, and then installed again
from the pool. The operator's normal Homebrew prefix and installed packages were
not upgraded or modified.

## Platform used

- macOS 26.7.1 (build 25G241), Intel x86_64;
- Python 3.14.8 for validation; runtime minimum remains Python 3.9;
- Xcode/Apple Command Line Tools available for the Swift and formula builds.

## Security and recovery properties checked

- modifying maintenance commands and pool-aware repair use the same exclusive
  Homebrew lock as upgrade/install jobs;
- read-only diagnostics use a shared lock and do not overlap a writer;
- command stdin is `/dev/null`; commands are launched only from explicit user
  input and never inferred from logs;
- destructive patterns require GUI confirmation;
- a leading `sudo` uses macOS native administrator authorization; the app does
  not receive or store the password;
- Repair Pool State and queue cancellation preserve configuration, token, spool,
  installed software and already completed bottle artifacts;
- the signed application bundle does not self-modify; code fixes require a later
  signed/notarized release.

## Known limits

- The exact 47-minute CMake and 31-minute coreutils production build was not
  repeated. Its failure mode is covered by dependency-order and queue-recovery
  regression fixtures plus the isolated real Formula/Cask pilots.
- Validation used one physical Intel Mac, not every supported macOS release or a
  multi-Mac production fleet.
- NAS/TrueNAS deployment and WAN/VPN failure behavior were not rerun for 0.3.3;
  the schema-1 server protocol was kept unchanged and covered by local tests.
- The console deliberately has closed stdin and is not a general interactive
  TTY. Normal stdout/stderr is live; administrator commands may be buffered by
  the native macOS authorization bridge until completion.
- Bottle reuse remains constrained by platform, prefix/Cellar, formula source,
  options and dependency/ABI context.
- Mutable Casks remain upstream-only, and ambiguous/dirty/divergent taps still
  require explicit review.

No GitHub repository, release, Actions workflow or CI resource was created or
modified during this local release.
