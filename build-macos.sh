#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_only=0
if [ "${1-}" = "--app-only" ]; then app_only=1; shift; fi
if [ "$#" -ne 0 ]; then echo "Usage: $0 [--app-only]" >&2; exit 2; fi
mkdir -p "$project_dir/build" "$project_dir/dist"
build_dir=$(mktemp -d "$project_dir/build/macos-XXXXXX")
dist_dir="$project_dir/dist"
app="$build_dir/Homebrew Pool.app"

case "$(uname -s):$(uname -m)" in
  Darwin:x86_64) ;;
  *) echo "Build this release on Intel macOS." >&2; exit 1 ;;
esac

command -v swiftc >/dev/null 2>&1 || { echo "swiftc is required (install Apple Command Line Tools)." >&2; exit 1; }
mkdir -p "$build_dir" "$app/Contents/MacOS" "$app/Contents/Resources/client"
mkdir -p "$build_dir/module-cache"
cp "$project_dir/macos/Info.plist" "$app/Contents/Info.plist"
cp "$project_dir/macos/HomebrewPool.icns" "$app/Contents/Resources/HomebrewPool.icns"
cp "$project_dir/entry.py" "$app/Contents/Resources/client/entry.py"
mkdir -p "$app/Contents/Resources/client/pool"
cp "$project_dir/pool/"*.py "$app/Contents/Resources/client/pool/"

CLANG_MODULE_CACHE_PATH="$build_dir/module-cache" \
SWIFT_MODULECACHE_PATH="$build_dir/module-cache" \
swiftc -swift-version 5 -O -target x86_64-apple-macos12.0 \
  -framework AppKit -framework Foundation -framework UserNotifications \
  "$project_dir/macos/HomebrewPoolMenu.swift" \
  -o "$app/Contents/MacOS/HomebrewPoolMenu"
if [ -n "${SIGNING_IDENTITY-}" ]; then
  xattr -cr "$app"
  if [ -n "${SIGNING_KEYCHAIN-}" ]; then
    codesign --force --options runtime --timestamp --keychain "$SIGNING_KEYCHAIN" --sign "$SIGNING_IDENTITY" "$app"
  else
    codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$app"
  fi
else
  codesign --force --sign - "$app"
fi
codesign --verify --deep --strict "$app"
ditto "$app" "$dist_dir/Homebrew Pool.app"

if [ "$app_only" -eq 1 ]; then
  echo "Built: $dist_dir/Homebrew Pool.app"
  exit 0
fi

ditto -c -k --sequesterRsrc --keepParent "$app" "$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.2.zip"

dmg_root="$build_dir/dmg"
mkdir -p "$dmg_root"
ditto "$app" "$dmg_root/Homebrew Pool.app"
ln -s /Applications "$dmg_root/Applications"
cp "$project_dir/QUICKSTART.txt" "$dmg_root/Read Me.txt"
cp "$project_dir/LICENSE" "$dmg_root/License.txt"
hdiutil create -quiet -volname "Homebrew Pool 0.3.2" -srcfolder "$dmg_root" \
  -ov -format UDZO "$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.2.dmg"
if [ -n "${SIGNING_IDENTITY-}" ]; then
  codesign --force --timestamp --sign "$SIGNING_IDENTITY" "$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.2.dmg"
fi
echo "Built: $app"
echo "Built: $dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.2.dmg"
