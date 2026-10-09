# Homebrew Intel Bottle Pool v0.3.6 — preview

**Current download:** [Complete v0.3.6 License 1.1 macOS app (DMG)](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/download/v0.3.6-license.1/Homebrew-Intel-Bottle-Pool-v0.3.6-license.1-standard.dmg) · [ZIP](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/download/v0.3.6-license.1/Homebrew-Intel-Bottle-Pool-v0.3.6-license.1-standard.zip) · [SHA256SUMS](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/download/v0.3.6-license.1/SHA256SUMS.txt) · [All release assets](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/tag/v0.3.6-license.1). The License 1.1 edition includes the full app; it is not a license-only package. This preview does not replace v0.3.5 as GitHub's latest stable release until acceptance tests are complete.

## License revision 1 — IMPORTANT

**Copyright © 2026 StefanAlMare. All rights reserved. Source-available, NOT open source.**
Personal, non-commercial use of the official unmodified app/server is permitted.
**Commercial/business use and any source reuse, modification, integration into
other projects, redistribution or derivative work require StefanAlMare's PRIOR
EXPLICIT WRITTEN PERMISSION.** Attribution or a fork is not consent.
See [LICENSE 1.1](LICENSE). Third-party packages retain their own licenses.

This license-revision edition keeps the same v0.3.6 runtime binary. It makes the
permission notice prominent and removes the earlier broad business-use grant
for newly licensed copies. Historical tags/licenses are not rewritten, and valid
prior grants are not retroactively revoked. Download the license-revision
edition linked from the current homepage, not a historical source snapshot.

Standard upgrade package, locally built for Intel macOS, Developer ID signed and Apple notarized. Published as a **prerelease** pending physical HP/MacBook Pro 2012/Core 2 Quad Q9300 tests.

## New features

- **Pause Safely / Resume:** immediate persistent request, current-formula safe boundary, atomic checkpoint, restart revalidation; Safely Paused only after save.
- **Stop Now:** separate controlled process-tree cancellation; no compiler-internal resume promise.
- **Sleep prevention** during active managed work.
- **Scan / Review / Import Existing Bottles:** real archive, SHA-256, metadata, dependency/provenance/prefix/CPU checks; deduplication, conflict refusal, durable staging and atomic publication.
- **Auto-import verified bottles:** OFF by default; extra scan/import only after a complete error-free Install/Upgrade.
- **Capture Installed Formula:** authentic receipt plus reviewed producer proof; copied keg, genuine sandbox, isolated bottle/pour/test/linkage; no receipt edits or automatic publication.
- **Compatibility Options:** read-only versioned-formula/support warnings and separately approved Core 2 solutions; no silent downgrade or Git branch switch.
- **Standard DMG:** Applications shortcut, original identity and settings/state paths; preserves config, token, queue and spool.

## Preserved

v0.3.5 installed-recipe provenance, pinned build inputs, bounded recovery, nested failure attribution, Retry/Resume, Repair and real-execution Maintenance Console. Schema 1 remains compatible; no server reset needed.

## Install

Verify the DMG digest in SHA256SUMS. Finish work and Quit before copying; v0.3.6 can Pause Safely first. Drag the app onto Applications; launch from Applications; review and explicitly Resume/Retry. Keep the old binary. **Do not delete job.json**. No automatic installation or production changes.

## Automatic uploads

App-managed Install/Upgrade already publishes validated output; offline output stays in spool. Existing external bottles need Scan/Review/Import or opt-in auto-import. A source-built keg alone is not a bottle. Capture creates a candidate only.

## Documentation and evidence

The English homepage retains the green architecture diagram and adds clear starting paths, user guide and server/TrueNAS setup guide. Read [VALIDATION.md](VALIDATION.md), [PARITY_REPORT.md](PARITY_REPORT.md) and [IMPORT_PROVENANCE.md](IMPORT_PROVENANCE.md).

All build/test/signing/notarization work is local. GitHub receives separately authorized source/documentation and assets only. No Actions, CI or hosted builds.

Created by StefanAlMare, developed with ChatGPT by OpenAI. Independent of Homebrew; [source-available license](LICENSE).
