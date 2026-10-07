"""Explicit adapters for downloads and locally produced binary packages."""
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .client import Lease, Unavailable
from .common import CHUNK, PoolError, digest, validate, version_order
from .processes import check_stop, run_command


def manifest_for(recipe, file=None):
    m = {"schema": 1, "kind": recipe.get("kind", "external"), "name": recipe["name"],
         "platform": recipe["platform"], "variant": recipe["variant"], "version": recipe["version"],
         "version_order": recipe.get("version_order") or version_order(recipe["version"]),
         "filename": recipe.get("filename", Path(recipe["destination"]).name),
         "metadata": {"publisher": "StefanAlMare", "context": recipe.get("context", {}),
                      "source": recipe.get("source", "configured adapter")}}
    if file:
        m.update(sha256=digest(file), size=Path(file).stat().st_size)
    else:
        m.update(sha256=recipe.get("sha256", "0" * 64), size=1)
    return validate(m)


def compatible(found, expected):
    return found and found["version"] == expected["version"] and found["version_order"] == expected["version_order"] and found["metadata"].get("context") == expected["metadata"].get("context")


def obtain(client, recipe, allow_build=True):
    """Consume pool first; run only explicitly configured producer commands."""
    if not recipe.get("enabled", True):
        return "disabled"
    expected = manifest_for(recipe)
    destination = Path(recipe["destination"]).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and recipe.get("sha256") and digest(destination) == recipe["sha256"]:
        entry = client.enqueue(manifest_for(recipe, destination), destination)
        try:
            return client.publish_entry(entry)["status"]
        except Unavailable:
            return "spooled"
    try:
        with Lease(client, expected, client.config.get("lock_wait_seconds", 600)) as lease:
            if not lease.token:
                raise PoolError("Artifact busy: " + recipe["name"])
            found = client.lookup(expected)
            if compatible(found, expected) and (not recipe.get("sha256") or found["sha256"] == recipe["sha256"]):
                client.fetch(found, destination)
                return "pool"
            return produce(client, recipe, destination, lease, allow_build)
    except Unavailable:
        local = client.local_match(expected)
        if local:
            import shutil
            shutil.copyfile(local[1], destination)
            return "local-spool"
        return produce(client, recipe, destination, None, allow_build)


def produce(client, recipe, destination, lease, allow_build):
    command = recipe.get("command")
    url = recipe.get("url")
    if command and not allow_build:
        return "deferred"
    if bool(command) == bool(url):
        raise PoolError("Adapter must have exactly one producer: url or command")
    if url and (not recipe.get("sha256") or not url.startswith("https://")):
        raise PoolError("External downloads need HTTPS and a reviewed upstream SHA-256")
    with tempfile.TemporaryDirectory(prefix="artifact-", dir=str(client.state)) as work:
        output = Path(work) / recipe.get("filename", destination.name)
        if command:
            if not isinstance(command, list) or not command or any(not isinstance(x, str) for x in command):
                raise PoolError("command must be an argv array (no shell)")
            argv = [x.replace("{output}", str(output)) for x in command]
            run_command(argv, cwd=recipe.get("cwd"), stream=True)
        else:
            with urllib.request.urlopen(url, timeout=60) as response, open(output, "xb") as f:
                while True:
                    check_stop()
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
        if not output.is_file():
            raise PoolError("Adapter did not create {output}")
        m = manifest_for(recipe, output)
        if recipe.get("sha256") and m["sha256"] != recipe["sha256"]:
            raise PoolError("External artifact differs from upstream SHA-256")
        entry = client.enqueue(m, output)
        os.replace(output, destination)
        if lease and not lease.lost:
            try:
                return client.publish_entry(entry, lease)["status"]
            except Unavailable:
                return "spooled"
        return "spooled"


def refresh(client, allow_build=True):
    results = []
    for recipe in client.config.get("artifacts", []):
        check_stop()
        results.append({"name": recipe["name"], "status": obtain(client, recipe, allow_build)})
    return results
