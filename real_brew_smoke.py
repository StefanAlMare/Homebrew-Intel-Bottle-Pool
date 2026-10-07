"""Opt-in Intel smoke test in a disposable Homebrew prefix, without real upgrades."""
import hashlib
import json
import os
import platform
import plistlib
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path

from pool.brew import Brew
from pool.client import Client
from pool.server import Server, Store


def main():
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise SystemExit("Real smoke test needs Intel macOS and Xcode/CLT")
    original = shutil.which("brew")
    if not original:
        raise SystemExit("Existing Homebrew required for an offline local clone")
    original_env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1")
    repo = Path(subprocess.check_output([original, "--repository"], env=original_env, text=True).strip())
    ruby = Path(subprocess.check_output([original, "ruby", "-e", "puts RbConfig.ruby"], env=original_env, text=True).strip())
    # Homebrew's own sandbox allows broad writes under system TMPDIR. Its executable
    # must live outside that tree, otherwise the inherited-sandbox check rejects it.
    test_parent = Path(__file__).resolve().parent / ".local-test"
    test_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="intel-pool-real-", dir=str(test_parent)) as name:
        root = Path(name).resolve()
        prefix = root / "prefix"
        prefix.mkdir()
        clone = prefix / "Homebrew"
        subprocess.run(["git", "clone", "--quiet", "--shared", str(repo), str(clone)], check=True)
        bundled = repo / "Library" / "Homebrew" / "vendor" / "bundle"
        if bundled.is_dir():
            shutil.copytree(bundled, clone / "Library" / "Homebrew" / "vendor" / "bundle", dirs_exist_ok=True)
        portable = clone / "Library" / "Homebrew" / "vendor" / "portable-ruby"
        portable.parent.mkdir(parents=True, exist_ok=True)
        if portable.exists():
            raise RuntimeError("Unexpected tracked portable-ruby directory")
        portable.symlink_to(ruby.parent.parent.parent, target_is_directory=True)
        (prefix / "bin").mkdir()
        executable = prefix / "bin" / "brew"
        executable.symlink_to(clone / "bin" / "brew")
        # Every mutable cache/log/config/Cellar is isolated from the real installation.
        env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_FROM_API="1",
                   HOMEBREW_NO_ANALYTICS="1", HOMEBREW_NO_ENV_HINTS="1",
                   HOMEBREW_CACHE=str(root / "cache"), HOMEBREW_LOGS=str(root / "logs"),
                   HOMEBREW_TEMP=str(root / "tmp"), XDG_CONFIG_HOME=str(root / "config"),
                   HOMEBREW_NO_INSTALL_CLEANUP="1", HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK="1")
        (root / "tmp").mkdir()
        os.environ.update(env)
        actual_prefix = subprocess.check_output([str(executable), "--prefix"], env=env, text=True).strip()
        if actual_prefix != str(prefix):
            raise RuntimeError("Isolation check failed; will not run installs")
        tap = clone / "Library" / "Taps" / "stefanalmare" / "homebrew-pool-smoke"
        (tap / "Formula").mkdir(parents=True)
        source = root / "source"
        source.mkdir()
        (source / "hello.c").write_text('#include <stdio.h>\nint main(void) { puts("pool-smoke-ok"); return 0; }\n')
        archive = root / "pool-smoke-1.0.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(source / "hello.c", arcname="pool-smoke-1.0/hello.c")
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        formula = '''class PoolSmoke < Formula
  desc "Disposable local bottle pool smoke test"
  homepage "https://example.invalid/StefanAlMare"
  url %s
  version "1.0"
  sha256 "%s"
  license "MIT"
  def install
    system ENV.cc, "hello.c", "-o", "pool-smoke"
    bin.install "pool-smoke"
  end
  test do
    assert_equal "pool-smoke-ok", shell_output("#{bin}/pool-smoke").strip
  end
end
''' % (json.dumps(archive.as_uri()), sha)
        (tap / "Formula" / "pool-smoke.rb").write_text(formula)
        subprocess.run(["git", "init", "--quiet", str(tap)], check=True)
        subprocess.run(["git", "-C", str(tap), "add", "Formula"], check=True)
        subprocess.run(["git", "-C", str(tap), "-c", "user.name=StefanAlMare", "-c", "user.email=StefanAlMare@example.invalid", "commit", "--quiet", "-m", "Disposable smoke formula"], check=True)
        remote = root / "tap-origin.git"
        subprocess.run(["git", "clone", "--quiet", "--bare", str(tap), str(remote)], check=True)
        branch = subprocess.check_output(["git", "-C", str(tap), "branch", "--show-current"], text=True).strip()
        subprocess.run(["git", "-C", str(tap), "remote", "add", "origin", str(remote)], check=True)
        subprocess.run(["git", "-C", str(tap), "fetch", "--quiet", "origin"], check=True)
        subprocess.run(["git", "-C", str(tap), "branch", "--set-upstream-to=origin/" + branch], check=True)
        # A minimal installed core tap avoids Homebrew's uninstall/linkage pass
        # downloading the real core repository, unrelated to this fixture.
        core = clone / "Library" / "Taps" / "homebrew" / "homebrew-core"
        core.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(core)], check=True)
        token = root / "token"
        token.write_text(secrets.token_hex(32))
        store = Store(root / "Diverse" / "Homebrew-Bottles")
        server = Server(("127.0.0.1", 0), store, token.read_text())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def client(name):
                return Client({"url": "http://127.0.0.1:%d" % server.server_port, "token_file": str(token),
                               "state_dir": str(root / name), "brew": str(executable)})
            name = "StefanAlMare/pool-smoke/pool-smoke"
            a = Brew(client("mac-a"))
            a.install(name, kind="formula", update=False)
            assert len(list(store.objects.glob("*/manifest.json"))) == 1
            # Uninstall ONLY the disposable formula in the verified temporary prefix.
            subprocess.run([str(executable), "uninstall", "--ignore-dependencies", "--formula", name], env=env, check=True)
            # Current Homebrew revokes formula trust on uninstall. Trust only our
            # own reviewed disposable fixture before simulating the second Mac.
            subprocess.run([str(executable), "trust", "--formula", name], env=env, check=True)
            b = Brew(client("mac-b"))
            b.install(name, kind="formula", allow_build=False, update=False)
            subprocess.run([str(executable), "test", name], env=env, check=True)
            result = subprocess.check_output([str(prefix / "bin" / "pool-smoke")], text=True).strip()
            assert result == "pool-smoke-ok"
            print("REAL INTEL BREW BUILD → POOL → POUR → TEST PASSED")
            # Exercise a real cask using a tiny app and an isolated appdir. Hide
            # the upstream archive on the second pass to prove pool-only reuse.
            caskdir = tap / "Casks"
            caskdir.mkdir()
            fixture_app = root / "cask-source" / "Pool Smoke.app"
            macos = fixture_app / "Contents/MacOS"
            macos.mkdir(parents=True)
            shutil.copy2(prefix / "bin/pool-smoke", macos / "pool-smoke")
            (fixture_app / "Contents/Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.stefanalmare.pool-smoke-fixture",
                "CFBundleExecutable": "pool-smoke", "CFBundleName": "Pool Smoke",
                "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.0",
                "CFBundleVersion": "1", "LSMinimumSystemVersion": "12.0"}))
            cask_archive = root / "pool-smoke-app-1.0.zip"
            subprocess.run(["ditto", "-c", "-k", "--keepParent", str(fixture_app), str(cask_archive)], check=True)
            cask_sha = hashlib.sha256(cask_archive.read_bytes()).hexdigest()
            (caskdir / "pool-smoke-app.rb").write_text('''cask "pool-smoke-app" do
  version "1.0"
  sha256 "%s"
  url %s
  name "Pool Smoke Fixture"
  desc "Disposable local cask pool smoke test"
  homepage "https://example.invalid/StefanAlMare"
  app "Pool Smoke.app"
end
''' % (cask_sha, json.dumps(cask_archive.as_uri())))
            subprocess.run(["git", "-C", str(tap), "add", "Casks"], check=True)
            subprocess.run(["git", "-C", str(tap), "-c", "user.name=StefanAlMare",
                            "-c", "user.email=StefanAlMare@example.invalid", "commit", "--quiet",
                            "-m", "Disposable smoke cask"], check=True)
            subprocess.run(["git", "-C", str(tap), "push", "--quiet"], check=True)
            appdir = root / "Applications"
            appdir.mkdir()
            os.environ["HOMEBREW_CASK_OPTS"] = "--appdir=" + str(appdir)
            cask_name = "StefanAlMare/pool-smoke/pool-smoke-app"
            subprocess.run([str(executable), "trust", "--cask", cask_name], env=dict(os.environ), check=True)
            c = Brew(client("cask-a"))
            c.install(cask_name, kind="cask", update=False)
            installed_app = appdir / "Pool Smoke.app/Contents/MacOS/pool-smoke"
            assert installed_app.exists(), "Cask did not use the isolated application directory"
            subprocess.run([str(executable), "uninstall", "--cask", cask_name], env=dict(os.environ), check=True)
            subprocess.run([str(executable), "trust", "--cask", cask_name], env=dict(os.environ), check=True)
            cache = Path(c.run("--cache", "--cask", cask_name))
            if cache.exists():
                cache.unlink()
            cask_archive.rename(root / "upstream-hidden.zip")
            d = Brew(client("cask-b"))
            d.install(cask_name, kind="cask", update=False)
            assert subprocess.check_output([str(installed_app)], text=True).strip() == "pool-smoke-ok"
            assert len(list(store.objects.glob("*/manifest.json"))) == 2
            print("REAL INTEL CASK DOWNLOAD → POOL → INSTALL WITHOUT UPSTREAM PASSED")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.close()
            os.environ.clear()
            os.environ.update(original_env)


if __name__ == "__main__":
    main()
