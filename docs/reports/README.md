# Local validation evidence

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
