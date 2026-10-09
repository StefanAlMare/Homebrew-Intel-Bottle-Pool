import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pool.legacy_policy import (BASE, CHANNEL, Denied, LegacyGate, artifact_key,
                           manifest_digest, reject_legacy_on_global, sha)


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


CONTEXT = {"arch": "x86_64", "macos_version": "26.0", "macos_build": "fixture-25A",
           "prefix": "/usr/local", "cellar": "/usr/local/Cellar"}
PLAN_FIELDS = ("name", "version", "revision", "rebuild", "context", "dependencies",
               "recipe_sha256", "embedded_recipe_sha256")


def fixture():
    """Synthetic identities and bytes; never enroll the real P5Q-Alex."""
    machines = {}
    hosts = {}
    for name, target, model in (("fixture-penryn", "penryn", 23),
                                ("fixture-conroe", "conroe-merom", 15)):
        isa = sorted(BASE | ({"SSE4_1"} if target == "penryn" else set()))
        cpu = {"vendor": "GenuineIntel", "family": 6, "model": model}
        machines[name] = {"enabled": True, "roles": ["consume", "publish", "test"],
                          "key_id": h(name), "cpu_target": target, "cpu": cpu,
                          "native_features": isa, "context": copy.deepcopy(CONTEXT),
                          "platform_kind": "hackintosh", "native_evidence_sha256": h("native-" + name)}
        hosts[name] = {"machine_id": name, "cpu_target": target, "cpu": cpu,
                       "observed_features": isa, "native_arch": "x86_64",
                       "process_arch": "x86_64", "translated": False,
                       "context": copy.deepcopy(CONTEXT)}
    payload = b"SYNTHETIC TEST BYTES; NOT A HOMEBREW BOTTLE\n"
    dependencies = {scope: {} for scope in ("runtime", "build", "test")}
    m = {"schema": 2, "channel": CHANNEL, "pool_id": "fixture-private-pool",
         "policy_revision": 1, "kind": "brew-local-bottle", "name": "homebrew/core/fixture",
         "version": "1.2.3", "revision": 0, "rebuild": 0,
         "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
         "context": copy.deepcopy(CONTEXT), "cpu_target": "penryn",
         "required_cpu_features": sorted(BASE | {"SSE4_1"}),
         "dependencies": dependencies, "recipe_sha256": h("recipe"),
         "embedded_recipe_sha256": h("embedded-recipe"),
         "provenance": {"producer_machine_id": "fixture-penryn",
                        "producer_key_id": h("fixture-penryn"), "producer_target": "penryn",
                        "recipe_sha256": h("recipe"), "embedded_recipe_sha256": h("embedded-recipe"),
                        "source_sha256": h("source"), "patches_sha256": [h("patch")],
                        "toolchain_sha256": h("toolchain"), "compiler": "fixture clang 1.0",
                        "sdk_sha256": h("sdk"), "build_log_sha256": h("log"),
                        "receipt_sha256": h("receipt"), "keg_tree_sha256": h("tree"),
                        "dependency_digest": sha(dependencies),
                        "build_argv": ["install", "--build-bottle", "--bottle-arch=core2", "fixture"],
                        "flags": {"cflags": ["-march=penryn", "-mno-popcnt"],
                                  "cxxflags": [], "ldflags": []}},
         "validation": {"isolated_pour": True, "formula_test": True, "linkage_test": True,
                        "isa_review": True, "machine_id": "fixture-penryn",
                        "report_sha256": h("test-report")}}
    p = {"schema": 2, "channel": CHANNEL, "pool_id": "fixture-private-pool", "revision": 1,
         "enabled": True, "auto_import_verified_bottles": False, "machines": machines,
         "reviewer_keys": [h("fixture-reviewer")], "reviews": {}}
    approve(p, m)
    return p, m, hosts, payload


def approve(p, m):
    p["reviews"][manifest_digest(m)] = {"status": "approved", "policy_revision": 1,
                                      "reviewer_key_id": h("fixture-reviewer")}


def plan(m):
    return {k: copy.deepcopy(m[k]) for k in PLAN_FIELDS}


class GateTests(unittest.TestCase):
    def setUp(self):
        self.p, self.m, self.hosts, data = fixture()
        self.host = self.hosts["fixture-penryn"]
        self.session = {"machine_id": "fixture-penryn", "key_id": h("fixture-penryn")}
        self.expected = plan(self.m)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = Path(self.temp.name) / "payload"
        self.payload.write_bytes(data)

    def run_gate(self, op="select", m=None, host=None, session=None, expected=None):
        return LegacyGate(self.p).authorize(self.m if m is None else m,
                    self.host if host is None else host,
                    self.session if session is None else session, op,
                    self.expected if expected is None else expected, self.payload)

    def test_all_seven_boundaries_accept_complete_pinned_fixture(self):
        for op in ("lookup", "fetch", "select", "enqueue", "upload", "server-read", "server-commit"):
            with self.subTest(op=op):
                self.assertEqual(self.run_gate(op), artifact_key(self.m))

    def test_any_fully_qualified_formula_including_custom_tap(self):
        for name in ("homebrew/core/xz", "homebrew/core/python@3.14", "private/formulae/other-tool"):
            with self.subTest(name=name):
                m = copy.deepcopy(self.m); m["name"] = name
                approve(self.p, m)
                self.assertTrue(self.run_gate(m=m, expected=plan(m)))

    def test_disabled_default_and_empty_allowlist_deny_every_operation(self):
        for change in ({"enabled": False}, {"machines": {}}, {"auto_import_verified_bottles": True}):
            p = copy.deepcopy(self.p); p.update(change)
            for op in ("lookup", "fetch", "select", "enqueue", "upload", "server-read", "server-commit"):
                with self.subTest(change=change, op=op), self.assertRaises(Denied):
                    LegacyGate(p).authorize(self.m, self.host, self.session, op, self.expected, self.payload)

    def test_no_default_when_auto_import_flag_missing(self):
        del self.p["auto_import_verified_bottles"]
        with self.assertRaises(Denied): self.run_gate()

    def test_unknown_revoked_wrong_key_and_role_denied(self):
        with self.assertRaises(Denied):
            self.run_gate(session={"machine_id": "P5Q-Alex", "key_id": h("fixture-penryn")})
        with self.assertRaises(Denied):
            self.run_gate(session={"machine_id": "fixture-penryn", "key_id": h("other-key")})
        self.p["machines"]["fixture-penryn"]["roles"] = ["consume", "test"]
        with self.assertRaises(Denied): self.run_gate("upload")
        self.p["machines"]["fixture-penryn"]["enabled"] = False
        with self.assertRaises(Denied): self.run_gate()

    def test_penryn_artifact_rejected_on_conroe_even_if_sysctl_claims_sse41(self):
        host = copy.deepcopy(self.hosts["fixture-conroe"])
        host["observed_features"].extend(["SSE4.1", "POPCNT", "SSE4.2", "AVX2"])
        with self.assertRaises(Denied):
            self.run_gate(host=host, session={"machine_id": "fixture-conroe", "key_id": h("fixture-conroe")})

    def test_conroe_artifact_can_be_consumed_on_penryn_after_conroe_validation(self):
        m = copy.deepcopy(self.m); m["cpu_target"] = "conroe-merom"
        m["required_cpu_features"] = sorted(BASE)
        m["validation"]["machine_id"] = "fixture-conroe"
        m["provenance"]["flags"]["cflags"] = ["-march=core2", "-mno-popcnt"]
        approve(self.p, m)
        self.assertTrue(self.run_gate(m=m))

    def test_penryn_requires_sse41_and_both_profiles_forbid_newer_isa(self):
        for isa in (sorted(BASE), sorted(BASE | {"SSE4_1", "POPCNT"}),
                    sorted(BASE | {"SSE4_1", "SSE4_2"}), sorted(BASE | {"SSE4_1", "AVX"}),
                    sorted(BASE | {"SSE4_1", "UNKNOWN_ISA"})):
            m = copy.deepcopy(self.m); m["required_cpu_features"] = isa; approve(self.p, m)
            with self.subTest(isa=isa), self.assertRaises(Denied): self.run_gate(m=m)

    def test_architecture_translation_cpu_or_context_change_denied(self):
        variants = [{"native_arch": "arm64"}, {"process_arch": "arm64"}, {"translated": True},
                    {"cpu": {"vendor": "GenuineIntel", "family": 6, "model": 60}},
                    {"observed_features": []}]
        for key in ("arch", "macos_version", "macos_build", "prefix", "cellar"):
            context = copy.deepcopy(CONTEXT); context[key] = "different"
            variants.append({"context": context})
        for change in variants:
            host = copy.deepcopy(self.host); host.update(change)
            with self.subTest(change=change), self.assertRaises(Denied): self.run_gate(host=host)

    def test_schema_global_other_pool_stale_and_relabelled_denied(self):
        for change in ({"schema": 1}, {"channel": "global"}, {"pool_id": "global-pool"},
                       {"policy_revision": 0}, {"kind": "brew-upstream-bottle"}):
            m = copy.deepcopy(self.m); m.update(change); approve(self.p, m)
            with self.subTest(change=change), self.assertRaises(Denied): self.run_gate(m=m)
        with self.assertRaises(Denied): reject_legacy_on_global(self.m)
        m = copy.deepcopy(self.m); m["channel"] = "global"
        with self.assertRaises(Denied): reject_legacy_on_global(m)

    def test_channel_and_isa_cannot_collide_in_key(self):
        m = copy.deepcopy(self.m); m["required_cpu_features"].append("POPCNT")
        self.assertNotEqual(artifact_key(m), artifact_key(self.m))
        m["channel"] = "global"
        with self.assertRaises(Denied): artifact_key(m)

    def test_review_true_is_not_approval_and_any_metadata_change_invalidates_approval(self):
        self.p["reviews"] = {}
        self.m["reviewed"] = True
        with self.assertRaises(Denied): self.run_gate()
        approve(self.p, self.m)
        self.m["provenance"]["compiler"] = "changed compiler"
        with self.assertRaises(Denied): self.run_gate()

    def test_malformed_missing_or_wrong_type_evidence_fails_closed(self):
        for field in list(self.m):
            m = copy.deepcopy(self.m); del m[field]
            with self.subTest(missing=field), self.assertRaises(Denied): self.run_gate(m=m)
        for field in ("context", "dependencies", "provenance", "validation", "required_cpu_features"):
            for value in (None, [], "", 1, True):
                m = copy.deepcopy(self.m); m[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(Denied): self.run_gate(m=m)

    def test_recipe_and_dependency_change_cannot_replace_pinned_plan(self):
        for field in ("recipe_sha256", "embedded_recipe_sha256", "version", "rebuild"):
            m = copy.deepcopy(self.m); m[field] = h("new") if "sha256" in field else 9
            approve(self.p, m)
            with self.subTest(field=field), self.assertRaises(Denied): self.run_gate(m=m)
        self.expected["dependencies"]["runtime"]["homebrew/core/xz"] = {"version": "fixture"}
        with self.assertRaises(Denied): self.run_gate()

    def test_dependency_versions_recipes_keg_abi_and_isa_bound(self):
        dep = {"version": "5.8.0", "channel": CHANNEL, "recipe_sha256": h("patched-xz"),
               "keg_tree_sha256": h("xz-tree"), "abi_sha256": h("xz-abi"),
               "artifact_key": h("xz-key"), "review_sha256": h("xz-review"),
               "required_cpu_features": sorted(BASE)}
        m = copy.deepcopy(self.m); m["dependencies"]["runtime"]["homebrew/core/xz"] = dep
        m["provenance"]["dependency_digest"] = sha(m["dependencies"]); approve(self.p, m)
        expected = plan(m)
        self.assertTrue(self.run_gate(m=m, expected=expected))
        for field in ("version", "recipe_sha256", "keg_tree_sha256", "abi_sha256", "artifact_key"):
            changed = copy.deepcopy(m); changed["dependencies"]["runtime"]["homebrew/core/xz"][field] = h("changed")
            changed["provenance"]["dependency_digest"] = sha(changed["dependencies"]); approve(self.p, changed)
            with self.subTest(field=field), self.assertRaises(Denied): self.run_gate(m=changed, expected=expected)
        dep["required_cpu_features"] = sorted(BASE | {"AVX2"})
        m["provenance"]["dependency_digest"] = sha(m["dependencies"]); approve(self.p, m)
        with self.assertRaises(Denied): self.run_gate(m=m, expected=plan(m))

    def test_incomplete_validation_untrusted_producer_and_custom_flags_denied(self):
        for flag in ("-march=native", "-mpopcnt", "-msse4.2", "-mavx2"):
            m = copy.deepcopy(self.m); m["provenance"]["flags"]["cflags"] = [flag]; approve(self.p, m)
            with self.subTest(flag=flag), self.assertRaises(Denied): self.run_gate(m=m)
        for key in ("isolated_pour", "formula_test", "linkage_test", "isa_review"):
            m = copy.deepcopy(self.m); m["validation"][key] = False; approve(self.p, m)
            with self.subTest(key=key), self.assertRaises(Denied): self.run_gate(m=m)
        m = copy.deepcopy(self.m); m["provenance"]["producer_machine_id"] = "unknown"; approve(self.p, m)
        with self.assertRaises(Denied): self.run_gate(m=m)

    def test_revoking_producer_or_tester_blocks_previously_approved_artifact(self):
        m = copy.deepcopy(self.m); m["cpu_target"] = "conroe-merom"
        m["required_cpu_features"] = sorted(BASE); m["validation"]["machine_id"] = "fixture-conroe"
        approve(self.p, m)
        self.p["machines"]["fixture-conroe"]["enabled"] = False
        with self.assertRaises(Denied): self.run_gate(m=m)

    def test_all_payload_boundaries_check_checksum_and_size(self):
        self.payload.write_bytes(b"x" * self.m["size"])
        for op in ("select", "enqueue", "upload", "server-commit"):
            with self.subTest(op=op), self.assertRaises(Denied): self.run_gate(op)
        self.payload.write_bytes(b"short")
        with self.assertRaises(Denied): self.run_gate()

    def test_payload_symlinks_and_missing_files_denied(self):
        link = self.payload.parent / "link"; link.symlink_to(self.payload)
        self.payload = link
        with self.assertRaises(Denied): self.run_gate()
        self.payload = link.parent / "missing"
        with self.assertRaises(Denied): self.run_gate()

    def test_policy_snapshot_cannot_be_mutated_by_caller(self):
        gate = LegacyGate(self.p)
        self.p["machines"] = {}
        self.assertTrue(gate.authorize(self.m, self.host, self.session, "select", self.expected, self.payload))

    def test_no_implicit_plan_unknown_operation_or_legacy_schema(self):
        for op in ("install", "fallback-global", "", None):
            with self.subTest(op=op), self.assertRaises(Denied): self.run_gate(op)
        with self.assertRaises(Denied): self.run_gate(expected={})


if __name__ == "__main__":
    unittest.main()
