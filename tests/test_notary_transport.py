"""Existing-profile remote submission verifies host, transfer and archive bytes."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from notary_transport import Notary


class NotaryTransportTests(unittest.TestCase):
    def test_local_submission_uses_only_existing_profile(self):
        with tempfile.NamedTemporaryFile(suffix='.zip') as archive:
            with patch('notary_transport.run', return_value='{"status":"Accepted"}') as call:
                Notary('HomebrewPoolNotary').submit(archive.name)
            argv = call.call_args.args[0]
            self.assertIn('--keychain-profile', argv)
            self.assertIn('HomebrewPoolNotary', argv)
            self.assertNotIn('--password', argv)

    def test_failed_ssh_prevents_archive_transfer(self):
        for host in ["-oProxyCommand=bad", "-user@host", "host; command"]:
            with self.assertRaises(ValueError):
                Notary("HomebrewPoolNotary", host)
        with tempfile.NamedTemporaryFile(suffix='.zip') as archive:
            with patch('notary_transport.run', side_effect=subprocess.CalledProcessError(255, 'ssh')) as call:
                with self.assertRaises(subprocess.CalledProcessError):
                    Notary('HomebrewPoolNotary', '192.168.10.10').submit(archive.name)
            self.assertEqual(call.call_count, 1)
            self.assertIn('StrictHostKeyChecking=yes', call.call_args.args[0])

    def test_checksum_mismatch_prevents_apple_submission(self):
        with tempfile.NamedTemporaryFile(suffix='.zip') as archive:
            with patch('notary_transport.run', side_effect=['/tmp/homebrew-pool-notary.ABCD1234\n', '', '0'*64+'  submit.zip\n']) as call:
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    Notary('HomebrewPoolNotary', '192.168.10.10').submit(archive.name)
            self.assertEqual(call.call_count, 3)
            self.assertFalse(any('notarytool' in str(c) for c in call.call_args_list))

    def test_remote_submission_retains_profile_on_remote_mac(self):
        with tempfile.NamedTemporaryFile(suffix='.zip') as archive:
            checksum = hashlib.sha256(Path(archive.name).read_bytes()).hexdigest()
            receipt = '{"status":"Accepted","id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}'
            with patch('notary_transport.run', side_effect=['/tmp/homebrew-pool-notary.ABCD1234\n', '', checksum+'  submit.zip\n', receipt, '', '']) as call:
                self.assertEqual(json.loads(Notary('HomebrewPoolNotary', '192.168.10.10').submit(archive.name))['status'], 'Accepted')
            self.assertEqual(call.call_count, 6)
            self.assertEqual(call.call_args_list[1].args[0][0], 'scp')
            self.assertIn('StrictHostKeyChecking=yes', call.call_args_list[1].args[0])
            self.assertIn('--keychain-profile HomebrewPoolNotary', call.call_args_list[3].args[0][-1])
            self.assertFalse(any('store-credentials' in str(c) or '--password' in str(c) for c in call.call_args_list))
