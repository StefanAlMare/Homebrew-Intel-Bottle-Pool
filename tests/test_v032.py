import contextlib
import copy
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pool.actions import ActionRequired, classify_command_failure
from pool.brew import Brew
from pool.common import PoolError, version_order
from pool.jobs import Job, step
from pool.preflight import OFFICIAL, Preflight, canonical_official, executable_candidate
from pool.processes import JobStopped, STOP, run_command
from test_pool import FakeBrew, Fixture
from test_v030 import SafeTapTests

ROOT = Path(__file__).resolve().parents[1]


class VersionAndOutputTests(unittest.TestCase):
    def test_dates_have_chronological_order_and_compatible_numeric_rank(self):
        self.assertGreater(version_order("2026-09-25"), version_order("2026-01-31"))
        self.assertGreater(version_order("2026-01-01"), version_order("2025-12-31"))
        self.assertEqual(version_order("2026-09-25"), version_order("2026.9.25"))
        self.assertGreater(version_order("2026-09-25", 1), version_order("2026-09-25", 0, 20))
        for value in ("2026-02-30", "2026-13-01", "latest", "2026-09-25-nightly"):
            with self.assertRaises(PoolError):
                version_order(value)

    def test_only_formula_lines_survive_realistic_warnings_and_ansi(self):
        output = """Warning: `brew deps` is not the actual runtime dependencies!
See: https://docs.brew.sh/FAQ
==> Dependencies
openssl@3
\x1b[33mgromgit/fuse/ntfs-3g-mac\x1b[0m
ca-certificates
  ca-certificates
Error: missing tool
--force
../bad
"""
        self.assertEqual(Brew.package_lines(output), ["openssl@3", "gromgit/fuse/ntfs-3g-mac", "ca-certificates"])

    def test_capture_keeps_stderr_out_of_json_and_dependency_output(self):
        with contextlib.redirect_stderr(io.StringIO()) as logged:
            output = run_command([sys.executable, "-c", "import sys; print('openssl@3'); print('Warning: old links',file=sys.stderr)"])
        self.assertEqual(output, "openssl@3")
        self.assertIn("Warning", logged.getvalue())

    def test_technical_errors_are_not_user_decisions(self):
        for output in ("Cannot order version '2026-09-25'", "Warning: brew deps", "unlink failed: I/O error", "compiler exited with error"):
            self.assertIsNone(classify_command_failure(output))
        self.assertEqual(classify_command_failure("This formula is not trusted; use brew trust").category, "trust")


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        STOP.clear()
        self.job = Job(self.root)
        self.job.start("upgrade", [step("formula", "first"), step("formula", "second")], {})

    def tearDown(self):
        STOP.clear()
        self.temporary.cleanup()

    def fail_first(self):
        calls = []
        def execute(item, job):
            calls.append(item["name"])
            raise PoolError("compiler failed")
        with self.assertRaisesRegex(PoolError, "Paused"):
            self.job.run(execute)
        self.assertEqual(calls, ["first"])
        self.assertEqual(Job(self.root).report()["failed_count"], 1)

    def test_first_error_stops_and_retry_only_failed_then_resume(self):
        self.fail_first()
        calls = []
        reloaded = Job(self.root)
        reloaded.run(lambda item, job: calls.append(item["name"]), "retry")
        self.assertEqual(calls, ["first"])
        self.assertEqual(reloaded.report()["status"], "paused")
        self.assertEqual(reloaded.report()["remaining_count"], 1)
        reloaded.run(lambda item, job: calls.append(item["name"]))
        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(reloaded.report()["status"], "completed")

    def test_resume_never_erases_failed_summary_until_resolved(self):
        self.fail_first()
        calls = []
        self.job.run(lambda item, job: calls.append(item["name"]))
        self.assertEqual(calls, ["second"])
        self.assertEqual(self.job.report()["status"], "paused_error")
        with self.assertRaisesRegex(PoolError, "saved job"):
            self.job.start("upgrade", [], {})
        self.job.resolve()
        self.assertEqual(Job(self.root).report()["failed_count"], 0)

    def test_stop_keeps_current_item_and_queue_for_resume(self):
        calls = []
        def stop(item, job):
            calls.append(item["name"])
            raise JobStopped()
        with self.assertRaises(JobStopped):
            self.job.run(stop)
        saved = Job(self.root)
        self.assertEqual(saved.report()["status"], "stopped")
        self.assertEqual(saved.report()["remaining_count"], 2)
        saved.run(lambda item, job: calls.append(item["name"]))
        self.assertEqual(calls, ["first", "first", "second"])

    def test_action_is_separate_and_skip_only_skips_current_queue_item(self):
        def action(item, job):
            raise ActionRequired("choose", subject=item["name"])
        with self.assertRaises(ActionRequired):
            self.job.run(action)
        self.assertEqual(self.job.report()["status"], "action_required")
        self.assertEqual(self.job.report()["failed_count"], 0)
        calls = []
        self.job.run(lambda item, job: calls.append(item["name"]), skip=["first"])
        self.assertEqual(calls, ["second"])

    def test_prerequisite_failure_cannot_be_bypassed_by_resume_or_resolve(self):
        self.job.data["steps"][0]["kind"] = "preflight"
        self.fail_first()
        with self.assertRaisesRegex(PoolError, "prerequisite"):
            self.job.run(lambda *_: self.fail("must not run"))
        with self.assertRaisesRegex(PoolError, "prerequisite"):
            self.job.resolve()
        self.job.resolve(cancel=True)
        self.assertEqual(self.job.report()["remaining_count"], 0)

    def test_crash_running_record_is_recovered_without_losing_queue(self):
        self.job.data["steps"][0]["status"] = "running"
        self.job.save()
        calls = []
        Job(self.root).run(lambda item, job: calls.append(item["name"]))
        self.assertEqual(calls, ["first", "second"])


class BrewPauseTests(Fixture):
    def test_stop_after_install_rebuilds_and_validates_on_resume(self):
        mac = FakeBrew(self.clients[0])
        original = mac.run
        blocked = True
        def run(*args, **kwargs):
            if blocked and args[0] == "bottle":
                raise JobStopped()
            return original(*args, **kwargs)
        mac.run = run
        with self.assertRaises(JobStopped):
            mac.upgrade(update=False, casks=False)
        saved = Job(mac.client.state)
        self.assertTrue(saved.remaining[0]["interrupted"])
        self.assertTrue(mac.up_to_date(mac.info("demo")))
        blocked = False
        mac.upgrade(mode="resume")
        self.assertIn(("install", "--formula", "--build-bottle", "--force", "demo"), mac.calls)
        self.assertFalse(any(call[0] == "reinstall" and "--build-bottle" in call for call in mac.calls))
        self.assertEqual(Job(mac.client.state).report()["status"], "completed")

    def test_retry_revalidates_dependency_whose_keg_was_installed_before_failure(self):
        mac = FakeBrew(self.clients[0])
        mac.records["dep"] = dict(copy.deepcopy(mac.records["demo"]), name="dep", full_name="dep")
        import hashlib
        mac.records["dep"]["ruby_source_checksum"]["sha256"] = hashlib.sha256(b"fixture recipe dep").hexdigest()
        original = mac.run
        def run(*args, **kwargs):
            if args[0] == "deps" and args[-1] == "demo":
                return "dep"
            return original(*args, **kwargs)
        mac.run = run
        mac.fail_test = True
        with self.assertRaises(PoolError):
            mac.upgrade(update=False, casks=False)
        self.assertEqual(Job(mac.client.state).failures[0]["failed_package"], "dep")
        mac.fail_test = False
        mac.upgrade(mode="retry")
        self.assertIn(("install", "--formula", "--build-bottle", "--force", "dep"), mac.calls)
        self.assertFalse(any(call[0] == "reinstall" and "--build-bottle" in call for call in mac.calls))
        self.assertEqual(Job(mac.client.state).report()["failed_count"], 0)

    def test_upgrade_pauses_before_next_formula_cask_adapter_or_final_sync(self):
        mac = FakeBrew(self.clients[0])
        calls = []
        mac.ensure = lambda name, allow_build: (calls.append(name), (_ for _ in ()).throw(PoolError("fixture failure")))[1]
        with self.assertRaisesRegex(PoolError, "Paused"):
            mac.upgrade(names=["first", "second"])
        self.assertEqual(calls, ["first"])
        self.assertNotIn(("missing",), mac.calls)
        self.assertEqual(mac.calls[:2], [("--prefix",), ("--cellar",)])
        self.assertLess(mac.calls.index(("fixture-preflight",)), mac.calls.index(("update",)))
        self.assertEqual(Job(mac.client.state).report()["failed_count"], 1)
        mac.ensure = lambda name, allow_build: calls.append(name)
        mac.upgrade(mode="retry")
        self.assertEqual(calls, ["first", "first"])
        mac.upgrade(mode="resume")
        self.assertEqual(calls, ["first", "first", "second"])

    def test_retry_failed_test_rebuilds_instead_of_skipping_current_keg(self):
        mac = FakeBrew(self.clients[0])
        mac.fail_test = True
        with self.assertRaises(PoolError):
            mac.upgrade(casks=False, update=False)
        mac.fail_test = False
        mac.upgrade(mode="retry")
        self.assertIn(("install", "--formula", "--build-bottle", "--force", "demo"), mac.calls)
        self.assertFalse(any(call[0] == "reinstall" and "--build-bottle" in call for call in mac.calls))
        self.assertTrue(list(self.store.objects.glob("*/manifest.json")))


class MigrationTests(SafeTapTests):
    def setUp(self):
        super().setUp()
        self.preflight = Preflight(self.mac)

    def test_legacy_urls_are_allowlisted_and_custom_urls_are_preserved(self):
        for url in ("git://github.com/mxcl/homebrew.git", "git@github.com:Homebrew/homebrew.git", "https://github.com/Linuxbrew/brew"):
            self.assertEqual(canonical_official("brew", url), OFFICIAL["brew"])
        for url in ("https://example.invalid/private/tap", "https://github.com.evil.invalid/Homebrew/brew", "https://github.com/another/brew"):
            self.assertEqual(canonical_official("brew", url), url)
        self.assertEqual(canonical_official("other/tap", "git://github.com/mxcl/homebrew.git"), "git://github.com/mxcl/homebrew.git")

    def redirect_official_locally(self):
        self.preflight.env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="url." + str(self.origin) + ".insteadOf",
                                  GIT_CONFIG_VALUE_0=OFFICIAL["brew"])

    def test_official_legacy_remote_migrates_and_fast_forwards_using_fixture(self):
        self.git("-C", str(self.repo), "remote", "set-url", "origin", "git://github.com/mxcl/homebrew.git")
        self.redirect_official_locally()
        self.commit(self.writer, "updated")
        self.git("-C", str(self.writer), "push")
        self.preflight.sync(self.repo, "brew")
        self.assertEqual(self.git("-C", str(self.repo), "remote", "get-url", "origin"), OFFICIAL["brew"])
        self.assertEqual((self.repo / "formula").read_text(), "updated")

    def test_missing_official_origin_and_upstream_are_repaired_without_network(self):
        self.git("-C", str(self.repo), "remote", "remove", "origin")
        self.redirect_official_locally()
        self.preflight.sync(self.repo, "brew")
        self.assertEqual(self.git("-C", str(self.repo), "remote", "get-url", "origin"), OFFICIAL["brew"])
        self.assertTrue(self.git("-C", str(self.repo), "rev-parse", "@{upstream}") )

    def test_missing_remote_url_is_repaired(self):
        self.git("-C", str(self.repo), "config", "--unset", "remote.origin.url")
        self.redirect_official_locally()
        self.preflight.sync(self.repo, "brew")
        self.assertEqual(self.git("-C", str(self.repo), "remote", "get-url", "origin"), OFFICIAL["brew"])

    def test_third_party_missing_origin_requires_action_and_does_not_guess(self):
        self.git("-C", str(self.repo), "remote", "remove", "origin")
        with self.assertRaises(ActionRequired):
            self.preflight.sync(self.repo, "custom/tap")
        self.assertEqual(self.git("-C", str(self.repo), "remote"), "")

    def test_existing_third_party_url_is_retained(self):
        before = self.git("-C", str(self.repo), "remote", "get-url", "origin")
        self.preflight.sync(self.repo, "custom/tap")
        self.assertEqual(self.git("-C", str(self.repo), "remote", "get-url", "origin"), before)

    def test_dirty_checkout_is_refused_before_remote_rewrite(self):
        url = "git://github.com/mxcl/homebrew.git"
        self.git("-C", str(self.repo), "remote", "set-url", "origin", url)
        (self.repo / "untracked").write_text("keep")
        with self.assertRaises(ActionRequired):
            self.preflight.sync(self.repo, "brew")
        self.assertEqual(self.git("-C", str(self.repo), "remote", "get-url", "origin"), url)
        self.assertEqual((self.repo / "untracked").read_text(), "keep")

    def test_api_mode_never_creates_core_or_cask_checkout(self):
        self.mac.prefix = str(self.root / "prefix")
        self.mac.run = lambda *args: str(self.repo) if args == ("--repository",) else "custom/tap" if args == ("tap",) else str(self.writer)
        called = []
        with patch.object(self.preflight, "sync", side_effect=lambda repo, name: called.append(name)), patch.object(self.preflight, "repair_launcher"):
            self.preflight.run()
        self.assertEqual(called, ["brew", "custom/tap"])
        self.assertFalse((self.repo / "Library/Taps/homebrew").exists())

    def test_stale_launcher_is_repaired_but_user_file_is_preserved(self):
        prefix = self.root / "prefix"
        (prefix / "bin").mkdir(parents=True)
        repo = prefix / "Homebrew"
        (repo / "bin").mkdir(parents=True)
        target = repo / "bin/brew"
        target.write_text("fixture executable")
        target.chmod(0o755)
        link = prefix / "bin/brew"
        link.symlink_to("../Library/Homebrew/bin/brew")
        self.mac.prefix = str(prefix)
        self.assertEqual(executable_candidate(str(link)), str(target))
        self.preflight.repair_launcher(repo)
        self.assertEqual(link.resolve(), target.resolve())
        link.unlink()
        link.write_text("user file")
        with self.assertRaises(ActionRequired):
            self.preflight.repair_launcher(repo)
        self.assertEqual(link.read_text(), "user file")

    def test_missing_fetch_refspec_and_renamed_upstream_are_repaired(self):
        self.git("-C", str(self.repo), "config", "--unset", "remote.origin.fetch")
        self.git("-C", str(self.repo), "config", "branch.master.merge", "refs/heads/removed")
        self.preflight.sync(self.repo, "custom/tap")
        self.assertEqual(self.git("-C", str(self.repo), "config", "branch.master.merge"), "refs/heads/master")
        self.assertEqual(self.git("-C", str(self.repo), "config", "remote.origin.fetch"), "+refs/heads/*:refs/remotes/origin/*")

    def test_stable_brew_stays_on_release_tags(self):
        self.git("-C", str(self.writer), "tag", "7.0.0")
        self.commit(self.writer, "release")
        self.git("-C", str(self.writer), "tag", "7.0.1")
        self.commit(self.writer, "unreleased")
        self.git("-C", str(self.writer), "push", "--tags", "origin", "master")
        self.git("-C", str(self.repo), "branch", "stable")
        self.git("-C", str(self.repo), "switch", "stable")
        self.preflight.sync(self.repo, "brew")
        self.assertEqual((self.repo / "formula").read_text(), "release")
        self.assertEqual(self.git("-C", str(self.repo), "branch", "--show-current"), "stable")

    def test_legacy_environment_override_is_normalized_and_private_mirror_preserved(self):
        self.mac.env["HOMEBREW_BREW_GIT_REMOTE"] = "git://github.com/mxcl/homebrew.git"
        Preflight(self.mac)
        self.assertEqual(self.mac.env["HOMEBREW_BREW_GIT_REMOTE"], OFFICIAL["brew"])
        self.mac.env["HOMEBREW_CORE_GIT_REMOTE"] = "https://example.invalid/mirror"
        Preflight(self.mac)
        self.assertEqual(self.mac.env["HOMEBREW_CORE_GIT_REMOTE"], "https://example.invalid/mirror")


class StopProcessTests(unittest.TestCase):
    def tearDown(self):
        STOP.clear()

    def exercise(self, stubborn, detached=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child_record = root / "child"
            cleaned = root / "cleaned"
            child = "import signal,time; " + ("signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); " if stubborn else "") + "time.sleep(60)"
            code = ("import subprocess,sys,time,pathlib,signal; "
                    + ("signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); " if stubborn else "")
                    + "p=subprocess.Popen([sys.executable,'-c',sys.argv[1]],start_new_session=" + str(detached) + "); pathlib.Path(sys.argv[2]).write_text(str(p.pid));\n"
                    + "try: time.sleep(60)\nexcept KeyboardInterrupt: p.wait(); pathlib.Path(sys.argv[3]).write_text('clean exit')\n")
            outcome = []
            def worker():
                try:
                    run_command([sys.executable, "-c", code, child, str(child_record), str(cleaned)], interrupt_timeout=0.4, terminate_timeout=0.3)
                except JobStopped:
                    outcome.append("stopped")
            thread = threading.Thread(target=worker)
            thread.start()
            deadline = time.monotonic() + 5
            while not child_record.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(child_record.exists())
            time.sleep(0.1)
            STOP.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome, ["stopped"])
            pid = int(child_record.read_text())
            status = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
            self.assertTrue(status.returncode != 0 or status.stdout.strip().startswith("Z"), status.stdout)
            if not stubborn:
                self.assertEqual(cleaned.read_text(), "clean exit")

    def test_graceful_stop_reaches_homebrew_child_and_preserves_cleanup(self):
        self.exercise(False)

    def test_stubborn_process_uses_fallback_only_after_timeout(self):
        start = time.monotonic()
        self.exercise(True)
        self.assertGreaterEqual(time.monotonic() - start, 0.7)

    def test_stop_also_reaches_child_that_created_a_separate_session(self):
        self.exercise(True, detached=True)


if __name__ == "__main__":
    unittest.main()
