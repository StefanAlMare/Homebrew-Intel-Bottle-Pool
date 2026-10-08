#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"
python3 release_checks.py verify-release 'dist/Homebrew Pool.app'
python3 verify_release.py
python3 -m unittest discover -s tests -v
echo 'GitHub publication is disabled. This is a local test copy; separate authorization required.' >&2
exit 1
