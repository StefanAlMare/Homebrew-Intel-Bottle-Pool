#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
applications_dir="$HOME/Applications"
prefix="$HOME/.local"
config="${XDG_CONFIG_HOME:-$HOME/.config}/intel-bottle-pool/config.json"
url=""
token_file=""
ca_file=""
login=1
launch=1

usage() {
  echo "Usage: $0 [--url URL --token-file FILE [--ca-file FILE]] [--applications-dir DIR] [--prefix DIR] [--config FILE] [--no-login-item] [--no-launch]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --url) url=${2:?}; shift 2 ;;
    --token-file) token_file=${2:?}; shift 2 ;;
    --ca-file) ca_file=${2:?}; shift 2 ;;
    --applications-dir) applications_dir=${2:?}; shift 2 ;;
    --prefix) prefix=${2:?}; shift 2 ;;
    --config) config=${2:?}; shift 2 ;;
    --no-login-item) login=0; shift ;;
    --no-launch) launch=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = x86_64 ] || { echo "This release is for Intel macOS." >&2; exit 1; }
if { [ -n "$url" ] && [ -z "$token_file" ]; } || { [ -z "$url" ] && [ -n "$token_file" ]; }; then
  echo "Use --url and --token-file together." >&2
  exit 2
fi

if [ ! -d "$project_dir/dist/Homebrew Pool.app" ]; then
  "$project_dir/build-macos.sh"
fi

mkdir -p "$applications_dir"
target_app="$applications_dir/Homebrew Pool.app"
codesign --verify --deep --strict "$project_dir/dist/Homebrew Pool.app"
if [ -e "$target_app" ]; then
  backup_dir=$(mktemp -d "$applications_dir/Homebrew-Pool-backup-XXXXXX")
  mv "$target_app" "$backup_dir/Homebrew Pool.app"
  echo "Previous application preserved: $backup_dir/Homebrew Pool.app"
fi
ditto "$project_dir/dist/Homebrew Pool.app" "$target_app"

sh "$project_dir/install.sh" --prefix "$prefix"
if [ -n "$url" ] && [ ! -e "$config" ]; then
  set -- --config "$config" configure --url "$url" --token-file "$token_file"
  if [ -n "$ca_file" ]; then set -- "$@" --ca-file "$ca_file"; fi
  "$prefix/bin/brew-pool" "$@"
elif [ -n "$url" ]; then
  echo "Existing config preserved: $config"
fi

plist="$HOME/Library/LaunchAgents/com.stefanalmare.homebrew-intel-bottle-pool.plist"
if [ "$login" -eq 1 ]; then
  mkdir -p "$(dirname "$plist")"
  cp "$project_dir/macos/LaunchAgent.plist.in" "$plist"
  plutil -replace ProgramArguments.0 -string "$target_app/Contents/MacOS/HomebrewPoolMenu" "$plist"
  launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || :
  launchctl bootstrap "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
fi

if [ "$launch" -eq 1 ]; then open "$target_app"; fi
echo "Installed Homebrew Pool 0.3.3 in: $target_app"
echo "No automatic brew upgrade was scheduled. Use the menu command when you choose."
