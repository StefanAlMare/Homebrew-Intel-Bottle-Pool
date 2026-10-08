"""Assemble only committed public release assets on the local Mac."""
import argparse
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from release_checks import ROOT, VERSION, check_bundle, clean_commit

STEM = 'Homebrew-Intel-Bottle-Pool-v' + VERSION + '-standard'
DOCUMENTS = ['README.md', 'INSTALLATION.md', 'QUICKSTART.txt', 'RELEASE_NOTES.md',
             'VALIDATION.md', 'CHANGELOG.md', 'RELEASING.md', 'SERVER_SETUP.md',
             'USER_GUIDE.md', 'IMPORT_PROVENANCE.md', 'PARITY_REPORT.md']
DIAGRAMS = ['how-it-works.png', 'how-it-works.svg']
NOTARY = ['app-notarization.json', 'dmg-notarization.json',
          'app-notarization-log.json', 'dmg-notarization-log.json']


def asset_names(notarized=True):
    names = [STEM + '.dmg', STEM + '.zip', STEM + '-source.zip'] + DOCUMENTS + DIAGRAMS
    return names + (NOTARY if notarized else []) + ['SHA256SUMS.txt']


def verify_manifest(dist, notarized=True):
    expected = set(asset_names(notarized)) - {'SHA256SUMS.txt'}
    entries = {}
    for line in (dist / 'SHA256SUMS.txt').read_text().splitlines():
        parts = line.split('  ', 1)
        if len(parts) != 2 or parts[1] in entries:
            raise SystemExit('Invalid or duplicate checksum entry')
        checksum, name = parts
        if name not in expected or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
            raise SystemExit('Unexpected asset or checksum in manifest')
        entries[name] = checksum
    if set(entries) != expected:
        raise SystemExit('Checksum manifest does not cover every required release asset')
    for name, expected_hash in entries.items():
        if hashlib.sha256((dist / name).read_bytes()).hexdigest() != expected_hash:
            raise SystemExit('Release checksum mismatch: ' + name)
    return entries


def assemble(notarized=True):
    raise SystemExit("Use local finalize-release.sh; Git-based packaging is disabled")
    commit = clean_commit()
    dist = ROOT / 'dist'
    app = dist / 'Homebrew Pool.app'
    check_bundle(app, True)
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app),
                    str(dist / (STEM + '.zip'))], check=True)
    with tempfile.TemporaryDirectory(prefix='pool-source-') as temporary:
        source = Path(temporary) / STEM
        source.mkdir()
        archive = subprocess.check_output(['git', '-C', str(ROOT), 'archive', '--format=tar', commit])
        subprocess.run(['tar', '-xf', '-', '-C', str(source)], input=archive, check=True)
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(source),
                        str(dist / (STEM + '-source.zip'))], check=True)
    for name in DOCUMENTS:
        shutil.copy2(ROOT / name, dist / name)
    for name in DIAGRAMS:
        shutil.copy2(ROOT / 'docs/assets' / name, dist / name)
    names = asset_names(notarized)
    checksums = ''.join(hashlib.sha256((dist / name).read_bytes()).hexdigest() + '  ' + name + '\n'
                        for name in names if name != 'SHA256SUMS.txt')
    (dist / 'SHA256SUMS.txt').write_text(checksums)
    verify_manifest(dist, notarized)
    print(('Final' if notarized else 'UNNOTARIZED local staging') + ' assets assembled from ' + commit)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--staging-only', action='store_true')
    parser.add_argument('--list-assets', action='store_true')
    args = parser.parse_args()
    if args.list_assets:
        print('\n'.join(asset_names(not args.staging_only)))
    else:
        assemble(not args.staging_only)
