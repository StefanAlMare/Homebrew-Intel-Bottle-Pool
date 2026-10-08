"""v0.3.5: installed-keg provenance and redundant tap-sync regressions."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from pool.brew import Brew, BeforeBuildContextChanged
from pool.common import PoolError, canonical, key_for
from pool.jobs import Job, step
import hashlib
from test_pool import FakeBrew, Fixture


class InstalledKegProvenanceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.prefix = self.root / "brew"
        self.mac = FakeBrew(self.clients[0], str(self.prefix))
        self.mac.installed_source_hash = Brew.installed_source_hash.__get__(self.mac, Brew)
        self.dep = copy.deepcopy(self.mac.records["demo"])
        self.dep.update(name="dep", full_name="dep",
                        installed=[{"version": "1.0", "used_options": []}])
        self.mac.records["dep"] = self.dep
        self.recipe = self.prefix / "Cellar/dep/1.0/.brew/dep.rb"
        self.recipe.parent.mkdir(parents=True)
        self.recipe.write_text("class Dep < Formula\n  url 'source-one'\nend\n")
        original = self.mac.run

        def run(*args, **kwargs):
            if args == ("deps", "--full-name", "--os=tahoe", "demo"):
                return "dep"
            return original(*args, **kwargs)

        self.mac.run = run

    def manifest(self):
        return self.mac.manifest(self.mac.info("demo"))

    def test_dependency_api_source_change_does_not_change_variant(self):
        before = self.manifest()
        self.dep["ruby_source_checksum"]["sha256"] = "f" * 64
        after = self.manifest()
        self.assertEqual(before["variant"], after["variant"])
        self.assertEqual(before["metadata"]["context"], after["metadata"]["context"])
        self.assertEqual(after["metadata"]["context"]["dependency_identity"],
                         "installed-keg-brew-sha256-v1")

    def test_change_in_actual_installed_recipe_changes_variant(self):
        before = self.manifest()
        self.recipe.write_text("class Dep < Formula\n  url 'source-two'\nend\n")
        after = self.manifest()
        self.assertNotEqual(before["variant"], after["variant"])
        self.assertIn("dep: source", Brew.context_delta(
            before["metadata"]["context"], after["metadata"]["context"]))

    def test_missing_installed_recipe_fails_closed(self):
        self.recipe.unlink()
        with self.assertRaisesRegex(PoolError, "Installed dependency recipe missing"):
            self.manifest()

    def test_symlinked_installed_recipe_fails_closed(self):
        alternate = self.root / "different.rb"
        alternate.write_text("different")
        self.recipe.unlink()
        self.recipe.symlink_to(alternate)
        with self.assertRaisesRegex(PoolError, "Installed dependency recipe missing or linked"):
            self.manifest()

    def test_unrelated_old_keg_does_not_change_variant(self):
        old = self.prefix / "Cellar/dep/0.9/.brew/dep.rb"
        old.parent.mkdir(parents=True)
        old.write_text("old")
        before = self.manifest()
        old.write_text("old-changed")
        self.assertEqual(before["variant"], self.manifest()["variant"])

    def test_target_formula_api_change_is_still_detected(self):
        before = self.manifest()
        self.mac.records["demo"]["ruby_source_checksum"]["sha256"] = "f" * 64
        after = self.manifest()
        self.assertNotEqual(before["metadata"]["context"], after["metadata"]["context"])
        self.assertIn("formula_sha256", Brew.context_delta(
            before["metadata"]["context"], after["metadata"]["context"]))

    def test_repeat_reads_are_deterministic(self):
        self.assertEqual(self.manifest()["variant"], self.manifest()["variant"])

    def test_installed_version_change_changes_variant(self):
        before = self.manifest()
        self.dep["versions"]["stable"] = "2.0"
        self.dep["installed"][0]["version"] = "2.0"
        new = self.prefix / "Cellar/dep/2.0/.brew/dep.rb"
        new.parent.mkdir(parents=True)
        new.write_bytes(self.recipe.read_bytes())
        self.assertNotEqual(before["variant"], self.manifest()["variant"])

    def test_linked_recipe_directory_is_refused(self):
        directory = self.recipe.parent
        saved = directory.with_name("saved")
        directory.rename(saved)
        directory.symlink_to(saved, target_is_directory=True)
        with self.assertRaisesRegex(PoolError, "linked ancestry"):
            self.manifest()

    def test_schema1_legacy_variant_is_separate_and_not_poured(self):
        current = self.manifest()
        old = copy.deepcopy(current)
        old["metadata"]["context"].pop("dependency_identity")
        old["variant"] = hashlib.sha256(canonical({
            "prefix": self.mac.prefix, "cellar": self.mac.cellar,
            "cpu": "homebrew-baseline", "options": [],
            "runtime_abi": current["metadata"]["context"]["dependencies"]})).hexdigest()
        payload = self.root / "old.bottle.tar.gz"
        payload.write_bytes(b"legacy bottle")
        from pool.common import digest
        old.update(sha256=digest(payload), size=payload.stat().st_size)
        # Model an artifact already published by the old client. The new client
        # intentionally quarantines incomplete legacy spool entries instead.
        import shutil
        lease = self.store.acquire(key_for(old), "legacy-fixture")
        staged = self.store.staging / "legacy-payload"
        shutil.copyfile(payload, staged)
        self.store.commit(old, staged, lease["token"])
        self.store.release(key_for(old), lease["token"])
        self.assertEqual(current["schema"], 1)
        self.assertNotEqual(key_for(old), key_for(current))
        self.assertFalse(self.mac.consume_local(current))
        self.assertEqual(self.clients[1].lookup(old)["sha256"], old["sha256"])


class TargetRecipeNormalizationTests(Fixture):
    def test_homebrew_bottle_stanza_removal_preserves_exact_other_bytes(self):
        mac = FakeBrew(self.clients[0])
        source = "class Demo < Formula\n  url 'source'\n\n  bottle do\n    sha256 cellar: :any, sequoia: 'abc'\n  end\n\n  depends_on 'brotli'\nend\n"
        expected = "class Demo < Formula\n  url 'source'\n\n  depends_on 'brotli'\nend\n"
        mac.records["demo"]["_fixture_recipe"] = source
        mac.records["demo"]["ruby_source_checksum"]["sha256"] = hashlib.sha256(source.encode()).hexdigest()
        self.assertEqual(mac.planned_installed_recipe_hash(mac.info("demo")), hashlib.sha256(expected.encode()).hexdigest())

    def test_unverified_local_recipe_is_rejected(self):
        mac = FakeBrew(self.clients[0])
        mac.records["demo"]["ruby_source_checksum"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(PoolError, "Local recipe bytes differ"):
            mac.planned_installed_recipe_hash(mac.info("demo"))


class AutomaticRecoveryTests(Fixture):
    def test_refresh_once_before_build_preserves_retry_boundary_and_six_remaining(self):
        mac = FakeBrew(self.clients[0])
        job = Job(mac.client.state)
        job.start("upgrade", [step("formula", "demo")] + [step("formula", "later-" + str(n)) for n in range(6)], {"allow_build": True})
        job.data["steps"][0].update(status="failed", failed_package="demo", error="context changed")
        job.data["status"] = "paused_error"
        job.save()
        original = mac.build
        calls = []
        def build(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise BeforeBuildContextChanged("fixture race")
            return original(*args, **kwargs)
        mac.build = build
        mac._run_job(Job(mac.client.state), "retry")
        report = Job(mac.client.state).report()
        self.assertEqual((report["status"], report["failed_count"], report["remaining_count"]), ("paused", 0, 6))
        self.assertEqual(len(calls), 2)
        self.assertEqual(sum(c[0] == "install" and "--build-bottle" in c for c in mac.calls), 1)
        self.assertFalse(any(c[0] == "update" for c in mac.calls))

    def test_repeated_context_drift_stops_without_compiling(self):
        mac = FakeBrew(self.clients[0])
        with patch.object(mac, "build", side_effect=BeforeBuildContextChanged("unstable")) as build:
            with self.assertRaisesRegex(BeforeBuildContextChanged, "unstable"):
                mac.ensure("demo")
        self.assertEqual(build.call_count, 2)
        self.assertFalse(any(c[0] == "install" for c in mac.calls))

    def test_missing_provenance_is_not_automatically_retried(self):
        mac = FakeBrew(self.clients[0])
        with patch.object(mac, "_ensure", side_effect=PoolError("recipe missing")) as ensure:
            with self.assertRaisesRegex(PoolError, "recipe missing"):
                mac.ensure("demo")
        self.assertEqual(ensure.call_count, 1)


class TapSynchronizationTests(Fixture):
    def test_tap_is_fetched_once_but_recipe_verified_each_time(self):
        mac = FakeBrew(self.clients[0])
        original = mac.run

        def run(*args, **kwargs):
            if args == ("--repository", "homebrew/core"):
                return str(self.root / "tap")
            return original(*args, **kwargs)

        mac.run = run
        import subprocess
        repo = self.root / "tap"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "branch." + subprocess.check_output(["git", "-C", str(repo), "branch", "--show-current"], text=True).strip() + ".remote", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "branch." + subprocess.check_output(["git", "-C", str(repo), "branch", "--show-current"], text=True).strip() + ".merge", "refs/heads/" + subprocess.check_output(["git", "-C", str(repo), "branch", "--show-current"], text=True).strip()], check=True)
        info = mac.info("demo")
        with patch("pool.brew.Preflight.sync") as sync, patch.object(
                mac, "verify_tap_formula", wraps=mac.verify_tap_formula) as verify:
            Brew.sync_tap_for_build(mac, info)
            Brew.sync_tap_for_build(mac, info)
            Brew.sync_tap_for_build(mac, info)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(mac.synced_taps, {"homebrew/core"})

class DeclaredGraphBuildTests(Fixture):
    """Model old-keg/new-keg graph switching, independent of formula names."""
    def mac(self):
        from pool.common import digest
        mac = FakeBrew(self.clients[0], str(self.root / "brew"))
        target = mac.records["demo"]
        target["ruby_source_checksum"]["sha256"] = hashlib.sha256(b"target recipe").hexdigest()
        target["_fixture_recipe"] = "target recipe"
        target["installed"] = [{"version": "0.9", "used_options": []}]
        dep = copy.deepcopy(target)
        dep.update(name="brotli", full_name="brotli", versions={"stable": "1.2.0"},
                   installed=[{"version": "1.2.0", "used_options": []}])
        recipe = Path(mac.cellar) / "brotli/1.2.0/.brew/brotli.rb"
        recipe.parent.mkdir(parents=True)
        recipe.write_text("installed brotli recipe")
        dep["ruby_source_checksum"]["sha256"] = digest(recipe)
        mac.records["brotli"] = dep
        mac.installed_source_hash = Brew.installed_source_hash.__get__(mac, Brew)
        original = mac.run
        def run(*args, **kwargs):
            if args[0] == "deps" and args[-1] == "demo":
                if "--os=tahoe" in args:
                    return "brotli"
                return "brotli" if target["installed"][0]["version"] == "1.0" else ""
            if args[0] == "install" and "--build-bottle" in args:
                self.assertEqual(mac.env.get("HOMEBREW_NO_INSTALL_FROM_API"), "1")
                result = original(*args, **kwargs)
                target["installed"][0]["built_as_bottle"] = True
                target_recipe = Path(mac.cellar) / "demo/1.0/.brew/demo.rb"
                target_recipe.parent.mkdir(parents=True, exist_ok=True)
                target_recipe.write_text("target recipe")
                return result
            return original(*args, **kwargs)
        mac.run = run
        return mac, recipe

    def test_old_runtime_graph_to_new_runtime_graph_does_not_invalidate_plan(self):
        mac, _ = self.mac()
        mac.ensure("demo")
        self.assertEqual(sum(c[0] == "install" and "--build-bottle" in c for c in mac.calls), 1)
        manifest = next(self.store.objects.glob("*/manifest.json"))
        import json
        self.assertIn("brotli", json.loads(manifest.read_text())["metadata"]["context"]["dependencies"])

    def test_real_dependency_change_rebuilds_once_and_keeps_five_pending(self):
        mac, recipe = self.mac()
        original = mac.run
        tests = []
        def run(*args, **kwargs):
            if args[0] == "test":
                tests.append(1)
                if len(tests) == 1:
                    recipe.write_text("changed binary provenance")
            return original(*args, **kwargs)
        mac.run = run
        job = Job(mac.client.state)
        job.start("upgrade", [step("formula", "demo")] + [step("formula", "later-" + str(n)) for n in range(5)], {"allow_build": True})
        job.data["steps"][0].update(status="failed", failed_package="demo", error="context drift")
        job.data["status"] = "paused_error"
        job.save()
        mac._run_job(Job(mac.client.state), "retry")
        report = Job(mac.client.state).report()
        self.assertEqual((report["status"], report["failed_count"], report["remaining_count"]), ("paused", 0, 5))
        self.assertEqual(len(tests), 2)
        self.assertEqual(sum(c[0] == "install" and "--build-bottle" in c for c in mac.calls), 2)
        self.assertEqual(len(list(self.store.objects.glob("*/manifest.json"))), 1)

    def test_failed_test_retries_proven_build_without_recompilation(self):
        mac, _ = self.mac()
        mac.fail_test = True
        with self.assertRaisesRegex(PoolError, "simulated brew test failure"):
            mac.ensure("demo")
        mac.fail_test = False
        mac.force_targets.add("demo")
        mac.ensure("demo")
        self.assertEqual(sum(c[0] == "install" and "--build-bottle" in c for c in mac.calls), 1)
        self.assertTrue(list(self.store.objects.glob("*/manifest.json")))

    def test_build_only_input_drift_also_requires_safe_rebuild(self):
        mac, _ = self.mac()
        tool = copy.deepcopy(mac.records["brotli"])
        tool.update(name="buildtool", full_name="buildtool")
        mac.records["buildtool"] = tool
        recipe = Path(mac.cellar) / "buildtool/1.2.0/.brew/buildtool.rb"
        recipe.parent.mkdir(parents=True)
        recipe.write_text("build tool recipe")
        original = mac.run
        tests = []
        def run(*args, **kwargs):
            if args[0] == "deps" and args[-1] == "demo" and "--include-build" in args:
                return "brotli\nbuildtool"
            if args[0] == "test":
                tests.append(1)
                if len(tests) == 1:
                    recipe.write_text("updated build tool recipe")
            return original(*args, **kwargs)
        mac.run = run
        mac.ensure("demo")
        self.assertEqual(len(tests), 2)
        self.assertEqual(sum(c[0] == "install" and "--build-bottle" in c for c in mac.calls), 2)
        self.assertEqual(len(list(self.store.objects.glob("*/manifest.json"))), 1)

    def test_repeated_real_dependency_drift_stops_after_two_builds(self):
        mac, recipe = self.mac()
        original = mac.run
        counter = []
        def run(*args, **kwargs):
            if args[0] == "test":
                counter.append(1)
                recipe.write_text("changed-" + str(len(counter)))
            return original(*args, **kwargs)
        mac.run = run
        with self.assertRaisesRegex(PoolError, "context changed during build"):
            mac.ensure("demo")
        self.assertEqual(len(counter), 2)
        self.assertFalse(list(self.store.objects.glob("*/manifest.json")))
        self.assertFalse(list(self.client("mac-a").spool.glob("entry-*/manifest.json")))
        self.assertFalse(list((Path(mac.cellar) / "demo").glob("*.pool-backup-*")))

    def test_undeclared_runtime_dependency_never_publishes(self):
        mac, _ = self.mac()
        original = mac.run
        def run(*args, **kwargs):
            if args == ("deps", "--full-name", "demo"):
                return "brotli\nunexpected-library"
            return original(*args, **kwargs)
        mac.run = run
        with self.assertRaisesRegex(PoolError, "Undeclared installed runtime"):
            mac.ensure("demo")
        self.assertFalse(list(self.store.objects.glob("*/manifest.json")))


if __name__ == "__main__":
    unittest.main()
