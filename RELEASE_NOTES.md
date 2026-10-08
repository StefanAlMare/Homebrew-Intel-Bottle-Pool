# Homebrew Intel Bottle Pool 0.3.5 — Release Notes

October 8, 2026. Intel x86_64, macOS 12 or newer, build 35.

## Provenance and recovery

The investigated gobject-introspection 1.86.0_4 failure occurred when API recipe
identity changed while the installed dependency remained unchanged. The client
now uses the SHA-256 of `.brew/FORMULA.rb` in the current installed keg. A change
to the installed version or installed recipe changes the variant; an API-only
change to dependency metadata does not. Missing evidence, read failures, and
symbolically linked recipes/directories stop publication with a diagnostic.

Planning explicitly selects the declared platform graph with `brew deps --os=TAG`
instead of the runtime graph of an existing keg. The local Homebrew implementation
shows that, without this selection, `deps` can read `runtime_dependencies` from
the receipt: the old keg before an upgrade and the new keg afterward. The harfbuzz
14.5.1 → 14.6.0 log, with brotli changing from absent to 1.2.0, is consistent with
this mechanism. The log alone does not rule out a concurrent recipe change.

For source builds, installation and subsequent commands use synchronized local
recipes with installation from the API disabled. The client pins and verifies
tap HEAD; local modifications or concurrent tap changes stop execution. Preflight
and building share synchronization evidence, avoiding repeated fetches within
the same operation. Local safety and recipe checks still run on every use.

Recovery allows at most one replan per package per execution, rereading the graph
and acquiring a new lease. A pre-build replan performs no compilation. If actual
inputs change during a build, the first artifact is rejected; required
dependencies are repaired and one transactional rebuild is allowed. A second
change stops the operation. Missing provenance and undeclared runtime dependencies
are never ignored or automatically accepted. `brew linkage --test` validates the
result before enqueueing or publication.

Local `build-proofs` record runtime context, build/test inputs, the installed
recipe hash, and keg identity immediately after compilation. The `.brew` copy
is checked using Homebrew's exact bottle-block removal transformation, after
verifying the complete source checksum. Retry skips recompilation only when the
proof, installed recipe, and all inputs match the current plan. A legacy keg
without this evidence may require a verified rebuild; an old compilation with
incomplete provenance is not assumed safe. Transactional rollback from 0.3.4
is preserved.

## Publication conflicts and synchronization

At the `node` step, the local log and spool identify `googletest 1.18.0` as the
failed package. Two local entries have the same SHA-256, rank, and context. The
server manifest was not read during this investigation, so the remote difference
is not attributed to either bytes or context. The general defect identified was
that formula recipe identity participated in context but not in the variant key.
A recipe change without a new rank could occupy the same key and cause repeated
publication refusals.

Variant identity now also includes the formula SHA-256, marked `formula-runtime-v1`.
When two local builds conflict at the same rank, the client may retain the
published bottle only if version, runtime context, and build/test inputs are
identical and its download passes If-Match, size, and SHA-256 checks. This is a
single attempt and never overwrites the server artifact. Changed context, missing
evidence, or a different official checksum still blocks publication.

Legacy Homebrew spool entries are moved automatically to `spool/quarantine` for
review without changing their manifests or payloads. They are not retried,
relabelled, or deleted; other entries can continue synchronizing.

## Compatibility

The pool protocol, spool, and `job.json` remain schema 1. No server migration is
required. Version 0.3.5 variants use a distinct identity even for formulae without
dependencies, avoiding rank conflicts with legacy artifacts. Existing artifacts
are not deleted, relabelled, or accepted as new provenance. The first build of a
new variant may be necessary; old clients retain their own variants.
Configuration, token, and existing queue are preserved. Retry runs only failed
steps; Resume runs the pending steps.

## Application, tests, and documentation

- Version 0.3.5 / build 35 in the client, bundle, installer, and packaging scripts.
- Fixes to the initial commit's regressions: cached-tap safety checks, a legacy
  fixture without an installed recipe, and the bundle test still expecting build 34.
- All 160 tests passed with no skips, covering provenance, graphs, concurrent
  publication, legacy spool preservation, notary transport, and publication gates.
  See VALIDATION.md for the complete validation record.
- Compiled application workflow tests for Retry/Resume/Stop, plus a real Homebrew
  test in a disposable prefix: build/bottle/pool/pour/test and Cask reuse with its
  upstream archive hidden and installed payload verified by SHA-256.
- Apple's reserved ticket file is accepted only after validation. Forged or linked
  tickets are rejected. A rebuild preserves the previous local product separately
  so its old ticket cannot be merged into the new application.
- SourceManifest.json binds the signed bundle to its commit and actual build
  inputs. Embedded sources, the source ZIP, and the release tag must agree.
- Updated README introduction, How it works PNG/SVG, installation and upgrade
  instructions, Retry/Resume guidance, Quick Start, and Changelog.
- English throughout the current repository documentation and distributed assets.
  The English documentation refresh rebuilds and notarizes the bundle to preserve
  the exact commit binding; application behavior is unchanged.
- RELEASING.md documents local build → tests → signing → notarization → stapling
  → container/checksum verification → final publication.
- Notarization can use an existing profile on an authorized SSH host, with strict
  host and archive checks. Credentials remain on the Mac that owns the profile.
- The default `stable` branch receives the final commit. Publication verifies
  downloaded artifacts before making a new release public/latest.

## Distribution

Builds run locally on Intel macOS. Final distribution requires Developer ID
Application signing for Team YWVVK7QZ6X, Apple Accepted results for the app and DMG,
attached and validated tickets, Gatekeeper acceptance, and ZIP/DMG contents
matching the committed source. SHA256SUMS.txt covers the artifacts, distributed
documents, diagram, and notarization evidence. GitHub provides distribution;
GitHub Actions and hosted compilation are not used.

See VALIDATION.md for completed checks and practical limitations.
