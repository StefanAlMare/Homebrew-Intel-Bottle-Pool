# Installation and deployment guide — 0.3.5

This guide covers the complete private deployment: one central server and every
Intel Mac that will use it.

Public examples use only these placeholders:

```text
Pool URL:   https://pool.example.internal
Data root: /srv/homebrew-pool
Token file:/run/secrets/pool.token
```

Replace them only in private configuration. Never commit the real hostname,
token, certificates, internal addresses, or storage paths.

## 1. Choose the central host

Use a NAS, TrueNAS system, Linux server, home server, or another always-on host.
The host needs:

- persistent local storage with enough free space for bottles and cached Casks;
- Python 3.9 or newer, or a container runtime for the supplied Docker image;
- reliable private connectivity to all participating Macs;
- a service account that can write only to `/srv/homebrew-pool`;
- a private bearer token readable from `/run/secrets/pool.token`;
- HTTPS termination, or access exclusively through a VPN/private LAN;
- backups or filesystem snapshots according to the operator's retention policy.

The server does not compile Homebrew formulae. Compilation happens on the Macs.
The server only authenticates clients, coordinates leases, verifies SHA-256, and
stores or serves artifacts.

Do not use an SMB/NFS mount as the server's active data root. Run the service on
the machine that has local access to the persistent storage. Only one server
process should own a data root.

## 2. Prepare storage and the service account

Create `/srv/homebrew-pool` on the central host. Give the dedicated service
account read/write access to this directory and no broader storage permission
than necessary.

The service creates its own manifests, blobs, temporary uploads, and lock data
below this directory. Macs do not need SMB, NFS, or SSH access to it.

## 3. Create and protect the token

Generate a random 256-bit token on the server:

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Store that value in `/run/secrets/pool.token` using the host's secret-management
method. The file should be readable by the service account only (normally mode
`0600`). Do not put the token in a URL, compose file, shell history, issue,
release, screenshot, or repository.

Provide the token to each authorized Mac through a private transfer or secret
manager. If one Mac is lost or no longer trusted, rotate the token on the server
and on every remaining Mac.

## 4. Provide secure network access

Recommended arrangements, in order:

1. HTTPS reverse proxy reachable only over a private network or VPN;
2. direct HTTPS on a trusted private LAN;
3. loopback server reached through an authenticated VPN or SSH tunnel.

The public client URL is `https://pool.example.internal`. Configure private DNS
or the VPN DNS so every Mac resolves that name to the private service endpoint.
If a private certificate authority is used, distribute only its CA certificate
to the Macs and select it in Setup.

Never expose plain HTTP plus the bearer token directly to the Internet. Remote
HTTP requires an explicit insecure-HTTP setting and is intended only for an
already protected private network.

## 5. Start the server directly

From the project checkout on the server:

```sh
python3 -m pool.server \
  --root /srv/homebrew-pool \
  --bind 127.0.0.1 \
  --port 8765 \
  --token-file /run/secrets/pool.token
```

This loopback configuration is appropriate when an HTTPS reverse proxy or VPN
gateway forwards private requests to port 8765. Configure the host's service
manager to run the same command as the dedicated account, restart it on failure,
and start it after storage and networking are ready.

For direct TLS, `pool.server` also accepts certificate and key arguments. Keep
the private key outside the repository and readable only by the service account.

## 6. Or start the supplied container

The included `compose.yaml` uses:

- `/srv/homebrew-pool` for persistent data;
- `/run/secrets/pool.token` as a read-only secret;
- loopback port 8765 by default;
- a read-only container filesystem, dropped capabilities, and no-new-privileges.

Create those paths on the host, set ownership for the container service account,
then run:

```sh
docker compose up -d --build
```

The image builds only the small Python server. It does not compile Homebrew
packages. Put the same private HTTPS/VPN layer in front of it.

## 7. Check the server before adding Macs

Confirm that:

- the process stays running after a restart;
- `/srv/homebrew-pool` is writable by the service account;
- `/run/secrets/pool.token` is not readable by unrelated users;
- `https://pool.example.internal` resolves only through the intended private path;
- the TLS certificate validates on a client Mac;
- the service is not reachable through public plain HTTP;
- backups or snapshots cover `/srv/homebrew-pool`.

The GUI's **Test Connection** is the authoritative end-to-end check because it
validates TLS, token authentication, and the API schema together.

## 8. Prepare every Intel Mac

Each Mac needs:

- Intel x86_64 hardware;
- macOS supported by the backend; the GUI requires macOS 12 or newer;
- Homebrew already installed;
- Python 3.9 or newer already installed;
- Apple Command Line Tools when that Mac may compile missing formulae;
- private network/VPN access to `https://pool.example.internal`;
- a private copy of the token and, when applicable, the private CA certificate.

Homebrew, Python, and Command Line Tools are not silently installed by this
project. Verify them on each Mac before enrolling it.

## 9. Install the app on every Mac

For each Mac:

1. Download the final v0.3.5 release assets and `SHA256SUMS.txt` together.
   The complete checksum check requires all files listed in the manifest.
2. Verify the downloads:

   ```sh
   shasum -a 256 -c SHA256SUMS.txt
   ```

   If you downloaded only the DMG, calculate its hash with
   `shasum -a 256 Homebrew-Intel-Bottle-Pool-v0.3.5.dmg` and compare the full value
   with that file's entry in `SHA256SUMS.txt`.

3. Open the DMG and drag `Homebrew Pool.app` to Applications.
4. Launch it from Applications. The first-run Setup window opens automatically.
5. Enter `https://pool.example.internal` in **Server URL**.
6. Paste the private token or select its private file under **Token/Token File**.
7. Select the private CA certificate only if the server uses one.
8. Leave insecure HTTP disabled when using HTTPS.
9. Choose **Test Connection**. Do not save until it reports a valid connection.
10. Choose **Save & Finish**.
11. Enable **Start at Login** only if this Mac should keep the status agent active.

A pasted token is copied to a private file with mode `0600`. Configuration is
stored in `~/.config/intel-bottle-pool/config.json` (or `XDG_CONFIG_HOME`). Do not
copy one Mac's entire config blindly to another; configure and test each machine.

## 10. Validate each newly enrolled Mac

Start with a small formula that is appropriate for the Mac:

1. On the first Mac, use **Install…** or **Update & Upgrade** and let it obtain or
   build the artifact, test it, and publish it.
2. Choose **Sync now** and confirm the local spool becomes empty.
3. On a second compatible Mac, request the same formula.
4. Confirm the log reports reuse from the pool rather than another source build.
5. Run the formula's normal command or Homebrew test/linkage checks.

Only then roll out a broad Update & Upgrade across the remaining Macs.

## 11. Understand compatibility boundaries

All Intel Macs are not automatically interchangeable. Reuse depends on the macOS
platform context, Homebrew prefix and Cellar, formula metadata and checksum,
options, and relevant runtime dependency/ABI context. The client keeps incompatible
variants separate and will build again rather than force an unsafe bottle.

Casks with fixed versions and SHA-256 values can be reused. Mutable `latest` or
`no_check` Casks are upstream-only and are never published to the pool.

## 12. Upgrade an existing client to 0.3.5

Install only final artifacts from the v0.3.5 release after checking their hashes.
Quit Homebrew Pool, replace the app, and reopen it. Keep the existing private
configuration, token file, state directory, spool, and `job.json`. The supplied
installer preserves configuration and a recoverable previous app. Avoid deleting
state to clear an error: Retry/Resume depends on that saved queue.

No server migration is needed: the pool protocol and persistent queue remain
schema 1. New dependency identities use separate variants, so older clients and
bottles can coexist. A first new-variant build may be needed. A legacy bottle-ready
keg without trustworthy build evidence may need a verified rebuild.

0.3.5 plans from the declared platform graph, identifies installed dependency
recipes, and pins local recipes during source builds. A real input change can
trigger one safe automatic replan/rebuild. Proven unchanged completed builds can
be reused; missing evidence, undeclared runtime dependencies, and repeated drift
stop publication. Existing paused jobs are preserved and are not started merely
by installing or launching the new app.

## 13. Daily operation and recovery

- **Healthy** means the server responds and the active local spool is empty; retained quarantine files are separate.
- **Busy** means a requested install, update, build, or sync is running.
- **Action Required** means a safe automatic choice is not possible.
- **Paused — Error** means processing stopped at a technical failure.
- **Retry Failed** retries failures only; **Resume** continues remaining work.
- **Stop** preserves the queue; **Sync now** retries offline publications.

A successful **Retry Failed** does not execute the pending queue. If there are
five or six remaining steps, they stay saved until **Resume**. Automatic context
recovery remains inside the current package and has at most one replan per package
per execution. A second context change stops rather than looping.

Review logs before skipping a failure. Do not grant automatic trust to unknown
third-party taps. Back up the server data root, but never publish private pool
manifests because their compatibility metadata may reveal local system details.

Legacy Homebrew uploads without the complete 0.3.5 provenance markers are kept
unchanged in `state_dir/spool/quarantine` for review. They no longer block active
synchronization. Keep this directory when transferring or backing up state.
A same-rank local build can reuse the pool winner only after exact input matching
and a verified download; official bottle checksums are never substituted.

## Credits

Homebrew Intel Bottle Pool was created and directed by **StefanAlMare** and
developed collaboratively with **ChatGPT by OpenAI**, including implementation,
testing, documentation, security review, and release preparation.

This project is independent from Homebrew and is not affiliated with or endorsed
by Homebrew.
