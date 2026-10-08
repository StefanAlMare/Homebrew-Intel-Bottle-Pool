import io
import json
import tarfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from pool.brew import Brew
from pool.common import digest, atomic_json
from pool.imports import BottleImporter, cpu_level, supported_cpu_levels
from pool.jobs import Job, request_pause, step
from test_pool import Fixture, FakeBrew


class SafePauseTests(unittest.TestCase):
    def test_pause_finishes_current_formula_and_resume_uses_checkpoint(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            job = Job(state)
            job.start("upgrade", [step("formula", "first"), step("formula", "second")],
                      {"allow_build": True, "casks": False})
            started = threading.Event()
            finish = threading.Event()
            visits = []

            def execute(item, active_job):
                visits.append(item["name"])
                if item["name"] == "first":
                    started.set()
                    self.assertTrue(finish.wait(3))
                    active_job.data["publication"] = {"package": "first", "state": "published", "sha256": "a" * 64}
                    active_job.save()

            worker = threading.Thread(target=job.run, args=(execute,))
            worker.start()
            self.assertTrue(started.wait(2))
            request_pause(state)
            self.assertEqual(Job(state).report()["status"], "pause_requested")
            finish.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            paused = Job(state)
            report = paused.report()
            self.assertEqual(report["status"], "safely_paused")
            self.assertEqual(report["remaining_count"], 1)
            self.assertEqual(paused.data["steps"][0]["status"], "done")
            self.assertEqual(paused.data["steps"][1]["status"], "pending")
            self.assertEqual(report["checkpoint"]["publication"]["state"], "published")

            restarted = Job(state)
            restarted.run(execute)
            self.assertEqual(visits, ["first", "second"])
            self.assertEqual(Job(state).report()["status"], "completed")


class ImportBrew:
    validate_name = staticmethod(Brew.validate_name)
    manifest = Brew.manifest
    check_options = Brew.check_options

    def __init__(self, cache, name="demo", version="1.0", built=True):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.prefix = "/usr/local"
        self.cellar = "/usr/local/Cellar"
        self.tag = "tahoe"
        self.major = 26
        self.cpu_features = {"SSE4.2", "SSSE3", "POPCNT", "CX16", "AVX", "AVX2", "BMI1", "BMI2", "FMA", "MOVBE"}
        self.cpu_features |= {"SSE2", "SSE3", "SSE4_1", "AES", "PCLMULQDQ"}
        self.recipe = b'class Demo < Formula\n  version "1.0"\nend\n'
        self.record = {
            "name": name, "full_name": name, "tap": "homebrew/core",
            "versions": {"stable": version}, "revision": 0, "version_scheme": 0,
            "ruby_source_checksum": {"sha256": "b" * 64}, "outdated": False,
            "installed": [{"version": version, "built_as_bottle": built, "used_options": []}],
            "bottle": {"stable": {"files": {}, "rebuild": 0}},
        }

    def run(self, *args, **kwargs):
        if args == ("info", "--json=v2", "--installed"):
            return json.dumps({"formulae": [self.record]})
        raise AssertionError(args)

    def info(self, name):
        return self.record

    def pkg_version(self, info):
        return info["versions"]["stable"]

    def planned_installed_recipe_hash(self, info):
        import hashlib
        return hashlib.sha256(self.recipe).hexdigest()

    def context(self, info):
        return {"formula_sha256": info["ruby_source_checksum"]["sha256"], "dependencies": {},
                "dependency_identity": "installed-keg-brew-sha256-v1",
                "dependency_graph": "declared-platform-v1", "variant_identity": "formula-runtime-v1",
                "prefix": self.prefix, "cellar": self.cellar, "options": []}

    def host_cpu_features(self):
        return self.cpu_features


def make_bottle(path, brew, built=True, recipe=None, tag="tahoe", proof=True, arch="x86_64", payload=b"fixture"):
    receipt = json.dumps({"built_as_bottle": built, "poured_from_bottle": False,
                          "arch": arch, "used_options": [], "source": {"tap": "homebrew/core"},
                          "runtime_dependencies": []}).encode()
    recipe = brew.recipe if recipe is None else recipe
    root = brew.record["name"] + "/" + brew.record["versions"]["stable"]
    with tarfile.open(path, "w:gz") as archive:
        for name, data in ((root + "/INSTALL_RECEIPT.json", receipt),
                           (root + "/.brew/" + brew.record["name"] + ".rb", recipe),
                           (root + "/bin/payload", payload)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    if proof:
        import hashlib
        atomic_json(str(path) + ".pool-provenance.json", {
            "schema": 1, "reviewed": True, "producer": "isolated-test-producer",
            "sha256": digest(path), "formula": brew.record["full_name"],
            "version": brew.pkg_version(brew.record), "arch": arch,
            "tag": tag, "rebuild": 0, "prefix": brew.prefix, "cellar": brew.cellar,
            "recipe_sha256": hashlib.sha256(recipe).hexdigest(),
            "dependencies": brew.context(brew.record)["dependencies"],
            "required_cpu_features": sorted(brew.cpu_features), "compiler_flags": [],
        })
    return path


class ImportBottleTests(Fixture):
    def test_commit_confirmed_by_server_but_response_lost_recovers_without_duplicate(self):
        from pool.client import Unavailable
        brew = ImportBrew(self.root / "cache")
        make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew)
        importer = BottleImporter(self.clients[0], brew)
        importer.scan()
        upload = self.clients[0].upload

        def lost_response(*args):
            upload(*args)
            raise Unavailable("simulated connection loss after server commit")

        with patch.object(self.clients[0], "upload", side_effect=lost_response):
            self.assertEqual(importer.import_verified()[0]["status"], "spooled_offline")
        self.assertEqual(len(list(self.store.objects.glob("*/manifest.json"))), 1)
        self.assertEqual(self.clients[0].sync(), ["exists"])
        self.assertFalse(list(self.clients[0].spool.glob("entry-*")))
        self.assertEqual(len(list(self.store.objects.glob("*/manifest.json"))), 1)

    def test_local_bottle_without_producer_evidence_requires_review(self):
        brew = ImportBrew(self.root / "cache")
        bottle = make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew, proof=False)
        candidate = BottleImporter(self.clients[0], brew).analyze_archive(bottle)
        self.assertEqual(candidate["classification"], "requires_review")
        self.assertIn("producer provenance", candidate["reason"])

    def test_official_checksum_import_needs_no_local_cpu_assumption(self):
        brew = ImportBrew(self.root / "cache")
        bottle = make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew, proof=False)
        brew.record["bottle"]["stable"]["files"]["tahoe"] = {"sha256": digest(bottle), "cellar": ":any"}
        importer = BottleImporter(self.clients[0], brew)
        candidate = next(x for x in importer.scan()["candidates"] if x.get("path"))
        self.assertEqual(candidate["classification"], "bottle_valid_importable")
        self.assertEqual(candidate["cpu_requirement"], "homebrew-baseline")
        self.assertTrue(candidate["relocatable"])
        self.assertEqual(candidate["cellar"], ":any")
        self.assertEqual(importer.import_verified()[0]["status"], "published")

    def test_architecture_and_producer_dependency_mismatch_rejected(self):
        brew = ImportBrew(self.root / "cache")
        bottle = make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew, arch="arm64")
        importer = BottleImporter(self.clients[0], brew)
        self.assertEqual(importer.analyze_archive(bottle)["classification"], "incompatible")
        make_bottle(bottle, brew)
        proof_path = Path(str(bottle) + ".pool-provenance.json")
        proof = json.loads(proof_path.read_text())
        proof["dependencies"] = {"missing": {"version": "1", "source": "a" * 64}}
        atomic_json(proof_path, proof)
        self.assertEqual(importer.analyze_archive(bottle)["classification"], "requires_review")

    def test_same_rank_conflict_and_changed_provenance_never_publish(self):
        brew = ImportBrew(self.root / "cache")
        bottle = make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew)
        importer = BottleImporter(self.clients[0], brew)
        importer.scan()
        proof_path = Path(str(bottle) + ".pool-provenance.json")
        proof = json.loads(proof_path.read_text())
        proof["producer"] = "changed-after-review"
        atomic_json(proof_path, proof)
        self.assertEqual(importer.import_verified()[0]["status"], "rejected")
        importer.scan()
        self.assertEqual(importer.import_verified()[0]["status"], "published")
        make_bottle(bottle, brew, payload=b"different archive bytes")
        conflict = importer.analyze_archive(bottle)
        self.assertEqual(conflict["classification"], "requires_review")
        self.assertIn("Same version rank", conflict["reason"])

    def test_valid_bottle_import_and_duplicate_skip(self):
        brew = ImportBrew(self.root / "cache")
        bottle = make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew)
        importer = BottleImporter(self.clients[0], brew)
        report = importer.scan()
        candidate = next(x for x in report["candidates"] if x.get("path") and Path(x["path"]) == bottle.resolve())
        self.assertEqual(candidate["classification"], "bottle_valid_importable")
        self.assertEqual(candidate["cpu_requirement"], "x86_64-v3")
        self.assertIn(importer.import_verified()[0]["status"], ("published", "exists"))
        duplicate = importer.scan()
        self.assertEqual(next(x for x in duplicate["candidates"] if x.get("path") and Path(x["path"]) == bottle.resolve())["classification"],
                         "already_present")
        self.assertEqual(importer.import_verified(), [])

    def test_interrupted_publication_stays_spooled_and_recovers(self):
        brew = ImportBrew(self.root / "cache")
        make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew)
        importer = BottleImporter(self.clients[0], brew)
        importer.scan()
        online = self.clients[0].url
        self.clients[0].url = "http://127.0.0.1:1"
        self.assertEqual(importer.import_verified()[0]["status"], "spooled_offline")
        self.assertEqual(len(list(self.clients[0].spool.glob("entry-*/manifest.json"))), 1)
        self.clients[0].url = online
        self.assertEqual(self.clients[0].sync(), ["published"])

    def test_incompatible_provenance_is_not_imported(self):
        brew = ImportBrew(self.root / "cache")
        bottle = make_bottle(brew.cache / "demo--1.0.tahoe.bottle.tar.gz", brew,
                             recipe=b"class Tampered; end\n")
        importer = BottleImporter(self.clients[0], brew)
        candidate = importer.analyze_archive(bottle)
        self.assertEqual(candidate["classification"], "requires_review")
        self.assertIn("Embedded formula", candidate["reason"])
        importer.scan()
        self.assertEqual(importer.import_verified(), [])

    def test_node_source_install_is_never_called_a_bottle(self):
        brew = ImportBrew(self.root / "empty-cache", name="node", version="26.11.0", built=False)
        report = BottleImporter(self.clients[0], brew).scan()
        node = next(x for x in report["candidates"] if x["id"] == "installed:node:26.11.0")
        self.assertEqual(node["classification"], "local_source_no_bottle")
        self.assertIn("Installed from source", node["reason"])
        brew.record["installed"][0]["built_as_bottle"] = True
        report = BottleImporter(self.clients[0], brew).scan()
        self.assertEqual(report["candidates"][0]["classification"], "local_source_no_bottle")

    def test_cpu_levels_fail_closed_for_older_intel_mac(self):
        modern = {"SSE4.2", "SSSE3", "POPCNT", "CX16", "AVX", "AVX2", "BMI1", "BMI2", "FMA", "MOVBE"}
        old = {"SSE4.2", "SSSE3", "POPCNT", "CX16"}
        old |= {"SSE2", "SSE3", "SSE4_1"}
        self.assertEqual(cpu_level(modern), "x86_64-v3")
        self.assertEqual(cpu_level(old), "x86_64-v2")
        self.assertNotIn("x86_64-v3", supported_cpu_levels(old))

        class LookupClient:
            def __init__(self, state):
                self.state = state
                self.lookups = []
            def local_match(self, manifest):
                return None
            def lookup(self, manifest):
                self.lookups.append(manifest["metadata"]["context"].get("cpu_requirement", "homebrew-baseline"))
                return manifest if self.lookups[-1] == "x86_64-v3" else None

        brew = ImportBrew(self.root / "cpu-cache")
        brew.cpu_features = old
        brew.client = LookupClient(self.root / "consumer-state")
        brew.client.state.mkdir()
        baseline = brew.manifest(brew.record)
        self.assertFalse(Brew.consume_local(brew, baseline))
        self.assertNotIn("x86_64-v3", brew.client.lookups)


class BrewCheckpointTests(Fixture):
    def test_changed_completed_context_is_requeued_instead_of_skipped(self):
        mac = FakeBrew(self.clients[0])
        mac.records["demo"]["installed"] = [{"version": "1.0", "used_options": []}]
        job = Job(mac.client.state)
        job.start("upgrade", [step("formula", "demo"), step("missing")], {"allow_build": True, "casks": False})
        mac.active_job = job
        mac.ensure("demo")
        job.data["steps"][0]["status"] = "done"
        job.safely_pause(completed_package="demo")
        mac.records["demo"]["ruby_source_checksum"]["sha256"] = "b" * 64
        mac._revalidate_checkpoints(Job(mac.client.state))
        self.assertEqual(Job(mac.client.state).data["steps"][0]["status"], "pending")
        self.assertIn("demo", mac.force_targets)

    def test_nested_dependency_safe_pause_does_not_force_current_parent_on_resume(self):
        import copy
        mac = FakeBrew(self.clients[0])
        mac.records["dep"] = dict(copy.deepcopy(mac.records["demo"]), name="dep", full_name="dep")
        import hashlib
        mac.records["dep"]["ruby_source_checksum"]["sha256"] = hashlib.sha256(b"fixture recipe dep").hexdigest()
        mac.records["demo"]["installed"] = [{"version": "1.0", "used_options": []}]
        job = Job(mac.client.state)
        job.start("upgrade", [step("formula", "demo"), step("missing")], {"allow_build": True, "casks": False})
        original = mac.run

        def run(*args, **kwargs):
            if args[0] == "deps" and args[-1] == "demo":
                return "dep"
            if args[0] == "install" and "--build-bottle" in args:
                request_pause(mac.client.state)
            return original(*args, **kwargs)

        mac.run = run
        mac._run_job(job, "start")
        paused = Job(mac.client.state)
        self.assertEqual(paused.report()["status"], "safely_paused")
        self.assertEqual(paused.data["steps"][0]["status"], "pending")
        self.assertEqual(paused.data["checkpoint"]["completed_package"], "dep")
        self.assertEqual(paused.data["active_package"], "")
        mac._run_job(Job(mac.client.state), "resume")
        builds = [x[-1] for x in mac.calls if x[0] == "install" and "--build-bottle" in x]
        self.assertEqual(builds, ["dep"])
        self.assertEqual(Job(mac.client.state).report()["status"], "completed")

    def test_real_brew_workflow_pauses_after_test_publish_and_skips_confirmed_on_resume(self):
        mac = FakeBrew(self.clients[0])
        job = Job(mac.client.state)
        job.start("upgrade", [step("formula", "demo"), step("missing")],
                  {"allow_build": True, "casks": False})
        original = mac.run

        def run(*args, **kwargs):
            if args[0] == "install" and "--build-bottle" in args:
                request_pause(mac.client.state)
            return original(*args, **kwargs)

        mac.run = run
        mac._run_job(job, "start")
        paused = Job(mac.client.state)
        self.assertEqual(paused.report()["status"], "safely_paused")
        self.assertEqual(paused.data["steps"][0]["status"], "done")
        self.assertEqual(paused.report()["remaining_count"], 1)
        self.assertIn(("test", "demo"), mac.calls)
        self.assertEqual(paused.data["formula_checkpoints"]["demo"]["publication"]["state"], "published")
        before = sum(x[0] == "install" for x in mac.calls)
        mac._run_job(Job(mac.client.state), "resume")
        self.assertEqual(sum(x[0] == "install" for x in mac.calls), before)
        self.assertEqual(Job(mac.client.state).report()["status"], "completed")

    def test_missing_checkpoint_lookup_rechecks_pool_without_compilation(self):
        mac = FakeBrew(self.clients[0])
        job = Job(mac.client.state)
        job.start("upgrade", [step("formula", "demo"), step("missing")],
                  {"allow_build": True, "casks": False})
        original = mac.run

        def run(*args, **kwargs):
            if args[0] == "install" and "--build-bottle" in args:
                request_pause(mac.client.state)
            return original(*args, **kwargs)

        mac.run = run
        mac._run_job(job, "start")
        mac.records["demo"]["installed"][0]["built_as_bottle"] = True
        before = sum(x[0] == "install" for x in mac.calls)
        lookup = mac.client.lookup
        visits = []

        def missing_once(manifest):
            visits.append(manifest)
            return None if len(visits) == 1 else lookup(manifest)

        with patch.object(mac.client, "lookup", side_effect=missing_once):
            mac._run_job(Job(mac.client.state), "resume")
        self.assertTrue(visits)
        self.assertEqual(sum(x[0] == "install" and "--build-bottle" in x for x in mac.calls), 1)
        self.assertEqual(Job(mac.client.state).report()["status"], "completed")


if __name__ == "__main__":
    unittest.main()
