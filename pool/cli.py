import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .actions import ActionRequired
from .artifacts import manifest_for, refresh
from .brew import Brew
from .client import Client, Unavailable, local_lock
from .common import PoolError, atomic_json
from .settings import check_connection, configure_gui
from .jobs import Job
from .processes import JobStopped, install_stop_handlers
from .maintenance import run_maintenance

VERSION = "0.3.4"


def default_config():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "intel-bottle-pool" / "config.json"


def main(argv=None):
    p = argparse.ArgumentParser(description="Cooperative Intel Homebrew and external artifact pool")
    p.add_argument("--version", action="version", version="Homebrew Intel Bottle Pool " + VERSION)
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
    job_command = commands.add_parser("job", help="Review, resolve, or cancel the saved queue")
    job_command.add_argument("action", choices=("review", "resolve", "cancel"))
    repair = commands.add_parser("repair", help="Repair a dependency or reconcile pool state")
    repair_sub = repair.add_subparsers(dest="repair_action", required=True)
    repair_dependency = repair_sub.add_parser("dependency")
    repair_dependency.add_argument("name")
    repair_state = repair_sub.add_parser("state")
    repair_state.add_argument("--cancel", action="store_true")
    maintenance = commands.add_parser("maintenance", help="Run one explicit maintenance command")
    maintenance.add_argument("--administrator", action="store_true")
    maintenance.add_argument("--confirmed", action="store_true")
    maintenance.add_argument("maintenance_command")
    settings = commands.add_parser("settings", help="GUI configuration JSON on stdin; secrets never in argv")
    settings.add_argument("--save", action="store_true")
    install = commands.add_parser("install")
    install.add_argument("name")
    install.add_argument("--type", choices=("auto", "formula", "cask"), default="auto")
    install.add_argument("--no-update", action="store_true")
    install.add_argument("--no-build", action="store_true")
    install.add_argument("--allow-upstream-only-cask", action="store_true")
    install_mode = install.add_mutually_exclusive_group()
    install_mode.add_argument("--resume", action="store_true")
    install_mode.add_argument("--retry-failed", action="store_true")
    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("formula", nargs="*")
    upgrade.add_argument("--no-build", action="store_true", help="Defer builds for this run only")
    upgrade.add_argument("--no-update", action="store_true")
    upgrade.add_argument("--no-casks", action="store_true")
    upgrade.add_argument("--skip", action="append", default=[], help=argparse.SUPPRESS)
    upgrade_mode = upgrade.add_mutually_exclusive_group()
    upgrade_mode.add_argument("--resume", action="store_true")
    upgrade_mode.add_argument("--retry-failed", action="store_true")
    external = commands.add_parser("refresh")
    external.add_argument("--no-build", action="store_true")
    record = commands.add_parser("publish")
    record.add_argument("--recipe", required=True, help="JSON identity, version_order, provenance")
    record.add_argument("file")
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--recipe", required=True)
    fetch.add_argument("destination")
    args = p.parse_args(argv)
    if args.command in ("upgrade", "install", "sync", "refresh", "publish", "fetch", "repair", "maintenance"):
        install_stop_handlers()
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
            saved_job = Job(client.state)
            saved_job.reconcile()
            job = saved_job.report()
            if args.json:
                state = job["status"] if job["failed_count"] or job["remaining_count"] else "healthy" if connected and queued == 0 else "spooling"
                print(json.dumps({"connected": connected, "spool_entries": queued,
                                  "state": state, "server": server, "job": job}, sort_keys=True))
            else:
                print(json.dumps(server) if connected else "Pool offline")
                print("Spool entries: " + str(queued))
        elif args.command == "job":
            with local_lock(client.state):
                job = Job(client.state)
                if args.action != "review":
                    job.resolve(cancel=args.action == "cancel")
                job.emit()
        elif args.command == "repair":
            if args.repair_action == "dependency":
                with local_lock(client.state):
                    print("Repaired dependency: " + Brew(client).repair_dependency(args.name))
            else:
                with local_lock(client.state):
                    job = Job(client.state)
                    if args.cancel:
                        job.resolve(cancel=True)
                    else:
                        job.reconcile()
                    job.emit()
        elif args.command == "maintenance":
            try:
                run_maintenance(args.maintenance_command, client.state, administrator=args.administrator,
                                confirmed=args.confirmed)
            except subprocess.CalledProcessError as error:
                code = error.returncode if 0 < error.returncode < 256 else 1
                print("HOMEBREW_POOL_EXIT_CODE=" + str(code), file=sys.stderr, flush=True)
                return code
            print("HOMEBREW_POOL_EXIT_CODE=0", flush=True)
        elif args.command == "sync":
            results = client.sync()
            print(json.dumps(results))
            if any(x.startswith("retained:") for x in results):
                return 1
            if any(x == "offline" or x.startswith("retained:") or x == "busy" for x in results):
                return 2
        elif args.command == "upgrade":
            Brew(client).upgrade(args.formula, not args.no_build, not args.no_update, not args.no_casks,
                                 args.skip, "retry" if args.retry_failed else "resume" if args.resume else "start")
        elif args.command == "install":
            Brew(client).install(args.name, args.type, not args.no_build, not args.no_update,
                                 args.allow_upstream_only_cask, "retry" if args.retry_failed else "resume" if args.resume else "start")
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
    except ActionRequired as e:
        print(e.marker(), file=sys.stderr)
        return 3
    except JobStopped as e:
        print(str(e), file=sys.stderr)
        return 4
    except (PoolError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        if "client" in locals():
            try:
                saved = Job(client.state)
                if saved.data and (saved.remaining or saved.failures or args.command == "job"):
                    saved.emit()
            except (OSError, ValueError, PoolError):
                pass
        print("Error: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
