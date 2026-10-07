#!/usr/bin/env python3
import sys
sys.dont_write_bytecode = True

if sys.version_info < (3, 9):
    raise SystemExit("Homebrew Pool requires Python 3.9 or newer.")

from pool.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
