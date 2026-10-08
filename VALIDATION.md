# Validation — Homebrew Intel Bottle Pool 0.3.5

October 8, 2026. This report distinguishes completed local tests from the checks
required for each final distribution. A branch checkout alone does not prove
that a public release exists.

## Independent audit

Initial commit 4c9c880: 120 tests, three failures, one error, and three skips
because the bundle was absent. Cached synchronization omitted the local tap
safety check; this test is also rediscovered through imports. The legacy fixture
did not provide an installed dependency recipe. The bundle test still expected
build 34 instead of 35. These issues were fixed without weakening production
checks.

## Completed checks

The expanded suite passed all **160 tests**, with no skips, using the local Intel
0.3.5 bundle, build 35. Coverage includes publication and notarization regressions
and the five publication-gate/asset-manifest checks. The suite exercises schema 1,
a loopback fixture server, leases/fencing, offline spool, Retry/Resume/Stop,
rollback, installation into temporary directories, provenance, declared graphs,
actual runtime/build/test changes, and embedded bundle sources.

New regressions cover API-only dependency changes with stable identity; changed
installed recipes/versions with new variants; rejected missing or linked evidence;
separate, unconsumed legacy variants; Retry with six or five pending steps;
old-keg/new-keg transitions without false recompilation; actual drift with one
rebuild; repeated drift stopped after two builds; reuse only with a valid build
proof; rejected undeclared runtime dependencies; changed build-only inputs;
rejected modified/divergent local taps; post-update snapshots without additional
fetches; exact bottle-block removal preserving other bytes/newlines; and rejected
modified embedded sources. Build proofs are bound to the keg and invalidated on
rollback.

Read-only inspection of real harfbuzz 14.5.1 and 14.6.0 receipts confirmed brotli
absent from the former and at 1.2.0 in the latter. The local Homebrew implementation
reads `runtime_dependencies` from the keg when dependency queries do not explicitly
select recipe mode. Normalizing the actual harfbuzz tap source produced the exact
hash of the installed 14.6.0 `.brew` copy. These checks ran no mutating Homebrew
commands.

The local `node` log and spool manifests identify googletest 1.18.0 as the failed
dependency, with two identical local copies. The remote manifest was not read;
remote bytes/context remain unconfirmed. Regressions cover separate variants
after formula changes, verified reuse of an already published build, rejected
context/build-input mismatches, preservation of upstream checksums, and legacy
quarantine without byte changes. Notary transport checks SSH authentication and
host identity, verifies the transferred archive hash, and keeps credentials on
the Mac that owns the profile.

The compiled application passed an isolated workflow check with real child
processes: pause on first error, persistent failure count, Retry only failed
steps, Resume remaining steps, Stop with child cleanup, Stop/Resume, Quit while
Busy, isolated configuration, and reconciliation of stale UI state at cold launch.
The bottle fixture uses the `all` tag rather than assuming every Mac runs Tahoe.

The real Homebrew functional test passed on Intel macOS 15.8.1 in a disposable
prefix: compile C → bottle → local schema 1 server → temporary uninstall →
pool-only pour → brew test and execution. The disposable Cask passed download →
pool → uninstall → reinstall with the upstream archive hidden. The installed
executable's SHA-256 matched the original payload. The unsigned synthetic app is
not launched as a Gatekeeper test. Ruby, cache, logs, Cellar, and Applications are
isolated; no real user package is modified.

One pre-publication run encountered a loopback connection timeout in the legacy
compatibility fixture. That test subsequently passed five isolated repetitions,
and complete serial runs passed all 160 tests without relaxing any assertion.

## Distribution gates

The final build must come from a clean checkout on the authorized branch.
SourceManifest.json is signed with the bundle and binds its commit to Swift,
plist, icon, and Python inputs. Gates compare source bytes and expected files,
verify x86_64/build 35, and require Developer ID Team YWVVK7QZ6X, hardened runtime,
and a timestamp. DMG/ZIP apps are compared with the signed original; every source
ZIP file is compared with Git, and SHA256SUMS.txt is verified. Final distribution
also requires Accepted results, attached tickets, and Gatekeeper acceptance for
both app and DMG.

`app-notarization.json` and `dmg-notarization.json` must report Accepted. Their
matching Apple logs and actual app/DMG tickets must pass validation. The logs are
included in the released assets and checksum manifest. Credentials are used
through the notarytool Keychain profile without extraction or chat transmission.
An authorized app-specific password is entered directly into Apple's secure local
prompt; the existing Developer ID certificate is retained. A signature or valid
checksum alone is not proof of notarization.

All seven public documents and both How it works diagram formats are required in
the source ZIP and final asset set. Publication verifies downloaded assets before
updating `stable` and publishing a new release. The English documentation refresh
also rebuilds/notarizes locally, replaces the v0.3.5 source/tag/assets together,
and verifies public downloads against the local final set. No application behavior
changes are introduced by this language refresh.

Server code, protocol validation, and the job format (`server.py`, `common.py`,
`jobs.py`) are identical to stable fee50c4. New provenance fields are metadata
accepted by schema 1. Compatibility is tested against a real local server without
changing the NAS service.

Read-only inspection of a previously notarized backup confirmed Apple's ticket
format: `Contents/CodeResources` is a regular file separate from the code
signature, and stapler validation succeeds. The verifier accepts this one reserved
addition only with a valid ticket, after checking sources and signatures. Forged
tickets and symbolic links are rejected. Rebuilds preserve the previous local
product separately before copying the replacement, preventing stale tickets from
surviving ditto's merge behavior. Each new bundle needs its own Accepted result
and ticket.

## Limits and production state

No mutating Homebrew operation or Retry was run against the live queue. The
installed app, TrueNAS, configuration, token, and spool were not changed. No
GitHub Actions/CI or hosted builds were triggered; the repository has zero
workflows. Physical validation on a second Mac and new builds of the affected
formulae in the user's live installation have not been performed. Legacy variants
are not migrated. Kegs without complete evidence may require a verified rebuild.
