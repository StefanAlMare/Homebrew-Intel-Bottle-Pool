"""HTTP transport, durable offline spool and renewable build leases."""
import base64
import contextlib
import http.client
import json
import os
import shutil
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .common import CHUNK, PoolError, atomic_json, canonical, digest, fsync_dir, key_for, validate


class Unavailable(PoolError):
    pass


class RemoteError(PoolError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, config):
        self.config = config
        self.url = config["url"].rstrip("/")
        parsed = urlsplit(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PoolError("Pool URL must be HTTP(S), without credentials/query/fragment")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1") and not config.get("allow_insecure_http"):
            raise PoolError("Use HTTPS/VPN tunnel; plain remote HTTP requires allow_insecure_http")
        self.token = Path(config["token_file"]).expanduser().read_text().strip()
        if not self.token or any(character.isspace() for character in self.token):
            raise PoolError("The token must be a single non-empty value")
        self.state = Path(config["state_dir"]).expanduser()
        self.state.mkdir(parents=True, exist_ok=True)
        self.spool = self.state / "spool"
        self.spool.mkdir(exist_ok=True)
        self.context = ssl.create_default_context(cafile=config.get("ca_file"))
        self.timeout = config.get("timeout", 10)

    def request(self, method, endpoint, body=None, headers=None):
        data = canonical(body) if body is not None else None
        all_headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        all_headers.update(headers or {})
        req = urllib.request.Request(self.url + "/v1/" + endpoint, data=data, method=method, headers=all_headers)
        # Pool credentials must never follow redirects to another host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=self.context))
        try:
            return opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read()).get("error", str(e.code))
            except (ValueError, OSError):
                message = str(e.code)
            finally:
                e.close()
            raise RemoteError(e.code, message) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise Unavailable("Pool unavailable: " + str(e)) from e

    def json_request(self, method, endpoint, body=None):
        with self.request(method, endpoint, body) as response:
            return json.load(response)

    def lookup(self, manifest):
        try:
            result = validate(self.json_request("GET", "manifest/" + key_for(manifest)))
            if key_for(result) != key_for(manifest):
                raise PoolError("Server returned a different identity")
            return result
        except RemoteError as e:
            if e.status == 404:
                return None
            raise

    def fetch(self, manifest, destination):
        from .processes import check_stop
        validate(manifest)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".fetch-", dir=str(destination.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                with self.request("GET", "blob/" + key_for(manifest), headers={"If-Match": manifest["sha256"]}) as response:
                    remaining = manifest["size"]
                    while remaining:
                        check_stop()
                        chunk = response.read(min(CHUNK, remaining))
                        if not chunk:
                            raise PoolError("Truncated download")
                        f.write(chunk)
                        remaining -= len(chunk)
                    if response.read(1):
                        raise PoolError("Oversized download")
                f.flush()
                os.fsync(f.fileno())
            if digest(name) != manifest["sha256"]:
                raise PoolError("Downloaded SHA-256 mismatch")
            os.replace(name, destination)
            fsync_dir(destination.parent)
            return destination
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def enqueue(self, manifest, source):
        validate(manifest)
        source = Path(source)
        if source.stat().st_size != manifest["size"] or digest(source) != manifest["sha256"]:
            raise PoolError("Source size/SHA-256 mismatch")
        # Immutable UUID entry: concurrent clients cannot overwrite one another.
        directory = Path(tempfile.mkdtemp(prefix="entry-", dir=str(self.spool)))
        target = directory / "payload"
        try:
            with open(source, "rb") as src, open(target, "xb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
                dst.flush()
                os.fsync(dst.fileno())
            if digest(target) != manifest["sha256"]:
                raise PoolError("Source changed during spool copy")
            atomic_json(directory / "manifest.json", manifest)
            fsync_dir(self.spool)
            return directory
        except BaseException:
            shutil.rmtree(directory)
            raise

    def upload(self, manifest, source, lease):
        validate(manifest)
        if not lease.token or lease.lost:
            raise PoolError("No valid lease for publication")
        if digest(source) != manifest["sha256"]:
            raise PoolError("Spool SHA-256 mismatch")
        url = urlsplit(self.url)
        conn_class = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        kwargs = {"timeout": max(60, self.timeout)}
        if url.scheme == "https":
            kwargs["context"] = self.context
        conn = conn_class(url.hostname, url.port, **kwargs)
        try:
            conn.putrequest("PUT", url.path.rstrip("/") + "/v1/blob/" + key_for(manifest))
            headers = {"Authorization": "Bearer " + self.token,
                       "Content-Length": str(manifest["size"]),
                       "Content-Type": "application/octet-stream",
                       "X-Pool-Manifest": base64.b64encode(canonical(manifest)).decode(),
                       "X-Pool-Lease": lease.token}
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            with open(source, "rb") as f:
                for chunk in iter(lambda: f.read(CHUNK), b""):
                    from .processes import check_stop
                    check_stop()
                    conn.send(chunk)
            response = conn.getresponse()
            body = json.loads(response.read())
            if response.status != 200:
                raise RemoteError(response.status, body.get("error", "Upload failed"))
            return body
        except (OSError, http.client.HTTPException) as e:
            raise Unavailable("Upload interrupted: " + str(e)) from e
        finally:
            conn.close()

    def publish_entry(self, directory, lease=None):
        directory = Path(directory)
        # A per-entry process lock also protects sync running during publication.
        import fcntl
        try:
            lock_file = open(directory / ".sync.lock", "a+")
        except FileNotFoundError:
            return {"status": "already-synced"}
        with lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"status": "busy"}
            try:
                manifest = validate(json.loads((directory / "manifest.json").read_text()))
            except FileNotFoundError:
                return {"status": "already-synced"}
            if lease:
                result = self.upload(manifest, directory / "payload", lease)
            else:
                with Lease(self, manifest, wait_seconds=0) as acquired:
                    if not acquired.token:
                        return {"status": "busy"}
                    result = self.upload(manifest, directory / "payload", acquired)
            if result["status"] in ("published", "exists", "older"):
                shutil.rmtree(directory)
            return result

    def sync(self):
        from .processes import check_stop
        results = []
        for directory in sorted(self.spool.glob("entry-*")):
            check_stop()
            if not (directory / "manifest.json").exists():
                continue  # incomplete enqueue from a crashed process; never publish it
            try:
                result = self.publish_entry(directory)
                results.append(result["status"])
            except Unavailable:
                results.append("offline")
                break
            except PoolError as e:
                results.append("retained: " + str(e))
                break
        return results

    def local_match(self, expected):
        for directory in self.spool.glob("entry-*"):
            path = directory / "manifest.json"
            if not path.exists():
                continue
            m = validate(json.loads(path.read_text()))
            if key_for(m) == key_for(expected) and m["version"] == expected["version"] and m.get("metadata", {}).get("context") == expected.get("metadata", {}).get("context"):
                if digest(directory / "payload") == m["sha256"]:
                    return m, directory / "payload"
        return None


class Lease:
    def __init__(self, client, manifest, wait_seconds=600):
        self.client, self.key = client, key_for(manifest)
        self.wait_seconds = wait_seconds
        self.token = None
        self.lost = False
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        from .processes import check_stop
        deadline = time.monotonic() + self.wait_seconds
        while True:
            check_stop()
            try:
                result = self.client.json_request("POST", "lease/" + self.key, {"action": "acquire"})
                self.token = result["token"]
                self.ttl = result["ttl"]
                break
            except RemoteError as e:
                if e.status != 423:
                    raise
                if time.monotonic() >= deadline:
                    return self
                time.sleep(min(2, max(0, deadline - time.monotonic())))
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.thread.start()
        return self

    def heartbeat(self):
        while not self.stop.wait(max(0.1, self.ttl / 3)):
            try:
                self.client.json_request("POST", "lease/" + self.key, {"action": "renew", "token": self.token})
            except PoolError:
                self.lost = True
                return

    def __exit__(self, *exc):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.client.timeout + 1)
        if self.token:
            with contextlib.suppress(PoolError):
                self.client.json_request("POST", "lease/" + self.key, {"action": "release", "token": self.token})


@contextlib.contextmanager
def local_lock(state):
    import fcntl
    with open(Path(state) / ".brew.lock", "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise PoolError("Another pool upgrade is running on this Mac") from e
        yield


@contextlib.contextmanager
def local_read_lock(state):
    """A diagnostic may share with diagnostics, never with a Brew writer."""
    import fcntl
    with open(Path(state) / ".brew.lock", "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise PoolError("A Homebrew operation is active; retry the diagnostic when it finishes") from e
        yield
