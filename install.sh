#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${POOL_PYTHON:-python3}" "$project_dir/install.py" "$@"
