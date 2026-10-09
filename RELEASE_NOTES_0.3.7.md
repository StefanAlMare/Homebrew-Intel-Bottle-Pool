# Homebrew Intel Bottle Pool v0.3.7 — Hotfix 1 (build 38)

**Publication status:** locally delivered October 9, 2026; the public GitHub release assets are **not yet verified as published**. Do not describe this as a downloadable release until authentic signed/notarized artifacts, matching source and checksums have been uploaded and checked. This is a version history document, not a downloadable binary.

## Included changes

- **Core2 Legacy private channel:** dedicated GUI panel, separate schema-2 policy and `/v2/core2-legacy` protocol, individual machine credentials, explicit role-based enrollment, reviewed CPU/ISA constraints, approved manifest identities, verified transfer and dedicated build workflow. It does not activate itself, enroll machines, import existing kegs, or bypass authorization.
- **Hotfix 1 authorization:** per-action confirmation is forwarded from the Swift UI to the CLI for Update & Upgrade, Install, Retry/Resume and Maintenance. Automatic status checking does not receive repository authorization; authorizations are not persisted.
- **GUI handling:** clearer diagnostic messages after a refused operation; Core2 Legacy menu placement immediately above Quit.
- **Preservation:** no automatic changes to existing Homebrew installations, queues, global Pool token, server storage, EFI/OpenCore or protected Core2 formulae.

## Validation and limitations

The local handover reports 87 automated tests and a compiled-app GUI smoke test (healthy status, Cancel, confirmation forwarding, later error display and menu placement). The handover reports Developer ID signing, Apple notarization/stapling and Gatekeeper acceptance; **the original artifacts and receipts must be independently checked before publication**. Those checks do not certify a real Homebrew upgrade or real Core2 bottle execution.

The private Core2 channel ships disabled and without machines or approved artifacts. The new private server requires separate deployment, TLS, machine enrollment and administrative review. No automatic global fallback; Auto-import remains OFF.

## Known issues reserved for the next client release

- Long Homebrew error output can obscure the dialog's close controls.
- Enabling Start at Login while the app is already running can launch an extra instance.
- A failed `cargo-c` publication revealed inconsistent Homebrew installed/current dependency-graph comparisons; repair must generalize across all formulas, not special-case cargo-c.
- Fast batch catalog discovery, automatic end-of-job reconciliation and broader concurrency/performance integration remain separate v0.3.8 work. A newer global server pilot exists independently and is not bundled in this v0.3.7 release.

## Installation and upgrade

Finish managed work, wait for Safely Paused if applicable, Quit and replace the app using the verified DMG. Preserve all existing configuration, token/CA references, queue, spool and runtime state. Keep the previous app for rollback. Never discard a saved job to force an upgrade.

## Rights and acknowledgments

This software is **source-available, not open source**. The accompanying [LICENSE 1.1](LICENSE) permits personal non-commercial use of the official unmodified software. Commercial/professional use, code reuse, modification, integration, redistribution or derivatives require **prior explicit written permission** from StefanAlMare; GitHub public viewing/forking rights, third-party licenses and historically granted rights remain unaffected. These conditions concern the project, not just this release.

Created and maintained by **StefanAlMare**; developed with **ChatGPT by OpenAI**. Independent of Homebrew and not endorsed by it.
