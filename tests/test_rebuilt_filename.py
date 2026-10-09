import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pool.legacy import LegacyClient, private_write
from test_policy import fixture, approve


class RebuiltFilenameTests(unittest.TestCase):
    def test_verified_download_accepts_homebrew_rebuild_suffix(self):
        p, m, hosts, data = fixture()
        m['filename'] = 'fixture--1.2.3.tahoe.bottle.2.tar.gz'
        token = 'synthetic-rebuild-token-' + 'a' * 64
        p['machines']['fixture-penryn']['credential_sha256'] = hashlib.sha256(token.encode()).hexdigest()
        approve(p, m)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / 'policy.json'; private_write(policy, p)
            credential = root / 'token'; credential.write_text(token); credential.chmod(0o600)
            client = LegacyClient({'channel':'core2-legacy','auto_import_verified_bottles':False,
                'pool_id':p['pool_id'],'policy_file':str(policy),'machine_id':'fixture-penryn',
                'url':'http://127.0.0.1:1','token_file':str(credential),'state_dir':str(root/'state')},
                host_provider=lambda _: hosts['fixture-penryn'])
            response = io.BytesIO(data); response.headers = {'Content-Length':str(len(data)), 'ETag':m['sha256']}
            from pool.legacy import plan_for
            with patch.object(client, 'request', return_value=response): target = client.fetch(m, plan_for(m))
            self.assertEqual(target.name,m['filename']); self.assertEqual(target.read_bytes(),data)

if __name__ == '__main__': unittest.main()
