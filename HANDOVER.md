# v0.3.6 standard preview — handover

Finish current work before replacing an older app. In v0.3.6: Pause Safely, wait for Safely Paused, Quit. Open the standard DMG, drag Homebrew Pool.app onto Applications, choose Replace only when ready. Keep the previous binary.

Launch from Applications. Existing legacy/XDG config, token/CA references, custom state_dir, queue and spool are reused. Do not delete job.json. Review and explicitly Resume/Retry. Separate .test settings are not migrated; do not run both editions on one Homebrew concurrently.

Install / Update & Upgrade publish validated artifacts. Offline output stays in spool for Sync now. Existing external bottles use Scan/Review/Import. Auto-import is OFF by default; ON adds import only after a complete error-free workflow. Capture requires authentic receipt/reviewed proof and creates a candidate, not an automatic upload.

Q9300 lacks SSE4.2/AVX. Incompatible artifacts are refused. Compatibility Options suggests reviewed versioned formulae or separately approved builds, never an automatic downgrade/branch switch or guaranteed unsupported compilation.

Existing schema 1 servers need no reset or TrueNAS changes. Read SERVER_SETUP for new deployments, USER_GUIDE for controls, IMPORT_PROVENANCE for evidence and VALIDATION for exact results. Physical HP/MBP2012/Q9300 tests are pending; this is a preview.

Local build/signing/notarization only. Authorized GitHub upload includes source/English docs/assets; no Actions/CI/remote builds. No automatic production installation.
