import copy
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from pool.brew import Brew
from pool.common import PoolError
from pool.jobs import Job, step
from pool.maintenance import command_is_read_only, needs_destructive_confirmation, run_maintenance
from test_pool import FakeBrew, Fixture


ROOT = Path(__file__).resolve().parents[1]


class StateReconciliationTests(unittest.TestCase):
    def test_main_cli_reports_release_version(self):
        result = subprocess.run([sys.executable, str(ROOT / "entry.py"), "--version"],
                                text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), "Homebrew Intel Bottle Pool 0.3.6")

    def test_stale_stopped_cache_with_no_work_becomes_resolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            job = Job(temporary)
            job.start("upgrade", [step("formula", "done")], {})
            job.data["steps"][0]["status"] = "done"
            job.data["status"] = "stopped"
            job.data["current"] = "done"
            job.save()
            self.assertTrue(Job(temporary).reconcile())
            report = Job(temporary).report()
            self.assertEqual(report["status"], "resolved")
            self.assertEqual(report["failed_count"], 0)
            self.assertEqual(report["remaining_count"], 0)

    def test_reconcile_never_erases_a_real_failure_or_pending_item(self):
        with tempfile.TemporaryDirectory() as temporary:
            job = Job(temporary)
            job.start("upgrade", [step("formula", "failed"), step("formula", "later")], {})
            job.data["steps"][0].update(status="failed", error="boom")
            job.data["status"] = "paused_error"
            job.save()
            self.assertFalse(Job(temporary).reconcile())
            report = Job(temporary).report()
            self.assertEqual((report["failed_count"], report["remaining_count"]), (1, 1))


class DependencyRecoveryTests(Fixture):
    def test_runtime_graph_is_checked_before_current_formula_shortcut(self):
        mac = FakeBrew(self.clients[0])
        mac.records["demo"]["installed"] = [{"version": "1.0", "used_options": []}]
        mac.records["dep"] = dict(copy.deepcopy(mac.records["demo"]), name="dep", full_name="dep")
        original = mac.run

        def run(*args, **kwargs):
            if args[:3] == ("deps", "--topological", "--full-name") and args[-1] == "demo":
                mac.calls.append(args)
                return "dep"
            return original(*args, **kwargs)

        mac.run = run
        mac.ensure("demo")
        dependency_info = mac.calls.index(("info", "--json=v2", "--formula", "dep"))
        self.assertGreater(dependency_info, mac.calls.index(("deps", "--topological", "--full-name", "--os=tahoe", "demo")))
        self.assertEqual(mac.records["demo"]["installed"][0]["version"], "1.0")

    def test_dependency_repair_revalidates_without_replacing_paused_queue(self):
        mac = FakeBrew(self.clients[0])
        mac.records["openssl@3"] = dict(copy.deepcopy(mac.records["demo"]),
                                        name="openssl@3", full_name="openssl@3",
                                        installed=[{"version": "1.0", "used_options": []}])
        job = Job(mac.client.state)
        job.start("upgrade", [step("formula", "coreutils")], {})
        job.data["steps"][0].update(status="failed", error="Runtime dependency not current: openssl@3")
        job.data["status"] = "paused_error"
        job.save()
        before = job.path.read_bytes()
        original = mac.run

        def run(*args, **kwargs):
            if args[0] == "linkage":
                mac.calls.append(args)
                return ""
            return original(*args, **kwargs)

        mac.run = run
        self.assertEqual(mac.repair_dependency("openssl@3"), "openssl@3")
        self.assertEqual(job.path.read_bytes(), before)
        self.assertIn(("missing",), mac.calls)
        self.assertIn(("linkage", "--test", "openssl@3"), mac.calls)


class MaintenanceSecurityTests(unittest.TestCase):
    def test_shortcuts_are_classified_and_mutations_are_not(self):
        for command in ("brew doctor", "brew outdated", "brew missing", "brew linkage --test"):
            self.assertTrue(command_is_read_only(command))
        for command in ("brew install openssl@3", "brew upgrade", "echo brew doctor"):
            self.assertFalse(command_is_read_only(command))

    def test_destructive_commands_require_explicit_confirmation(self):
        self.assertTrue(needs_destructive_confirmation("brew uninstall openssl@3"))
        self.assertTrue(needs_destructive_confirmation("rm -rf /tmp/example"))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PoolError, "confirmation"):
                run_maintenance("brew cleanup", temporary)

    def test_explicit_command_has_closed_stdin_and_exit_output_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = run_maintenance("printf maintenance-ok", temporary)
            self.assertEqual(output, "maintenance-ok")


class SwiftRecoverySurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "macos/HomebrewPoolMenu.swift").read_text()

    def test_console_and_recovery_actions_are_permanently_present(self):
        for title in ("Maintenance Console…", "Repair / Install Dependency…", "Repair Pool State…"):
            self.assertIn(title, self.source)
        self.assertIn("maintenanceItem.isEnabled = true", self.source)
        self.assertIn("[exit code \\(process.terminationStatus)]", self.source)
        self.assertIn("FileHandle.nullDevice", self.source)

    def test_cold_launch_and_periodic_refresh_use_backend_authority(self):
        self.assertIn("Backend state is authoritative", self.source)
        self.assertIn("withTimeInterval: 10", self.source)
        self.assertIn("cold_launch_stale_ui_reconciled", self.source)
        self.assertNotIn("guard pendingRun == nil else { showRunVisual(); return }", self.source)


if __name__ == "__main__":
    unittest.main()
