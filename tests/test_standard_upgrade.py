"""Upgrade packaging: legacy data reuse, no production operations in tests."""
import contextlib
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pool.cli import default_config, main
from pool.common import atomic_json
from pool.isolation import default_state_dir
from pool.jobs import Job, step, RUN_MARKER

ROOT = Path(__file__).resolve().parents[1]


class StandardUpgradeTests(unittest.TestCase):
    def test_defaults_match_legacy_not_test_copy(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            home = Path(temporary)
            with patch("pathlib.Path.home", return_value=home):
                self.assertEqual(default_config(), home / ".config/intel-bottle-pool/config.json")
                self.assertEqual(default_state_dir(), home / "Library/Caches/IntelBottlePool")

    def fixture(self, root):
        config = root / "config/intel-bottle-pool/config.json"
        token = root / "existing-token"
        token.write_text("fixture-credentials")
        state = root / "custom-existing-state"
        state.mkdir()
        atomic_json(config, dict(url="http://127.0.0.1:9", token_file=str(token),
                                state_dir=str(state), artifacts=[], timeout=0.1,
                                private_setting="preserve-me"))
        job = Job(state)
        job.start("upgrade", [step("formula", "already-failed")] +
                  [step("formula", "remaining-" + str(n)) for n in range(10)], {})
        job.data["steps"][0].update(status="failed", error="fixture prior failure")
        job.data.update(status="paused_error", current="already-failed")
        job.save()
        (state / "spool/entry-preserved").mkdir(parents=True)
        (state / "spool/entry-preserved/payload").write_bytes(b"existing validated bottle")
        return config, state

    def test_embedded_standard_backend_reuses_existing_config_queue_and_spool(self):
        entry = ROOT / "dist/Homebrew Pool.app/Contents/Resources/client/entry.py"
        self.assertTrue(entry.is_file(), "Build standard app before tests")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, state = self.fixture(root)
            watched = [config, root / "existing-token", state / "job.json",
                       state / "spool/entry-preserved/payload"]
            before = {p: p.read_bytes() for p in watched}
            env = dict(os.environ, XDG_CONFIG_HOME=str(root / "config"))
            env.pop("HOMEBREW_POOL_TEST_ROOT", None)
            env.pop("POOL_FIXTURE_ROOT", None)
            result = subprocess.run([sys.executable, "-B", str(entry), "job", "review"],
                                    env=env, check=True, capture_output=True, text=True)
            report = json.loads(next(x for x in result.stdout.splitlines()
                                    if x.startswith(RUN_MARKER))[len(RUN_MARKER):])
            self.assertEqual(report["remaining_count"], 10)
            self.assertEqual(report["failed_count"], 1)
            self.assertEqual(report["status"], "paused_error")
            self.assertEqual({p: p.read_bytes() for p in watched}, before)
            self.assertFalse((root / "config/intel-bottle-pool/token").exists())

    def test_swift_legacy_paths_identity_and_dmg_shortcut(self):
        source = (ROOT / "macos/HomebrewPoolMenu.swift").read_text()
        self.assertIn(".config/intel-bottle-pool/config.json", source)
        self.assertIn("Library/Application Support/Homebrew Pool", source)
        self.assertIn("Library/Logs/HomebrewIntelBottlePool/agent.log", source)
        self.assertNotIn("Homebrew Pool 0.3.6 Test", source)
        info = plistlib.loads((ROOT / "macos/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleIdentifier"], "com.stefanalmare.homebrew-intel-bottle-pool")
        for name in ("build-macos.sh", "notarize-macos.sh"):
            self.assertIn("ln -s /Applications", (ROOT / name).read_text())

    def test_upgrade_auto_import_is_opt_in_and_only_after_complete_job(self):
        for enabled, failed, remaining, expected in (
                (False, 0, 0, False), (True, 0, 0, True),
                (True, 1, 10, False), (True, 0, 1, False)):
            with self.subTest(enabled=enabled, failed=failed, remaining=remaining):
                with tempfile.TemporaryDirectory() as temporary:
                    config = Path(temporary) / "config.json"
                    atomic_json(config, dict(auto_import_verified_bottles=enabled))
                    with patch("pool.cli.Client"), patch("pool.cli.Brew") as brew, patch(
                            "pool.cli.Job") as job, patch("pool.cli.BottleImporter") as importer:
                        job.return_value.report.return_value = dict(failed_count=failed, remaining_count=remaining)
                        importer.return_value.import_verified.return_value = []
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(main(["--config", str(config), "upgrade", "--no-update"]), 0)
                        brew.return_value.upgrade.assert_called_once()
                        self.assertEqual(importer.return_value.scan.called, expected)
                        self.assertEqual(importer.return_value.import_verified.called, expected)
