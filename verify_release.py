"""Verify signed/stapled deliverables and their packaged copies, without install."""
import json
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"


def run(*args, env=None):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, env=env).strip()


def verify_app(app):
    run("codesign", "--verify", "--deep", "--strict", str(app))
    signing = run("codesign", "--display", "--verbose=4", str(app))
    assert "TeamIdentifier=YWVVK7QZ6X" in signing
    assert "runtime" in signing and "Timestamp=" in signing
    with tempfile.TemporaryDirectory(prefix="pool-cert-") as temporary:
        certificate = str(Path(temporary) / "certificate")
        run("codesign", "--display", "--extract-certificates=" + certificate, str(app))
        fingerprint = run("openssl", "x509", "-inform", "DER", "-in", certificate + "0", "-noout", "-fingerprint", "-sha1")
        assert fingerprint.split("=")[-1].replace(":", "").strip().upper() == "9FEDAF606F7CB05FC9FB2DB6B31C5F518BD78724"
    run("xcrun", "stapler", "validate", str(app))
    assessment = run("spctl", "--assess", "--type", "execute", "--verbose=2", str(app))
    assert "Notarized Developer ID" in assessment
    assert run("lipo", "-archs", str(app / "Contents/MacOS/HomebrewPoolMenu")) == "x86_64"
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == "0.3.6"
    assert info["CFBundleVersion"] == "36"
    assert info["CFBundleIdentifier"] == "com.stefanalmare.homebrew-intel-bottle-pool"
    from release_checks import check_bundle
    check_bundle(app, True)
    assert not list(app.rglob("*.pyc"))
    return "Notarized Developer ID / stapled / x86_64"


def main():
    app = DIST / "Homebrew Pool.app"
    results = {"app": verify_app(app)}
    embedded = app / "Contents/Resources/client"
    assert (ROOT / "entry.py").read_bytes() == (embedded / "entry.py").read_bytes()
    for module in (ROOT / "pool").glob("*.py"):
        assert module.read_bytes() == (embedded / "pool" / module.name).read_bytes(), module.name
    results["embedded_client_matches_source"] = True
    # Verify bundle hygiene without opening production configuration or secrets.
    for path in app.rglob("*"):
        assert path.name not in ("config.json", "token", "job.json", "imports.json", "pending-run.json")
    results["runtime_state_not_embedded"] = True
    for filename in ("app-notarization.json", "dmg-notarization.json"):
        receipt = json.loads((DIST / filename).read_text())
        assert receipt["status"] == "Accepted"
        results[filename] = receipt
        log = json.loads((DIST / filename.replace(".json", "-log.json")).read_text())
        assert log["status"] == "Accepted" and not log.get("issues")
    with tempfile.TemporaryDirectory(prefix="pool-release-") as temporary:
        root = Path(temporary)
        env = dict(os.environ, XDG_CONFIG_HOME=str(root / "isolated-config"))
        run(str(app / "Contents/MacOS/HomebrewPoolMenu"), "--ui-smoke", str(ROOT / "validation/ui"), env=env)
        assert not (root / "isolated-config").exists()
        results["ui_config_untouched"] = True
        results["signature_after_ui_smoke"] = verify_app(app)
        unpacked = root / "zip"
        run("ditto", "-x", "-k", str(DIST / "Homebrew-Intel-Bottle-Pool-v0.3.6-standard.zip"), str(unpacked))
        results["zip_app"] = verify_app(unpacked / "Homebrew Pool.app")
        mountpoint = root / "volume"
        mountpoint.mkdir()
        dmg = DIST / "Homebrew-Intel-Bottle-Pool-v0.3.6-standard.dmg"
        dmg_assessment = run("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=2", str(dmg))
        assert "Notarized Developer ID" in dmg_assessment
        results["dmg_gatekeeper"] = "Notarized Developer ID / accepted"
        run("xcrun", "stapler", "validate", str(dmg))
        run("hdiutil", "verify", str(dmg))
        run("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mountpoint), str(dmg))
        try:
            results["dmg_app"] = verify_app(mountpoint / "Homebrew Pool.app")
            assert (mountpoint / "Applications").is_symlink()
            assert os.readlink(mountpoint / "Applications") == "/Applications"
            assert (mountpoint / "Read Me.txt").read_bytes() == (ROOT / "QUICKSTART.txt").read_bytes()
            assert (mountpoint / "Read Me.txt").is_file()
        finally:
            run("hdiutil", "detach", str(mountpoint))
    (ROOT / "validation").mkdir(exist_ok=True)
    (ROOT / "validation/release-verification.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
