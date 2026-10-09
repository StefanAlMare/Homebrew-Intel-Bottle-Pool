# v0.3.6 standard release — historical handover

**Latest local delivery:** v0.3.7 Hotfix 1, build 38; officially published on GitHub October 9, 2026. Read [v0.3.7 notes](RELEASE_NOTES_0.3.7.md), [Core2 guide](CORE2_LEGACY.md), [publication checklist](RELEASE_CHECKLIST_0.3.7.md) and [server-next status](SERVER_NEXT.md). The material below applies specifically to the historical published v0.3.6 application; do not confuse its tests or embedded sources with build 38.

Finish current work before replacing an older app. In v0.3.6: Pause Safely, wait for Safely Paused, Quit. Open the standard DMG, drag Homebrew Pool.app onto Applications, choose Replace only when ready. Keep the previous binary.

Launch from Applications. Existing legacy/XDG config, token/CA references, custom state_dir, queue and spool are reused. Do not delete job.json. Review and explicitly Resume/Retry. Separate .test settings are not migrated; do not run both editions on one Homebrew concurrently.

Install / Update & Upgrade publish validated artifacts. Offline output stays in spool for Sync now. Existing external bottles use Scan/Review/Import. Auto-import is OFF by default; ON adds import only after a complete error-free workflow. Capture requires authentic receipt/reviewed proof and creates a candidate, not an automatic upload.

Q9300 lacks SSE4.2/AVX. Incompatible artifacts are refused. Compatibility Options suggests reviewed versioned formulae or separately approved builds, never an automatic downgrade/branch switch or guaranteed unsupported compilation.

Existing schema 1 servers need no reset or TrueNAS changes. Read SERVER_SETUP for new deployments, USER_GUIDE for controls, IMPORT_PROVENANCE for evidence and VALIDATION for exact results. Physical HP/MBP2012/Q9300 acceptance tests remain pending; regular release status does not mean those tests passed.

Local build/signing/notarization only. Authorized GitHub upload includes source/English docs/assets; no Actions/CI/remote builds. No automatic production installation.

## Security and project-wide software permissions

The [LICENSE](LICENSE) applies to all original Homebrew Intel Bottle Pool software distributed under it: the app, server, CLI, source, scripts, tests and guides. It is not limited to a particular release. Under the current license, personal non-commercial use of official unmodified software is permitted; commercial or professional use, source-code reuse, modification, integration, redistribution and derivatives require prior explicit written permission from StefanAlMare. GitHub viewing and forking permissions under its Terms of Service, third-party licenses and valid historical grants are preserved. Protect authentication tokens, certificates and private deployment data.
