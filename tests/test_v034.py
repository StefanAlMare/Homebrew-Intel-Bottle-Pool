import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pool.brew import Brew
from pool.jobs import Job, step
from pool.common import digest, PoolError, atomic_json, canonical
import hashlib
from pool.processes import STOP
from test_pool import FakeBrew, Fixture


ROOT = Path(__file__).resolve().parents[1]


class CurrentKegBottleTests(Fixture):
    def _current_mac(self):
        prefix = self.root / "brew"
        mac = FakeBrew(self.clients[0], str(prefix))
        record = mac.records["demo"]
        record["installed"] = [{"version": "1.0", "used_options": [],
                                "installed_on_request": False, "built_as_bottle": False}]
        keg = prefix / "Cellar" / "demo" / "1.0"
        keg.mkdir(parents=True)
        (keg / "payload").write_text("original")
        recipe = keg / ".brew/demo.rb"
        recipe.parent.mkdir()
        recipe.write_text("class Demo < Formula; end")
        record["ruby_source_checksum"]["sha256"] = digest(recipe)
        record["_fixture_recipe"] = recipe.read_text()
        linked = prefix / "var" / "homebrew" / "linked" / "demo"
        linked.parent.mkdir(parents=True)
        linked.symlink_to(keg)
        original_run = mac.run

        def run(*args, **kwargs):
            if args[0] == "unlink":
                mac.calls.append(args)
                linked.unlink(missing_ok=True)
                return ""
            if args[0] == "link":
                mac.calls.append(args)
                linked.unlink(missing_ok=True)
                linked.symlink_to(keg)
                return ""
            if args[0] == "install" and "--build-bottle" in args:
                self.assertIn("--force", args)
                self.assertNotIn("--build-from-source", args)
                self.assertFalse(keg.exists())
                mac.calls.append(args)
                keg.mkdir(parents=True)
                (keg / "payload").write_text("replacement")
                (keg / ".brew").mkdir()
                (keg / ".brew/demo.rb").write_text("class Demo < Formula; end")
                linked.unlink(missing_ok=True)
                linked.symlink_to(keg)
                record["installed"][0]["built_as_bottle"] = True
                return ""
            return original_run(*args, **kwargs)

        mac.run = run
        mac._run_recovery = lambda *args: run(*args, capture=False)
        mac.force_targets.add("demo")
        return mac, record, keg, linked

    def test_current_keg_uses_force_install_and_commits_only_after_validation(self):
        mac, _, keg, linked = self._current_mac()
        info = mac.info("demo")
        mac.build(info, mac.manifest(info), None, as_dependency=True)
        install = next(call for call in mac.calls if call[0] == "install" and "--build-bottle" in call)
        self.assertEqual(install[:3], ("install", "--formula", "--build-bottle"))
        self.assertIn("--force", install)
        self.assertIn("--as-dependency", install)
        self.assertFalse(any(call[0] == "reinstall" for call in mac.calls))
        self.assertEqual((keg / "payload").read_text(), "replacement")
        self.assertTrue(linked.is_symlink())
        self.assertFalse(list(keg.parent.glob("*.pool-backup-*")))

    def test_failed_test_restores_original_keg_and_does_not_publish(self):
        mac, _, keg, linked = self._current_mac()
        mac.fail_test = True
        info = mac.info("demo")
        with self.assertRaisesRegex(Exception, "simulated brew test failure"):
            mac.build(info, mac.manifest(info), None, as_dependency=True)
        self.assertEqual((keg / "payload").read_text(), "original")
        self.assertTrue(linked.is_symlink())
        self.assertFalse(list(keg.parent.glob("*.pool-backup-*")))
        self.assertFalse(list((mac.client.state / "build-proofs").glob("*.json")))
        self.assertFalse(list(self.clients[0].spool.glob("entry-*/manifest.json")))
        self.assertFalse(list(self.store.objects.glob("*/manifest.json")))

    def test_stop_flag_cannot_block_atomic_restore(self):
        mac, _, keg, linked = self._current_mac()
        staged = mac._stage_current_keg(mac.info("demo"))
        keg.mkdir(parents=True)
        (keg / "payload").write_text("interrupted")
        linked.unlink(missing_ok=True)
        linked.symlink_to(keg)

        def recovery(*args):
            mac.calls.append(("recovery", *args))
            if args[0] == "unlink":
                linked.unlink(missing_ok=True)
            elif args[0] == "link":
                linked.unlink(missing_ok=True)
                linked.symlink_to(keg)
            return ""

        mac._run_recovery = recovery
        STOP.set()
        try:
            mac._restore_staged_keg(staged)
        finally:
            STOP.clear()
        self.assertEqual((keg / "payload").read_text(), "original")
        self.assertTrue(linked.is_symlink())
        self.assertIn(("recovery", "unlink", "demo"), mac.calls)
        self.assertIn(("recovery", "link", "demo"), mac.calls)

    def test_bottle_ready_current_keg_is_not_compiled_again(self):
        mac, record, _, _ = self._current_mac()
        record["installed"][0]["built_as_bottle"] = True
        info = mac.info("demo")
        manifest = mac.manifest(info)
        proof_path = mac.client.state / "build-proofs" / (hashlib.sha256(canonical(["demo", "1.0"])).hexdigest() + ".json")
        atomic_json(proof_path, {"inputs": {"runtime": manifest["metadata"]["context"], "build": {}, "installed_recipe_sha256": mac.planned_installed_recipe_hash(info)}, "keg": mac.installed_keg_identity(info)})
        mac.build(info, manifest, None, as_dependency=True)
        self.assertFalse(any(call[0] in ("install", "reinstall") and "--build-bottle" in call
                             for call in mac.calls))
        self.assertTrue(any(call[0] == "bottle" for call in mac.calls))

    def test_legacy_bottle_ready_keg_without_proof_requires_safe_rebuild(self):
        mac, record, keg, _ = self._current_mac()
        record["installed"][0]["built_as_bottle"] = True
        info = mac.info("demo")
        mac.build(info, mac.manifest(info), None)
        self.assertEqual((keg / "payload").read_text(), "replacement")
        self.assertTrue(any(call[0] == "install" and "--force" in call for call in mac.calls))


class RetryAttributionTests(Fixture):
    def test_nested_dependency_is_only_force_target_and_queue_is_unchanged(self):
        mac = FakeBrew(self.clients[0])
        job = Job(mac.client.state)
        steps = [step("formula", "fastfetch"), step("formula", "pkgconf")]
        steps.extend(step("formula", "remaining-" + str(index)) for index in range(10))
        job.start("upgrade", steps, {"allow_build": True, "casks": True})
        legacy_error = "Formula was not installed with `--build-bottle`: pkgconf"
        for item in job.data["steps"][:2]:
            item.update(status="failed", error=legacy_error)
        job.data["status"] = "paused_error"
        job.save()
        before = job.path.read_bytes()
        captured = {}
        job.run = lambda execute, mode, skip: captured.update(mode=mode, targets=set(mac.force_targets))
        mac._run_job(job, "retry")
        self.assertEqual(captured, {"mode": "retry", "targets": {"pkgconf"}})
        self.assertEqual(Job(mac.client.state).report()["remaining_count"], 10)
        self.assertEqual(job.path.read_bytes(), before)


class MaintenanceCLITests(unittest.TestCase):
    def _run(self, command, root):
        token = root / "token"
        token.write_text("fixture-token")
        config = root / "config.json"
        config.write_text(json.dumps({"url": "http://127.0.0.1:9", "token_file": str(token),
                                      "state_dir": str(root / "state")}))
        return subprocess.run([sys.executable, str(ROOT / "entry.py"), "--config", str(config),
                               "maintenance", command], text=True, capture_output=True)

    def test_read_only_output_is_live_and_success_is_real(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run("/usr/bin/printf readonly-output", Path(temporary))
        self.assertEqual(result.returncode, 0)
        self.assertIn("readonly-output", result.stdout)
        self.assertIn("HOMEBREW_POOL_EXIT_CODE=0", result.stdout)

    def test_failure_propagates_original_exit_code_and_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run("/bin/sh -c 'echo controlled-failure >&2; exit 7'", Path(temporary))
        self.assertEqual(result.returncode, 7)
        self.assertIn("controlled-failure", result.stderr)
        self.assertIn("HOMEBREW_POOL_EXIT_CODE=7", result.stderr)
        self.assertNotIn("HOMEBREW_POOL_EXIT_CODE=0", result.stdout + result.stderr)

    def test_controlled_mutation_executes_exact_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "maintenance-created"
            result = self._run("/usr/bin/touch '" + str(marker) + "'", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(marker.is_file())


if __name__ == "__main__":
    unittest.main()
