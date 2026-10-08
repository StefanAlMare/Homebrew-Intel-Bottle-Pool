import concurrent.futures
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pool.artifacts import manifest_for, obtain
from pool.brew import Brew
from pool.client import Client, Lease, RemoteError, Unavailable
from pool.common import PoolError, digest, key_for, version_order
from pool.server import Server, Store


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.token = self.root / "token"
        self.token.write_text("test-" + "a" * 64)
        self.store = Store(self.root / "server", lease_seconds=1.2)
        self.server = Server(("127.0.0.1", 0), self.store, self.token.read_text())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.clients = [self.client("mac-a"), self.client("mac-b")]

    def client(self, name):
        return Client({"url": "http://127.0.0.1:%s" % self.server.server_port,
                       "token_file": str(self.token), "state_dir": str(self.root / name), "timeout": 0.5,
                       "lock_wait_seconds": 5})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.close()
        self.temp.cleanup()

    def artifact(self, version="1.0", contents=b"compiled binary", variant="default"):
        file = self.root / ("input-" + version)
        file.write_bytes(contents)
        recipe = {"name": "toolchain/example", "version": version, "platform": "macos-x86_64-tahoe",
                  "variant": variant, "destination": "example.pkg", "source": "reviewed vendor"}
        return manifest_for(recipe, file), file

    def publish(self, manifest, source, client=None):
        client = client or self.clients[0]
        queued = client.enqueue(manifest, source)
        return client.publish_entry(queued)


class ProtocolTests(Fixture):
    def test_publish_download_and_keep_only_latest(self):
        m1, f1 = self.artifact()
        self.assertEqual(self.publish(m1, f1)["status"], "published")
        m2, f2 = self.artifact("2.0", b"new binary")
        self.assertEqual(self.publish(m2, f2)["status"], "published")
        directory = self.store.objects / key_for(m2)
        blobs = [x for x in directory.iterdir() if len(x.name) == 64]
        self.assertEqual([x.name for x in blobs], [m2["sha256"]])
        self.assertEqual(self.publish(m1, f1)["status"], "older")
        found = self.clients[1].lookup(m2)
        output = self.root / "received.pkg"
        self.clients[1].fetch(found, output)
        self.assertEqual(output.read_bytes(), b"new binary")

    def test_version_not_upload_time_and_no_equal_rank_overwrite(self):
        m, f = self.artifact("10.0")
        self.publish(m, f)
        old, file = self.artifact("9.9", b"later but older")
        self.assertEqual(self.publish(old, file)["status"], "older")
        conflict, file = self.artifact("10.0", b"different compilation")
        with self.assertRaises(RemoteError):
            self.publish(conflict, file)
        self.assertEqual(self.clients[0].lookup(m)["sha256"], m["sha256"])
        self.assertEqual(len(list(self.clients[0].spool.glob("entry-*/manifest.json"))), 1)

    def test_corrupt_upload_never_replaces_good_artifact(self):
        m, f = self.artifact()
        self.publish(m, f)
        newer, f = self.artifact("2.0", b"valid new bytes")
        with Lease(self.clients[0], newer) as lease:
            bad = self.root / "bad-upload"
            bad.write_bytes(b"tampered bytes")
            with self.assertRaises(PoolError):
                self.clients[0].upload(newer, bad, lease)
            # Bypass the client check to exercise server-side verification.
            staged = self.store.staging / "direct-bad"
            staged.write_bytes(b"tampered bytes")
            with self.assertRaises(PoolError):
                self.store.commit(newer, staged, lease.token)
        self.assertEqual(self.clients[0].lookup(m)["sha256"], m["sha256"])

    def test_corrupt_storage_is_not_served_and_can_be_repaired(self):
        m, f = self.artifact()
        self.publish(m, f)
        (self.store.objects / key_for(m) / m["sha256"]).write_bytes(b"corruption")
        with self.assertRaises(RemoteError):
            self.clients[1].fetch(m, self.root / "must-not-exist")
        self.assertFalse((self.root / "must-not-exist").exists())
        self.assertEqual(self.publish(m, f)["status"], "published")

    def test_platform_and_prefix_variants_are_independent(self):
        m, f = self.artifact(variant="prefix-a")
        self.publish(m, f)
        other = copy.deepcopy(m)
        other["variant"] = "prefix-b"
        self.assertIsNone(self.clients[1].lookup(other))
        other["variant"] = m["variant"]
        other["platform"] = "macos-x86_64-sequoia"
        self.assertIsNone(self.clients[1].lookup(other))

    def test_lease_exclusion_heartbeat_and_fencing(self):
        m, f = self.artifact()
        with Lease(self.clients[0], m) as first:
            with Lease(self.clients[1], m, wait_seconds=0) as second:
                self.assertIsNone(second.token)
            time.sleep(1.4)  # exceeds TTL, heartbeat must keep lease alive
            with Lease(self.clients[1], m, wait_seconds=0) as second:
                self.assertIsNone(second.token)
        stale = self.store.acquire(key_for(m), "StefanAlMare")
        with self.store.guard:
            self.store.leases[key_for(m)]["expires"] = time.monotonic() - 1
        replacement = self.store.acquire(key_for(m), "StefanAlMare")
        staged = self.store.staging / "stale"
        staged.write_bytes(f.read_bytes())
        with self.assertRaises(PoolError):
            self.store.commit(m, staged, stale["token"])
        self.store.release(key_for(m), replacement["token"])

    def test_offline_spool_then_sync(self):
        m, f = self.artifact()
        client = self.clients[0]
        entry = client.enqueue(m, f)
        actual_url = client.url
        client.url = "http://127.0.0.1:1"
        self.assertEqual(client.sync(), ["offline"])
        self.assertTrue(entry.exists())
        client.url = actual_url
        self.assertEqual(client.sync(), ["published"])
        self.assertFalse(entry.exists())
        self.assertEqual(self.clients[1].lookup(m)["sha256"], m["sha256"])

    def test_authentication_and_traversal_rejected(self):
        client = self.clients[1]
        client.token = "wrong"
        with self.assertRaises(RemoteError) as error:
            client.json_request("GET", "health")
        self.assertEqual(error.exception.status, 401)
        m, f = self.artifact()
        m["filename"] = "../../other"
        with self.assertRaises(PoolError):
            self.clients[0].enqueue(m, f)
        m["filename"] = "valid.pkg"
        m["sha256"] = 42
        with self.assertRaises(PoolError):
            self.clients[0].enqueue(m, f)

    def test_inflight_download_is_pinned_to_checksum(self):
        m, f = self.artifact()
        self.publish(m, f)
        newer, f = self.artifact("2.0", b"other")
        self.publish(newer, f)
        with self.assertRaises(RemoteError) as error:
            self.clients[1].fetch(m, self.root / "stale-download")
        self.assertEqual(error.exception.status, 412)

    def test_atomic_manifest_failure_keeps_previous(self):
        m, f = self.artifact()
        self.publish(m, f)
        newer, f = self.artifact("2.0", b"other")
        with Lease(self.clients[0], newer) as lease:
            staged = self.store.staging / "interrupted"
            staged.write_bytes(f.read_bytes())
            with patch("pool.server.atomic_json", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    self.store.commit(newer, staged, lease.token)
        self.assertEqual(self.clients[1].lookup(m)["sha256"], m["sha256"])

    def test_only_one_server_owns_dataset(self):
        with self.assertRaises(PoolError):
            Store(self.store.root)

    def test_restart_cleans_orphans_and_fences_old_lease(self):
        m, f = self.artifact()
        self.publish(m, f)
        old_lease = self.store.acquire(key_for(m), "StefanAlMare")
        directory = self.store.objects / key_for(m)
        (directory / ("b" * 64)).write_bytes(b"uncommitted crash residue")
        (self.store.staging / "interrupted-upload").write_bytes(b"partial")
        root = self.store.root
        self.store.close()
        self.store = Store(root, lease_seconds=1.2)
        self.server.store = self.store
        with self.assertRaises(PoolError):
            self.store.check_lease(key_for(m), old_lease["token"])
        self.assertFalse((directory / ("b" * 64)).exists())
        self.assertFalse(list(self.store.staging.iterdir()))
        self.assertEqual(self.clients[1].lookup(m)["sha256"], m["sha256"])

    def test_slow_verification_does_not_block_heartbeat(self):
        m, f = self.artifact()
        self.publish(m, f)
        newer, file = self.artifact("2.0", b"new binary")
        old_blob = self.store.objects / key_for(m) / m["sha256"]
        started, finish = threading.Event(), threading.Event()
        from pool.server import digest as original_digest
        def delayed(path):
            if Path(path) == old_blob:
                started.set()
                finish.wait(4)
            return original_digest(path)
        staged = self.store.staging / "new-upload"
        staged.write_bytes(file.read_bytes())
        with Lease(self.clients[0], newer) as lease:
            with patch("pool.server.digest", side_effect=delayed):
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self.store.commit, newer, staged, lease.token)
                    self.assertTrue(started.wait(1))
                    time.sleep(1.4)
                    self.assertFalse(lease.lost)
                    finish.set()
                    self.assertEqual(future.result()["status"], "published")

    def test_external_producer_is_automatically_shared(self):
        recipe = {"name": "python-wheel/demo", "version": "1.0.0", "platform": "macos-x86_64-tahoe",
                  "variant": "cp313", "destination": str(self.root / "mac-a.whl"),
                  "command": [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'wheel')", "{output}"]}
        self.assertEqual(obtain(self.clients[0], recipe), "published")
        recipe["destination"] = str(self.root / "mac-b.whl")
        recipe["command"] = [sys.executable, "-c", "raise SystemExit('should not run')"]
        self.assertEqual(obtain(self.clients[1], recipe), "pool")
        self.assertEqual((self.root / "mac-b.whl").read_bytes(), b"wheel")

    def test_offline_external_build_and_later_sync(self):
        client = self.clients[0]
        original = client.url
        client.url = "http://127.0.0.1:1"
        recipe = {"name": "native-package", "version": "1.0", "platform": "macos-x86_64-tahoe",
                  "variant": "default", "destination": str(self.root / "offline.pkg"),
                  "command": [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'pkg')", "{output}"]}
        self.assertEqual(obtain(client, recipe), "spooled")
        client.url = original
        self.assertEqual(client.sync(), ["published"])


class FakeBrew(Brew):
    """Stateful public-CLI fixture: each instance represents a separate Intel Mac."""
    builds = 0
    build_guard = threading.Lock()

    def installed_keg_identity(self, info):
        if (Path(self.cellar) / info["name"] / self.pkg_version(info)).exists():
            return super().installed_keg_identity(info)
        return [0, 0]  # simulated filesystem only

    def installed_source_hash(self, info):
        if self.fixture_filesystem:
            return self.records[info["name"]]["ruby_source_checksum"]["sha256"]
        recipe = Path(self.cellar) / info["name"] / self.pkg_version(info) / ".brew" / (info["name"] + ".rb")
        if not recipe.exists():
            return self.records[info["name"]]["ruby_source_checksum"]["sha256"]
        return super().installed_source_hash(info)

    def snapshot_updated_taps(self):
        self.calls.append(("fixture-snapshot-updated-taps",))

    def preflight(self):
        self.calls.append(("fixture-preflight",))

    def sync_tap_for_build(self, info):
        self.verify_tap_formula(info)

    def __init__(self, client, prefix=None):
        self.fixture_filesystem = prefix is None
        prefix = prefix or "/custom/brew"
        self.records = {"demo": {"name": "demo", "full_name": "demo", "tap": "homebrew/core",
                                "versions": {"stable": "1.0"}, "revision": 0, "version_scheme": 0,
                                "ruby_source_checksum": {"sha256": hashlib.sha256(b"fixture recipe demo").hexdigest()}, "installed": [],
                                "outdated": False, "bottle": {"stable": {"files": {}, "rebuild": 0}}}}
        self.calls = []
        self.custom_prefix = prefix
        self.fail_test = False
        self.build_delay = 0
        with patch("pool.brew.platform.system", return_value="Darwin"), patch("pool.brew.platform.machine", return_value="x86_64"), patch.object(Brew, "run_system", return_value="26.0"):
            super().__init__(client, "fixture-brew")

    def run(self, *args, cwd=None, capture=True, env_extra=None):
        self.calls.append(args)
        if args == ("--prefix",):
            return self.custom_prefix
        if args == ("--cellar",):
            return self.custom_prefix + "/Cellar"
        if args == ("--cache",):
            return str(self.client.state / "brew-cache")
        if args[0] == "tap":
            return "homebrew/core"
        if args[0] == "info":
            return json.dumps({"formulae": [copy.deepcopy(self.records[args[-1].split("/")[-1]])]})
        if args[0] == "formula":
            record = self.records[args[-1].split("/")[-1]]
            path = self.client.state / "fixture-source" / (record["name"] + ".rb")
            path.parent.mkdir(exist_ok=True)
            path.write_text(record.get("_fixture_recipe", "fixture recipe " + record["name"]))
            return str(path)
        if args[0] == "deps":
            return ""
        if args[0] in ("install", "reinstall"):
            name = args[-1]
            if name.endswith(".tar.gz"):
                if env_extra != {"HOMEBREW_DEVELOPER": "1"}:
                    raise AssertionError("Local bottle install needs scoped developer mode")
                name = "demo"
                if not Path(args[-1]).exists():
                    raise AssertionError("Bottle path missing")
            else:
                with self.build_guard:
                    FakeBrew.builds += 1
                time.sleep(self.build_delay)
            self.records[name]["installed"] = [{"version": "1.0", "used_options": []}]
            if self.fixture_filesystem:
                keg = self.client.state / "fixture-kegs" / name / "1.0"
                keg.mkdir(parents=True, exist_ok=True)
                (keg / "fixture-payload").write_text("installed")
                (keg / ".brew").mkdir(exist_ok=True)
                (keg / ".brew" / (name.split("/")[-1] + ".rb")).write_text("fixture recipe " + name)
            return ""
        if args[0] == "bottle":
            file = Path(cwd) / "demo--1.0.tahoe.bottle.1.tar.gz"
            file.write_bytes(b"fixture Homebrew bottle")
            (Path(cwd) / "demo.json").write_text(json.dumps({"demo": {"bottle": {"cellar": self.cellar, "rebuild": 1, "tags": {"tahoe": {"sha256": digest(file)}}}}}))
            return ""
        if args[0] == "test":
            if self.fail_test:
                raise PoolError("simulated brew test failure")
            return ""
        if args[0] in ("postinstall", "missing", "update", "linkage"):
            return ""
        if args[0] == "outdated":
            return json.dumps({"formulae": [{"name": "demo", "pinned": False}], "casks": []})
        raise AssertionError("Unhandled fixture brew command: " + str(args))

    def _stage_current_keg(self, info):
        if not self.fixture_filesystem:
            return super()._stage_current_keg(info)
        keg = self.client.state / "fixture-kegs" / info["name"] / self.pkg_version(info)
        if not keg.is_dir():
            raise PoolError("Fixture keg is missing: " + str(keg))
        backup = keg.parent / (keg.name + ".pool-backup-fixture")
        os.replace(keg, backup)
        return {"name": info["full_name"], "keg": keg, "backup": backup,
                "linked_record": self.client.state / "fixture-linked" / info["name"],
                "was_linked": False}


class BrewTests(Fixture):
    def setUp(self):
        super().setUp()
        FakeBrew.builds = 0

    def test_two_macs_one_build_custom_prefix(self):
        a, b = FakeBrew(self.clients[0]), FakeBrew(self.clients[1])
        a.build_delay = 0.4
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(mac.ensure, "demo") for mac in (a, b)]
            for future in futures:
                future.result()
        self.assertEqual(FakeBrew.builds, 1)
        self.assertTrue(b.up_to_date(b.info("demo")))
        self.assertTrue(a.up_to_date(a.info("demo")))
        self.assertTrue(any(x[0] == "test" for x in a.calls + b.calls))

    def test_prefix_mismatch_builds_separate_variant(self):
        a, b = FakeBrew(self.clients[0], "/prefix/a"), FakeBrew(self.clients[1], "/prefix/b")
        a.ensure("demo")
        b.ensure("demo")
        self.assertEqual(FakeBrew.builds, 2)
        self.assertEqual(len(list(self.store.objects.glob("*/manifest.json"))), 2)

    def test_context_mismatch_never_pours_stale_formula(self):
        a = FakeBrew(self.clients[0])
        a.ensure("demo")
        b = FakeBrew(self.clients[1])
        b.records["demo"]["_fixture_recipe"] = "changed target source"
        b.records["demo"]["ruby_source_checksum"]["sha256"] = hashlib.sha256(b"changed target source").hexdigest()
        # Same rank, different target source: independent provenance variant.
        b.ensure("demo")
        self.assertEqual(FakeBrew.builds, 2)
        self.assertEqual(len(list(self.store.objects.glob("*/manifest.json"))), 2)
        self.assertFalse(any(x[0] == "install" and x[-1].endswith(".tar.gz") for x in b.calls))

    def test_offline_build_then_other_mac_consumes(self):
        client = self.clients[0]
        original = client.url
        client.url = "http://127.0.0.1:1"
        a = FakeBrew(client)
        a.ensure("demo")
        self.assertEqual(len(list(client.spool.glob("entry-*/manifest.json"))), 1)
        client.url = original
        self.assertEqual(client.sync(), ["published"])
        b = FakeBrew(self.clients[1])
        b.ensure("demo")
        self.assertEqual(FakeBrew.builds, 1)

    def test_failed_brew_test_does_not_publish(self):
        a = FakeBrew(self.clients[0])
        a.fail_test = True
        with self.assertRaises(PoolError):
            a.ensure("demo")
        self.assertFalse(list(self.store.objects.glob("*/manifest.json")))
        self.assertFalse(list(self.clients[0].spool.glob("entry-*/manifest.json")))

    def test_no_fixed_role_and_no_build_for_one_run(self):
        a = FakeBrew(self.clients[0])
        with self.assertRaises(PoolError):
            a.ensure("demo", allow_build=False)
        self.assertEqual(FakeBrew.builds, 0)
        a.ensure("demo", allow_build=True)
        self.assertEqual(FakeBrew.builds, 1)

    def test_upgrade_routine_and_installer(self):
        mac = FakeBrew(self.clients[0])
        mac.upgrade(casks=False)
        self.assertEqual(mac.calls.count(("update",)), 1)
        self.assertEqual(FakeBrew.builds, 1)
        prefix = self.root / "installed prefix"
        subprocess.run([sys.executable, "install.py", "--prefix", str(prefix)], check=True, capture_output=True)
        result = subprocess.run([str(prefix / "bin" / "brew-pool"), "--help"], check=True, capture_output=True, text=True)
        self.assertIn("upgrade", result.stdout)

    def test_pinned_and_custom_options_are_not_silently_changed(self):
        mac = FakeBrew(self.clients[0])
        mac.records["demo"]["pinned"] = True
        with self.assertRaises(PoolError):
            mac.ensure("demo")
        self.assertEqual(FakeBrew.builds, 0)
        mac.records["demo"]["pinned"] = False
        mac.records["demo"]["installed"] = [{"version": "0.9", "used_options": ["--with-special"]}]
        with self.assertRaises(PoolError):
            mac.ensure("demo")
        self.assertEqual(FakeBrew.builds, 0)

    def test_older_official_bottle_selection_respects_cellar(self):
        mac = FakeBrew(self.clients[0])
        info = mac.info("demo")
        info["bottle"]["stable"]["files"] = {"sonoma": {"cellar": ":any", "sha256": "c" * 64}}
        self.assertEqual(mac.official_bottle(info)[0], "sonoma")
        info["bottle"]["stable"]["files"]["sonoma"]["cellar"] = "/different/Cellar"
        self.assertIsNone(mac.official_bottle(info))
        info["bottle"]["stable"]["files"]["sonoma"]["cellar"] = mac.cellar
        info["pour_bottle_only_if"] = {"reason": "special requirement"}
        self.assertIsNone(mac.official_bottle(info))

    def test_dependency_mark_is_preserved_during_upgrade(self):
        mac = FakeBrew(self.clients[0])
        mac.records["demo"]["installed"] = [{"version": "0.9", "used_options": [], "installed_on_request": False}]
        mac.records["demo"]["outdated"] = True
        original_run = mac.run
        def run(*args, **kwargs):
            result = original_run(*args, **kwargs)
            if args[0] == "install":
                mac.records["demo"]["outdated"] = False
            return result
        mac.run = run
        mac.ensure("demo")
        install = next(call for call in mac.calls if call[0] == "install")
        self.assertIn("--as-dependency", install)

    def test_reviewed_newer_pool_rebuild_can_be_consumed(self):
        a = FakeBrew(self.clients[0])
        a.ensure("demo")
        m = a.manifest(a.info("demo"))
        found = self.clients[0].lookup(m)
        found["version_order"][-1] += 1
        file = self.root / "reviewed-rebuild"
        file.write_bytes(b"reviewed new build for identical formula and ABI")
        found.update(sha256=digest(file), size=file.stat().st_size)
        self.publish(found, file)
        b = FakeBrew(self.clients[1])
        b.ensure("demo", allow_build=False)
        self.assertEqual(FakeBrew.builds, 1)


class VersionTests(unittest.TestCase):
    def test_numeric_semver_revision_and_rebuild(self):
        self.assertGreater(version_order("10.0"), version_order("9.99"))
        self.assertGreater(version_order("1.0"), version_order("1.0rc2"))
        self.assertGreater(version_order("1.0rc2"), version_order("1.0beta4"))
        self.assertGreater(version_order("1.0", 1), version_order("1.0", 0, 99))
        with self.assertRaises(PoolError):
            version_order("latest")


if __name__ == "__main__":
    unittest.main()
