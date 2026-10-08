"""Local release gates: bind signed bundle resources to the exact Git source."""
import argparse
import hashlib
import json
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "0.3.5"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def sources():
    paths = [ROOT / "entry.py", ROOT / "macos/Info.plist", ROOT / "macos/HomebrewPool.icns",
             ROOT / "macos/HomebrewPoolMenu.swift", ROOT / "build-macos.sh"]
    paths += sorted((ROOT / "pool").glob("*.py"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def clean_commit():
    branch = run("git", "-C", str(ROOT), "branch", "--show-current")
    if branch != "fix/provenance-v0.3.5":
        raise SystemExit("Release requires the authorized fix/provenance-v0.3.5 branch")
    if run("git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"):
        raise SystemExit("Commit reviewed sources before building/notarizing release artifacts")
    return run("git", "-C", str(ROOT), "rev-parse", "HEAD")


def check_bundle(app, require_release=False):
    resources = app / "Contents/Resources"
    receipt = json.loads((resources / "SourceManifest.json").read_text())
    if receipt["sources"] != sources():
        raise SystemExit("Build source hashes differ from the current release sources")
    if require_release and receipt["commit"] != clean_commit():
        raise SystemExit("Signed bundle was built from another commit")
    embedded = resources / "client"
    expected = {"entry.py"} | {"pool/" + p.name for p in (ROOT / "pool").glob("*.py")}
    actual = {str(p.relative_to(embedded)) for p in embedded.rglob("*") if p.is_file()}
    if actual != expected:
        raise SystemExit("Unexpected or missing files in embedded client")
    expected_bundle = {"Contents/Info.plist", "Contents/MacOS/HomebrewPoolMenu",
                       "Contents/Resources/HomebrewPool.icns", "Contents/Resources/SourceManifest.json",
                       "Contents/_CodeSignature/CodeResources"}
    expected_bundle |= {"Contents/Resources/client/" + path for path in expected}
    actual_bundle = {str(p.relative_to(app)) for p in app.rglob("*") if p.is_file()}
    if actual_bundle != expected_bundle:
        raise SystemExit("Unexpected or missing files in application bundle")
    for path in expected:
        if (embedded / path).read_bytes() != (ROOT / path).read_bytes():
            raise SystemExit("Embedded source differs: " + path)
    for origin, target in (("macos/Info.plist", "Contents/Info.plist"),
                           ("macos/HomebrewPool.icns", "Contents/Resources/HomebrewPool.icns")):
        if (ROOT / origin).read_bytes() != (app / target).read_bytes():
            raise SystemExit("Bundle resource differs: " + origin)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if (info["CFBundleShortVersionString"], info["CFBundleVersion"]) != (VERSION, "35"):
        raise SystemExit("Unexpected bundle version/build")
    if run("lipo", "-archs", str(app / "Contents/MacOS/HomebrewPoolMenu")) != "x86_64":
        raise SystemExit("Expected Intel x86_64 binary")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    if require_release:
        signature = subprocess.run(["codesign", "-dv", "--verbose=4", str(app)], text=True, capture_output=True, check=True).stderr
        if "TeamIdentifier=YWVVK7QZ6X" not in signature or "runtime" not in signature or "Authority=Developer ID Application:" not in signature or "Timestamp=" not in signature:
            raise SystemExit("Expected timestamped Developer ID hardened runtime signature")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["record-build", "verify", "verify-release"])
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    if args.mode == "record-build":
        commit = run("git", "-C", str(ROOT), "rev-parse", "HEAD")
        receipt = dict(version=VERSION, commit=commit, sources=sources(),
                       clean=not bool(run("git", "-C", str(ROOT), "status", "--porcelain")))
        (args.app / "Contents/Resources/SourceManifest.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    else:
        result = check_bundle(args.app, args.mode == "verify-release")
        if args.mode == "verify-release" and not result["clean"]:
            raise SystemExit("Bundle was built from an uncommitted checkout")
        print("Verified bundle source identity: " + result["commit"])
