import copy
import unittest
from unittest.mock import patch
from pool.actions import classify_command_failure
from pool.brew import Brew
from pool.capture import Q9300_FEATURES
from pool.compatibility import solutions, format_solutions
from pool.imports import normalize_cpu_features, homebrew_baseline_features
from test_pool import Fixture, FakeBrew


class CompatibilitySolutionsTests(Fixture):
    def test_cpu_failure_offers_review_not_blind_retry(self):
        action = classify_command_failure("Requires SSE4.2 and AVX: unsupported CPU instructions", "python")
        self.assertEqual(action.category, "cpu_compatibility")
        self.assertEqual(action.choices[0]["id"], "compatibility")
        self.assertNotIn("continue", [x["id"] for x in action.choices])

    def test_python_version_candidates_are_not_cpu_approved_or_auto_selected(self):
        brew = FakeBrew(self.clients[0])
        record = brew.records["demo"]
        record["versioned_formulae"] = ["python@legacy", "python@disabled"]
        for name in record["versioned_formulae"]:
            brew.records[name] = dict(copy.deepcopy(record), name=name, full_name=name,
                                      deprecated=name.endswith("legacy"), disabled=name.endswith("disabled"),
                                      versioned_formulae=[])
        with patch.object(brew, "host_cpu_features", return_value=Q9300_FEATURES):
            report = solutions(brew, "demo")
        self.assertFalse(report["mutations_performed"])
        self.assertIn("SSE4_2", report["missing_baseline_features"])
        self.assertTrue(report["core2_build_target_available"])
        self.assertTrue(all(not x["cpu_verified"] for x in report["versioned_candidates"]))
        self.assertIn("not recommended", report["versioned_candidates"][1]["status"])
        self.assertFalse(any(x[0] in ("install", "reinstall", "update", "bottle") for x in brew.calls))
        self.assertIn("not a Git branch", format_solutions(report))

    def test_q9300_rejects_official_baseline_and_builds_in_separate_cpu_variant(self):
        brew = FakeBrew(self.clients[0])
        brew.records["demo"]["bottle"]["stable"]["files"]["tahoe"] = {"cellar": ":any", "sha256": "a" * 64}
        modern = brew.manifest(brew.info("demo"))
        with patch.object(brew, "host_cpu_features", return_value=Q9300_FEATURES):
            self.assertIsNone(brew.official_bottle(brew.info("demo")))
            legacy = brew.manifest(brew.info("demo"))
        self.assertNotEqual(legacy["variant"], modern["variant"])
        self.assertEqual(legacy["metadata"]["context"]["cpu_requirement"], "x86_64-v1")
        self.assertNotIn("AVX", legacy["metadata"]["required_cpu_features"])
        self.assertFalse(homebrew_baseline_features("tahoe") <= Q9300_FEATURES)

    def test_mac_avx_aliases_are_normalized(self):
        self.assertEqual(normalize_cpu_features(["AVX1.0", "SSE4.2", "AESNI"]), {"AVX", "SSE4_2", "AES"})

    def test_q9300_source_build_uses_real_core2_option_and_reuses_cpu_variant(self):
        brew = FakeBrew(self.clients[0])
        with patch.object(brew, "host_cpu_features", return_value=Q9300_FEATURES):
            brew.ensure("demo")
        builds = [x for x in brew.calls if x[0] == "install" and "--build-bottle" in x]
        self.assertEqual(len(builds), 1)
        self.assertIn("--bottle-arch=core2", builds[0])
        consumer = FakeBrew(self.clients[0])
        with patch.object(consumer, "host_cpu_features", return_value=Q9300_FEATURES):
            consumer.ensure("demo", allow_build=False)
        self.assertFalse(any("--build-bottle" in x for x in consumer.calls))

    def test_q9300_consumer_refuses_new_cpu_bytes_even_with_same_cpu_variant(self):
        brew = FakeBrew(self.clients[0])
        with patch.object(brew, "host_cpu_features", return_value=Q9300_FEATURES):
            manifest = brew.manifest(brew.info("demo"))
            manifest["metadata"]["required_cpu_features"] = ["SSE4.2", "AVX"]
            with patch.object(brew.client, "lookup", return_value=manifest), patch.object(
                    brew.client, "fetch") as fetch, patch.object(brew, "pour") as pour:
                self.assertFalse(brew.consume_local(manifest))
                fetch.assert_not_called()
                pour.assert_not_called()
