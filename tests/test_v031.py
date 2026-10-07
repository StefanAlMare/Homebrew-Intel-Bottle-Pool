import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from pool.actions import ACTION_MARKER, ActionRequired, classify_command_failure
from pool.brew import Brew
from test_pool import FakeBrew, Fixture


ROOT = Path(__file__).resolve().parents[1]


class BottleRootURLTests(Fixture):
    def _build(self, tap, root_url=None):
        mac = FakeBrew(self.clients[0])
        record = mac.records["demo"]
        record["tap"] = tap
        record["full_name"] = (tap + "/demo") if tap != "homebrew/core" else "demo"
        mac.records[record["full_name"]] = record
        if root_url:
            record["bottle"]["stable"]["root_url"] = root_url
        info = mac.info(record["full_name"])
        mac.build(info, mac.manifest(info), None)
        return next(call for call in mac.calls if call[0] == "bottle")

    def test_external_tap_root_url_is_passed_to_brew_bottle(self):
        command = self._build("gromgit/fuse", "https://github.com/gromgit/homebrew-fuse/releases/download/test")
        self.assertEqual(command[:5], ("bottle", "--json", "--keep-old", "--root-url",
                                      "https://github.com/gromgit/homebrew-fuse/releases/download/test"))
        self.assertEqual(command[-1], "gromgit/fuse/demo")

    def test_homebrew_core_keeps_canonical_bottle_behavior(self):
        command = self._build("homebrew/core", "https://ghcr.io/v2/homebrew/core")
        self.assertNotIn("--root-url", command)


class GUIEnvironmentTests(unittest.TestCase):
    def test_path_preserves_existing_and_adds_intel_homebrew_locations_once(self):
        path = Brew.normalized_path("/custom/bin:/usr/local/bin:/bin")
        self.assertEqual(path.split(os.pathsep),
                         ["/custom/bin", "/usr/local/bin", "/bin", "/usr/local/sbin"])

    def test_brew_environment_is_noninteractive(self):
        mac = Brew.__new__(Brew)
        existing = "/custom/bin:/bin"
        normalized = Brew.normalized_path(existing)
        self.assertTrue(normalized.startswith(existing))
        self.assertIn("/usr/local/bin", normalized)
        self.assertIn("/usr/local/sbin", normalized)
        source = (ROOT / "macos/HomebrewPoolMenu.swift").read_text()
        self.assertIn('environment["HOMEBREW_NO_ASK"] = "1"', source)
        self.assertIn('"/usr/local/bin", "/usr/local/sbin"', source)


class ActionRequiredTests(Fixture):
    def test_classifier_and_marker_are_structured(self):
        action = classify_command_failure("sudo: a password is required", "example")
        self.assertIsInstance(action, ActionRequired)
        self.assertEqual(action.category, "authentication")
        marker = action.marker()
        self.assertTrue(marker.startswith(ACTION_MARKER))
        payload = json.loads(marker[len(ACTION_MARKER):])
        self.assertEqual(payload["subject"], "example")
        self.assertEqual([x["id"] for x in payload["choices"]], ["continue", "skip", "cancel"])

    def test_ambiguous_auto_install_requires_action(self):
        mac = FakeBrew(self.clients[0])
        both = json.dumps({"formulae": [{}], "casks": [{}]})
        original = mac.run
        mac.run = lambda *args, **kwargs: both if args[0] == "info" else original(*args, **kwargs)
        with self.assertRaises(ActionRequired) as raised:
            mac.resolve("demo")
        self.assertEqual(raised.exception.category, "package_type")

    def test_skip_resumes_upgrade_without_touching_item(self):
        mac = FakeBrew(self.clients[0])
        mac.upgrade(casks=False, skip=["demo"])
        self.assertEqual(FakeBrew.builds, 0)

    def test_cli_returns_action_required_exit_code_and_machine_marker(self):
        code = ("from pool.actions import ActionRequired; "
                "e=ActionRequired('review', subject='demo'); "
                "print(e.marker()); raise SystemExit(3)")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn(ACTION_MARKER, result.stdout)

    def test_macos_ui_has_persistent_action_state_and_single_notification_key(self):
        source = (ROOT / "macos/HomebrewPoolMenu.swift").read_text()
        self.assertIn('title: "Review Action…"', source)
        self.assertIn('title: "🔴 Action Required"', source)
        self.assertIn('"notified-action-\\(action.id)"', source)
        self.assertIn("UNUserNotificationCenter.current().add", source)
        self.assertIn("notification.sound = .default", source)
        self.assertIn("with administrator privileges", source)
        self.assertIn("SecurityAgent", source)


if __name__ == "__main__":
    unittest.main()
