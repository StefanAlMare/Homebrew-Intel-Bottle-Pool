# Validation — v0.3.7 distribution checks and historical v0.3.6 evidence

**Current release (v0.3.7 Hotfix 1, build 38):** the original DMG SHA-256, version/build identity, Developer ID signature, Gatekeeper acceptance and stapled notarization were verified locally on October 9, 2026. All seven GitHub release assets were downloaded and checked against the distributed SHA256SUMS. The local handover reports **87 automated checks** plus one compiled GUI dispatch smoke test; those results have not been independently rerun during publication. Real Homebrew Update & Upgrade and native Core2 bottle execution remain unverified. See [the official v0.3.7 release](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/tag/v0.3.7), [the attached build 38 verification archive](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/tag/v0.3.7/) and [the release checklist](RELEASE_CHECKLIST_0.3.7.md). **The detailed results below are specific to the earlier v0.3.6 package and must not be attributed to v0.3.7.**

## Historical v0.3.6 distribution verification

This edition changes license/documentation and distribution packaging only.
The v0.3.6 application binary is unchanged; the 201-test/13-GUI results below
are the completed functional checks of that same runtime, not a claim that the
entire suite was rerun for a legal-text edit. Revised license copies, archive
contents, exact runtime source identity, signatures, DMG notarization and final
downloaded hashes must be verified again before publishing the new edition.

October 8, 2026. Local isolated fixtures only unless explicitly identified. No production TrueNAS, token, queue, spool or installed app changes.

## Executed

- Full standard-package regression suite: **201 passed**, no skips in the completed run. Exact latest report accompanies the release.
- Compiled GUI workflow: **13 passed**, including current-formula Safe Pause, saved restart/Resume, Stop/child cleanup, retry-only failures, remaining queue, sticky errors, stale UI reconciliation, isolated config and sleep prevention.
- Standard upgrade fixtures preserve config/token/custom state/queue with **10 remaining operations** and spool byte-for-byte. Auto-import OFF/ON/completed-job gating verified.
- Local Intel x86_64 build, macOS 12 minimum, timestamped hardened-runtime Developer ID signature. SourceManifest binds embedded resources/runtime to exact local source hashes.
- Apple accepted app/DMG; staple validation and Gatekeeper passed. Current receipts/hashes accompany the release.
- Distribution checks: original and extracted ZIP/DMG app signatures/tickets/certificate/architecture, source equality, bundle hygiene, Applications -> /Applications and embedded Read Me matching QUICKSTART.
- Official v0.3.5 audit against commit 5158c90fb92db54cb0d765a02e0ef3ec56ed0da3; see PARITY_REPORT.

Coverage includes pause during simulated build, completion before pause, restart without unnecessary rebuild, interrupted publication, valid import/deduplication, incompatible provenance/CPU rejection, nested failures and controlled Maintenance Console commands with real exit codes.

## Earlier isolated v0.3.6 pilots

A real local Homebrew capture pilot used a small C fixture: external source install, copied-keg bottle creation, isolated pour/test/linkage, original-keg preservation. Sandbox probes denied network/outside writes. No automatic publication.

Read-only local Node 26.11.0 inspection classified it as a source installation without a confirmed bottle, not a verified bottle. No real Node capture/rebuild was performed.

These are earlier isolated-edition pilots, not physical fleet tests or a new standard-edition real-Homebrew pilot. Standard packaging changes identity/paths, not capture/build/import/CPU backend.

## Not established

- Physical HP, MacBook Pro 2012 or Q9300 execution.
- Node 26.11.0 capture/rebuild or Q9300 compatibility.
- Universal binary instruction auditing: trusted producer proof is attestation.
- Production server deployment/import or live fleet upgrade.

Q9300 lacks SSE4.2/AVX. Required-feature refusal occurs before fetch/pour. No automatic downgrade or receipt patch.

## Distribution refresh

English documentation changes do not alter the signed application binary. Changed DMG documentation requires a locally recreated/signed/notarized/stapled DMG. The unchanged app retains its valid ticket; current receipts are published.

Public source excludes private config/token/job/spool, build scratch space, upstream binary backups and local working logs. Publication is separately authorized; no Actions/CI/remote builds. Physical acceptance testing remains outstanding. Classification as a regular release does not imply that these tests were completed.
