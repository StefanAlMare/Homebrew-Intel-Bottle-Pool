"""User-local installer, no sudo, no downloads, no shell profile mutation."""
import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path


def main():
    if sys.version_info < (3, 9):
        raise SystemExit("Python 3.9 or newer is required")
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", default=str(Path.home() / ".local"))
    p.add_argument("--url")
    p.add_argument("--token-file")
    p.add_argument("--config")
    p.add_argument("--state-dir")
    p.add_argument("--ca-file")
    args = p.parse_args()
    if bool(args.url) != bool(args.token_file):
        p.error("Configure with both --url and --token-file")
    prefix = Path(args.prefix).expanduser().resolve()
    project = Path(__file__).resolve().parent
    target = prefix / "lib" / "intel-bottle-pool"
    if project == target or project in target.parents:
        p.error("Installation prefix must be outside the source project")
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("entry.py",):
        shutil.copy2(project / filename, target / filename)
    shutil.copytree(project / "pool", target / "pool", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    binary_dir = prefix / "bin"
    binary_dir.mkdir(parents=True, exist_ok=True)
    launcher = binary_dir / "brew-pool"
    launcher.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(target / "entry.py")) + " \"$@\"\n")
    launcher.chmod(0o755)
    print("Installed brew-pool in " + str(binary_dir))
    if args.url:
        sys.path.insert(0, str(target))
        from pool.cli import main as configure
        argv = (["--config", args.config] if args.config else []) + ["configure", "--url", args.url, "--token-file", args.token_file]
        if args.state_dir:
            argv += ["--state-dir", args.state_dir]
        if args.ca_file:
            argv += ["--ca-file", args.ca_file]
        raise SystemExit(configure(argv))
    print("Add that directory to PATH, then run brew-pool configure.")


if __name__ == "__main__":
    main()
