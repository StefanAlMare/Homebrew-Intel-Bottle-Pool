# Local release procedure — 0.3.5

All development, documentation, diagrams, tests, compilation, signing, and
notarization are driven from the local Intel Mac. An authorized existing Mac
may submit archives to Apple through its own existing Keychain profile. GitHub
receives only the final verified sources and artifacts. Use `fix/provenance-v0.3.5` for preparation;
publication updates `stable`. Never use `main`, GitHub Actions, or hosted builds.

## 1. Finish the complete product locally

Review the backend, persistent schema-1 queue, Retry/Resume boundaries, automatic
recovery limits, legacy variant separation, and build evidence. Update README,
INSTALLATION, QUICKSTART, RELEASE_NOTES, CHANGELOG, VALIDATION, this guide, and the
PNG/SVG How it works diagram. Inspect the rendered diagram and verify local links.

Run the complete test suite, including regression and release-gate tests. Commit
the reviewed result locally on the authorized branch. A local commit is needed to
bind the signed app and source archive to one exact source revision. Do not push.

## 2. Build and sign on Intel macOS

`build-macos.sh` compiles the Swift application for x86_64 with deployment target
macOS 12, embeds the Python client, and records SourceManifest.json before signing.
For a final build, set SIGNING_IDENTITY to the existing Developer ID Application
identity for Team YWVVK7QZ6X. A build without that identity is development-only.

The source gate requires a clean local checkout, version 0.3.5/build 35, matching
embedded source bytes, expected bundle files, x86_64, hardened runtime, Developer ID,
and timestamp. Rebuild/re-sign after any new local source commit; do not patch a
signed bundle or reuse a source archive from another commit.

## 3. Notarize and staple locally

Use `notarize-macos.sh` with the existing SIGNING_IDENTITY and NOTARY_PROFILE.
NOTARY_PROFILE is the name of a notarytool profile already configured on the Mac;
no Apple account password is read from files, requested, or extracted from Keychain.
If that profile exists on an authorized Mac instead, set NOTARY_HOST to its
known SSH host. Existing SSH authentication and
strict known-host checking are required. The helper transfers only the signed
archive, verifies its SHA-256 remotely, and returns the Apple receipt/log; no
credentials are copied. If SSH/profile access is unavailable, stop before
publication and restore access to that existing Mac. Do not create new credentials.
ZIP files submitted for an older release do not contain reusable
notarization credentials or tickets for a changed application.

The script submits the exact new app, requires Accepted, staples and validates it,
then rebuilds the DMG containing the stapled app. It signs and submits the DMG,
requires Accepted again, staples it, and checks Gatekeeper. Receipt and log files
for both submissions are retained as release evidence.

## 4. Assemble and verify every final asset

`package_release.py` packages the stapled app ZIP, archives the exact committed
source, and copies all seven public documents plus both diagram formats. It
creates SHA256SUMS.txt covering every required asset and notarization evidence.
Only a fixed public asset list is used; private configuration, state, tokens,
HANDOVER files, and local logs are excluded.

`verify_distribution.py` checks the full checksum coverage, document/diagram bytes,
app source identity, signatures, Accepted receipts, staples, and Gatekeeper. It
extracts the app ZIP, mounts the DMG read-only, compares both apps with the signed
original, verifies the DMG Read Me/license/Applications shortcut, and compares every
source ZIP file with Git. Apple's reserved Contents/CodeResources ticket file
is allowed only after real stapler validation; arbitrary extra files remain
forbidden. Each new build preserves the previous local bundle separately before
copying its replacement, preventing stale tickets from a merged destination.
`--staging-only` skips notarization gates for local
inspection; it never authorizes publication.

## 5. Publish the final product once

Run `publish-release.sh` only after all previous local stages pass. It repeats the
local product gates and complete tests before its first GitHub request. It then:

1. checks that the default branch is stable and the repository has zero workflows;
2. verifies that stable can advance to the reviewed final commit without force;
3. refuses an existing public release or a v0.3.5 tag for another commit;
4. uploads the final source/tag and final assets into a draft release;
5. downloads every draft asset and verifies its checksum against the local set;
6. advances stable to the final commit so the first page and diagram are updated;
7. makes v0.3.5 public and latest, then reads back its release metadata.

The draft is a verification step for already completed products, not a development
workspace. A failed download check leaves it unpublished. Resume an interrupted
draft only with the same reviewed commit; never force a tag or overwrite an
existing public release. No remote writes occur when any local release gate fails.

## Required assets

- Homebrew-Intel-Bottle-Pool-v0.3.5.dmg
- Homebrew-Intel-Bottle-Pool-v0.3.5.zip
- Homebrew-Intel-Bottle-Pool-v0.3.5-source.zip
- SHA256SUMS.txt
- README.md, INSTALLATION.md, QUICKSTART.txt, RELEASE_NOTES.md
- VALIDATION.md, CHANGELOG.md, RELEASING.md
- how-it-works.png, how-it-works.svg
- app-notarization.json, dmg-notarization.json
- app-notarization-log.json, dmg-notarization-log.json

A successful source push, local signature, or checksum check alone does not mean
that v0.3.5 is released. Completion requires all final gates plus confirmation of
the public release and the exact default-branch commit. Keep actual local status
and blockers in the ignored build directory until final publication.
