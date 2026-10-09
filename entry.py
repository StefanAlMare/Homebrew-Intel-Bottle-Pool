#!/usr/bin/env python3
import sys
import os
import plistlib
from pathlib import Path
sys.dont_write_bytecode = True

if sys.version_info < (3, 9):
    raise SystemExit("Homebrew Pool requires Python 3.9 or newer.")

from pool.cli import main
from pool.isolation import test_root

bundle_info = Path(__file__).resolve().parents[2] / "Info.plist"
if bundle_info.is_file():
    info = plistlib.loads(bundle_info.read_bytes())
    if info.get("PoolUpgradePreserveSettings") is True and (len(sys.argv) < 2 or sys.argv[1] != "legacy"):
        from pool.upgrade_paths import configure_environment
        configure_environment(info)
    elif info.get("CFBundleIdentifier", "").endswith(".test"):
        root = os.environ.get("HOMEBREW_POOL_TEST_ROOT") or os.environ.get("POOL_FIXTURE_ROOT") or str(test_root())
        os.environ["HOMEBREW_POOL_TEST_ROOT"] = root
        os.environ.setdefault("XDG_CONFIG_HOME", str(Path(root) / "config"))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "legacy":
        from pool.legacy_cli import main as legacy_main
        raise SystemExit(legacy_main(sys.argv[2:]))
    raise SystemExit(main())
