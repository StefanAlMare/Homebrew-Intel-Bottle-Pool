"""v0.3.5: installed-keg provenance and redundant tap-sync regressions."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from pool.brew import Brew
from pool.common import PoolError
from test_pool import FakeBrew, Fixture


class InstalledKegProvenanceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.prefix = self.root / "brew"
        self.mac = FakeBrew(self.clients[0], str(self.prefix))
        self.dep = copy.deepcopy(self.mac.records["demo"])
        self.dep.update(name="dep", full_name="dep",
                        installed=[{"version": "1.0", "used_options": []}])
        self.mac.records["dep"] = self.dep
        self.recipe = self.prefix / "Cellar/dep/1.0/.brew/dep.rb"
        self.recipe.parent.mkdir(parents=True)
        self.recipe.write_text("class Dep < Formula\n  url 'source-one'\nend\n")
        original = self.mac.run

        def run(*args, **kwargs):
            if args == ("deps", "--full-name", "demo"):
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


class TapSynchronizationTests(Fixture):
    def test_tap_is_fetched_once_but_recipe_verified_each_time(self):
        mac = FakeBrew(self.clients[0])
        original = mac.run

        def run(*args, **kwargs):
            if args == ("--repository", "homebrew/core"):
                return str(self.root / "tap")
            return original(*args, **kwargs)

        mac.run = run
        info = mac.info("demo")
        with patch("pool.brew.Preflight.sync") as sync, patch.object(
                mac, "verify_tap_formula", wraps=mac.verify_tap_formula) as verify:
            Brew.sync_tap_for_build(mac, info)
            Brew.sync_tap_for_build(mac, info)
            Brew.sync_tap_for_build(mac, info)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(mac.synced_taps, {"homebrew/core"})


if __name__ == "__main__":
    unittest.main()
