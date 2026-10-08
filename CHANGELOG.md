# Changelog

## 0.3.6 preview — October 8, 2026

- Add persistent Safe Pause / Resume at a current-formula safe boundary, separate Stop Now and active sleep prevention.
- Add existing bottle Scan / Review / Import, SHA-256/provenance/dependency/CPU validation, deduplication and atomic publication.
- Keep auto-import OFF by default; run it only after complete error-free Install/Upgrade when explicitly enabled.
- Add authentic-receipt, producer-proof capture using copied kegs, a genuine Homebrew sandbox and real isolated bottle/pour/test/linkage validation. No automatic publication or receipt patching.
- Add read-only Compatibility Options and separately approved Core 2 alternatives; refuse SSE4.2/AVX artifacts on Q9300.
- Preserve v0.3.5 commands, schema 1, dependency provenance, bounded recovery, Retry/Repair/Console and persistent queue.
- Restore the standard DMG Applications shortcut and legacy settings/state paths without automatic installation or data reset.
- Validate 201 local regression tests and 13 compiled-GUI workflow checks; publish exact reports and Apple receipts. Physical HP/MBP2012/Q9300 tests remain pending.
- Refresh the English homepage, green PNG/SVG diagram, installation/user/server guides, release notes and validation/parity reports.
- Publish locally built signed/notarized artifacts and full source only with separate authorization. No Actions, CI or remote builds. Keep preview status.

## 0.3.5 — October 8, 2026

- Identify dependencies by the `.brew` recipe in the installed keg; API changes do not invalidate unchanged installed kegs.
- Stop publication with a diagnostic when provenance is missing or relies on symbolic links.
- Keep new and legacy variants separate while preserving the schema 1 protocol.
- Select the declared platform dependency graph explicitly, avoiding implicit switches between old and new installed-keg graphs.
- Pin local recipes and tap HEAD throughout each build.
- Replan at most once per package; rebuild safely only when actual inputs change.
- Keep runtime/build/test evidence to avoid unnecessary recompilation on Retry, and validate runtime dependencies and linkage separately.
- Recheck local tap safety without repeated fetches.
- Add regression coverage for schema 1, Retry with six pending steps, provenance, and bounded recovery.
- Correct the bundle test for build 35 and block publication when embedded sources differ from the release source.
- Update the README introduction, How it works diagram in PNG/SVG, installation guide, Quick Start, release notes, validation report, and local release guide.
- Include the formula recipe in variant identity to prevent conflicts when the version rank is unchanged.
- Reuse the winner of a local-build publication conflict only after verifying identical proven inputs and downloaded bytes; preserve legacy spool entries separately.
- Run the application workflow fixture on macOS releases before Tahoe. Copy Ruby into the disposable Homebrew test prefix and verify the Cask payload without launching an unsigned synthetic app.
- Support an existing notarytool profile on an authorized SSH host without transferring credentials; verify the archive checksum before submission.
- Accept Apple's reserved ticket file only after validation, reject forged or linked tickets, and prevent stale tickets from surviving a local rebuild.
- Verify downloaded release assets before updating the default `stable` branch and making v0.3.5 public/latest.
- Publish all current documentation and release notes in English. Rebuild and notarize the documentation refresh so the signed source manifest, source archive, and release tag identify the same commit.

## 0.3.4 — October 8, 2026

- Fix Retry Failed for current installed formulae with the Homebrew-supported command `brew install --formula --build-bottle --force`, replacing the invalid `brew reinstall --build-bottle` combination.
- Move the current keg atomically to a backup on the same volume and restore it on failure. Remove the backup only after artifact validation.
- Skip recompilation when the receipt already records `built_as_bottle`.
- Retry the exact failed nested package instead of unnecessarily rebuilding its parent.
- Fix the Maintenance Console argument and propagate live stdout/stderr and the real exit code.
- Add regressions for current kegs, rollback, nested dependencies, ten pending steps, and controlled console commands.

## 0.3.3 — October 7, 2026

- Reconcile GUI state with the authoritative backend at cold launch, when opening the menu, and every ten seconds. A job with no failures or remaining steps unlocks Update & Upgrade, Install, and Sync even if the GUI cache still says Stopped.
- Bring runtime dependencies up to date before considering the dependent formula current or building/publishing it.
- Add `Repair / Install Dependency…`, including support for `openssl@3`, while preserving the queue; run `brew missing` and `brew linkage --test` after repair.
- Add `Repair Pool State…` to refresh the UI or explicitly discard the pending queue while preserving installations, bottles, configuration, token, and spool.
- Provide an always-available Maintenance Console with explicit command input, live stdout/stderr, session history, Stop Command, exit status, and doctor/outdated/missing/linkage shortcuts.
- Serialize commands that modify Homebrew with the job lock. Read-only diagnostics use a shared lock and do not overlap a writer.
- Close child-process stdin, never execute log text, require confirmation for destructive commands, and delegate administrator authentication to the native macOS dialog without collecting the password.
- Preserve schema 1 and all 0.3.2 features; add `tests/test_v033.py` for stale UI, dependency ordering, locking, and console security.

## 0.3.2 — October 7, 2026

- Add the complete `INSTALLATION.md` guide for the server, HTTPS/VPN, storage, token, and configuration/verification of every Mac.
- Credit StefanAlMare and collaboration with ChatGPT by OpenAI explicitly.
- Replace the permissive MIT license with a source-available license: official unmodified releases may be downloaded and used free of charge; source reuse, modification, or redistribution requires StefanAlMare's prior written permission.
- Use template menu-bar icons with native contrast and distinct symbols for Healthy, animated Busy, Action Required, Paused — Error, and Paused/Stopped.
- Save the queue atomically. Stop at the first error; Retry runs only failed steps, Resume continues the remaining steps, and errors remain visible until resolved.
- Keep Stop and Quit available during work. Send SIGINT, then SIGTERM after eight seconds, and SIGKILL only after another four seconds. Track children that create separate sessions, with a separate GUI fallback if the worker does not respond.
- Run preflight before updates: repair official legacy remotes, missing upstream/refspec settings, and the brew launcher using fetch --prune and merge --ff-only. Preserve local commits, private mirrors, and external tap URLs; reject dirty, detached, or divergent checkouts.
- Avoid cloning core/cask in API mode. Create a core checkout only when bottling requires one.
- Support calendar-style versions and separate stderr. Accept only valid formula-name lines from dependency output so Homebrew messages cannot become command arguments.
- Revalidate an installed dependency on Retry when its test previously failed.
- Add fixture repositories, child-process tests, an isolated Intel Homebrew pilot, and a GUI pilot.

## 0.3.1 — October 7, 2026

- Preserve `root_url` for bottles generated from external taps.
- Normalize the GUI process PATH for the Intel Homebrew prefix.
- Add persistent Action Required state, a single notification, and Review Action.
- Keep ordinary operations automatic with `HOMEBREW_NO_ASK=1`.
- Distinguish Healthy, Busy, Action Required, and Error visually.

## 0.3.0 — October 7, 2026

- Rename the main action to `Update & Upgrade`.
- Add `Install…` and the pool-aware `install` command with Auto/Formula/Cask selection and rejection of ambiguous names.
- Add native Setup/Settings for URL, pasted token or token file, CA, Test Connection, and atomic saving after successful authentication/API validation.
- Preserve existing adapters/configuration and copy the token to a private 0600 file. Connection tests use temporary state.
- Publish and reuse official bottles, tested local bottles, and verified Cask downloads. Mutable Casks have an explicit upstream-only option and are not published.
- Preserve safe tap synchronization from v0.2.1 and revalidate dirty/detached/divergent state before bottling, even after an earlier synchronization.
- Preserve Start at Login, Healthy/Connected, spool, and logs; do not introduce automatic upgrades.
- Prevent Python bytecode writes inside the sealed bundle.
- Distribute an Intel x86_64 app and Developer ID DMG with Apple notarization and attached tickets.
- Validate real Formula and Cask installations in a disposable Homebrew prefix without modifying packages in the current installation.

## 0.2.0 — October 7, 2026

- Add the native Intel macOS `Homebrew Pool.app` with a status item and the v0.1 client embedded.
- Expose Healthy/Connected, Offline/Spooling, Busy/Building or Syncing, and Error states.
- Add explicit Sync now, Upgrade via Pool, Open logs, Open config, Start at Login, and Quit commands.
- Start at login through a user-local LaunchAgent without a privileged daemon.
- Add a user-local installer/uninstaller; uninstall preserves configuration, spool, and logs by default.
- Add JSON agent status without changing the protocol or v0.1 backend logic.
- Add an Intel `.app`, ZIP archive, and DMG image with ad-hoc signing for private distribution.

There are no automatic Homebrew updates, GitHub workflows, or hosted builds.
