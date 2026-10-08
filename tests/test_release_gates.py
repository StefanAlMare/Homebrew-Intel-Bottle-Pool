"""Publication cannot contact GitHub before the local product is verified."""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from package_release import asset_names, verify_manifest

ROOT = Path(__file__).resolve().parents[1]


class PublicationBoundaryTests(unittest.TestCase):
    def check_local_failure(self, failure_call):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            count, contacted = root / 'python-count', root / 'github-contacted'
            python = root / 'python3'
            python.write_text('''#!/bin/sh
n=0
[ ! -f "$COUNT" ] || n=$(cat "$COUNT")
n=$((n + 1))
printf '%s' "$n" > "$COUNT"
[ "$n" -ne "$FAILURE_CALL" ]
''')
            github = root / 'gh'
            github.write_text('#!/bin/sh\ntouch "$CONTACTED"\nexit 99\n')
            python.chmod(0o755)
            github.chmod(0o755)
            result = subprocess.run(['sh', str(ROOT / 'publish-release.sh')],
                                    env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                                             COUNT=str(count), CONTACTED=str(contacted),
                                             FAILURE_CALL=str(failure_call)), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(contacted.exists(), 'GitHub was contacted before local verification finished')
            self.assertEqual(count.read_text(), str(failure_call))

    def test_invalid_signed_app_stops_before_github(self):
        self.check_local_failure(1)

    def test_unnotarized_distribution_stops_before_github(self):
        self.check_local_failure(2)

    def test_failing_local_suite_stops_before_github(self):
        self.check_local_failure(3)


class CompleteAssetManifestTests(unittest.TestCase):
    def test_every_public_document_and_diagram_is_required(self):
        required = {'README.md', 'INSTALLATION.md', 'QUICKSTART.txt', 'RELEASE_NOTES.md',
                    'VALIDATION.md', 'CHANGELOG.md', 'RELEASING.md',
                    'how-it-works.png', 'how-it-works.svg'}
        self.assertTrue(required.issubset(asset_names()))
        self.assertNotIn('HANDOVER.md', asset_names())
        self.assertNotIn('STAGING_VERIFICATION.json', asset_names())

    def test_manifest_with_missing_document_is_rejected_even_if_listed_hashes_are_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = set(asset_names(False)) - {'SHA256SUMS.txt'}
            for name in names:
                (root / name).write_bytes(name.encode())
            lines = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() + '  ' + name
                     for name in names}
            (root / 'SHA256SUMS.txt').write_text('\n'.join(lines.values()) + '\n')
            self.assertEqual(set(verify_manifest(root, False)), names)
            lines.pop('INSTALLATION.md')
            (root / 'SHA256SUMS.txt').write_text('\n'.join(lines.values()) + '\n')
            with self.assertRaisesRegex(SystemExit, 'every required release asset'):
                verify_manifest(root, False)
