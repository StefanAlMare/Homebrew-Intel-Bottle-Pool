"""Verify downloaded official v0.3.5 source against release and pinned snapshot."""
import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "validation/upstream-v035"
PIN = "5158c90fb92db54cb0d765a02e0ef3ec56ed0da3"


def main():
    archive = EVIDENCE / "Homebrew-Intel-Bottle-Pool-v0.3.5-source.zip"
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    release = json.loads((EVIDENCE / "release.json").read_text())
    asset = next(x for x in release["assets"] if x["name"] == archive.name)
    assert asset["digest"] == "sha256:" + checksum
    assert checksum + "  " + archive.name in (EVIDENCE / "SHA256SUMS.txt").read_text().splitlines()
    assert json.loads((EVIDENCE / "annotated-tag.json").read_text())["object"]["sha"] == PIN
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        official = {x.filename.split("/", 1)[1]: zipped.read(x) for x in zipped.infolist() if not x.is_dir()}
    with tarfile.open(EVIDENCE / "commit-5158c90.tar.gz", "r:gz") as tar:
        snapshot = {x.name.split("/", 1)[1]: tar.extractfile(x).read() for x in tar if x.isfile()}
    mismatched = [name for name, content in official.items() if snapshot.get(name) != content]
    assert not mismatched, mismatched
    changes = {}
    for name, content in official.items():
        current = ROOT / name
        changes[name] = "missing" if not current.exists() else "identical" if current.read_bytes() == content else "modified"
    old_swift = official["macos/HomebrewPoolMenu.swift"].decode()
    new_swift = (ROOT / "macos/HomebrewPoolMenu.swift").read_text()
    funcs = lambda text: set(re.findall(r"func\s+(\w+)\s*\(", text))
    removed = sorted(funcs(old_swift) - funcs(new_swift))
    assert not removed, removed
    report = dict(upstream_commit=PIN, archive_sha256=checksum, release_digest_matches=True,
        published_checksum_matches=True, tag_target_matches=True,
        all_official_archive_files_match_commit=True, official_files=len(official),
        missing_official_files=[x for x, state in changes.items() if state == "missing"],
        file_comparison=changes, swift_removed_functions=removed,
        swift_added_functions=sorted(funcs(new_swift) - funcs(old_swift)),
        scope="HTTP GET only; no GitHub writes/Actions/CI/clone/fetch")
    (ROOT / "validation/parity.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
