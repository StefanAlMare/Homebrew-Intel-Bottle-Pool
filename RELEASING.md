# Local release workflow

The permission correction is published as v0.3.6-license.1, with the same
runtime and LICENSE 1.1 inside the refreshed DMG, source and app ZIP packaging.
Never move/rewrite the historical v0.3.6 tag or claim retroactive revocation.

For **v0.3.7 Hotfix 1, build 38**, use the original local deliverable, source and verification reports. Do not relabel a v0.3.6 binary, substitute source from the default branch, or claim successful notarization without checking the actual distribution. See [release checklist](RELEASE_CHECKLIST_0.3.7.md). The existing v0.3.6 release and historical tags remain unchanged.

Builds/tests/signing/notarization run on the authorized local Intel Mac. No GitHub Actions, CI, hosted runners or remote builds. Publication requires separate explicit authorization.

## Local gates

1. Verify complete source; preserve installed app and production data.
2. Build with build-macos.sh --app-only and the existing SIGNING_IDENTITY. No sudo.
3. Run validate_tests.py and workflow_smoke.py with disposable fixtures.
4. Run notarize-macos.sh using existing Developer ID and NOTARY_PROFILE. Require Accepted, staple and Gatekeeper.
5. Run verify_release.py: app/ZIP/DMG signature, ticket, exact sources and layout.
6. Package source/docs excluding private state/secrets, build scratch, upstream binaries and working logs. Generate final SHA256SUMS and verify.
7. Confirm runtime hashes in SourceManifest match published source.

Changed binaries need new signing/notarization, never stale tickets. Documentation-only DMG changes need a new DMG ticket; an unchanged app retains its valid ticket. Receipt uses local-sha256 identity, not a fabricated Git commit.

## Authorized publication

Confirm repository/default branch/current head; use **stable**, not main. Check zero workflows, preserve unrelated files, use expected-parent non-force update, add no workflows. For the next separately authorized release, create a new version tag; never move or reuse the existing v0.3.6 tags. Upload locally built DMG/app ZIP/complete source ZIP/checksums/validation, and verify downloaded assets before publishing.

v0.3.6 is a regular release; physical HP/MBP2012/Q9300 acceptance remains outstanding and must not be reported as completed. Apple notarization is not functionality/CPU approval. Legacy publish/package helpers intentionally do not automatically publish; credentials alone are not authorization. No production deployment.

## Security and project-wide software permissions

The [LICENSE](LICENSE) applies to all original Homebrew Intel Bottle Pool software distributed under it: the app, server, CLI, source, scripts, tests and guides. It is not limited to a particular release. Under the current license, personal non-commercial use of official unmodified software is permitted; commercial or professional use, source-code reuse, modification, integration, redistribution and derivatives require prior explicit written permission from StefanAlMare. GitHub viewing and forking permissions under its Terms of Service, third-party licenses and valid historical grants are preserved. Protect authentication tokens, certificates and private deployment data.
