"""Protocol validation shared by the server and clients (stdlib only)."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SCHEMA = 1
CHUNK = 1024 * 1024


class PoolError(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def identity(manifest):
    return {k: manifest[k] for k in ("kind", "name", "platform", "variant")}


def key_for(manifest):
    return hashlib.sha256(canonical(identity(manifest))).hexdigest()


def validate(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise PoolError("Unsupported manifest schema")
    for field in ("kind", "name", "platform", "variant", "version", "filename"):
        v = manifest.get(field)
        if not isinstance(v, str) or not v or len(v) > 4096 or any(ord(c) < 32 for c in v):
            raise PoolError("Invalid manifest field: " + field)
    if Path(manifest["filename"]).name != manifest["filename"] or "/" in manifest["filename"] or "\\" in manifest["filename"] or manifest["filename"] in (".", ".."):
        raise PoolError("Filename must be a basename")
    checksum = manifest.get("sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise PoolError("Invalid SHA-256")
    order = manifest.get("version_order")
    if not isinstance(order, list) or not 1 <= len(order) <= 16 or any(type(i) is not int or i < 0 or i > 2**63 - 1 for i in order):
        raise PoolError("version_order must be a non-negative integer vector")
    if type(manifest.get("size")) is not int or manifest["size"] < 1:
        raise PoolError("Empty or invalid artifact")
    if not isinstance(manifest.get("metadata", {}), dict):
        raise PoolError("metadata must be an object")
    return manifest


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".json-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical(value))
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def version_order(version, revision=0, rebuild=0):
    """Conservative numeric/semver ordering; ambiguous schemes need explicit ranks."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,5})(?:[-.]?(alpha|a|beta|b|pre|rc)(\d*))?(?:\+[^\s]+)?", version)
    if not match:
        raise PoolError("Cannot order version %r; supply an explicit version_order" % version)
    numbers = [int(x) for x in match[1].split(".")]
    stages = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "pre": 2, "rc": 3, None: 4}
    return numbers + [0] * (6 - len(numbers)) + [stages[match[2]], int(match[3] or 0), int(revision), int(rebuild)]
