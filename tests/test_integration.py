import copy
import hashlib
import io
import json
import os
import ssl
import subprocess
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from pool.common import PoolError, validate
from pool.legacy_policy import Denied, artifact_key, manifest_digest
from pool.legacy import (LegacyClient, LegacyServer, LegacyStore, authenticate,
                         inspect_archive, install_verified, load_policy,
                         namespace, plan_for, private_json, private_write)
from pool.legacy_cli import main as cli_main
from test_policy import fixture, approve, h, plan


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.p, self.m, self.hosts, _ = fixture()
        self.m['filename'] = 'fixture--1.2.3.tahoe.bottle.tar.gz'
        self.tokens = {name: 'fixture-token-' + h(name) for name in self.p['machines']}
        for name, machine in self.p['machines'].items():
            machine['credential_sha256'] = hashlib.sha256(self.tokens[name].encode()).hexdigest()
        self.bottle = self.root / self.m['filename']
        recipe = b'class Fixture < Formula\nend\n'
        self.m['embedded_recipe_sha256'] = hashlib.sha256(recipe).hexdigest()
        self.m['provenance']['embedded_recipe_sha256'] = self.m['embedded_recipe_sha256']
        receipt = {'built_as_bottle': True, 'poured_from_bottle': False, 'arch': 'x86_64',
                   'used_options': [], 'runtime_dependencies': []}
        with tarfile.open(self.bottle, 'w:gz') as archive:
            for name, data in [('fixture/1.2.3/.brew/fixture.rb', recipe),
                               ('fixture/1.2.3/INSTALL_RECEIPT.json', json.dumps(receipt).encode()),
                               ('fixture/1.2.3/bin/fixture', b'SYNTHETIC NONEXECUTABLE TEST DATA')]:
                member = tarfile.TarInfo(name); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        self.m['size'] = self.bottle.stat().st_size
        self.m['sha256'] = hashlib.sha256(self.bottle.read_bytes()).hexdigest()
        self.p['reviews'] = {}; approve(self.p, self.m)
        self.policy = self.root / 'policy.json'; private_write(self.policy, self.p)
        self.store = LegacyStore(self.root / 'server', self.policy)
        self.server = LegacyServer(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop)
        self.url = 'http://127.0.0.1:%s' % self.server.server_address[1]
        self.client = self.make_client('fixture-penryn')

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.store.close(); self.thread.join(2)

    def make_client(self, name, url=None, ca=None):
        credential = self.root / (name + '-token')
        credential.write_text(self.tokens[name]); credential.chmod(0o600)
        config = {'channel': 'core2-legacy', 'auto_import_verified_bottles': False,
                  'pool_id': self.p['pool_id'], 'policy_file': str(self.policy), 'url': url or self.url,
                  'machine_id': name, 'token_file': str(credential),
                  'state_dir': str(self.root / ('client-' + name)),
                  'prefix': '/usr/local', 'cellar': '/usr/local/Cellar', 'brew': '/not-executed/brew'}
        if ca: config['ca_file'] = str(ca)
        return LegacyClient(config, host_provider=lambda config: copy.deepcopy(self.hosts[config['machine_id']]))

    def envelope(self):
        return {'manifest': self.m, 'host': self.hosts['fixture-penryn']}

    def auth(self, name='fixture-penryn'):
        return 'Bearer ' + self.tokens[name]

    def test_real_loopback_publish_lookup_download_keeps_local_evidence(self):
        inspect_archive(self.bottle, self.m)
        entry = self.client.enqueue(self.m, self.bottle, plan(self.m))
        result = self.client.upload(entry)
        self.assertEqual(result['status'], 'published')
        self.assertTrue((entry / 'payload').exists())
        self.assertEqual(self.client.lookup(self.m, plan(self.m))['key'], artifact_key(self.m))
        target = self.client.fetch(self.m, plan(self.m))
        self.assertEqual(target.read_bytes(), self.bottle.read_bytes())
        inspect_archive(target, self.m)
        self.assertEqual(target.name, self.m['filename'])

    def test_conroe_cannot_download_penryn_via_direct_server_request(self):
        entry = self.client.enqueue(self.m, self.bottle, plan(self.m)); self.client.upload(entry)
        conroe = self.make_client('fixture-conroe')
        with self.assertRaises(Denied): conroe.fetch(self.m, plan(self.m))
        with self.assertRaises(Denied):
            with conroe.request('download', {'manifest': self.m, 'host': self.hosts['fixture-conroe']}): pass

    def test_global_and_unlabelled_artifacts_refused_on_actual_private_route(self):
        for change in ({'channel': 'global'}, {'schema': 1}, {'pool_id': 'other'}):
            body = self.envelope(); body['manifest'] = dict(self.m, **change)
            with self.subTest(change=change), self.assertRaises(Denied):
                with self.client.request('lease', body): pass

    def test_wrong_token_and_duplicate_credentials_fail_closed(self):
        with self.assertRaises(Denied): authenticate(self.p, 'Bearer ' + 'x' * 64)
        p = copy.deepcopy(self.p)
        p['machines']['fixture-conroe']['credential_sha256'] = p['machines']['fixture-penryn']['credential_sha256']
        with self.assertRaises(Denied): authenticate(p, self.auth())

    def test_lease_owner_expiry_and_revocation_checked(self):
        lease = self.store.acquire(self.auth(), self.m, self.hosts['fixture-penryn'])
        with self.assertRaises(Denied): self.store.renew(self.auth('fixture-conroe'), lease['key'], lease['lease'])
        self.store.leases[lease['key']]['expires'] = 0
        with self.assertRaises(Denied): self.store.renew(self.auth(), lease['key'], lease['lease'])
        lease = self.store.acquire(self.auth(), self.m, self.hosts['fixture-penryn'])
        self.p['machines']['fixture-penryn']['enabled'] = False; private_write(self.policy, self.p)
        with self.assertRaises(Denied): self.store.commit(self.auth(), lease['key'], lease['lease'], self.bottle)
        self.assertFalse((self.store.objects / artifact_key(self.m)).exists())

    def test_policy_change_blocks_queued_entry_before_network(self):
        entry = self.client.enqueue(self.m, self.bottle, plan(self.m))
        self.p['reviews'] = {}; private_write(self.policy, self.p)
        with patch.object(self.client, 'request', side_effect=AssertionError('network must not be used')):
            with self.assertRaises(Denied): self.client.upload(entry)
        self.assertTrue((entry / 'payload').exists())

    def test_server_checks_checksum_even_when_client_bypassed(self):
        lease = self.store.acquire(self.auth(), self.m, self.hosts['fixture-penryn'])
        bad = self.root / 'corrupt'; bad.write_bytes(b'x' * self.m['size'])
        with self.assertRaises(Denied): self.store.commit(self.auth(), lease['key'], lease['lease'], bad)

    def test_upload_conflict_never_substitutes_a_global_winner(self):
        entry = self.client.enqueue(self.m, self.bottle, plan(self.m))
        self.assertEqual(self.client.upload(entry)['status'], 'published')
        self.assertEqual(self.client.upload(entry)['status'], 'exists')
        self.assertEqual(len(list(self.store.objects.iterdir())), 1)

    def test_remote_http_redirects_and_global_state_are_refused(self):
        config = dict(self.client.config, url='http://private.example')
        with self.assertRaises(Denied): LegacyClient(config)
        with self.assertRaises(Denied): namespace(self.client.state, 'other-pool')
        global_root = self.root / 'global'; global_root.mkdir(mode=0o700); (global_root / 'spool').mkdir()
        with self.assertRaises(Denied): namespace(global_root, self.p['pool_id'])
        from pool.server import Store
        with self.assertRaises(PoolError): Store(self.store.root)

    def test_global_validator_rejects_legacy_even_if_schema_relabelled(self):
        with self.assertRaises(PoolError): validate(self.m)
        m = copy.deepcopy(self.m); m.update(schema=1, channel='global')
        with self.assertRaises(PoolError): validate(m)
        old = {'schema': 1, 'kind': 'brew-local-bottle', 'metadata': {'context': {'cpu_requirement': 'x86_64-v1'}}}
        with self.assertRaises(PoolError): validate(old)

    def test_private_policy_permissions_symlinks_and_duplicate_json_denied(self):
        self.policy.chmod(0o644)
        with self.assertRaises(Denied): load_policy(self.policy)
        self.policy.chmod(0o600)
        link = self.root / 'policy-link'; link.symlink_to(self.policy)
        with self.assertRaises(OSError): load_policy(link)
        self.policy.write_text('{"schema":2,"schema":1}'); self.policy.chmod(0o600)
        with self.assertRaises(Denied): load_policy(self.policy)

    def test_archive_recipe_and_receipt_mismatch_refused(self):
        m = copy.deepcopy(self.m); m['embedded_recipe_sha256'] = h('wrong')
        with self.assertRaises(Denied): inspect_archive(self.bottle, m)

    def rewrite_archive(self, extra):
        replacement = self.root / 'rewritten.bottle.tar.gz'
        with tarfile.open(self.bottle, 'r:gz') as original, tarfile.open(replacement, 'w:gz') as target:
            for member in original.getmembers():
                target.addfile(member, original.extractfile(member) if member.isfile() else None)
            for member, data in extra:
                target.addfile(member, io.BytesIO(data) if data is not None else None)
        return replacement

    def test_archive_link_chain_cannot_escape_keg(self):
        first = tarfile.TarInfo('fixture/1.2.3/a'); first.type = tarfile.SYMTYPE; first.linkname = '.'
        second = tarfile.TarInfo('fixture/1.2.3/b'); second.type = tarfile.SYMTYPE; second.linkname = 'a/..'
        malicious = self.rewrite_archive([(first, None), (second, None)])
        with self.assertRaises(Denied): inspect_archive(malicious, self.m)
        safe = tarfile.TarInfo('fixture/1.2.3/lib/link'); safe.type = tarfile.SYMTYPE; safe.linkname = '../bin/fixture'
        self.assertEqual(inspect_archive(self.rewrite_archive([(safe, None)]), self.m)['name'], 'fixture')

    def test_duplicate_binary_archive_member_is_rejected(self):
        member = tarfile.TarInfo('fixture/1.2.3/bin/fixture'); member.size = 3
        with self.assertRaises(Denied): inspect_archive(self.rewrite_archive([(member, b'bad')]), self.m)
        m = copy.deepcopy(self.m); m['version'] = '9.9'
        with self.assertRaises(Denied): inspect_archive(self.bottle, m)

    def test_install_requires_per_operation_authorization_and_protects_python_xz_tcl(self):
        with patch('subprocess.run', side_effect=AssertionError('Homebrew must not run')):
            with self.assertRaises(Denied): install_verified(self.client, self.m, plan(self.m), self.bottle)
            for name in ('python@3.14', 'xz', 'tcl-tk', 'tcl', 'tk'):
                m = copy.deepcopy(self.m); m['name'] = 'homebrew/core/' + name
                with self.subTest(name=name), self.assertRaises(Denied):
                    install_verified(self.client, m, plan(m), self.bottle, True)

    def test_cli_default_init_is_disabled_and_status_has_no_side_effects(self):
        root = self.root / 'gui'
        with patch.dict(os.environ, {'HOMEBREW_POOL_APP_ROOT': str(root)}), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(cli_main(['status']), 0); self.assertFalse(root.exists())
            self.assertEqual(cli_main(['init']), 0)
            p = load_policy(root / 'legacy/policy.json')
            self.assertFalse(p['enabled']); self.assertFalse(p['auto_import_verified_bottles']); self.assertEqual(p['machines'], {})

    def test_missing_hardware_never_uses_configuration_as_cpu_evidence(self):
        with patch('pool.legacy.observe_host', side_effect=Denied('CPU unknown')):
            # Explicit failing provider used instead of a configuration feature override.
            client = LegacyClient(self.client.config, host_provider=lambda _: (_ for _ in ()).throw(Denied('CPU unknown')))
            with self.assertRaises(Denied): client.enqueue(self.m, self.bottle, plan(self.m))

    def test_actual_homebrew_prefix_mismatch_blocks_install_before_mutation(self):
        brew = self.root / 'fake-brew'; brew.write_text('never executed'); brew.chmod(0o700)
        self.client.config['brew'] = str(brew)
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='/different-prefix')) as runner:
            with self.assertRaises(Denied): install_verified(self.client, self.m, plan(self.m), self.bottle, True)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.args[0], [str(brew), '--prefix'])

    def test_publish_role_does_not_implicitly_grant_consumption(self):
        self.p['machines']['fixture-penryn']['roles'] = ['publish', 'test']
        private_write(self.policy, self.p)
        lease = self.store.acquire(self.auth(), self.m, self.hosts['fixture-penryn'])
        self.assertEqual(lease['key'], artifact_key(self.m))
        with self.assertRaises(Denied): self.store.read(self.auth(), self.m, self.hosts['fixture-penryn'])

    def test_v1_routes_and_path_traversal_refused(self):
        for path in ('/v1/health', '/v2/global/health', '/v2/core2-legacy/../health'):
            request = urllib.request.Request(self.url + path, headers={'Authorization': self.auth()})
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request, timeout=2, context=self.client.context)
            self.assertEqual(context.exception.code, 403); context.exception.close()


class TLSIntegrationTests(IntegrationTests):
    def setUp(self):
        super().setUp()
        self.server.shutdown(); self.thread.join(2)
        cert, key = self.root / 'server.crt', self.root / 'server.key'
        conf = self.root / 'openssl.cnf'
        conf.write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n[dn]\nCN=127.0.0.1\n[ext]\nsubjectAltName=IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n')
        subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-config', str(conf), '-keyout', str(key), '-out', str(cert)],
                       check=True, capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = 'https://127.0.0.1:%s' % self.server.server_address[1]
        self.client = self.make_client('fixture-penryn', ca=cert)

    def test_untrusted_tls_certificate_refused(self):
        client = self.make_client('fixture-penryn')
        with self.assertRaises(Denied):
            with client.request('health'): pass


if __name__ == '__main__': unittest.main()
