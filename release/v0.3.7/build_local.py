"""Reproducible local app build. No Git, downloads, signing account or deployment."""
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
BUILD.mkdir(exist_ok=True)
DIST.mkdir(exist_ok=True)
APP = DIST / "Homebrew Pool.app"
if APP.exists(): shutil.rmtree(APP)
contents = APP / "Contents"
resources = contents / "Resources"
(contents / "MacOS").mkdir(parents=True)
resources.mkdir()
shutil.copytree(SOURCE / "pool", resources / "client/pool", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copy2(SOURCE / "entry.py", resources / "client/entry.py")
shutil.copy2(SOURCE / "macos/HomebrewPool.icns", resources / "HomebrewPool.icns")
shutil.copy2(SOURCE / "LICENSE", resources / "LICENSE")
if (ROOT / "GUIDE.txt").exists(): shutil.copy2(ROOT / "GUIDE.txt", resources / "Core2-Legacy-Guide.txt")
info = plistlib.loads((SOURCE / "macos/Info.plist").read_bytes())
info.update(CFBundleIdentifier="com.stefanalmare.homebrew-intel-bottle-pool",
            PoolUpgradePreserveSettings=True, PoolUpgradePreferredProfile="test",
            CFBundleName="Homebrew Pool", CFBundleDisplayName="Homebrew Pool",
            CFBundleShortVersionString="0.3.7", CFBundleVersion="38", LSMinimumSystemVersion="12.0")
(contents / "Info.plist").write_bytes(plistlib.dumps(info))
(BUILD / "main.swift").write_bytes((SOURCE / "macos/HomebrewPoolMenu.swift").read_bytes())
env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(BUILD / "module-cache"),
           SWIFT_MODULECACHE_PATH=str(BUILD / "module-cache"))
sdk = subprocess.check_output(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
for arch in ("x86_64", "arm64"):
    if "--resources-only" in sys.argv:
        if not (BUILD / ("HomebrewPoolMenu-" + arch)).is_file():
            raise SystemExit("Compiled native slice missing; run a full build")
        continue
    cpu_flags = ["-target-cpu", "core2", "-Xcc", "-march=core2"] if arch == "x86_64" else []
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-O", "-sdk", sdk,
                    "-target", arch + "-apple-macos12.0", "-module-cache-path", str(BUILD / "module-cache"),
                    *cpu_flags,
                    str(BUILD / "main.swift"), str(SOURCE / "macos/Core2Controller.swift"), str(SOURCE / "macos/UpgradePaths.swift"), str(SOURCE / "macos/GUICommand.swift"),
                    "-o", str(BUILD / ("HomebrewPoolMenu-" + arch)),
                    "-framework", "AppKit", "-framework", "UserNotifications"], env=env, check=True)
subprocess.run(["/usr/bin/lipo", "-create", str(BUILD / "HomebrewPoolMenu-x86_64"),
                str(BUILD / "HomebrewPoolMenu-arm64"), "-output", str(contents / "MacOS/HomebrewPoolMenu")], check=True)
manifest = {"product": "core2-legacy-upgrade", "version": "0.3.7", "build": 38, "repository_access": False,
            "x86_cpu_target": "core2",
            "installed_application_modified": False,
            "sources": {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(SOURCE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}}
(resources / "SourceManifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(APP)], check=True)
subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(APP)], check=True)
print(APP)
