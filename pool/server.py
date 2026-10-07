"""A single authoritative filesystem service; run on TrueNAS, never build here."""
import argparse
import hmac
import json
import os
import secrets
import shutil
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .common import CHUNK, PoolError, atomic_json, digest, fsync_dir, key_for, validate


class Store:
    def __init__(self, root, lease_seconds=180, max_bytes=20 * 1024**3):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects = self.root / "artifacts"
        self.objects.mkdir(exist_ok=True)
        self.staging = self.root / "staging"
        self.staging.mkdir(exist_ok=True)
        # A second service must never mutate the same dataset.
        import fcntl
        self.process_lock = open(self.root / ".service.lock", "a+")
        try:
            fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self.process_lock.close()
            raise PoolError("Another server already owns this pool") from e
        self.guard = threading.RLock()
        self.artifact_locks = {}
        self.leases = {}
        self.lease_seconds = lease_seconds
        self.max_bytes = max_bytes
        # Crash recovery removes only internal unreferenced files.
        for path in self.staging.iterdir():
            if path.is_file():
                path.unlink()
        for directory in self.objects.iterdir():
            if not directory.is_dir():
                continue
            current = self.current(directory.name)
            keep = current["sha256"] if current else None
            for path in directory.iterdir():
                if path.is_file() and (path.name.startswith(".json-") or (len(path.name) == 64 and path.name != keep)):
                    path.unlink()

    def close(self):
        self.process_lock.close()

    def current(self, key):
        path = self.objects / key / "manifest.json"
        if not path.exists():
            return None
        return validate(json.loads(path.read_text()))

    def artifact_lock(self, key):
        with self.guard:
            return self.artifact_locks.setdefault(key, threading.RLock())

    def acquire(self, key, owner):
        with self.guard:
            old = self.leases.get(key)
            if old and old["expires"] > time.monotonic():
                return None
            lease = {"token": secrets.token_hex(32), "owner": owner, "expires": time.monotonic() + self.lease_seconds}
            self.leases[key] = lease
            return {"token": lease["token"], "ttl": self.lease_seconds}

    def check_lease(self, key, token):
        lease = self.leases.get(key)
        if not lease or lease["expires"] <= time.monotonic() or not hmac.compare_digest(lease["token"].encode(), token.encode()):
            raise PoolError("Lease expired or superseded; publication fenced")

    def renew(self, key, token):
        with self.guard:
            self.check_lease(key, token)
            self.leases[key]["expires"] = time.monotonic() + self.lease_seconds
            return {"ttl": self.lease_seconds}

    def release(self, key, token):
        with self.guard:
            self.check_lease(key, token)
            del self.leases[key]

    def commit(self, manifest, staged, token):
        validate(manifest)
        if staged.stat().st_size != manifest["size"] or digest(staged) != manifest["sha256"]:
            raise PoolError("Uploaded size/SHA-256 mismatch")
        key = key_for(manifest)
        with self.artifact_lock(key):
            with self.guard:
                self.check_lease(key, token)
            current = self.current(key)
            if current:
                new_order, old_order = tuple(manifest["version_order"]), tuple(current["version_order"])
                old_path = self.objects / key / current["sha256"]
                valid_old = old_path.is_file() and digest(old_path) == current["sha256"]
                if len(new_order) != len(old_order):
                    raise PoolError("Version rank shape changed; use the same ordering vector for a variant")
                if new_order < old_order:
                    return {"status": "older", "manifest": current}
                if new_order == old_order and valid_old:
                    if manifest["sha256"] != current["sha256"] or manifest["version"] != current["version"] or manifest.get("metadata", {}).get("context") != current.get("metadata", {}).get("context"):
                        raise PoolError("Same version rank with different bytes/context; specify a reviewed rebuild rank")
                    return {"status": "exists", "manifest": current}
            # Hashing a large previous blob must not prevent heartbeat renewal.
            # Fence again at the commit point, including after service-side I/O.
            with self.guard:
                self.check_lease(key, token)
                directory = self.objects / key
                directory.mkdir(exist_ok=True)
                fsync_dir(self.objects)
                destination = directory / manifest["sha256"]
                os.replace(staged, destination)
                fsync_dir(directory)
                # Manifest is the atomic commit point, AFTER the durable verified blob.
                try:
                    atomic_json(directory / "manifest.json", manifest)
                except OSError:
                    # A fsync failure may happen after the rename; inspect the pointer
                    # before removing a blob so the visible manifest never dangles.
                    visible = self.current(key)
                    if not visible or visible["sha256"] != manifest["sha256"]:
                        destination.unlink()
                        fsync_dir(directory)
                    raise
            for path in directory.iterdir():
                if path.is_file() and len(path.name) == 64 and path.name != manifest["sha256"]:
                    path.unlink()
            fsync_dir(directory)
            return {"status": "published", "manifest": manifest}


class Handler(BaseHTTPRequestHandler):
    server_version = "IntelBottlePool/0.1"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        # Never log Authorization, lease tokens, host identities or URL query secrets.
        print("pool request: %s" % (args[1] if len(args) > 1 else "completed"), flush=True)

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorize(self):
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + self.server.token).encode()):
            self.reply(401, {"error": "Authentication required"})
            return False
        return True

    def body(self, limit=128 * 1024):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= limit:
            raise PoolError("Invalid request length")
        data = self.rfile.read(length)
        if len(data) != length:
            raise PoolError("Truncated request")
        return json.loads(data)

    def route(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if parts == ["v1", "health"]:
            return parts
        if len(parts) != 3 or parts[0] != "v1" or parts[1] not in ("manifest", "blob", "lease"):
            raise PoolError("Unknown endpoint")
        import re
        if not re.fullmatch(r"[a-f0-9]{64}", parts[2]):
            raise PoolError("Invalid artifact key")
        return parts

    def do_GET(self):
        if not self.authorize():
            return
        try:
            parts = self.route()
            store = self.server.store
            if parts[-1] == "health":
                self.reply(200, {"schema": 1, "status": "ok"})
                return
            stream = None
            with store.artifact_lock(parts[2]):
                m = store.current(parts[2])
                if not m:
                    self.reply(404, {"error": "Not found"})
                elif parts[1] == "manifest":
                    self.reply(200, m)
                elif parts[1] == "blob":
                    if self.headers.get("If-Match") != m["sha256"]:
                        self.reply(412, {"error": "Artifact changed; refresh manifest"})
                        return
                    path = store.objects / parts[2] / m["sha256"]
                    if digest(path) != m["sha256"]:
                        self.reply(409, {"error": "Stored artifact failed SHA-256 verification"})
                        return
                    # An open Unix fd remains valid if a newer publication unlinks it.
                    # Streaming must not block lease heartbeats or other clients.
                    stream = open(path, "rb")
                else:
                    self.reply(404, {"error": "Not found"})
            if stream:
                with stream:
                    self.send_response(200)
                    self.send_header("Content-Length", str(m["size"]))
                    self.send_header("Content-Type", "application/octet-stream")
                    self.end_headers()
                    shutil.copyfileobj(stream, self.wfile, CHUNK)
        except (PoolError, ValueError, OSError) as e:
            self.reply(400, {"error": str(e)})

    def do_POST(self):
        if not self.authorize():
            return
        try:
            parts = self.route()
            if parts[1] != "lease":
                raise PoolError("Expected lease endpoint")
            body = self.body()
            action = body.get("action")
            store = self.server.store
            if action == "acquire":
                result = store.acquire(parts[2], "StefanAlMare")
                self.reply(200 if result else 423, result or {"error": "Artifact is busy"})
            elif action == "renew":
                self.reply(200, store.renew(parts[2], str(body.get("token", ""))))
            elif action == "release":
                store.release(parts[2], str(body.get("token", "")))
                self.reply(200, {"status": "released"})
            else:
                raise PoolError("Unknown lease action")
        except (PoolError, ValueError, OSError) as e:
            self.reply(409, {"error": str(e)})

    def do_PUT(self):
        if not self.authorize():
            return
        staged = None
        try:
            parts = self.route()
            if parts[1] != "blob":
                raise PoolError("Expected blob endpoint")
            import base64
            manifest = validate(json.loads(base64.b64decode(self.headers.get("X-Pool-Manifest", ""), validate=True)))
            if key_for(manifest) != parts[2]:
                raise PoolError("Manifest/key mismatch")
            length = int(self.headers.get("Content-Length", "0"))
            if length != manifest["size"] or length > self.server.store.max_bytes:
                raise PoolError("Upload size rejected")
            token = self.headers.get("X-Pool-Lease", "")
            with self.server.store.guard:
                self.server.store.check_lease(parts[2], token)
            fd, name = tempfile.mkstemp(dir=str(self.server.store.staging), prefix="upload-")
            staged = Path(name)
            self.connection.settimeout(60)
            with os.fdopen(fd, "wb") as f:
                remaining = length
                while remaining:
                    data = self.rfile.read(min(CHUNK, remaining))
                    if not data:
                        raise PoolError("Truncated upload")
                    f.write(data)
                    remaining -= len(data)
                f.flush()
                os.fsync(f.fileno())
            self.reply(200, self.server.store.commit(manifest, staged, token))
        except (PoolError, ValueError, OSError) as e:
            self.reply(409, {"error": str(e)})
        finally:
            if staged and staged.exists():
                staged.unlink()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, token):
        super().__init__(address, Handler)
        self.store, self.token = store, token


def main(argv=None):
    parser = argparse.ArgumentParser(description="TrueNAS artifact pool service")
    parser.add_argument("--root", required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--lease-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text().strip()
    if len(token) < 32:
        parser.error("Use a randomly generated token of at least 32 characters")
    if bool(args.cert) != bool(args.key):
        parser.error("TLS needs both --cert and --key")
    if args.lease_seconds < 10:
        parser.error("Lease must be at least 10 seconds")
    store = Store(args.root, args.lease_seconds)
    server = Server((args.bind, args.port), store, token)
    if args.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print("Pool ready on %s:%s" % server.server_address, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
