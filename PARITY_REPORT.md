# v0.3.5 parity — v0.3.6 standard release

Base: complete official v0.3.5 at commit 5158c90fb92db54cb0d765a02e0ef3ec56ed0da3. The local audit compared 61 official files with the verified source archive/commit snapshot.

## Findings

Published v0.3.5 Swift was byte-identical to v0.3.4; no unique v0.3.5 Swift callbacks were lost. Backend, CLI, tests and release tooling were audited separately. Missing v0.3.5 tests/tooling and source-bundle/stale-ticket gates were restored during integration.

## Retained

Commands/schema 1/settings/adapters; persistent queue/errors/Retry/Resume/Repair/Console; safe current-keg build-bottle recovery; nested failure attribution; installed-recipe provenance; pinned input graph; bounded replan; durable spool/lease fencing/atomic publication/conflict checks; child cancellation/locking/destructive-command confirmation.

## Additions

Safe Pause, verified imports, sandboxed capture and CPU-aware alternatives extend the audited base. Standard packaging restores normal bundle/agent identity, legacy/XDG configuration, existing custom state_dir, UI/log paths, CLI prefix and Applications shortcut. Explicit fixture isolation remains; separate .test settings are not migrated. Destructive uninstall helper remains disabled.

The signed receipt records local-sha256 source identity, not a fabricated build-time Git commit. The published tag includes English documentation; SourceManifest verifies unchanged runtime bytes.

No production state reset, package installation, TrueNAS change or automatic app replacement. See [VALIDATION.md](VALIDATION.md).
