# Publication checklist — v0.3.7 Hotfix 1, build 38

**Release published after source, signature and downloaded-asset verification.** Never mark the release as published until real artifacts have been verified and attached to the correct GitHub release.

1. Locate the original iMac local delivery `Homebrew-Pool-0.3.7-Hotfix1-DMG/` and inspect `Homebrew-Pool-0.3.7-hotfix1.dmg`, `Source/`, `Verification/`, `Read Me.txt`, `Core2 Legacy Guide.txt` and `SHA256SUMS.txt`.
2. Verify the DMG SHA-256 and embedded application: version **0.3.7**, `CFBundleVersion=38`, Developer ID Application signature and actual notarization/stapling/Gatekeeper evidence. Inspect SourceManifest and source/runtime identity. Do not substitute earlier build 37 or v0.3.6 assets.
3. Validate the complete source archive is from build 38, includes `legacy.py`, `legacy_cli.py`, `legacy_policy.py`, `legacy_build.py`, Swift UI and tests, and excludes tokens, host-specific config, private state and third-party copyrighted binaries not licensed for redistribution.
4. Cross-check local test reports. The handover reports **87 automated tests** plus one compiled GUI smoke test, not a real Homebrew upgrade or tested Core2 native bottle. Do not claim broader validation.
5. Confirm project-wide [LICENSE](LICENSE) in the distributed files matches the intended non-commercial source-available permissions, preserves GitHub platform rights, third-party licensing and earlier valid grants. Do not rewrite historical release tags or binaries.
6. Publish on the authorized **`stable`** default branch, not `main`. Publish the genuine signed DMG, app ZIP if actually built/verified, source ZIP, checksums, guide and appropriate validation receipts to the GitHub `v0.3.7` release. **Never invent a link or relabel a v0.3.6 binary.**
7. Verify every published download URL, checksum, asset size and GitHub Latest status before changing the homepage's latest-version link from 0.3.6 to 0.3.7. Do not erase v0.3.6 or v0.3.5; no GitHub Actions/CI.
8. Once release assets are independently verified, update [README.md](README.md), [INSTALLATION.md](INSTALLATION.md), [QUICKSTART.txt](QUICKSTART.txt), [RELEASE_NOTES.md](RELEASE_NOTES.md) and [CHANGELOG.md](CHANGELOG.md) to describe v0.3.7 as **published**, with correct paths. The next planned client v0.3.8 must remain distinctly unpublished.

All builds, signing and notarization must occur on the authorized local machine, not GitHub. If a required artifact or proof is missing, stop publication instead of creating a misleading release.
