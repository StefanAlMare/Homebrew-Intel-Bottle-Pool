"""Private Core2 Legacy transport and immutable store, independent of protocol v1.

Policy and approval files are administrative trust roots. A unique random
credential is issued per enrolled machine; only its digest resides server-side.
Clients never enroll themselves, add approvals or widen the native ISA ceiling.
"""
import argparse
import contextlib
import hashlib
import hmac
import http.client
import json
import os
import platform
import posixpath
import re
import secrets
import socket
import shutil
import ssl
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .common import PoolError, atomic_json, digest
from .legacy_policy import (CHANNEL, Denied, LegacyGate, artifact_key, canonical,
                            features, is_hash, manifest_digest, verify_payload)

MAX_JSON = 1024 * 1024
MAX_BLOB = 20 * 1024**3
PLAN_FIELDS = ("name", "version", "revision", "rebuild", "context", "dependencies",
               "recipe_sha256", "embedded_recipe_sha256")
PROTECTED = {"python@3.14", "xz", "tcl-tk", "tcl-tk@8", "tcl-tk@9", "tcl", "tk"}


def require(condition, reason):
    if not condition:
        raise Denied(reason)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(data):
    require(len(data) <= MAX_JSON, "metadata exceeds limit")
    return json.loads(data, object_pairs_hook=no_duplicates,
                      parse_constant=lambda x: (_ for _ in ()).throw(Denied("invalid JSON constant")))


def private_json(path):
    path = Path(path).expanduser()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        s = os.fstat(stream.fileno())
        require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and
                s.st_mode & 0o077 == 0, "trust file must be owned by this user with mode 0600")
        require(s.st_size <= MAX_JSON, "trust file exceeds limit")
        value = decode(stream.read(MAX_JSON + 1))
    require(isinstance(value, dict), "JSON object required")
    return value


def private_write(path, value):
    atomic_json(path, value)
    Path(path).chmod(0o600)


def load_policy(path):
    p = private_json(path)
    require(p.get("schema") == 2 and p.get("channel") == CHANNEL and
            p.get("auto_import_verified_bottles") is False, "invalid Legacy policy; Auto-import must be OFF")
    require(isinstance(p.get("pool_id"), str) and
            __import__('re').fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", p["pool_id"]), "invalid private pool ID")
    require(isinstance(p.get("machines"), dict) and isinstance(p.get("reviews"), dict), "invalid policy registry")
    return p


def plan_for(manifest):
    return {key: manifest[key] for key in PLAN_FIELDS}


def authenticate(policy, authorization):
    require(policy.get("enabled") is True, "Core2 Legacy is disabled")
    require(isinstance(authorization, str) and authorization.startswith("Bearer "), "authentication required")
    token = authorization[7:]
    require(len(token) >= 32 and not any(x.isspace() for x in token), "authentication required")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    matches = []
    for machine_id, enrolled in policy["machines"].items():
        expected = enrolled.get("credential_sha256", "") if isinstance(enrolled, dict) else ""
        if isinstance(expected, str) and hmac.compare_digest(token_hash, expected):
            matches.append((machine_id, enrolled))
    require(len(matches) == 1 and matches[0][1].get("enabled") is True,
            "authentication required or machine revoked")
    machine_id, enrolled = matches[0]
    return {"machine_id": machine_id, "key_id": enrolled["key_id"]}


def namespace(root, pool_id):
    root = Path(root).expanduser()
    require(not root.is_symlink(), "linked state root denied")
    if root.exists():
        require(root.is_dir() and root.stat().st_uid == os.getuid() and
                root.stat().st_mode & 0o077 == 0, "state root must be private and owned by this user")
    else:
        root.mkdir(parents=True, mode=0o700)
    marker = root / "namespace.json"
    identity = {"schema": 2, "channel": CHANNEL, "pool_id": pool_id}
    if marker.exists():
        require(private_json(marker) == identity, "state belongs to another channel/pool")
    else:
        require(not any(root.iterdir()), "unlabelled/nonempty state cannot be reused")
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            require(private_json(marker) == identity, "state belongs to another channel/pool")
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical(identity)); stream.flush(); os.fsync(stream.fileno())
    return root


def _sysctl(key):
    result = subprocess.run(["/usr/sbin/sysctl", "-n", key], capture_output=True,
                            text=True, timeout=5, check=True)
    return result.stdout.strip()


def observe_host(config):
    """No Homebrew invocation. Failure to read native facts is a hard denial."""
    require(platform.system() == "Darwin", "native macOS required")
    try:
        translated = _sysctl("sysctl.proc_translated") != "0"
    except subprocess.CalledProcessError:
        # On native Intel this sysctl may not exist; it cannot excuse ARM hardware.
        translated = False
    native_arch = _sysctl("hw.machine")
    cpu = {"vendor": _sysctl("machdep.cpu.vendor"),
           "family": int(_sysctl("machdep.cpu.family")), "model": int(_sysctl("machdep.cpu.model"))}
    observed = _sysctl("machdep.cpu.features").split()
    try:
        observed += _sysctl("machdep.cpu.leaf7_features").split()
    except subprocess.CalledProcessError:
        pass
    version = subprocess.run(["/usr/bin/sw_vers", "-productVersion"], text=True,
                             capture_output=True, timeout=5, check=True).stdout.strip()
    build = subprocess.run(["/usr/bin/sw_vers", "-buildVersion"], text=True,
                           capture_output=True, timeout=5, check=True).stdout.strip()
    target = {15: "conroe-merom", 23: "penryn"}.get(cpu["model"], "unknown")
    return {"machine_id": config["machine_id"], "cpu": cpu, "cpu_target": target,
            "observed_features": sorted(features(observed)), "native_arch": native_arch,
            "process_arch": platform.machine(), "translated": translated,
            "context": {"arch": native_arch, "macos_version": version, "macos_build": build,
                        "prefix": config["prefix"], "cellar": config["cellar"]}}


class LegacyStore:
    def __init__(self, root, policy_file, lease_seconds=180):
        self.policy_file = Path(policy_file)
        policy = load_policy(self.policy_file)
        self.pool_id = policy["pool_id"]
        self.root = namespace(root, self.pool_id)
        self.objects = self.root / "objects"
        self.staging = self.root / "staging"
        for path in (self.objects, self.staging):
            require(not path.is_symlink(), "linked storage denied")
            path.mkdir(exist_ok=True, mode=0o700)
        import fcntl
        self.lock_file = open(self.root / ".service.lock", "a+")
        os.chmod(self.root / ".service.lock", 0o600)
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise Denied("another server owns this private pool")
        self.guard = threading.RLock()
        self.leases = {}
        self.lease_seconds = lease_seconds

    def close(self):
        self.lock_file.close()

    def policy(self):
        p = load_policy(self.policy_file)
        require(p["pool_id"] == self.pool_id, "pool identity changed; restart required")
        return p

    def check(self, authorization, manifest, host, operation, payload=None):
        p = self.policy()
        session = authenticate(p, authorization)
        key = LegacyGate(p).authorize(manifest, host, session, operation, plan_for(manifest), payload)
        return key, session

    def acquire(self, authorization, manifest, host):
        key, session = self.check(authorization, manifest, host, "lease")
        # lease acquisition requires publish role and authenticated original producer;
        # blob integrity is checked at commit, since no bytes have arrived yet.
        p = self.policy()
        require("publish" in p["machines"][session["machine_id"]].get("roles", []), "publication role required")
        require(manifest["provenance"]["producer_machine_id"] == session["machine_id"], "producer must own publication lease")
        with self.guard:
            lease = self.leases.get(key)
            if lease and lease["expires"] > time.monotonic():
                raise Denied("artifact is busy")
            lease = {"token": secrets.token_hex(32), "expires": time.monotonic() + self.lease_seconds,
                     "session": session, "manifest": json.loads(canonical(manifest)),
                     "host": json.loads(canonical(host))}
            self.leases[key] = lease
            return {"key": key, "lease": lease["token"], "ttl": self.lease_seconds}

    def lease(self, authorization, key, token):
        require(is_hash(key), "invalid artifact key")
        with self.guard:
            lease = self.leases.get(key)
            require(lease and lease["expires"] > time.monotonic() and
                    isinstance(token, str) and hmac.compare_digest(token, lease["token"]), "invalid or expired lease")
            _, session = self.check(authorization, lease["manifest"], lease["host"], "lease")
            require(session == lease["session"], "lease belongs to another machine")
            require("publish" in self.policy()["machines"][session["machine_id"]].get("roles", []), "publisher revoked")
            return lease

    def renew(self, authorization, key, token):
        with self.guard:
            lease = self.lease(authorization, key, token)
            lease["expires"] = time.monotonic() + self.lease_seconds
            return {"ttl": self.lease_seconds}

    def release(self, authorization, key, token):
        with self.guard:
            self.lease(authorization, key, token)
            del self.leases[key]
            return {"status": "released"}

    def commit(self, authorization, key, token, staged):
        with self.guard:
            lease = self.lease(authorization, key, token)
            m = lease["manifest"]
            actual, _ = self.check(authorization, m, lease["host"], "server-commit", staged)
            inspect_archive(staged, m)
            require(actual == key, "manifest identity differs")
            directory = self.objects / key
            require(not directory.is_symlink(), "linked object denied")
            if directory.exists():
                old = private_json(directory / "manifest.json")
                require(old == m, "immutable object conflict")
                verify_payload(directory / "payload", m)
                del self.leases[key]
                return {"status": "exists", "key": key}
            temporary = Path(tempfile.mkdtemp(prefix="object-", dir=self.staging))
            try:
                shutil.copyfile(staged, temporary / "payload")
                os.chmod(temporary / "payload", 0o400)
                verify_payload(temporary / "payload", m)
                private_write(temporary / "manifest.json", m)
                # Re-read policy immediately before making the immutable object visible.
                self.check(authorization, m, lease["host"], "server-commit", temporary / "payload")
                os.rename(temporary, directory)
            finally:
                if temporary.exists(): shutil.rmtree(temporary)
            del self.leases[key]
            return {"status": "published", "key": key}

    def read(self, authorization, manifest, host):
        key, _ = self.check(authorization, manifest, host, "server-read")
        directory = self.objects / key
        require(not directory.is_symlink(), "linked object denied")
        if not directory.exists(): return None
        require(private_json(directory / "manifest.json") == manifest, "stored manifest differs")
        verify_payload(directory / "payload", manifest)
        return directory / "payload"


class LegacyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "HomebrewPoolCore2/0.3.7"

    def log_message(self, *args):
        pass  # Never log authentication headers, bodies or host identities.

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def reply(self, code, body):
        data = canonical(body)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        require(self.headers.get("Transfer-Encoding") is None, "chunked requests denied")
        value = self.headers.get("Content-Length", "")
        require(value.isdecimal() and 0 < int(value) <= MAX_JSON, "invalid metadata size")
        data = self.rfile.read(int(value))
        require(len(data) == int(value), "truncated metadata")
        result = decode(data)
        require(isinstance(result, dict), "object body required")
        return result

    def dispatch(self):
        require(self.path.startswith("/v2/core2-legacy/") and "?" not in self.path and
                "#" not in self.path, "wrong channel or protocol")
        operation = self.path[len("/v2/core2-legacy/"):]
        store = self.server.store
        authorization = self.headers.get("Authorization", "")
        session = authenticate(store.policy(), authorization)
        if self.command == "GET" and operation == "health":
            self.reply(200, {"schema": 2, "channel": CHANNEL, "pool_id": store.pool_id,
                             "status": "ok", "machine_id": session["machine_id"]})
            return
        if self.command == "POST":
            body = self.body()
            if operation in ("lookup", "download", "lease"):
                m, host = body["manifest"], body["host"]
                if operation == "lease":
                    self.reply(200, store.acquire(authorization, m, host)); return
                path = store.read(authorization, m, host)
                if path is None:
                    self.reply(404, {"error": "approved artifact not present"}); return
                if operation == "lookup":
                    self.reply(200, {"manifest": m, "key": artifact_key(m)}); return
                with open(path, "rb") as stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(m["size"]))
                    self.send_header("ETag", m["sha256"])
                    self.end_headers()
                    shutil.copyfileobj(stream, self.wfile, 1024 * 1024)
                return
            if operation in ("renew", "release"):
                self.reply(200, getattr(store, operation)(authorization, body["key"], body["lease"])); return
        if self.command == "PUT" and operation.startswith("objects/"):
            key = operation[len("objects/"):]
            token = self.headers.get("X-Pool-Lease", "")
            lease = store.lease(authorization, key, token)
            length = self.headers.get("Content-Length", "")
            require(self.headers.get("Transfer-Encoding") is None and length.isdecimal() and
                    int(length) == lease["manifest"]["size"] and 0 < int(length) <= MAX_BLOB,
                    "invalid blob size")
            fd, path = tempfile.mkstemp(prefix="upload-", dir=store.staging)
            try:
                with os.fdopen(fd, "wb") as stream:
                    remaining = int(length)
                    while remaining:
                        block = self.rfile.read(min(1024 * 1024, remaining))
                        require(bool(block), "truncated upload")
                        stream.write(block); remaining -= len(block)
                    stream.flush(); os.fsync(stream.fileno())
                self.reply(200, store.commit(authorization, key, token, path))
            finally:
                Path(path).unlink(missing_ok=True)
            return
        raise Denied("unknown Legacy operation")

    def handle_request(self):
        try:
            self.dispatch()
        except (Denied, PoolError, KeyError, ValueError, TypeError, OSError, AttributeError) as error:
            # Malformed requests never expose token/hash/host details in diagnostics.
            with contextlib.suppress(OSError):
                self.reply(403, {"error": str(error) if isinstance(error, Denied) else "invalid request or evidence"})

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request


class LegacyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store):
        self.store = store
        if ":" in address[0]: self.address_family = socket.AF_INET6
        super().__init__(address, LegacyHandler)


class LegacyClient:
    def __init__(self, config, host_provider=observe_host):
        self.config = config
        require(config.get("channel") == CHANNEL and config.get("auto_import_verified_bottles") is False,
                "explicit Legacy channel and Auto-import OFF required")
        self.policy_file = config["policy_file"]
        self.host_provider = host_provider
        p = load_policy(self.policy_file)
        self.pool_id = p["pool_id"]
        require(config["pool_id"] == self.pool_id, "configuration pool differs")
        self.url = config["url"].rstrip("/")
        u = urlsplit(self.url)
        require(u.scheme in ("https", "http") and bool(u.hostname) and not
                (u.username or u.password or u.query or u.fragment or u.path), "use a dedicated server origin")
        require(u.scheme == "https" or u.hostname in ("127.0.0.1", "::1"),
                "remote Legacy transport requires HTTPS")
        credential_path = Path(config["token_file"])
        fd = os.open(credential_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r") as stream:
            s = os.fstat(stream.fileno())
            require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and
                    s.st_mode & 0o077 == 0 and s.st_size <= 4096, "credential file must be private")
            self.token = stream.read().strip()
        require(len(self.token) >= 32 and not any(c.isspace() for c in self.token), "invalid machine credential")
        self.state = namespace(config["state_dir"], self.pool_id)
        self.spool = self.state / "spool"; self.spool.mkdir(exist_ok=True, mode=0o700)
        require(not self.spool.is_symlink(), "linked spool denied")
        self.context = ssl.create_default_context(cafile=config.get("ca_file"))

    def authorize(self, manifest, operation, expected, payload=None):
        p = load_policy(self.policy_file)
        require(p["pool_id"] == self.pool_id, "pool identity changed")
        session = authenticate(p, "Bearer " + self.token)
        require(session["machine_id"] == self.config["machine_id"], "credential belongs to another machine")
        host = self.host_provider(self.config)
        key = LegacyGate(p).authorize(manifest, host, session, operation, expected, payload)
        return key, host

    def request(self, operation, body=None):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=self.context))
        request = urllib.request.Request(self.url + "/v2/core2-legacy/" + operation,
                    data=canonical(body) if body is not None else None,
                    headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
                    method="POST" if body is not None else "GET")
        try:
            return opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            error.close()
            raise Denied("Legacy server refused request (HTTP %d)" % error.code) from None
        except (urllib.error.URLError, OSError):
            raise Denied("Legacy server unavailable; no global fallback") from None

    def lookup(self, manifest, expected):
        key, host = self.authorize(manifest, "lookup", expected)
        with self.request("lookup", {"manifest": manifest, "host": host}) as response:
            body = decode(response.read(MAX_JSON + 1))
        require(body.get("key") == key and body.get("manifest") == manifest, "server identity differs")
        return body

    def enqueue(self, manifest, payload, expected):
        key, _ = self.authorize(manifest, "enqueue", expected, payload)
        target = Path(tempfile.mkdtemp(prefix="entry-", dir=self.spool))
        try:
            shutil.copyfile(payload, target / "payload"); os.chmod(target / "payload", 0o400)
            self.authorize(manifest, "enqueue", expected, target / "payload")
            private_write(target / "manifest.json", manifest)
            private_write(target / "plan.json", expected)
            return target
        except BaseException:
            shutil.rmtree(target); raise

    def upload(self, entry):
        entry = Path(entry)
        require(not entry.is_symlink() and entry.resolve().parent == self.spool.resolve(), "entry outside Legacy spool")
        m = private_json(entry / "manifest.json"); expected = private_json(entry / "plan.json")
        key, host = self.authorize(m, "upload", expected, entry / "payload")
        with self.request("lease", {"manifest": m, "host": host}) as response:
            lease = decode(response.read(MAX_JSON + 1))
        require(lease["key"] == key and isinstance(lease["lease"], str), "invalid lease response")
        u = urlsplit(self.url)
        conn = (http.client.HTTPSConnection(u.hostname, u.port, context=self.context, timeout=60)
                if u.scheme == "https" else http.client.HTTPConnection(u.hostname, u.port, timeout=60))
        try:
            self.authorize(m, "upload", expected, entry / "payload")
            conn.putrequest("PUT", "/v2/core2-legacy/objects/" + key)
            for name, value in {"Authorization": "Bearer " + self.token, "X-Pool-Lease": lease["lease"],
                                "Content-Type": "application/octet-stream", "Content-Length": str(m["size"])}.items():
                conn.putheader(name, value)
            conn.endheaders()
            with open(entry / "payload", "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    conn.send(block)
            response = conn.getresponse(); result = decode(response.read(MAX_JSON + 1))
            require(response.status == 200 and result.get("key") == key and
                    result.get("status") in ("published", "exists"), "Legacy publication denied")
            # Keep the durable local entry; synchronization never deletes evidence.
            private_write(entry / "publication.json", result)
            return result
        finally:
            conn.close()
            with contextlib.suppress(Denied, OSError):
                with self.request("release", {"key": key, "lease": lease["lease"]}): pass

    def fetch(self, manifest, expected):
        key, host = self.authorize(manifest, "fetch", expected)
        downloads = self.state / "downloads"; downloads.mkdir(exist_ok=True, mode=0o700)
        require(not downloads.is_symlink(), "linked downloads denied")
        filename = manifest.get("filename")
        require(isinstance(filename, str) and Path(filename).name == filename and
                "/" not in filename and "\\" not in filename and
                re.search(r"\.bottle(?:\.\d+)?\.tar\.gz$", filename) is not None,
                "reviewed bottle filename required")
        directory = Path(tempfile.mkdtemp(prefix="verified-", dir=downloads))
        target = directory / filename
        try:
            with self.request("download", {"manifest": manifest, "host": host}) as response, open(target, "xb") as stream:
                require(response.headers.get("Content-Length") == str(manifest["size"]) and
                        response.headers.get("ETag") == manifest["sha256"], "download identity differs")
                remaining = manifest["size"]
                while remaining:
                    block = response.read(min(1024 * 1024, remaining))
                    require(bool(block), "truncated download")
                    stream.write(block); remaining -= len(block)
                require(not response.read(1), "oversized download")
                stream.flush(); os.fsync(stream.fileno())
            os.chmod(target, 0o400)
            self.authorize(manifest, "select", expected, target)
            private_write(directory / "manifest.json", manifest)
            private_write(directory / "plan.json", expected)
            return target
        except BaseException:
            shutil.rmtree(directory); raise


def inspect_archive(payload, manifest):
    """Reuse the installed archive safety parser; never extract into a live Cellar."""
    from .imports import BottleImporter
    importer = BottleImporter.__new__(BottleImporter)
    evidence = importer._archive_evidence(Path(payload))
    # Resolve link chains, not just lexical ../ segments: an intermediate link
    # can change the meaning of a subsequent parent traversal during extraction.
    with tarfile.open(payload, "r:gz") as archive:
        members = archive.getmembers()
        paths = [x.name.rstrip("/") for x in members]
        require(len(paths) == len(set(paths)), "duplicate archive paths denied")
        links = {x.name.rstrip("/"): x for x in members if x.issym() or x.islnk()}
        keg_root = (evidence["name"], evidence["version"])
        for member in members:
            resolved = []
            pending = list(PurePosixPath(member.name).parts)
            expansions = 0
            while pending:
                part = pending.pop(0)
                if part in ("", "."): continue
                if part == "..":
                    require(len(resolved) > len(keg_root), "archive link escapes its formula keg")
                    resolved.pop(); continue
                resolved.append(part)
                link = links.get("/".join(resolved))
                if link is not None:
                    expansions += 1
                    require(expansions <= 40, "cyclic archive link denied")
                    require(not link.linkname.startswith("/"), "absolute archive link denied")
                    resolved = resolved[:-1] if link.issym() else []
                    pending = list(PurePosixPath(link.linkname).parts) + pending
            require(tuple(resolved[:2]) == keg_root or
                    (member.isdir() and tuple(resolved) == keg_root[:1]),
                    "archive link resolves outside its formula keg")
    require(evidence["name"] == manifest["name"].split("/")[-1] and
            evidence["version"] == manifest["version"] + ("_" + str(manifest["revision"]) if manifest["revision"] else "") and
            evidence["recipe_sha256"] == manifest["embedded_recipe_sha256"], "archive recipe/formula/version differs")
    receipt = evidence["receipt"]
    require(receipt.get("built_as_bottle") is True and not receipt.get("poured_from_bottle") and
            receipt.get("arch") == "x86_64" and not receipt.get("used_options"), "archive lacks source-build receipt")
    runtime = receipt.get("runtime_dependencies")
    require(isinstance(runtime, list) and all(isinstance(x, dict) for x in runtime), "runtime receipt graph missing")
    actual = {x.get("full_name"): x.get("pkg_version") for x in runtime}
    require(len(actual) == len(runtime) and actual ==
            {k: v["version"] for k, v in manifest["dependencies"]["runtime"].items()}, "archive runtime graph differs")
    return evidence


def install_verified(client, manifest, expected, payload, repository_authorized=False):
    require(repository_authorized is True, "installation needs explicit current repository-access authorization")
    require(manifest["name"].split("/")[-1] not in PROTECTED, "protected formula: preserve existing installation")
    client.authorize(manifest, "select", expected, payload)
    inspect_archive(payload, manifest)
    # Current installed runtime dependencies must match the pinned plan exactly.
    from .capture import tree_hash
    for name, dep in manifest["dependencies"]["runtime"].items():
        version = dep["version"]
        require(isinstance(version, str) and version not in (".", "..") and "/" not in version, "unsafe dependency path")
        keg = Path(client.config["cellar"]) / name.split("/")[-1] / version
        require(keg.is_dir() and not keg.is_symlink(), "runtime dependency absent or linked")
        recipe = keg / ".brew" / (name.split("/")[-1] + ".rb")
        require(not recipe.is_symlink() and digest(recipe) == dep["recipe_sha256"] and
                tree_hash(keg) == dep["keg_tree_sha256"], "installed runtime dependency changed")
    brew = Path(client.config["brew"])
    require(brew.is_absolute() and brew.is_file() and os.access(brew, os.X_OK), "explicit Homebrew executable required")
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
               HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK="1", HOMEBREW_NO_ASK="1",
               HOMEBREW_DEVELOPER="1")
    for flag, expected_path in (("--prefix", client.config["prefix"]), ("--cellar", client.config["cellar"])):
        actual = subprocess.run([str(brew), flag], env=env, capture_output=True, text=True, check=True).stdout.strip()
        require(actual == expected_path, "actual Homebrew paths differ from approved context")
    client.authorize(manifest, "select", expected, payload)
    # No dependency installation, source fallback or upgrade is authorized here.
    return subprocess.run([str(brew), "install", "--formula", "--ignore-dependencies", "--force-bottle", str(payload)],
                          env=env, check=True).returncode


def run_server(argv):
    parser = argparse.ArgumentParser(description="Private Core2 Legacy server")
    parser.add_argument("--root", required=True); parser.add_argument("--policy", required=True)
    parser.add_argument("--bind", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--cert"); parser.add_argument("--key")
    args = parser.parse_args(argv)
    require(bool(args.cert) == bool(args.key), "TLS requires both certificate and key")
    require(args.bind in ("127.0.0.1", "::1") or bool(args.cert), "remote server requires TLS")
    store = LegacyStore(args.root, args.policy)
    server = LegacyServer((args.bind, args.port), store)
    if args.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print("Private Core2 Legacy server ready; policy is reloaded for each operation", flush=True)
    try: server.serve_forever()
    finally: server.server_close(); store.close()
