"""Schema-1 publication recovery without overwrites or unproven substitutions."""
from unittest.mock import patch

from pool.client import RemoteError
from pool.common import digest, key_for
from test_pool import FakeBrew, Fixture


class PublicationRecoveryTests(Fixture):
    def bottle(self, contents, kind='brew-local-bottle'):
        mac = FakeBrew(self.clients[0])
        manifest = mac.manifest(mac.info('demo'), kind)
        manifest['metadata']['build_inputs'] = {}
        payload = self.root / ('bottle-' + str(len(contents)))
        payload.write_bytes(contents)
        manifest.update(sha256=digest(payload), size=payload.stat().st_size)
        return manifest, payload

    def test_two_offline_compilations_reuse_verified_winner_without_overwrite(self):
        first, source = self.bottle(b'first compiled archive')
        self.publish(first, source)
        second, source = self.bottle(b'independently compiled archive')
        client = self.clients[1]
        entry = client.enqueue(second, source)
        with patch.object(client, 'fetch', wraps=client.fetch) as fetch:
            result = client.publish_entry(entry)
        self.assertEqual(result['status'], 'reused')
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(entry.exists())
        self.assertEqual(self.store.current(key_for(first))['sha256'], first['sha256'])
        self.assertEqual((self.store.objects / key_for(first) / first['sha256']).read_bytes(), b'first compiled archive')

    def test_same_rank_changed_context_is_retained_and_never_substituted(self):
        first, source = self.bottle(b'original')
        self.publish(first, source)
        second, source = self.bottle(b'changed build inputs')
        # Simulate an incompatible old/bad key: the client must still fail closed.
        second['metadata']['context']['formula_sha256'] = 'f' * 64
        entry = self.clients[1].enqueue(second, source)
        with self.assertRaises(RemoteError):
            self.clients[1].publish_entry(entry)
        self.assertTrue(entry.exists())
        self.assertEqual(self.store.current(key_for(first))['sha256'], first['sha256'])

    def test_upstream_checksum_conflict_never_substitutes_other_bytes(self):
        first, source = self.bottle(b'upstream first', 'brew-upstream-bottle')
        self.publish(first, source)
        second, source = self.bottle(b'upstream changed', 'brew-upstream-bottle')
        entry = self.clients[1].enqueue(second, source)
        with self.assertRaises(RemoteError):
            self.clients[1].publish_entry(entry)
        self.assertTrue(entry.exists())

    def test_changed_build_only_inputs_never_substitute_winner(self):
        first, source = self.bottle(b'first build')
        self.publish(first, source)
        second, source = self.bottle(b'new compiler build')
        second['metadata']['build_inputs'] = {'compiler': {'version': '2.0', 'source': 'f' * 64}}
        entry = self.clients[1].enqueue(second, source)
        with self.assertRaises(RemoteError):
            self.clients[1].publish_entry(entry)
        self.assertTrue(entry.exists())

    def test_failed_winner_verification_retains_local_payload(self):
        first, source = self.bottle(b'published first')
        self.publish(first, source)
        second, source = self.bottle(b'local second')
        client = self.clients[1]
        entry = client.enqueue(second, source)
        with patch.object(client, 'fetch', side_effect=RemoteError(409, 'Stored artifact failed SHA-256 verification')):
            with self.assertRaises(RemoteError):
                client.publish_entry(entry)
        self.assertEqual((entry / 'payload').read_bytes(), b'local second')

    def test_legacy_googletest_spool_quarantined_without_network_or_byte_changes(self):
        manifest, source = self.bottle(b'legacy googletest', 'brew-upstream-bottle')
        manifest.update(name='homebrew/core/googletest', version='1.18.0')
        manifest['metadata']['context'].pop('dependency_graph')
        manifest['metadata']['context'].pop('variant_identity')
        client = self.clients[0]
        entry = client.enqueue(manifest, source)
        before_manifest = (entry / 'manifest.json').read_bytes()
        with patch.object(client, 'upload', side_effect=AssertionError('legacy upload')):
            self.assertEqual(client.sync(), ['quarantined'])
            self.assertEqual(client.sync(), [])
        saved = client.spool / 'quarantine' / entry.name
        self.assertEqual((saved / 'manifest.json').read_bytes(), before_manifest)
        self.assertEqual((saved / 'payload').read_bytes(), b'legacy googletest')
        self.assertFalse(list(self.store.objects.glob('*/manifest.json')))

    def test_external_schema1_spool_is_still_published(self):
        manifest, source = self.artifact()
        self.assertEqual(self.publish(manifest, source)['status'], 'published')

    def test_target_recipe_change_changes_variant_even_without_dependencies(self):
        mac = FakeBrew(self.clients[0])
        first = mac.manifest(mac.info('demo'))
        mac.records['demo']['ruby_source_checksum']['sha256'] = 'f' * 64
        second = mac.manifest(mac.info('demo'))
        self.assertNotEqual(key_for(first), key_for(second))
        self.assertIn('variant_identity', first['metadata']['context'])
