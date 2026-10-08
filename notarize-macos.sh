#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${SIGNING_IDENTITY:?Set the existing Developer ID Application identity}"
: "${NOTARY_PROFILE:?Set the existing notarytool Keychain profile name}"
dist_dir="$project_dir/dist"
app="$dist_dir/Homebrew Pool.app"
codesign --verify --deep --strict "$app"
mkdir -p "$project_dir/build"
stage=$(mktemp -d "$project_dir/build/notarize-XXXXXX")
ditto -c -k --sequesterRsrc --keepParent "$app" "$stage/submit.zip"
xcrun notarytool submit "$stage/submit.zip" --keychain-profile "$NOTARY_PROFILE" --wait --output-format json > "$stage/app-notarization.json"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r); sys.exit(0 if r.get("status")=="Accepted" else 1)' "$stage/app-notarization.json"
xcrun stapler staple "$app"
xcrun stapler validate "$app"
mkdir -p "$stage/dmg"
ditto "$app" "$stage/dmg/Homebrew Pool.app"
ln -s /Applications "$stage/dmg/Applications"
cp "$project_dir/QUICKSTART.txt" "$stage/dmg/Read Me.txt"
cp "$project_dir/LICENSE" "$stage/dmg/License.txt"
dmg="$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.4.dmg"
hdiutil create -quiet -volname "Homebrew Pool 0.3.4" -srcfolder "$stage/dmg" -ov -format UDZO "$dmg"
codesign --force --timestamp --sign "$SIGNING_IDENTITY" "$dmg"
xcrun notarytool submit "$dmg" --keychain-profile "$NOTARY_PROFILE" --wait --output-format json > "$stage/dmg-notarization.json"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r); sys.exit(0 if r.get("status")=="Accepted" else 1)' "$stage/dmg-notarization.json"
xcrun stapler staple "$dmg"
xcrun stapler validate "$dmg"
spctl --assess --type execute --verbose=2 "$app"
spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg"
ditto -c -k --sequesterRsrc --keepParent "$app" "$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.4.zip"
cp "$stage/app-notarization.json" "$dist_dir/app-notarization.json"
cp "$stage/dmg-notarization.json" "$dist_dir/dmg-notarization.json"
app_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$stage/app-notarization.json")
dmg_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$stage/dmg-notarization.json")
xcrun notarytool log "$app_id" --keychain-profile "$NOTARY_PROFILE" "$dist_dir/app-notarization-log.json"
xcrun notarytool log "$dmg_id" --keychain-profile "$NOTARY_PROFILE" "$dist_dir/dmg-notarization-log.json"
source_stage="$stage/Homebrew-Intel-Bottle-Pool-v0.3.4"
mkdir -p "$source_stage"
rsync -a --exclude build --exclude dist --exclude .local-test --exclude __pycache__ --exclude '*.pyc' --exclude .DS_Store \
  "$project_dir/" "$source_stage/"
ditto -c -k --sequesterRsrc --keepParent "$source_stage" \
  "$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.4-source.zip"
cp "$project_dir/VALIDATION.md" "$dist_dir/VALIDATION.md"
cp "$project_dir/QUICKSTART.txt" "$dist_dir/QUICKSTART.txt"
cp "$project_dir/HANDOVER.md" "$dist_dir/HANDOVER.md"
cp "$project_dir/RELEASE_NOTES.md" "$dist_dir/RELEASE_NOTES.md"
(cd "$dist_dir" && shasum -a 256 \
  Homebrew-Intel-Bottle-Pool-v0.3.4.dmg \
  Homebrew-Intel-Bottle-Pool-v0.3.4.zip \
  Homebrew-Intel-Bottle-Pool-v0.3.4-source.zip > SHA256SUMS.txt)
echo "App and DMG accepted, stapled and assessed."
