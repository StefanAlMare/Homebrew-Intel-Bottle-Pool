#!/bin/sh
set -eu

purge=0
applications_dir="$HOME/Applications"
prefix="$HOME/.local"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --purge-data) purge=1; shift ;;
    --applications-dir) applications_dir=${2:?}; shift 2 ;;
    --prefix) prefix=${2:?}; shift 2 ;;
    *) echo "Usage: $0 [--purge-data] [--applications-dir DIR] [--prefix DIR]" >&2; exit 2 ;;
  esac
done

plist="$HOME/Library/LaunchAgents/com.stefanalmare.homebrew-intel-bottle-pool.plist"
launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || :
rm -f "$plist"
rm -rf "$applications_dir/Homebrew Pool.app"
rm -f "$prefix/bin/brew-pool"
rm -rf "$prefix/lib/intel-bottle-pool"

if [ "$purge" -eq 1 ]; then
  rm -rf "$HOME/.config/intel-bottle-pool"
  rm -rf "$HOME/Library/Caches/IntelBottlePool"
  rm -rf "$HOME/Library/Logs/HomebrewIntelBottlePool"
  echo "Removed app, client, config, spool, and logs."
else
  echo "Removed app and client. Config, spool, and logs were preserved."
fi
