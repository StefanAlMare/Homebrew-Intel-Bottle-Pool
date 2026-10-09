# Core2 Legacy — private compatibility and distribution channel

**Availability:** included in the verified [official Homebrew Pool v0.3.7 Hotfix 1, build 38 release](https://github.com/StefanAlMare/Homebrew-Intel-Bottle-Pool/releases/tag/v0.3.7). The private channel remains **OFF by default**; publishing a DMG does not enroll any machine or authorize a Core2 bottle.

## Purpose and separation

Share validated Homebrew bottles built specifically for authorized Intel Core 2 machines, without forcing every compatible Mac to rebuild. The channel is separate from the global pool: distinct schema-2 policy, machine tokens, HTTPS endpoint, state, spool and artifact approval ledger. The protocol is `/v2/core2-legacy`; the client **never falls back to the global pool**.

The panel is near the bottom of the Homebrew Pool menu, after Maintenance Console. **Review status** and **Review hardware** inspect settings only. **Create disabled setup** initializes a disabled policy and configuration without enrolling machines. **Load approved setup** requires administrator-supplied private configuration. **Verify**, **Publish**, **Download approved bottle** and **Review source build plan** are separately authorized operations; download does not mean installation.

## Hardware profiles

| Target | Minimum reviewed instructions | Disallowed assumptions |
| --- | --- | --- |
| Conroe/Merom | SSE2, SSE3, SSSE3, CX16 | No automatic SSE4.1, POPCNT, SSE4.2 or AVX |
| Penryn | SSE2, SSE3, SSSE3, CX16, SSE4.1 | No automatic POPCNT, SSE4.2, AVX or AVX2 |

CPU spoofing and instruction emulation on Hackintosh can distort OS reports: physical CPU evidence needs human administrative review. A machine identity, name or SMBIOS is not sufficient. A Penryn artifact may not run on Conroe/Merom; a purported Conroe build needs testing on an authorized Conroe/Merom machine.

## Enrollment and approval

Each machine needs a distinct secret token over HTTPS and an approved `machines` policy entry with assigned roles such as `consume`, `test`, `publish` and `build`. Enrollment pins the CPU target/ISA evidence, macOS version/build, architecture, Homebrew prefix and Cellar. Token plaintext is not published; the server records only a digest. Tokens are not hardware attestation.

Manifest approval requires a registered reviewer and the digest of the complete canonical manifest, covering exact formula/version/rebuild, archive SHA-256, installed/embedded recipe identity, dependencies, toolchain/flags, producer evidence and native validation. A field such as `reviewed: true` is insufficient.

**Do not import generic installed kegs as bottles.** Rebuilding with `--build-bottle`, exact build records, isolated pour/formula/linkage tests, an ISA review and manifest approval are required before reuse. Protected Python/XZ/Tcl/Tk installations must not be overwritten through Legacy install. No silent downgrade or unauthorized build; Auto-import verified bottles remains **OFF**.

## Operator guide

1. Open **Core2 Legacy… → Review status** and **Review hardware**.
2. Create a disabled setup only if one does not already exist. Preserve private configuration, token and backup.
3. Deploy an independent TLS private server and enroll an identified machine with separately reviewed physical evidence.
4. Review a source-build plan on a dedicated authorized builder, then validate the resulting archive and manifest before approving and publishing.
5. Recheck compatibility for each recipient; never assume a bottle is valid across all Core 2 computers.

**Current limit:** controlled software tests and local signing/notarization do not establish that a real bottle has run natively on every Core 2 target. Keep enabled/published status dependent on successful observed checks.

## Security and licensing

Do not post configuration JSON, machine tokens, secret keys, private addresses or evidence containing personal identifiers to the public repository. See [SECURITY.md](SECURITY.md). The same project-wide [LICENSE](LICENSE) applies; separate private machine enrollment does not grant commercial use or source redistribution rights.
