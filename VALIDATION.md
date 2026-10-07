# Validation — Homebrew Intel Bottle Pool 0.3.0

Validation date: 7 October 2026.

## Release result

The final Intel x86_64 application and DMG were signed with Developer ID,
notarized by Apple, and stapled. Strict signature checks, stapler validation,
Gatekeeper assessment, and read-only DMG verification passed for the application,
the app extracted from the ZIP, and the app mounted from the DMG.

The embedded Python client matched the final source byte-for-byte. The release did
not embed the configured private pool URL or token. The source release excludes
local configuration, credentials, Keychain data, notarization receipts, internal
logs, temporary builds, and private handover notes.

## Automated and workflow validation

All 50 automated tests passed. Coverage includes:

- HTTP authentication, schema checks, SHA-256 integrity, atomic publication,
  leases, heartbeat/fencing, recovery, and durable offline spool behavior;
- formula dependency handling, official/local bottle paths, Cask caching,
  external adapters, version ordering, prefix/context separation, and retry;
- Setup/Settings configuration, Token/Token File, optional CA, Test Connection,
  Update & Upgrade, Install Auto/Formula/Cask, Sync now, and Start at Login;
- Healthy/Connected, Offline/Spooling, Busy, and Error states;
- safe tap synchronization using fast-forward only while refusing dirty,
  detached, or divergent repositories.

An isolated Homebrew smoke test compiled and tested a small C formula, published
its bottle, and reinstalled it from the pool with source building disabled. A
deterministic test Cask was also republished and reinstalled after its upstream
copy was made unavailable. The test used temporary Homebrew/cache/config/storage
locations and did not update or modify the operator's normal Homebrew installation.

Native UI workflow tests verified readable Setup and Install dialogs and the
menu-bar workflow. The app
does not collect administrator passwords; macOS SecurityAgent handles system
authorization where supported.

## Platform used

The final build was produced and validated on one Intel x86_64 Mac with a macOS 12
deployment target and Python 3.14. The application requires Python 3.9 or newer at
runtime. Homebrew is required, and Apple Command Line Tools are required when a
formula must be compiled from source.

## Known limits

- Validation used one Intel Mac and small fixtures, not every supported macOS
  release or a production fleet upgrade.
- NAS/TrueNAS deployment, WAN/VPN behavior, and two simultaneous physical Macs
  were not exercised in the final local pilot.
- Bottle reuse still depends on platform, macOS context, prefix/Cellar, formula
  metadata, options, and relevant dependency/ABI context.
- Third-party repositories that disappeared or changed identity are never guessed;
  ambiguous, dirty, detached, or divergent taps require manual review.
- Mutable Casks (`latest` or `no_check`) are upstream-only and are not published.
- The service uses one bearer token for the trusted private pool and does not
  provide per-artifact ACLs.
- HTTP plus a token must not be exposed directly to the Internet; use HTTPS, a
  VPN, or a protected private LAN.

Homebrew Intel Bottle Pool is independent software. It is not Homebrew, and it is
not affiliated with or endorsed by Homebrew.
