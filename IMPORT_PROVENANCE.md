# Verified imports and producer evidence

Official Homebrew bottles can be verified against the exact checksum in the
current Homebrew formula metadata. A filename or an installed keg alone is never
enough evidence for a local bottle.

Homebrew's INSTALL_RECEIPT.json does not contain the original compiler flags,
the full required CPU instruction set, original prefix/Cellar or dependency
recipe hashes. Version 0.3.6 therefore leaves a local archive as **Needs
verification** unless it has reviewed producer evidence alongside it. It never
fills these unknown values from the scanning Mac. This is especially important
when copying archives between Intel Macs.

For a trusted producer with recorded build evidence, the sidecar is named
`ARCHIVE.bottle.tar.gz.pool-provenance.json`. Its schema is:

```json
{
  "schema": 1,
  "reviewed": true,
  "producer": "trusted-producer-and-build-record-identifier",
  "sha256": "exact archive SHA-256",
  "formula": "formula full_name from brew info",
  "version": "pkg_version including revision",
  "arch": "x86_64",
  "tag": "monterey",
  "rebuild": 0,
  "prefix": "/usr/local",
  "cellar": "/usr/local/Cellar",
  "recipe_sha256": "SHA-256 of the embedded .brew formula",
  "dependencies": {
    "example-dependency": {
      "version": "exact installed pkg_version",
      "source": "SHA-256 of that dependency's build-time embedded .brew recipe"
    }
  },
  "required_cpu_features": ["SSE4.2", "AVX", "AVX2"],
  "compiler_flags": []
}
```

The feature list must describe the producer build requirements, including any
instructions outside a standard x86-64 level. The example is illustrative, not
a default. Custom compiler flags require separate review and are not imported
automatically. `dependencies` is empty only for a formula with no runtime
dependencies. Evidence is an operator attestation from a trusted producer, not
an Apple signature or proof reconstructed from an unknown binary.

The scanner verifies the sidecar against the archive receipt, embedded recipe,
checksum, current exact formula/dependency graph, prefix and Cellar. It records
the full CPU feature list and consumers check that list before pouring. It
rechecks evidence immediately before staging. Missing or inconsistent evidence
remains for review; do not invent it just to enable an import.

This release does not automatically create a bottle from an ordinary source
installation. Node 26.11.0 built directly from source is reported accordingly.

## Capture Installed Formula (explicit, local validation)

Inspect Only reads the authentic receipt, embedded recipe and dependency context.
It does not change `built_as_bottle`. Without that genuine receipt flag, recovery
without recompilation is refused and a separately approved rebuild is offered.
Even a true flag does not prove CPU compatibility or create an archive by itself.

For Capture with Producer Proof, provide reviewed JSON with `schema: 1`,
`reviewed: true`, `producer`, `compiler_flags: []`, the FULL
`required_cpu_features` list and these exact fields from the inspection:
`formula`, `version`, `prefix`, `cellar`, `receipt_sha256`, `recipe_sha256`,
`keg_tree_sha256`, `context`. Never copy values from a different machine or
invent a short feature list to claim Core 2 compatibility. Modern producer
families require conservative SSE4.2/AVX/AVX2 evidence. Unknown CPU families or
custom compiler flags remain at review.

The capture copies the target and installed build/test/runtime dependencies.
It uses the existing local Homebrew repository, taps and portable Ruby, not a
download. Homebrew's genuine sandbox API confines all child operations to the
temporary root and denies network access. Missing sandbox support fails closed.
Only the copy is bottled. The archive checksum, recipe and receipt are checked;
only relocatable bottles proceed to real isolated installation, `brew test` and
`brew linkage --test`. Original keg/dependency hashes and context are checked
again before a durable candidate is created. Local policy forbidding package
installation from paths is honored. No receipt is patched and no automatic
publication occurs; use Review Imports afterwards.

Validation records appear under `capture_validation` in the provenance and
manifest metadata. Success on the producer is NOT physical Core 2 testing.
Q9300 lacks SSE4.2 and AVX. A candidate requiring either remains unavailable to
it, even when both machines report x86_64. Producer attestation is not a full
static binary audit; actual testing on the old Mac remains necessary.

## Alternatives when refused

Compatibility Options is read-only. It lists versioned formula candidates with
disabled/deprecated/support warnings, offers an explicitly approved Core 2
source build, or a separately reviewed legacy-source patch. A Python versioned
formula is not a Git branch. No automatic downgrade, dependency substitution,
branch selection or unsafe artifact publication occurs.
