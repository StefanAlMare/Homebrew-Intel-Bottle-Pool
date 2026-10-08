# Private server setup

[Home](README.md) · [Full installation](INSTALLATION.md) · [User guide](USER_GUIDE.md)

For **new deployments**. Existing schema 1 servers need no reset, credential rotation or TrueNAS modification for a v0.3.6 client upgrade.

## Plan the deployment

One NAS/TrueNAS/Linux host stores artifacts and coordinates leases; builds remain on Macs. Use persistent local storage, Python 3.9+ or Docker/Compose, a dedicated account, private connectivity and TLS. One service owns one data root. Do not use SMB/NFS as the active root.

| Item | Placeholder | Purpose |
| --- | --- | --- |
| Client URL | https://pool.example.internal | Private HTTPS endpoint |
| Data root | /srv/homebrew-pool | Persistent artifacts/manifests/staging |
| Secret file | /run/secrets/pool.token | Private shared bearer token |
| Backend port | 8765 | Local service behind TLS proxy |
| Container UID:GID | 10001:10001 | Supplied Dockerfile service identity |

## 1. Storage and credentials

Download and checksum-verify the official source ZIP; extract it on the server. Keep real config/credentials out of the source directory.

Create a dedicated persistent directory/dataset writable by the service account only. Generate a random token privately:

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Save it using a private editor/secret manager, not a token-bearing command line. Restrict it to the service account (normally 0600). Persist or reprovision it after reboot: /run is often temporary.

For the supplied container, the data mount must be writable and the secret readable by UID 10001. Set ownership only on those dedicated paths; never make the secret world-readable or reset permissions broadly.

All token-holding clients are trusted peers, not read-only roles. If a peer is compromised, rotate the secret across server and clients.

## 2. Choose one service method

### Supplied container

[compose.yaml](compose.yaml) builds the server **locally from the extracted source**. It uses persistent data, a read-only secret, read-only root filesystem, dropped capabilities and loopback host binding.

```sh
docker compose up -d --build
docker compose logs --tail 100 bottle-pool
```

Container listener: 0.0.0.0:8765. Supplied host binding: **127.0.0.1:8765**. A proxy in a different container cannot use its own loopback to reach this backend; use a deliberately configured private container network or host-local proxy. Do not open it publicly as a workaround.

### Direct Python

From the extracted source, as the dedicated service user:

```sh
python3 -m pool.server \
  --root /srv/homebrew-pool \
  --bind 127.0.0.1 --port 8765 \
  --token-file /run/secrets/pool.token
```

Set the service manager's working directory to that source directory, restart on failure and start after storage/network readiness. Only the secret's path is passed, not its value.

Direct TLS supports `--cert /private/path/server.crt --key /private/path/server.key`. Remote direct-TLS clients need an appropriate private bind address, not loopback. Protect the key and firewall the port.

### TrueNAS mapping

Use a dedicated dataset and your installed edition's supported Apps/container or VM deployment method; screens vary by version.

Map the dataset to **/srv/homebrew-pool**, the protected token read-only to **/run/secrets/pool.token**, and the service to UID:GID **10001:10001** for the supplied image. Use one replica/owner. The compose file is the reference for mounts, listener and hardening.

If the Apps interface cannot build a local Dockerfile, build/import the image locally using that platform's supported method, or run direct Python in a managed VM. No unpublished registry image is assumed. Do not mount live artifact storage read/write on clients. Use snapshots/backups and targeted permissions, not recursive permission resets.

## 3. HTTPS and private networking

Configure a reverse proxy with a certificate for your private DNS name, routing to the correct backend. Preserve Authorization headers, methods and paths; allow large bottle uploads/timeouts; do not cache authenticated API responses.

Every Mac must resolve/reach the private endpoint. Distribute a private CA certificate if required, never the server's private key. Keep TLS verification enabled, including over VPN. Never expose HTTP plus the bearer token to the Internet.

Authenticated `GET /v1/health` returns `{"schema":1,"status":"ok"}`. Other routes are `/v1/manifest/<key>`, `/v1/blob/<key>`, `/v1/lease/<key>`. Keep tokens out of URLs/logs/screenshots.

## 4. Enroll Macs

Install the standard app; new clients use Setup:

| Field | Enter |
| --- | --- |
| Server URL | HTTPS endpoint, no token in URL |
| Token / Token File | Private shared token or readable private file |
| CA certificate | Only if using a private CA |
| Insecure HTTP | Off for HTTPS |
| Test Connection | Must validate TLS, token and schema before Save & Finish |

Existing clients retain their settings. Do not overwrite working configs.

## 5. Acceptance before broad upgrades

1. Service starts after reboot; storage writable; token persists and is protected.
2. HTTPS DNS/certificate works from every Mac.
3. Test Connection succeeds with the correct token, fails with a wrong token.
4. Mac A installs one suitable small formula, validates/publishes; Sync now if needed.
5. Compatible Mac B requests it and confirms verified pool reuse.
6. Verify normal command behavior and Homebrew test/linkage.
7. Confirm incompatible artifacts are refused.
8. Test backup restoration on a separate root, never over the live pool.

## Troubleshooting and backups

| Symptom | Check |
| --- | --- |
| Refused connection | Service health, private firewall and proxy/backend address |
| TLS failure | Hostname, CA chain, selected CA and clock; do not bypass TLS |
| Unauthorized | Correct token, service-user readability, matching client secret |
| Permission denied | Actual UID, dedicated dataset ownership and mount mode |
| Large upload fails | Proxy limits/timeouts and free disk space |
| Another service owns pool | Do not start a second owner or delete a live lock |
| Offline/Spooling | Restore connectivity, then Sync now |
| Same-rank conflict | Review differing bytes/context; do not overwrite manually |

Back up the whole data root consistently and protect secret/config backups separately. Prefer a stopped-service snapshot for restore testing. Recovery removes incomplete internal staging; artifacts become visible at the manifest's atomic commit. Restore to a separate root first.

No production server was changed while preparing this guide.
