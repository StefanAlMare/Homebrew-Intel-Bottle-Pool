import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pool.legacy import private_write
from pool.legacy_policy import Denied, sha
from pool.legacy_build import build, review_request
from test_policy import fixture, h


class SourceBuildGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.p, manifest, hosts, _ = fixture()
        self.token = 'fixture-token-' + h('builder')
        machine = self.p['machines']['fixture-penryn']
        machine['roles'].append('build'); machine['dedicated_build_host'] = True
        machine['credential_sha256'] = hashlib.sha256(self.token.encode()).hexdigest()
        files = {}
        for name in ('fixture.rb', 'clang', 'sdk.json', 'source.tar.gz', 'patch.diff'):
            path = self.root / name; path.write_bytes(('fixture-' + name).encode())
            files[name] = str(path)
        self.request = {'schema': 1, 'pool_id': self.p['pool_id'], 'policy_revision': 1,
            'machine_id': 'fixture-penryn', 'name': 'homebrew/core/fixture',
            'context': hosts['fixture-penryn']['context'], 'cpu_target': 'penryn',
            'required_cpu_features': manifest['required_cpu_features'],
            'dependencies': manifest['dependencies'], 'version': '1.2.3', 'revision': 0, 'rebuild': 0,
            'compiler': 'fixture clang', 'flags': manifest['provenance']['flags'],
            'formula_file': files['fixture.rb'], 'formula_sha256': self.hash_file(files['fixture.rb']),
            'toolchain_file': files['clang'], 'toolchain_sha256': self.hash_file(files['clang']),
            'sdk_manifest_file': files['sdk.json'], 'sdk_sha256': self.hash_file(files['sdk.json']),
            'source_files': {files['source.tar.gz']: self.hash_file(files['source.tar.gz'])},
            'patch_files': {files['patch.diff']: self.hash_file(files['patch.diff'])}}
        self.policy_file = self.root / 'policy.json'
        self.approve()
        self.client = SimpleNamespace(policy_file=self.policy_file, token=self.token,
            config={'machine_id': 'fixture-penryn', 'allow_builds': True,
                    'brew': '/not-executed/brew', 'cellar': str(self.root / 'Cellar')},
            host_provider=lambda _: hosts['fixture-penryn'], state=self.root / 'state')

    @staticmethod
    def hash_file(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def approve(self):
        self.p['build_reviews'] = {sha(self.request): {'status': 'approved', 'policy_revision': 1,
                                                     'reviewer_key_id': h('fixture-reviewer')}}
        private_write(self.policy_file, self.p)

    def test_review_produces_exact_core2_command_without_executing_homebrew(self):
        with patch('subprocess.run', side_effect=AssertionError('must not run')):
            result = review_request(self.client, self.request)
        self.assertIn('--bottle-arch=penryn', result['commands'][0])
        self.assertIn('--ignore-dependencies', result['commands'][0])
        self.assertTrue(result['requires_current_repository_authorization'])

    def test_build_requires_current_repository_authorization_before_any_probe(self):
        with patch('subprocess.run', side_effect=AssertionError('must not run')):
            with self.assertRaises(Denied): build(self.client, self.request)

    def test_existing_formula_is_preserved_even_on_approved_dedicated_builder(self):
        brew = self.root / 'brew'; brew.write_text('unused'); brew.chmod(0o700)
        self.client.config['brew'] = str(brew)
        keg = Path(self.client.config['cellar']) / 'fixture'; keg.mkdir(parents=True)
        marker = keg / 'preserve'; marker.write_text('stable')
        with patch('subprocess.run', side_effect=AssertionError('must not run')):
            with self.assertRaises(Denied): build(self.client, self.request, True)
        self.assertEqual(marker.read_text(), 'stable')

    def test_no_builder_role_or_dedicated_host_means_no_build(self):
        self.p['machines']['fixture-penryn']['dedicated_build_host'] = False
        private_write(self.policy_file, self.p)
        with self.assertRaises(Denied): review_request(self.client, self.request)

    def test_recipe_patch_toolchain_source_and_flags_cannot_drift(self):
        for field in ('formula_file', 'toolchain_file', 'sdk_manifest_file'):
            path = Path(self.request[field]); original = path.read_bytes(); path.write_bytes(b'changed')
            with self.subTest(field=field), self.assertRaises(Denied): review_request(self.client, self.request)
            path.write_bytes(original)
        self.request['flags']['cflags'].append('-mpopcnt'); self.approve()
        with self.assertRaises(Denied): review_request(self.client, self.request)

    def test_reviewed_true_without_exact_build_approval_is_rejected(self):
        self.p['build_reviews'] = {}; private_write(self.policy_file, self.p)
        self.request['reviewed'] = True
        with self.assertRaises(Denied): review_request(self.client, self.request)

    def test_source_inventory_cannot_override_formula_hash(self):
        self.request['source_files'][self.request['formula_file']] = h('wrong')
        self.approve()
        with self.assertRaises(Denied): review_request(self.client, self.request)


if __name__ == '__main__': unittest.main()
