"""Exercise actual Python/Swift upgrade paths and the packaged backend."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pool.upgrade_paths import resolve_paths

ROOT = Path(__file__).resolve().parents[1]


class UpgradePreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler_root = tempfile.TemporaryDirectory(prefix="pool-upgrade-swift-")
        stage = Path(cls.compiler_root.name)
        main = stage / "main.swift"
        main.write_text('''import Foundation
let input = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: Any]
let p = UpgradePaths(home: URL(fileURLWithPath: input["home"] as! String), environment: input["environment"] as! [String: String], preferred: input["preferred"] as! String)
let result: [String: Any] = ["config": p.config.path, "test_root": p.testRoot?.path as Any? ?? NSNull(), "support": p.support.path, "log": p.log.path, "legacy_root": p.legacyRoot.path, "agent_label": p.agentLabel]
print(String(data: try JSONSerialization.data(withJSONObject: result, options: .sortedKeys), encoding: .utf8)!)
''')
        cls.binary = stage / "paths"
        subprocess.run(["/usr/bin/xcrun", "swiftc", "-module-cache-path", str(stage / "cache"),
                        str(ROOT / "source/macos/UpgradePaths.swift"), str(main), "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.compiler_root.cleanup()

    def check_paths(self, standard=False, test=False, preferred="standard", environment=None):
        with tempfile.TemporaryDirectory(prefix="pool-upgrade-paths-") as temporary:
            home = Path(temporary)
            old_test = home / "Library/Application Support/Homebrew Pool 0.3.6 Test"
            for enabled, path in [(standard, home / ".config/intel-bottle-pool/config.json"),
                                  (test, old_test / "config/intel-bottle-pool/config.json")]:
                if enabled:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('{"existing": "unchanged"}')
            before = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            env = {key: str(home / value) for key, value in (environment or {}).items()}
            expected = resolve_paths(home, env, preferred)
            data = {"home": str(home), "environment": env, "preferred": preferred}
            fixture = Path(self.compiler_root.name) / "case.json"
            fixture.write_text(json.dumps(data))
            actual = json.loads(subprocess.check_output([str(self.binary), str(fixture)], text=True))
            self.assertEqual(actual, {k: str(v) if isinstance(v, Path) else v for k, v in expected.items()})
            self.assertEqual(before, {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()})
            self.assertNotEqual(actual["legacy_root"], actual["support"])
            return actual, str(home), str(old_test)

    def test_standard_existing_data_keeps_legacy_paths(self):
        actual, home, _ = self.check_paths(standard=True)
        self.assertEqual(actual["config"], home + "/.config/intel-bottle-pool/config.json")
        self.assertIsNone(actual["test_root"])

    def test_test_only_data_keeps_existing_versioned_root(self):
        actual, _, old = self.check_paths(test=True)
        self.assertEqual(actual["test_root"], old)

    def test_detected_current_test_profile_wins_when_both_exist(self):
        actual, _, old = self.check_paths(standard=True, test=True, preferred="test")
        self.assertEqual(actual["test_root"], old)
        self.assertTrue(actual["agent_label"].endswith(".test"))

    def test_standard_profile_wins_when_both_exist(self):
        actual, _, _ = self.check_paths(standard=True, test=True)
        self.assertIsNone(actual["test_root"])

    def test_explicit_xdg_configuration_wins_over_detected_test(self):
        actual, home, _ = self.check_paths(standard=True, test=True, preferred="test", environment={"XDG_CONFIG_HOME": "custom"})
        self.assertEqual(actual["config"], home + "/custom/intel-bottle-pool/config.json")

    def test_isolated_ui_override_cannot_use_live_paths(self):
        actual, home, _ = self.check_paths(standard=True, test=True, environment={"HOMEBREW_POOL_APP_ROOT": "isolated", "XDG_CONFIG_HOME": "hostile"})
        self.assertEqual(actual["test_root"], home + "/isolated/global")

    def test_explicit_fixture_root_keeps_test_boundary(self):
        actual, home, _ = self.check_paths(standard=True, environment={"HOMEBREW_POOL_TEST_ROOT": "fixture"})
        self.assertEqual(actual["test_root"], home + "/fixture")

    def test_packaged_backend_keeps_config_token_spool_and_queue(self):
        entry = ROOT / "dist/Homebrew Pool.app/Contents/Resources/client/entry.py"
        self.assertTrue(entry.is_file())
        from pool.jobs import Job, step, RUN_MARKER
        from pool.common import atomic_json
        with tempfile.TemporaryDirectory(prefix="pool-upgrade-state-") as temporary:
            root = Path(temporary)
            config = root / "config/intel-bottle-pool/config.json"
            token = root / "existing-token"
            token.write_text("fixture-only-token")
            state = root / "custom-state"
            state.mkdir()
            atomic_json(config, {"url": "http://127.0.0.1:9", "allow_insecure_http": True,
                                "token_file": str(token), "state_dir": str(state), "artifacts": [],
                                "timeout": 0.1, "private_setting": "preserve-me"})
            job = Job(state)
            job.start("upgrade", [step("formula", "failed")] + [step("formula", "remaining-" + str(n)) for n in range(10)], {})
            job.data["steps"][0].update(status="failed", error="previous failure")
            job.data.update(status="paused_error", current="failed")
            job.save()
            bottle = state / "spool/retained/payload"
            bottle.parent.mkdir(parents=True)
            bottle.write_bytes(b"retained fixture artifact")
            watched = [config, token, state / "job.json", bottle]
            before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
            for profile_env in ({"XDG_CONFIG_HOME": str(root / "config")}, {"HOMEBREW_POOL_TEST_ROOT": str(root)}):
                env = dict(os.environ)
                for key in ("XDG_CONFIG_HOME", "HOMEBREW_POOL_APP_ROOT", "HOMEBREW_POOL_TEST_ROOT", "POOL_FIXTURE_ROOT"):
                    env.pop(key, None)
                env.update(profile_env)
                result = subprocess.run([sys.executable, "-B", str(entry), "job", "review"], env=env,
                                        check=True, capture_output=True, text=True)
                report = json.loads(next(x for x in result.stdout.splitlines() if x.startswith(RUN_MARKER))[len(RUN_MARKER):])
                self.assertEqual(report["remaining_count"], 10)
                self.assertEqual(report["failed_count"], 1)
                self.assertEqual(report["status"], "paused_error")
                self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched})
