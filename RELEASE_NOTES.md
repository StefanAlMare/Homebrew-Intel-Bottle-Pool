# Homebrew Intel Bottle Pool v0.3.6 — preview

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
