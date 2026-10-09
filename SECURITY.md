# Security and responsible disclosure

Homebrew Intel Bottle Pool stores software artifacts, dependency/CPU compatibility metadata and private service credentials. The server is intended for **trusted machines**.

## Report a vulnerability privately

Use GitHub's private vulnerability reporting feature for this repository **if enabled**, or contact [StefanAlMare](https://github.com/StefanAlMare) using a private channel. Do not publish vulnerability details, tokens, private server addresses, personally identifying hardware reports or reproducible exploitation steps in a public issue.

Do not assume private vulnerability reporting is enabled merely because this document exists. No public bug bounty or guaranteed response time is promised.

## Deployment security

- Use encrypted HTTPS with correct hostname/CA verification for network-exposed deployments. Existing HTTP-on-LAN configurations require strict LAN/VPN isolation and must not be forwarded to the public Internet.
- Store pool/global tokens separately from Core2 Legacy machine-specific credentials. Restrict file permissions and rotate/revoke exposed credentials.
- Do not trust binaries solely because they arrived from a pool. Validate SHA-256, recipe/dependency identity, exact platform/ISA requirements, provenance and producer approvals.
- Do not overwrite published artifacts or delete active downloads; honor leases, immutable archive identities and consistent manifests.
- Keep private data/secret files out of published source and GitHub release archives.
- Third-party Homebrew packages keep their own licenses; distributing the pool's software does not relicense third-party content.

## Licensing and GitHub rights

The original application, server, client, scripts, tests and documentation are distributed under the accompanying project-wide [LICENSE](LICENSE). Personal non-commercial use of the official unmodified product is permitted under its current terms. Commercial/professional use and source reuse, integration, modification or redistribution require prior explicit written permission from StefanAlMare. Public GitHub viewing and forking rights under the [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service) are preserved, as are historical grants and third-party licenses. This is **source-available software, not an open-source license**.
