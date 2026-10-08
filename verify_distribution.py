"""Verify final local release containers before any GitHub publication."""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from release_checks import ROOT, VERSION, check_bundle, clean_commit
from package_release import DOCUMENTS, DIAGRAMS, verify_manifest


def checked(*args):
    return subprocess.check_output(args, text=True).strip()


def tree(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()}


def verify(dist, notarized=True):
    commit = clean_commit()
    verify_manifest(dist, notarized)
    for name in DOCUMENTS:
        if (dist / name).read_bytes() != (ROOT / name).read_bytes():
            raise SystemExit("Release document differs from committed source: " + name)
    for name in DIAGRAMS:
        if (dist / name).read_bytes() != (ROOT / "docs/assets" / name).read_bytes():
            raise SystemExit("Release diagram differs from committed source: " + name)
    stem = "Homebrew-Intel-Bottle-Pool-v" + VERSION
    app, dmg = dist / "Homebrew Pool.app", dist / (stem + ".dmg")
    check_bundle(app, True)
    checked("hdiutil", "verify", str(dmg))
    checked("codesign", "--verify", "--strict", str(dmg))
    signature = subprocess.run(["codesign", "-dv", "--verbose=4", str(dmg)], text=True, capture_output=True, check=True).stderr
    if "TeamIdentifier=YWVVK7QZ6X" not in signature:
        raise SystemExit("DMG has an unexpected signing team")
    if notarized:
        for item in (app, dmg):
            checked("xcrun", "stapler", "validate", str(item))
        checked("spctl", "--assess", "--type", "execute", str(app))
        checked("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", str(dmg))
        for item in ("app", "dmg"):
            receipt = json.loads((dist / (item + "-notarization.json")).read_text())
            if receipt.get("status") != "Accepted":
                raise SystemExit("Notarization was not Accepted: " + item)
            log = json.loads((dist / (item + "-notarization-log.json")).read_text())
            if not receipt.get("id") or log.get("jobId") != receipt["id"] or log.get("status") != "Accepted":
                raise SystemExit("Notarization log does not confirm this submission: " + item)
    with tempfile.TemporaryDirectory(prefix="pool-release-verify-") as temporary:
        temporary = Path(temporary)
        unpacked = temporary / "zip"
        checked("ditto", "-x", "-k", str(dist / (stem + ".zip")), str(unpacked))
        zip_app = unpacked / "Homebrew Pool.app"
        check_bundle(zip_app, True)
        if tree(zip_app) != tree(app):
            raise SystemExit("ZIP bundle differs from signed app")
        mount = temporary / "dmg"
        mount.mkdir()
        checked("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg))
        try:
            if (mount / "Read Me.txt").read_bytes() != (ROOT / "QUICKSTART.txt").read_bytes():
                raise SystemExit("DMG Quick Start differs from release source")
            if (mount / "License.txt").read_bytes() != (ROOT / "LICENSE").read_bytes():
                raise SystemExit("DMG license differs from release source")
            if not (mount / "Applications").is_symlink() or (mount / "Applications").readlink() != Path("/Applications"):
                raise SystemExit("DMG Applications shortcut has an unexpected target")
            dmg_app = mount / "Homebrew Pool.app"
            check_bundle(dmg_app, True)
            if tree(dmg_app) != tree(app):
                raise SystemExit("DMG bundle differs from signed app")
        finally:
            checked("hdiutil", "detach", str(mount))
        source_dir = temporary / "source"
        checked("ditto", "-x", "-k", str(dist / (stem + "-source.zip")), str(source_dir))
        source_root = source_dir / stem
        tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")
        expected_paths = set(filter(None, tracked))
        actual_paths = {str(p.relative_to(source_root)) for p in source_root.rglob("*") if p.is_file()}
        if actual_paths != expected_paths:
            raise SystemExit("Unexpected or missing files in source ZIP")
        for path in sorted(expected_paths):
            expected = subprocess.check_output(["git", "-C", str(ROOT), "show", commit + ":" + path])
            if (source_root / path).read_bytes() != expected:
                raise SystemExit("Source ZIP differs from release commit: " + path)
    subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS.txt"], cwd=dist, check=True)
    print("Verified " + ("notarized release" if notarized else "UNNOTARIZED staging only") + ": " + commit)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-only", action="store_true")
    args = parser.parse_args()
    verify(ROOT / "dist", not args.staging_only)
