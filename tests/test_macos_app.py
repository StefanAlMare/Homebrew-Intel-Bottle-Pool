import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentStatusTests(unittest.TestCase):
    def test_machine_status_reports_offline_spool(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            token = root / "token"
            token.write_text("test-token")
            state = root / "state"
            queued = state / "spool" / "entry-test"
            queued.mkdir(parents=True)
            (queued / "manifest.json").write_text("{}")
            config = root / "config.json"
            config.write_text(json.dumps({
                "url": "http://127.0.0.1:9",
                "token_file": str(token),
                "state_dir": str(state),
                "timeout": 0.05,
            }))
            result = subprocess.run(
                [sys.executable, str(ROOT / "entry.py"), "--config", str(config), "status", "--json"],
                text=True, capture_output=True, timeout=5, check=True,
            )
            status = json.loads(result.stdout)
            self.assertFalse(status["connected"])
            self.assertEqual(status["spool_entries"], 1)
            self.assertEqual(status["state"], "spooling")


class MacApplicationTests(unittest.TestCase):
    def test_bundle_metadata_and_embedded_client(self):
        app = ROOT / "dist" / "Homebrew Pool.app"
        if not app.exists():
            self.skipTest("Run build-macos.sh to validate the compiled bundle")
        with (app / "Contents" / "Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        self.assertTrue(info["LSUIElement"])
        self.assertEqual(info["CFBundleShortVersionString"], "0.3.5")
        self.assertEqual(info["CFBundleVersion"], "35")
        self.assertTrue((app / "Contents" / "Resources" / "client" / "pool" / "client.py").is_file())
        self.assertTrue((app / "Contents" / "Resources" / "HomebrewPool.icns").is_file())
        self.assertTrue((app / "Contents" / "MacOS" / "HomebrewPoolMenu").is_file())

    def test_bundle_sources_match_build_receipt(self):
        app = ROOT / "dist/Homebrew Pool.app"
        if not app.exists():
            self.skipTest("Build the app first")
        from release_checks import check_bundle
        check_bundle(app)

    def test_tampered_embedded_source_is_rejected(self):
        app = ROOT / "dist/Homebrew Pool.app"
        if not app.exists():
            self.skipTest("Build the app first")
        import shutil
        from release_checks import check_bundle
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "Homebrew Pool.app"
            shutil.copytree(app, copy)
            embedded = copy / "Contents/Resources/client/pool/brew.py"
            embedded.write_text(embedded.read_text() + "\n# modified\n")
            (copy / "Contents/CodeResources").write_bytes(b"ticket fixture")
            with patch("release_checks.check_stapled_ticket", side_effect=AssertionError("Check source before ticket")):
                with self.assertRaisesRegex(SystemExit, "Embedded source differs"):
                    check_bundle(copy)

    def test_validated_apple_ticket_is_accepted_without_relaxing_signature_checks(self):
        import shutil
        from release_checks import check_bundle
        app = ROOT / "dist/Homebrew Pool.app"
        if not app.exists():
            self.skipTest("Build the app first")
        original = subprocess.run
        calls = []
        def run(argv, **kwargs):
            if argv[:3] == ["xcrun", "stapler", "validate"]:
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "The validate action worked!", "")
            return original(argv, **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "Homebrew Pool.app"
            shutil.copytree(app, copy)
            (copy / "Contents/CodeResources").write_bytes(b"fixture for Apple-validated ticket")
            with patch("release_checks.subprocess.run", side_effect=run):
                check_bundle(copy)
            self.assertEqual(len(calls), 1)

    def test_forged_apple_ticket_is_rejected(self):
        import shutil
        from release_checks import check_bundle
        app = ROOT / "dist/Homebrew Pool.app"
        if not app.exists():
            self.skipTest("Build the app first")
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "Homebrew Pool.app"
            shutil.copytree(app, copy)
            (copy / "Contents/CodeResources").write_bytes(b"forged ticket")
            with self.assertRaisesRegex(SystemExit, "Invalid Apple notarization ticket"):
                check_bundle(copy)

    def test_linked_apple_ticket_is_rejected(self):
        import shutil
        from release_checks import check_bundle
        app = ROOT / "dist/Homebrew Pool.app"
        if not app.exists():
            self.skipTest("Build the app first")
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "Homebrew Pool.app"
            shutil.copytree(app, copy)
            (copy / "Contents/CodeResources").unlink(missing_ok=True)
            (copy / "Contents/CodeResources").symlink_to(copy / "Contents/_CodeSignature/CodeResources")
            with self.assertRaisesRegex(SystemExit, "Invalid or linked Apple notarization ticket"):
                check_bundle(copy)

    def test_upgrade_is_only_bound_to_explicit_menu_action(self):
        source = (ROOT / "macos" / "HomebrewPoolMenu.swift").read_text()
        self.assertIn('@objc private func upgradeViaPool()', source)
        self.assertIn('runInteractive(command: ["upgrade"]', source)
        startup = source[source.index("func applicationDidFinishLaunching"):source.index("private func buildMenu")]
        self.assertNotIn('["upgrade"]', startup)

    def test_public_files_use_only_public_identity(self):
        for relative in ("macos/HomebrewPoolMenu.swift", "macos/Info.plist", "macos/LaunchAgent.plist.in"):
            text = (ROOT / relative).read_text()
            self.assertNotIn(str(Path.home()), text)
        self.assertIn("StefanAlMare", (ROOT / "macos" / "Info.plist").read_text())

    def test_embedded_client_preserves_signature_when_launched(self):
        app = ROOT / "dist" / "Homebrew Pool.app"
        if not app.exists():
            self.skipTest("Build the app first")
        entry = app / "Contents/Resources/client/entry.py"
        subprocess.run([sys.executable, str(entry), "--help"], check=True, capture_output=True)
        self.assertFalse(list((app / "Contents").rglob("*.pyc")))
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True, capture_output=True)
        arch = subprocess.check_output(["lipo", "-archs", str(app / "Contents/MacOS/HomebrewPoolMenu")], text=True).strip()
        self.assertEqual(arch, "x86_64")

    def test_installer_keeps_config_and_recoverable_previous_app(self):
        if not (ROOT / "dist/Homebrew Pool.app").exists():
            self.skipTest("Build the app first")
        with tempfile.TemporaryDirectory(prefix="pool-installer-") as temporary:
            root = Path(temporary)
            config = root / "config.json"
            original = b'{"private_adapter":"preserved"}'
            config.write_bytes(original)
            args = ["sh", str(ROOT / "install-app.sh"), "--applications-dir", str(root / "Applications"),
                    "--prefix", str(root / "CLI prefix"), "--config", str(config),
                    "--no-login-item", "--no-launch"]
            subprocess.run(args, check=True, capture_output=True)
            subprocess.run(args, check=True, capture_output=True)
            self.assertEqual(config.read_bytes(), original)
            backups = list((root / "Applications").glob("Homebrew-Pool-backup-*/Homebrew Pool.app"))
            self.assertEqual(len(backups), 1)
            subprocess.run(["codesign", "--verify", "--deep", "--strict",
                            str(root / "Applications/Homebrew Pool.app")], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
