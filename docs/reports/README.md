# Local validation evidence

**Scope note:** these evidence files accompany the published v0.3.6 distribution. The separately built v0.3.7 Hotfix 1, build 38, requires its own locally verified receipts, source parity, test reports and notarization assets before GitHub release publication. See [v0.3.7 checklist](../../RELEASE_CHECKLIST_0.3.7.md). Do not present the v0.3.6 receipts as proof for build 38.

[Home](../../README.md) · [Scope and limitations](../../VALIDATION.md)

- [Regression summary](tests.json): exact count, duration and exit status.
- [Compiled GUI workflow](workflow-smoke.json): thirteen isolated checks.
- [Official v0.3.5 source parity](parity.json): verified archive/commit comparison.
- [Distribution verification](release-verification.json): app, ZIP, DMG and embedded sources.
- [Application notarization](app-notarization.json) and [Apple log](app-notarization-log.json).
- [Refreshed DMG notarization](dmg-notarization.json) and [Apple log](dmg-notarization-log.json).

These are local results, not GitHub Actions or physical fleet tests. The first
publication-time regression attempt was denied fixture loopback ports by the
sandbox; the completed rerun used permission for isolated local services and
processes only. macOS signature verification likewise required normal system
access; it passed when that access was available.

The application binary is unchanged by the English documentation refresh and
keeps its valid existing Apple ticket. The changed DMG was newly signed,
notarized and stapled. No production configuration, token, queue, spool or server
was used. Operator working logs and upstream binary backups are excluded.
