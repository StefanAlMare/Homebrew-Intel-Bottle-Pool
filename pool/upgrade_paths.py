"""Read-only upgrade path selection; never migrate credentials or live state."""
import os
from pathlib import Path


def resolve_paths(home=None, environment=None, preferred="standard"):
    home = Path(home) if home is not None else Path.home()
    env = os.environ if environment is None else environment
    standard = home / ".config/intel-bottle-pool/config.json"
    old_test = home / "Library/Application Support/Homebrew Pool 0.3.6 Test"
    test_config = old_test / "config/intel-bottle-pool/config.json"
    app_override = env.get("HOMEBREW_POOL_APP_ROOT")
    explicit_test = env.get("HOMEBREW_POOL_TEST_ROOT") or env.get("POOL_FIXTURE_ROOT")
    xdg = env.get("XDG_CONFIG_HOME")
    test = None
    if app_override:
        test = Path(app_override) / "global"
        config = test / "config/intel-bottle-pool/config.json"
    elif explicit_test:
        test = Path(explicit_test)
        config = test / "config/intel-bottle-pool/config.json"
    elif xdg:
        config = Path(xdg) / "intel-bottle-pool/config.json"
    elif test_config.is_file() and (preferred == "test" or not standard.is_file()):
        test = old_test
        config = test_config
    else:
        config = standard
    return {"config": config, "test_root": test,
            "support": test if test else home / "Library/Application Support/Homebrew Pool",
            "log": (test / "logs/agent.log") if test else home / "Library/Logs/HomebrewIntelBottlePool/agent.log",
            "legacy_root": Path(app_override) if app_override else home / "Library/Application Support/Homebrew Pool Core2 Legacy",
            "agent_label": "com.stefanalmare.homebrew-intel-bottle-pool" + (".test" if test else "")}


def configure_environment(bundle_info):
    preferred = bundle_info.get("PoolUpgradePreferredProfile", "standard")
    paths = resolve_paths(preferred=preferred)
    os.environ["XDG_CONFIG_HOME"] = str(paths["config"].parents[1])
    if paths["test_root"] is not None:
        os.environ["HOMEBREW_POOL_TEST_ROOT"] = str(paths["test_root"])
    else:
        os.environ.pop("HOMEBREW_POOL_TEST_ROOT", None)
    return paths
