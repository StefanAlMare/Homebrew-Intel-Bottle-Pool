# User guide — v0.3.6

[Home](README.md) · [Installation](INSTALLATION.md) · [Server](SERVER_SETUP.md) · [Import evidence](IMPORT_PROVENANCE.md)

## Core2 Legacy in the local v0.3.7 Hotfix 1 (build 38)

Core2 Legacy is a separate, opt-in private channel accessible from the **Core2 Legacy…** menu, after Maintenance Console. **Review status**, **Review hardware**, and **Create disabled setup** do not enroll a machine or publish a bottle. Use **Load approved setup…** only with a separately approved private configuration. Verify, Publish, Download and Build Plan are explicit actions with independent authorization; no global-pool fallback is permitted. See [Core2 Legacy guide](CORE2_LEGACY.md).

The v0.3.7 Hotfix 1 DMG is a local deliverable pending official publication; the public v0.3.6 guide remains valid for the latest downloadable release. Known UI/dependency bugs affecting the local v0.3.7 build are tracked for the next client version. Do not run a paused failed Homebrew batch merely to test the server.

## First session

Open the standard app from Applications. Complete Setup only if no existing config is found: private HTTPS URL, token/token file, CA only when needed, Test Connection, then Save & Finish.

Start with a small appropriate formula using **Install…**. Auto detects Formula/Cask; choose an explicit type for ambiguous names. **Update & Upgrade** starts a requested Homebrew workflow. Both can download, install or compile packages. Start at Login starts the agent, not upgrades.

Managed active work prevents automatic sleep. Manual sleep, closing a lid, shutdown and power loss are not safe-pause requests.

## Pause, stop, resume

| Control / status | Meaning | Next step |
| --- | --- | --- |
| Pause Safely | Persist a request; no next formula after the current safe boundary. | Leave the worker running. |
| Pause requested — finishing current formula | Build/bottle/test/publication checkpoint is not finished. | Wait. |
| Safely Paused | Persistent checkpoint saved, queue/publication state retained. | You may Quit; later open and Resume. |
| Resume… | Recheck installed/completed work and confirmed publications. | Review the queue first. |
| Stop Now | Controlled worker/child termination; queue retained. | Interrupted formula may need rebuilding. |
| Retry Failed… | Retry failures only, retaining remaining steps. | Read Review Errors first. |

Safe pause is a formula boundary, not a snapshot of a compiler. Stop Now cannot resume inside `make`. Failed/stopped work is not falsely marked completed.

After crash/restart, review the authoritative queue. Completed work is revalidated; interrupted publication is reconciled with the durable spool and server manifest. **Never delete job.json or spool entries just to resume.**

## Scan, review and import

1. **Scan Existing Bottles** examines cache archives and installed formulae. It is not an upload.
2. **Review Imports…** explains each candidate.
3. **Import to Pool…** stages/publishes selected verified candidates.
4. If offline, use **Sync now** later.

| Classification | Meaning |
| --- | --- |
| Verified / importable | Archive, required identity, checksum, dependency and compatibility evidence match. |
| Already present | Identical verified pool artifact; no duplicate upload. |
| Local source installation without a confirmed bottle | A keg alone is not an archive or portability evidence. |
| Incompatible | CPU, OS, prefix, dependency or another required context fails. |
| Needs verification | Missing/unproven evidence; keep at review. |

Detailed reports may use machine-readable equivalents. Same-rank different bytes/context are rejected, not overwritten.

Normal Install/Upgrade already publish validated results. **Auto-import verified bottles** is separate, **OFF by default**. ON adds scan/import after fully completed work with zero errors/remaining steps. Direct Homebrew operations outside the app are not watched/uploaded automatically. Source-installed Node 26.11.0 alone is not a verified bottle.

## Capture Installed Formula

**Inspect Only** reads authentic receipt, embedded recipe, keg/dependency hashes and context without mutation.

**Capture with Producer Proof** requires authentic `built_as_bottle` plus reviewed evidence. The app copies the keg/dependencies into a disposable prefix; Homebrew's genuine sandbox denies network/outside writes. It bottles the copy, then performs real isolated pour/test/linkage. Original hashes/context are rechecked. Non-relocatable output, missing sandbox or incomplete evidence fails closed.

Success creates a candidate, **not a publication**. Review Imports afterwards. See [proof fields](IMPORT_PROVENANCE.md); never fabricate them.

## CPU refusal and solutions

**Compatibility Options…** shows constraints, versioned formula candidates with support/disabled/deprecated warnings, separately approved Core 2 builds or legacy patches requiring review.

Q9300 lacks SSE4.2/AVX. Intel/x86_64 does not prove compatibility. A different software version is an option only if it supports the Mac and meets your needs. No automatic downgrade, branch switch or unsupported-build promise.

## Recovery tools

- **Review Action / Review Errors:** understand the issue before deciding.
- **Repair / Install Dependency:** repair one dependency while preserving the queue; missing/linkage checks still apply.
- **Repair Pool State:** reconcile UI state. Queue cancellation is a separate explicit choice.
- **Maintenance Console:** executes entered commands, streams output and reports the real exit code. **Stop Command** cancels that command. Mutations are serialized; destructive commands require confirmation. Never paste secrets into commands.
- **Sync now:** retry queued publications.
- **Open logs:** diagnose, but redact tokens/private addresses before sharing.

Healthy/Connected: reachable pool, empty spool. Offline/Spooling: validated output waiting. Busy: active work. Action Required: decision needed. Paused — Error: failures/remaining queue retained. Safely Paused: checkpoint finished.

## Upgrade

Finish/safely pause work, Quit, then use the DMG Applications shortcut. Existing settings remain outside the app. Keep the previous binary for rollback; do not erase state. Do not run standard/.test editions concurrently on one Homebrew.

The app does not install itself or start upgrades automatically. Physical HP/MacBook Pro 2012/Q9300 acceptance tests remain outstanding; see [VALIDATION.md](VALIDATION.md).

## Software license, security and permissions

The [LICENSE](LICENSE) applies to the original Homebrew Intel Bottle Pool software distributed under it, including the macOS app, server, command-line client, source, build scripts, tests and documentation; it is not limited to v0.3.6. Official unmodified copies may be used personally and non-commercially under the current license. Commercial or professional use, source reuse, integration, modification, redistribution and derivatives require prior explicit written permission from StefanAlMare. Public GitHub viewing and forking remain permitted by GitHub's Terms of Service. Third-party licenses and valid permissions accompanying historical releases remain unaffected. Protect pool tokens, keys and private deployment data.
