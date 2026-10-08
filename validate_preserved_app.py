"""Read-only installed-app audit and verify a separate official v0.3.5 reserve."""
import hashlib
import json
import plistlib
import subprocess
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent
evidence = root / "validation/upstream-v035"
archive = evidence / "Homebrew-Intel-Bottle-Pool-v0.3.5.zip"
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
asset = next(a for a in json.loads((evidence / "release.json").read_text())["assets"] if a["name"] == archive.name)
assert asset["digest"] == "sha256:" + checksum
assert checksum + "  " + archive.name in (evidence / "SHA256SUMS.txt").read_text().splitlines()
with zipfile.ZipFile(archive) as zipped:
    assert zipped.testzip() is None
reserve = evidence / "official-app"
if not reserve.exists():
    subprocess.run(["ditto", "-x", "-k", str(archive), str(reserve)], check=True)

def inspect(app):
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    return dict(path=str(app), version=info["CFBundleShortVersionString"],
                build=info["CFBundleVersion"], bundle_id=info["CFBundleIdentifier"],
                signature_valid=True)

backup = inspect(reserve / "Homebrew Pool.app")
assert backup["version"] == "0.3.5" and backup["build"] == "35"
subprocess.run(["xcrun", "stapler", "validate", backup["path"]], check=True)
subprocess.run(["spctl", "--assess", "--type", "execute", "--verbose=2", backup["path"]], check=True)
installed = inspect(Path("/Applications/Homebrew Pool.app"))
report = dict(installed=installed, official_v035_reserve=backup, reserve_sha256=checksum,
              reserve_stapled=True, reserve_gatekeeper_accepted=True,
              installed_or_launched=False,
              limitation="Installed app already reports 0.3.6; no automatic rollback or production queue access performed.")
(root / "validation/preserved-app.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
