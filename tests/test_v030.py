import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pool.brew import Brew
from pool.common import PoolError
from pool.settings import configure_gui
from test_pool import Fixture, FakeBrew


class SettingsTests(Fixture):
    def values(self):
        return {"url": self.clients[0].url, "token": self.token.read_text(), "ca_file": ""}

    def test_test_connection_changes_neither_config_nor_live_spool(self):
        config = self.root / "new/config.json"
        result = configure_gui(config, self.values())
        self.assertTrue(result["connected"])
        self.assertFalse(config.exists())
        self.assertFalse(config.parent.exists())

    def test_save_preserves_adapters_and_existing_secret_and_state(self):
        config = self.root / "config.json"
        initial = dict(self.clients[0].config, artifacts=[{"name": "private-adapter"}], python=sys.executable)
        config.write_text(json.dumps(initial))
        old_token = self.token.read_bytes()
        values = self.values()
        configure_gui(config, values, save=True)
        updated = json.loads(config.read_text())
        self.assertEqual(updated["artifacts"], initial["artifacts"])
        self.assertEqual(updated["python"], sys.executable)
        self.assertEqual(updated["state_dir"], initial["state_dir"])
        self.assertEqual(self.token.read_bytes(), old_token)
        self.assertNotEqual(updated["token_file"], initial["token_file"])
        self.assertEqual(Path(updated["token_file"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_bad_token_does_not_overwrite_configuration(self):
        config = self.root / "config.json"
        config.write_text(json.dumps(self.clients[0].config))
        before = config.read_bytes()
        with self.assertRaisesRegex(PoolError, "Authentication failed"):
            configure_gui(config, dict(self.values(), token="wrong"), save=True)
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse(list(self.root.glob("token-*")))

    def test_file_token_and_api_version(self):
        values = dict(self.values(), token="", token_file=str(self.token))
        self.assertTrue(configure_gui(self.root / "config.json", values)["connected"])
        with patch("pool.settings.Client.json_request", return_value={"schema": 2, "status": "ok"}):
            with self.assertRaisesRegex(PoolError, "incompatible"):
                configure_gui(self.root / "config.json", values, save=True)
        self.assertFalse((self.root / "config.json").exists())

    def test_gui_stdin_does_not_echo_token(self):
        result = subprocess.run([sys.executable, "entry.py", "--config", str(self.root / "new.json"), "settings"],
                                input=json.dumps(self.values()), capture_output=True, text=True, check=True)
        self.assertNotIn(self.token.read_text(), result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["connected"])


class FakeCaskBrew(FakeBrew):
    payload = b"verified fixture cask download"

    def __init__(self, client):
        super().__init__(client)
        self.cask_record = {"token": "browser", "full_token": "browser", "version": "1.2.3",
                            "sha256": hashlib.sha256(self.payload).hexdigest(),
                            "url": "https://example.invalid/browser.dmg", "installed": None,
                            "depends_on": {}, "language": []}
        self.bad_download = False

    def run(self, *args, **kwargs):
        if "--cask" in args and args[0] in ("info", "--cache", "fetch", "install", "upgrade"):
            self.calls.append(args)
            if args[0] == "info":
                return json.dumps({"casks": [copy.deepcopy(self.cask_record)]})
            cache = self.client.state / "cask-cache/browser.dmg"
            if args[0] == "--cache":
                return str(cache)
            if args[0] == "fetch":
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(b"bad" if self.bad_download else self.payload)
            if args[0] in ("install", "upgrade"):
                self.cask_record["installed"] = "1.2.3"
            return ""
        return super().run(*args, **kwargs)


class InstallTests(Fixture):
    def test_formula_install_then_pool_hit_with_build_disabled(self):
        FakeBrew.builds = 0
        first, second = FakeBrew(self.clients[0]), FakeBrew(self.clients[1])
        first.install("demo", "formula", update=False)
        second.install("demo", "formula", allow_build=False, update=False)
        self.assertEqual(FakeBrew.builds, 1)
        self.assertTrue(second.up_to_date(second.info("demo")))

    def test_auto_ambiguity_and_invalid_names_install_nothing(self):
        mac = FakeBrew(self.clients[0])
        with patch.object(mac, "run", return_value=json.dumps({"formulae": [{}], "casks": [{}]})):
            with self.assertRaisesRegex(PoolError, "both Formula and Cask"):
                mac.resolve("demo")
        for name in ("--force", "foo;bar", "https://example.com", "/tmp/package.rb", "a b", "../foo"):
            with self.assertRaises(PoolError):
                mac.install(name, update=False)
        self.assertFalse(any(call[0] == "install" for call in mac.calls))

    def test_cask_install_then_other_mac_fetches_pool_without_upstream(self):
        first, second = FakeCaskBrew(self.clients[0]), FakeCaskBrew(self.clients[1])
        first.install("browser", "cask", update=False)
        self.assertIn(("install", "--cask", "browser"), first.calls)
        second.install("browser", "cask", update=False)
        self.assertNotIn(("fetch", "--cask", "browser"), second.calls)
        self.assertEqual(len(list(self.store.objects.glob("*/manifest.json"))), 1)

    def test_existing_cask_uses_upgrade(self):
        mac = FakeCaskBrew(self.clients[0])
        mac.cask_record["installed"] = "1.0"
        mac.install("browser", "cask", update=False)
        self.assertIn(("upgrade", "--cask", "browser"), mac.calls)

    def test_corrupt_cask_is_neither_published_nor_installed(self):
        mac = FakeCaskBrew(self.clients[0])
        mac.bad_download = True
        with self.assertRaisesRegex(PoolError, "checksum mismatch"):
            mac.install("browser", "cask", update=False)
        self.assertFalse(list(self.store.objects.glob("*/manifest.json")))
        self.assertNotIn(("install", "--cask", "browser"), mac.calls)

    def test_mutable_cask_requires_explicit_upstream_only_and_never_publishes(self):
        mac = FakeCaskBrew(self.clients[0])
        mac.cask_record.update(version="latest", sha256="no_check")
        with self.assertRaisesRegex(PoolError, "cannot be pooled"):
            mac.install("browser", "cask", update=False)
        mac.install("browser", "cask", update=False, allow_mutable_cask=True, mode="resume")
        self.assertIn(("install", "--cask", "browser"), mac.calls)
        self.assertFalse(list(self.store.objects.glob("*/manifest.json")))

    def test_failed_cask_dependency_is_not_marked_as_success(self):
        mac = FakeCaskBrew(self.clients[0])
        mac.bad_download = True
        with self.assertRaises(PoolError):
            mac.cask("browser", install=True)
        self.assertNotIn("browser", mac.casks_seen)
        mac.bad_download = False
        mac.cask("browser", install=True)
        self.assertIn("browser", mac.casks_seen)

    def test_cyclic_cask_dependency_is_refused_before_install(self):
        mac = FakeCaskBrew(self.clients[0])
        mac.cask_record["depends_on"] = {"cask": ["browser"]}
        with self.assertRaisesRegex(PoolError, "Cyclic"):
            mac.install("browser", "cask", update=False)
        self.assertNotIn(("install", "--cask", "browser"), mac.calls)


class FakeOfficialBrew(FakeBrew):
    payload = b"fixture official bottle"

    def __init__(self, client):
        super().__init__(client)
        self.records["demo"]["bottle"]["stable"]["files"] = {
            "tahoe": {"cellar": ":any", "sha256": hashlib.sha256(self.payload).hexdigest()}}

    def run(self, *args, **kwargs):
        cache = self.client.state / "official-cache/demo.bottle.tar.gz"
        if args[0] == "--cache" and len(args) > 1:
            self.calls.append(args)
            return str(cache)
        if args[0] == "fetch":
            self.calls.append(args)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(self.payload)
            return ""
        return super().run(*args, **kwargs)


class OfficialBottleTests(Fixture):
    def test_official_bottle_is_published_and_reused_without_upstream_or_build(self):
        FakeBrew.builds = 0
        first, second = FakeOfficialBrew(self.clients[0]), FakeOfficialBrew(self.clients[1])
        first.install("demo", "formula", update=False)
        second.install("demo", "formula", allow_build=False, update=False)
        self.assertEqual(FakeBrew.builds, 0)
        self.assertTrue(any(call[0] == "fetch" for call in first.calls))
        self.assertFalse(any(call[0] == "fetch" for call in second.calls))
        self.assertTrue(second.up_to_date(second.info("demo")))
        manifests = list(self.store.objects.glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        self.assertEqual(json.loads(manifests[0].read_text())["kind"], "brew-upstream-bottle")


class SafeTapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.origin = self.root / "origin.git"
        self.repo = self.root / "tap"
        self.writer = self.root / "writer"
        self.git("init", "--bare", str(self.origin))
        self.git("clone", str(self.origin), str(self.repo))
        self.commit(self.repo, "initial")
        self.git("-C", str(self.repo), "push", "-u", "origin", "HEAD")
        self.git("clone", str(self.origin), str(self.writer))
        self.mac = Brew.__new__(Brew)
        self.mac.env = dict(os.environ)
        self.mac.synced_taps = set()
        self.mac.run = lambda *args: "homebrew/core" if args == ("tap",) else str(self.repo)
        self.mac.verify_tap_formula = lambda info: None

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self, repo, value):
        (repo / "formula").write_text(value)
        self.git("-C", str(repo), "add", "formula")
        self.git("-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", value)

    def sync(self):
        self.mac.sync_tap_for_build({"tap": "homebrew/core"})

    def test_clean_fast_forward(self):
        self.commit(self.writer, "upstream")
        self.git("-C", str(self.writer), "push")
        self.sync()
        self.assertEqual((self.repo / "formula").read_text(), "upstream")

    def test_cached_sync_still_refuses_new_dirty_files_and_local_commits(self):
        self.sync()
        (self.repo / "during-build").write_text("preserve")
        with self.assertRaisesRegex(PoolError, "modified"):
            self.sync()
        (self.repo / "during-build").unlink()
        self.commit(self.repo, "local-during-build")
        with self.assertRaisesRegex(PoolError, "divergent"):
            self.sync()
        self.assertEqual((self.repo / "formula").read_text(), "local-during-build")

    def test_dirty_detached_and_divergent_are_preserved(self):
        (self.repo / "untracked").write_text("keep")
        with self.assertRaisesRegex(PoolError, "modified"):
            self.sync()
        self.assertEqual((self.repo / "untracked").read_text(), "keep")
        (self.repo / "untracked").unlink()
        branch = self.git("-C", str(self.repo), "branch", "--show-current")
        self.git("-C", str(self.repo), "switch", "--detach")
        before = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        with self.assertRaisesRegex(PoolError, "detached"):
            self.sync()
        self.assertEqual(self.git("-C", str(self.repo), "rev-parse", "HEAD"), before)
        self.git("-C", str(self.repo), "switch", branch)
        self.commit(self.repo, "local")
        self.commit(self.writer, "remote")
        self.git("-C", str(self.writer), "push")
        before = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        with self.assertRaisesRegex(PoolError, "divergent"):
            self.sync()
        self.assertEqual(self.git("-C", str(self.repo), "rev-parse", "HEAD"), before)
        self.assertEqual((self.repo / "formula").read_text(), "local")


if __name__ == "__main__":
    unittest.main()
