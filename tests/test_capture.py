import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pool.capture import FormulaCapture, IsolatedBrew, Q9300_FEATURES, tree_hash
from pool.common import PoolError, atomic_json, digest
from pool.imports import BottleImporter
from pool.isolation import require_private_path
from pool.processes import JobStopped
from test_pool import Fixture
from test_v036 import ImportBrew, make_bottle


class CaptureTests(Fixture):
    def setUp(self):
        super().setUp()
        self.brew = ImportBrew(self.root / "cache")
        self.brew.prefix = str(self.root / "producer")
        self.brew.cellar = str(Path(self.brew.prefix) / "Cellar")
        self.keg = Path(self.brew.cellar) / "demo/1.0"
        (self.keg / ".brew").mkdir(parents=True)
        (self.keg / ".brew/demo.rb").write_bytes(self.brew.recipe)
        (self.keg / "payload").write_bytes(b"original keg")
        self.receipt = {"built_as_bottle": True, "poured_from_bottle": False, "arch": "x86_64",
                        "compiler": "clang", "used_options": [], "runtime_dependencies": [],
                        "source": {"tap": "homebrew/core"}, "built_on": {"cpu_family": "penryn"}}
        self.save_receipt()
        self.brew.up_to_date = lambda info: True
        self.brew.declared_dependencies = lambda *args: []
        self.capture = FormulaCapture(self.clients[0], self.brew)

    def save_receipt(self):
        atomic_json(self.keg / "INSTALL_RECEIPT.json", self.receipt)

    def proof(self, features=None):
        evidence = self.capture.inspect("demo")[1]
        keys = ("formula", "version", "prefix", "cellar", "receipt_sha256",
                "recipe_sha256", "keg_tree_sha256", "context")
        proof = {x: evidence[x] for x in keys}
        proof.update(schema=1, reviewed=True, producer="controlled fixture",
                     compiler_flags=[], required_cpu_features=features or ["SSSE3"])
        path = self.root / "producer-proof.json"
        atomic_json(path, proof)
        return path

    def test_no_build_bottle_receipt_is_reviewed_without_any_command(self):
        self.receipt["built_as_bottle"] = False
        self.save_receipt()
        before = tree_hash(self.keg)
        with patch("pool.capture.IsolatedBrew") as isolated:
            result = self.capture.capture("demo")
        self.assertEqual(result["classification"], "requires_review")
        self.assertIn("separate approval", result["reason"])
        isolated.assert_not_called()
        self.assertEqual(tree_hash(self.keg), before)
        self.assertFalse(self.receipt["built_as_bottle"])

    def test_node_modern_receipt_without_compiler_proof_is_never_auto_bottled(self):
        self.receipt["built_on"]["cpu_family"] = "kabylake"
        self.save_receipt()
        with patch("pool.capture.IsolatedBrew") as isolated:
            result = self.capture.capture("demo")
        self.assertIn("Missing reviewed producer", result["reason"])
        isolated.assert_not_called()

    def test_false_cpu_claim_on_modern_receipt_is_refused(self):
        self.receipt["built_on"]["cpu_family"] = "kabylake"
        self.save_receipt()
        with patch("pool.capture.IsolatedBrew") as isolated:
            result = self.capture.capture("demo", self.proof(["SSSE3"]))
        self.assertIn("conservative", result["reason"])
        isolated.assert_not_called()

    def test_receipt_or_keg_change_invalidates_proof(self):
        proof = self.proof()
        (self.keg / "payload").write_bytes(b"changed")
        result = self.capture.capture("demo", proof)
        self.assertIn("keg_tree_sha256", result["reason"])

    def test_unknown_compiler_flags_are_reviewed(self):
        path = self.proof()
        proof = json.loads(path.read_text())
        proof["compiler_flags"] = ["-march=native"]
        atomic_json(path, proof)
        self.assertIn("compiler flags", self.capture.capture("demo", path)["reason"])

    def test_isolated_failure_never_creates_importable_artifact(self):
        with patch("pool.capture.IsolatedBrew") as factory:
            factory.return_value.prepare.side_effect = PoolError("isolation failed")
            result = self.capture.capture("demo", self.proof())
        self.assertEqual(result["classification"], "requires_review")
        self.assertFalse((self.clients[0].state / "imports.json").exists())
        self.assertEqual(len(list(self.clients[0].spool.glob("entry-*"))), 0)

    def test_path_install_policy_is_not_bypassed(self):
        self.brew.env = {"HOMEBREW_FORBID_PACKAGES_FROM_PATHS": "1"}
        with patch("pool.capture.IsolatedBrew") as factory:
            result = self.capture.capture("demo", self.proof())
        factory.assert_not_called()
        self.assertIn("policy forbids", result["reason"])

    def test_real_command_sequence_gates_artifact_and_does_not_publish(self):
        before = tree_hash(self.keg)
        commands = []
        def run(*args, **kwargs):
            commands.append(args)
            if args[0] == "install":
                self.assertEqual(kwargs["env_extra"], {"HOMEBREW_DEVELOPER": "1"})
            else:
                self.assertNotIn("env_extra", kwargs)
            if args[0] == "bottle":
                output = make_bottle(Path(kwargs["cwd"]) / "demo--1.0.tahoe.bottle.tar.gz", self.brew, proof=False)
                atomic_json(Path(kwargs["cwd"]) / "demo.json", {"demo": {"bottle": {
                    "cellar": ":any", "tags": {"tahoe": {"sha256": digest(output)}}}}})
            if args[0] == "info":
                record = copy.deepcopy(self.brew.record)
                record["installed"][0]["poured_from_bottle"] = True
                return json.dumps({"formulae": [record]})
            return ""
        with patch("pool.capture.IsolatedBrew") as factory:
            factory.return_value.run.side_effect = run
            result = self.capture.capture("demo", self.proof())
        self.assertEqual(result["classification"], "bottle_valid_importable", result["reason"])
        self.assertTrue(result["validation"]["q9300_compatible"])
        self.assertEqual(tree_hash(self.keg), before)
        self.assertEqual([x[0] for x in commands], ["bottle", "uninstall", "trust", "install", "info", "test", "linkage"])
        self.assertIn("--force-bottle", commands[3])
        self.assertFalse(list(self.clients[0].spool.glob("entry-*")))
        candidate = BottleImporter(self.clients[0], self.brew).scan()["candidates"][-1]
        self.assertTrue(candidate["manifest"]["metadata"]["capture_validation"]["isolated_pour"])

    def test_test_failure_keeps_review_no_import(self):
        def run(*args, **kwargs):
            if args[0] == "bottle":
                output = make_bottle(Path(kwargs["cwd"]) / "demo--1.0.tahoe.bottle.tar.gz", self.brew, proof=False)
                atomic_json(Path(kwargs["cwd"]) / "demo.json", {"demo": {"bottle": {
                    "cellar": ":any", "tags": {"tahoe": {"sha256": digest(output)}}}}})
            if args[0] == "info":
                return json.dumps({"formulae": [{"installed": [{"version": "1.0", "poured_from_bottle": True}]}]})
            if args[0] == "test":
                raise subprocess.CalledProcessError(9, args)
            return ""
        with patch("pool.capture.IsolatedBrew") as factory:
            factory.return_value.run.side_effect = run
            result = self.capture.capture("demo", self.proof())
        self.assertEqual(result["classification"], "requires_review")
        self.assertFalse((self.clients[0].state / "imports.json").exists())

    def test_stop_during_capture_is_not_marked_complete(self):
        with patch("pool.capture.IsolatedBrew") as factory:
            factory.return_value.prepare.side_effect = JobStopped("fixture stop")
            with self.assertRaises(JobStopped):
                self.capture.capture("demo", self.proof())
        report = json.loads((self.clients[0].state / "capture-review.json").read_text())
        self.assertEqual(report["classification"], "requires_review")
        self.assertFalse((self.clients[0].state / "imports.json").exists())

    def test_q9300_never_pours_sse42_or_avx_capture(self):
        self.assertNotIn("SSE4_2", Q9300_FEATURES)
        self.assertNotIn("AVX", Q9300_FEATURES)
        self.brew.cpu_features = set(Q9300_FEATURES)
        self.assertIn("exceed", self.capture.capture("demo", self.proof(["SSE4.2", "AVX"]))["reason"])


class IsolationTests(unittest.TestCase):
    def test_installed_cli_keeps_opt_in_fixture_boundary(self):
        import sys
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run([sys.executable, str(root / "install.py"), "--prefix", temporary],
                           check=True, capture_output=True)
            env = dict(os.environ, HOMEBREW_POOL_TEST_ROOT=temporary)
            result = subprocess.run([str(Path(temporary) / "bin/brew-pool"),
                "--config", "/usr/local/production-config-must-not-be-read.json", "status"],
                capture_output=True, text=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refuses production/outside", result.stderr)

    def test_test_uninstaller_never_touches_production(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(["sh", str(root / "uninstall-app.sh"), "--purge-data"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("disabled", result.stderr)

    def test_test_bundle_rejects_production_paths_including_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "escape").symlink_to("/usr/local")
            with patch.dict(os.environ, HOMEBREW_POOL_TEST_ROOT=temporary):
                require_private_path(root / "state")
                with self.assertRaises(PoolError):
                    require_private_path("/usr/local/state")
                with self.assertRaises(PoolError):
                    require_private_path(root / "escape/state")

    def test_capture_runner_denies_network_and_external_writes(self):
        isolated = IsolatedBrew("/private/tmp/capture-fixture", None)
        self.assertIn("Sandbox.for_operation", isolated.policy)
        self.assertIn("network_access: false", isolated.policy)
        self.assertIn("write_paths: [root]", isolated.policy)
        self.assertIn("Sandbox.ensure_sandbox_available!", isolated.policy)
        self.assertNotIn("HOMEBREW_POOL_TEST_ROOT", isolated.env)

    def test_gui_standard_identity_and_all_new_surfaces(self):
        root = Path(__file__).resolve().parents[1]
        import plistlib
        info = plistlib.loads((root / "macos/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleIdentifier"], "com.stefanalmare.homebrew-intel-bottle-pool")
        source = (root / "macos/HomebrewPoolMenu.swift").read_text()
        for label in ("Pause Safely", "Stop Now", "Scan Existing Bottles", "Review Imports…",
                      "Import to Pool…", "Capture Installed Formula…", "Auto-import verified bottles"):
            self.assertIn(label, source)
        self.assertIn("Library/Application Support/Homebrew Pool", source)
        self.assertNotIn("Homebrew Pool 0.3.6 Test", source)
        self.assertIn(".idleSystemSleepDisabled", source)
