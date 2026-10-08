"""Use one existing notarytool profile locally or over authorized SSH.

Only the signed archive and public Apple receipt/log cross the SSH connection.
Keychain credentials stay on the machine that already owns the profile.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12', '-o', 'StrictHostKeyChecking=yes']


def run(argv):
    return subprocess.check_output(argv, text=True)


class Notary:
    def __init__(self, profile, host=''):
        if not profile or any(ord(c) < 32 for c in profile):
            raise ValueError('An existing notarytool profile name is required')
        if host and not re.fullmatch(r'(?:[A-Za-z0-9][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*', host):
            raise ValueError('NOTARY_HOST must be a known SSH host, optionally user@host')
        self.profile, self.host = profile, host

    def command(self, argv):
        if self.host:
            return run(['ssh', *SSH_OPTIONS, self.host, shlex.join(argv)])
        return run(argv)

    def submit(self, archive):
        archive = Path(archive).resolve(strict=True)
        if not self.host:
            return self.command(['xcrun', 'notarytool', 'submit', str(archive), '--keychain-profile', self.profile,
                                 '--wait', '--output-format', 'json'])
        # SSH must authenticate and validate its known host before any transfer.
        directory = run(['ssh', *SSH_OPTIONS, self.host,
                         'umask 077; mktemp -d /tmp/homebrew-pool-notary.XXXXXXXX']).strip()
        if not re.fullmatch(r'/tmp/homebrew-pool-notary\.[A-Za-z0-9]+', directory):
            raise RuntimeError('Unexpected remote staging path; no transfer attempted')
        destination = directory + '/submit' + archive.suffix
        # Keep isolated staging on error for recovery; never delete arbitrary paths.
        run(['scp', *SSH_OPTIONS, str(archive), self.host + ':' + destination])
        checksum = self.command(['/usr/bin/shasum', '-a', '256', destination]).split()[0]
        if checksum != hashlib.sha256(archive.read_bytes()).hexdigest():
            raise RuntimeError('Remote archive checksum mismatch; not submitted')
        result = self.command(['xcrun', 'notarytool', 'submit', destination, '--keychain-profile', self.profile,
                               '--wait', '--output-format', 'json'])
        # Only this known uploaded file is removed, and only after a receipt exists.
        json.loads(result)
        # A cleanup interruption must not lose an Apple submission identifier.
        with contextlib.suppress(subprocess.CalledProcessError):
            self.command(['/bin/rm', '-f', destination])
            self.command(['/bin/rmdir', directory])
        return result

    def log(self, submission):
        if not re.fullmatch(r'[a-fA-F0-9-]{36}', submission):
            raise ValueError('Expected Apple submission UUID')
        return self.command(['xcrun', 'notarytool', 'log', submission, '--keychain-profile', self.profile])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['submit', 'log'])
    parser.add_argument('input')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    transport = Notary(os.environ.get('NOTARY_PROFILE', ''), os.environ.get('NOTARY_HOST', ''))
    result = getattr(transport, args.action)(args.input)
    json.loads(result)
    args.output.write_text(result)
