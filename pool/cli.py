import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .artifacts import manifest_for, refresh
from .brew import Brew
from .client import Client, Unavailable
from .common import PoolError, atomic_json
from .settings import check_connection, configure_gui


def default_config():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "intel-bottle-pool" / "config.json"


def main(argv=None):
    p = argparse.ArgumentParser(description="Cooperative Intel Homebrew and external artifact pool")
    p.add_argument("--config", default=str(default_config()))
    commands = p.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure")
    setup.add_argument("--url", required=True)
    setup.add_argument("--token-file", required=True)
    setup.add_argument("--state-dir", default=str(Path.home() / "Library" / "Caches" / "IntelBottlePool"))
    setup.add_argument("--ca-file")
    setup.add_argument("--allow-insecure-http", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("--json", action="store_true", help="Machine-readable status for the macOS agent")
    commands.add_parser("sync")
    settings = commands.add_parser("settings", help="GUI configuration JSON on stdin; secrets never in argv")
    settings.add_argument("--save", action="store_true")
    install = commands.add_parser("install")
    install.add_argument("name")
    install.add_argument("--type", choices=("auto", "formula", "cask"), default="auto")
    install.add_argument("--no-update", action="store_true")
    install.add_argument("--no-build", action="store_true")
    install.add_argument("--allow-upstream-only-cask", action="store_true")
    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("formula", nargs="*")
    upgrade.add_argument("--no-build", action="store_true", help="Defer builds for this run only")
    upgrade.add_argument("--no-update", action="store_true")
    upgrade.add_argument("--no-casks", action="store_true")
    external = commands.add_parser("refresh")
    external.add_argument("--no-build", action="store_true")
    record = commands.add_parser("publish")
    record.add_argument("--recipe", required=True, help="JSON identity, version_order, provenance")
    record.add_argument("file")
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--recipe", required=True)
    fetch.add_argument("destination")
    args = p.parse_args(argv)
    try:
        config_path = Path(args.config).expanduser()
        if args.command == "settings":
            print(json.dumps(configure_gui(config_path, json.load(sys.stdin), args.save)))
            return 0
        if args.command == "configure":
            if config_path.exists():
                raise PoolError("Config already exists; edit it explicitly to preserve adapters")
            config = {"url": args.url, "token_file": str(Path(args.token_file).expanduser().resolve()),
                      "state_dir": str(Path(args.state_dir).expanduser().resolve()),
                      "allow_insecure_http": args.allow_insecure_http,
                      "lock_wait_seconds": 600, "artifacts": []}
            if args.ca_file:
                config["ca_file"] = str(Path(args.ca_file).expanduser().resolve())
            Client(config)  # validate before saving
            atomic_json(config_path, config)
            config_path.chmod(0o600)
            print("Configured: " + str(config_path))
            return 0
        config = json.loads(config_path.read_text())
        client = Client(config)
        if args.command == "status":
            connected = True
            server = None
            try:
                server = check_connection(client)
            except Unavailable:
                connected = False
            queued = len(list(client.spool.glob("entry-*/manifest.json")))
            if args.json:
                state = "healthy" if connected and queued == 0 else "spooling"
                print(json.dumps({"connected": connected, "spool_entries": queued,
                                  "state": state, "server": server}, sort_keys=True))
            else:
                print(json.dumps(server) if connected else "Pool offline")
                print("Spool entries: " + str(queued))
        elif args.command == "sync":
            results = client.sync()
            print(json.dumps(results))
            if any(x == "offline" or x.startswith("retained:") or x == "busy" for x in results):
                return 2
        elif args.command == "upgrade":
            Brew(client).upgrade(args.formula, not args.no_build, not args.no_update, not args.no_casks)
        elif args.command == "install":
            Brew(client).install(args.name, args.type, not args.no_build, not args.no_update,
                                 args.allow_upstream_only_cask)
        elif args.command == "refresh":
            print(json.dumps(refresh(client, not args.no_build)))
        elif args.command == "publish":
            recipe = json.loads(Path(args.recipe).read_text())
            entry = client.enqueue(manifest_for(recipe, args.file), args.file)
            try:
                print(json.dumps(client.publish_entry(entry)))
            except Unavailable:
                print("Pool offline; saved to local spool")
        elif args.command == "fetch":
            recipe = json.loads(Path(args.recipe).read_text())
            expected = manifest_for(recipe)
            found = client.lookup(expected)
            from .artifacts import compatible
            if not compatible(found, expected) or (recipe.get("sha256") and recipe["sha256"] != found["sha256"]):
                raise PoolError("No matching version/context/checksum in pool")
            client.fetch(found, args.destination)
        return 0
    except (PoolError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        print("Error: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
