# Homebrew Pool Next — separate server-side deployment

**Status (October 9, 2026):** a separately deployed TrueNAS server pilot, **not the server code of the last published GitHub release**. This document records observed operation without claiming those modifications are included in the repository source archive or the v0.3.7 DMG.

The global server remains compatible with existing authenticated `/v1` clients on its established endpoint. An optional **`/v2/catalog/meta`** and **`/v2/catalog/batch`** API supplies a cached index of exact artifact identities in one request; it does **not** independently authorize installation. Clients still must validate the full manifest, archive checksum, dependency/CPU context and provenance.

## Verified pilot capabilities

- Migration of **112 existing validated artifacts** (50 official and 62 locally built), with source and destination SHA-256 verification and successful real authenticated download.
- Batch catalog lookup, ETag revision metadata and simulated concurrent catalog queries.
- Existing per-artifact leases, SHA-256 verification and atomic publication, with newly added preservation of old blobs and historical manifests.
- Tested handling of same-rank conflicts, concurrent publication and historical downloads; these are controlled tests, not proof of fleet-wide deployment.
- Startup catalog reconciliation and a 15-minute maintenance schedule, with `upload-*` staging cleanup after 24 hours only when no active upload/lease blocks it. Never automatically delete valid current or historical bottles; report orphan blobs for manual review.

## Boundaries

The global server and **Core2 Legacy** server use distinct state and authentication. Core2 Legacy lives on a separately configured HTTPS endpoint and schema-2 policy; see [CORE2_LEGACY.md](CORE2_LEGACY.md). The pilot's global gateway retained pre-existing HTTP bearer-token semantics for existing clients on a private LAN/VPN; it **must not** be exposed publicly without HTTPS/TLS.

The client application **v0.3.7** does not yet consume fast catalog batch responses or implement planned end-of-job reconciliation. Those integrations belong to the next client release, contingent on tests. The pilot code must be audited and moved into the official release sources before its features are claimed for that client.

## Deployment and rollback

Keep versioned, hash-verified backups of the original artifacts and pre-migration server until independent restore and client compatibility checks pass. Use the TrueNAS Apps management interface for deployment changes; do not directly alter the TrueNAS system installation. Release documentation should not expose private addresses or tokens.
