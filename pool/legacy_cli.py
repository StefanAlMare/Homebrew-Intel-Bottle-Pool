"""Explicit Core2 workflow. Does not read or inherit the global Pool config."""
import argparse
import json
import os
import sys
from pathlib import Path

from .legacy_policy import Denied, LegacyGate, manifest_digest
from .common import PoolError
from .legacy import (LegacyClient, PROTECTED, inspect_archive, install_verified,
                     load_policy, observe_host, plan_for, private_json, private_write,
                     run_server, require)


def default_root():
    return Path(os.environ.get("HOMEBREW_POOL_APP_ROOT",
                    str(Path.home() / "Library/Application Support/Homebrew Pool Core2 Legacy")))


def status(root):
    config_file = root / "legacy" / "config.json"
    policy_file = root / "legacy" / "policy.json"
    result = {"channel": "core2-legacy", "auto_import_verified_bottles": False,
              "state": "disabled", "configured": config_file.exists(),
              "enrolled_machines": 0, "approved_artifacts": 0,
              "message": "Core2 Legacy is disabled. No machines are enrolled.",
              "config_path": str(config_file), "policy_path": str(policy_file),
              "protected_formulas": sorted(PROTECTED)}
    if policy_file.exists():
        policy = load_policy(policy_file)
        result["enrolled_machines"] = sum(isinstance(x, dict) and x.get("enabled") is True for x in policy["machines"].values())
        result["approved_artifacts"] = len(policy["reviews"])
        result["state"] = "enabled" if policy.get("enabled") is True else "disabled"
        result["pool_id"] = policy["pool_id"]
        result["message"] = "Private channel policy loaded. Hardware and artifact authorization are checked for every transfer."
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Homebrew Pool — private Core2 Legacy")
    parser.add_argument("--config")
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("status")
    subs.add_parser("hardware", help="Read native CPU facts; does not enroll this machine")
    subs.add_parser("init", help="Create a disabled private configuration, without credentials")
    configure = subs.add_parser("configure", help="Load explicitly selected administrator configuration")
    configure.add_argument("--file", required=True)
    server = subs.add_parser("server"); server.add_argument("args", nargs=argparse.REMAINDER)
    for action in ("verify", "publish", "fetch", "install"):
        command = subs.add_parser(action)
        command.add_argument("--manifest", required=True)
        command.add_argument("--plan", required=True)
        if action in ("verify", "publish"): command.add_argument("--bottle", required=True)
        if action == "install": command.add_argument("--authorize-repository-access", action="store_true")
    sync = subs.add_parser("sync"); sync.add_argument("--entry", required=True)
    for action in ("build-plan", "build"):
        command = subs.add_parser(action)
        command.add_argument("--request", required=True)
        if action == "build": command.add_argument("--authorize-repository-access", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = default_root()
        if args.action == "status":
            print(json.dumps(status(root), indent=2)); return 0
        if args.action == "server":
            run_server(args.args); return 0
        if args.action == "configure":
            config = private_json(args.file)
            # Administrative file selection is explicit; live global state is never reused.
            target = root / "legacy"
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            config["state_dir"] = str(target / "state")
            client = LegacyClient(config)
            private_write(target / "config.json", config)
            print(json.dumps({"state": "configured", "message": "Private configuration loaded; no artifact was transferred.",
                              "auto_import_verified_bottles": False}, indent=2)); return 0
        if args.action == "init":
            target = root / "legacy"
            require(not target.is_symlink(), "linked configuration root denied")
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            policy_path, config_path = target / "policy.json", target / "config.json"
            require(not policy_path.exists() and not config_path.exists(), "configuration exists; explicit administrative editing required")
            pool_id = "private-core2-" + __import__('secrets').token_hex(8)
            private_write(policy_path, {"schema": 2, "channel": "core2-legacy", "pool_id": pool_id,
                "revision": 1, "enabled": False, "auto_import_verified_bottles": False,
                "machines": {}, "reviewer_keys": [], "reviews": {}})
            private_write(config_path, {"channel": "core2-legacy", "pool_id": pool_id,
                "auto_import_verified_bottles": False, "policy_file": str(policy_path),
                "state_dir": str(target / "state"), "url": "https://configure-private-server.invalid",
                "machine_id": "not-enrolled", "token_file": str(target / "machine-token"),
                "prefix": "/usr/local", "cellar": "/usr/local/Cellar", "brew": "/usr/local/bin/brew"})
            print(json.dumps(status(root), indent=2)); return 0
        config_path = Path(args.config) if args.config else root / "legacy/config.json"
        config = private_json(config_path)
        if args.action == "hardware":
            print(json.dumps({"observations": observe_host(config),
                   "enrolled": False, "warning": "OS observations do not prove physical ISA when CPU spoofing or emulation is present. Native evidence needs administrative review."}, indent=2)); return 0
        client = LegacyClient(config)
        if args.action in ("build-plan", "build"):
            from .legacy_build import review_request, build
            request = private_json(args.request)
            result = (review_request(client, request) if args.action == "build-plan" else
                      build(client, request, args.authorize_repository_access))
            print(json.dumps(result, indent=2)); return 0
        if args.action == "sync":
            print(json.dumps(client.upload(args.entry), indent=2)); return 0
        manifest, expected = private_json(args.manifest), private_json(args.plan)
        if args.action in ("verify", "publish"):
            # Full local gate and archive parser both run BEFORE any network call.
            client.authorize(manifest, "enqueue", expected, args.bottle)
            inspect_archive(args.bottle, manifest)
            if args.action == "verify":
                print(json.dumps({"status": "verified", "manifest_digest": manifest_digest(manifest),
                                  "published": False}, indent=2)); return 0
            entry = client.enqueue(manifest, args.bottle, expected)
            result = client.upload(entry)
            print(json.dumps(dict(result, retained_local_entry=str(entry)), indent=2)); return 0
        if args.action == "install":
            require(args.authorize_repository_access, "installation requires explicit current repository-access authorization")
            require(manifest["name"].split("/")[-1] not in PROTECTED, "protected formula; preserve existing installation")
        target = client.fetch(manifest, expected)
        inspect_archive(target, manifest)
        if args.action == "install":
            install_verified(client, manifest, expected, target, args.authorize_repository_access)
        print(json.dumps({"status": "installed" if args.action == "install" else "verified-download",
                          "path": str(target), "global_fallback": False}, indent=2))
        return 0
    except (Denied, PoolError, OSError, ValueError, KeyError, TypeError, __import__('subprocess').SubprocessError) as error:
        print(json.dumps({"state": "blocked", "channel": "core2-legacy", "auto_import_verified_bottles": False,
                          "error": str(error), "global_fallback": False}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
