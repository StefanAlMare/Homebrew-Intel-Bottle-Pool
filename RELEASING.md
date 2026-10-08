# Local release workflow

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

Confirm repository/default branch/current head; use **stable**, not main. Check zero workflows, preserve unrelated files, use expected-parent non-force update, add no workflows. Tag v0.3.6, upload locally built DMG/app ZIP/complete source ZIP/checksums/validation, and verify downloaded assets before publishing.

Keep v0.3.6 a prerelease pending physical HP/MBP2012/Q9300 acceptance. Apple notarization is not functionality/CPU approval. Legacy publish/package helpers intentionally do not automatically publish; credentials alone are not authorization. No production deployment.
