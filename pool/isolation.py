"""Test-bundle data boundary, including explicit --config overrides."""
import os
from pathlib import Path
from .common import PoolError


def test_root():
    return Path.home() / "Library/Application Support/Homebrew Pool 0.3.6 Test"


def require_private_path(path):
    root = os.environ.get("HOMEBREW_POOL_TEST_ROOT")
    if root:
        try:
            Path(path).expanduser().resolve().relative_to(Path(root).resolve())
        except ValueError:
            raise PoolError("Test copy refuses production/outside configuration or state path")


def default_state_dir():
    root = os.environ.get("HOMEBREW_POOL_TEST_ROOT")
    return Path(root) / "state" if root else Path.home() / "Library/Caches/IntelBottlePool"
