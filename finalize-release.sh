#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dist_dir="$project_dir/dist"
app="$dist_dir/Homebrew Pool.app"
codesign --verify --deep --strict "$app"
xcrun stapler validate "$app"
spctl --assess --type execute --verbose=2 "$app"
stage=$(mktemp -d "$project_dir/build/finalize-XXXXXX")
source_stage="$stage/Homebrew-Intel-Bottle-Pool-v0.3.6-standard"
mkdir -p "$source_stage" "$project_dir/validation/apple"
cp "$dist_dir/app-notarization.json" "$dist_dir/dmg-notarization.json" \
  "$dist_dir/app-notarization-log.json" "$dist_dir/dmg-notarization-log.json" "$project_dir/validation/apple/"
rsync -a --exclude .git --exclude build --exclude dist --exclude .local-test --exclude __pycache__ \
  --exclude '*.pyc' --exclude .DS_Store "$project_dir/" "$source_stage/"
ditto -c -k --sequesterRsrc --keepParent "$source_stage" "$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.6-standard-source.zip"
ditto -c -k --sequesterRsrc --keepParent "$app" "$dist_dir/Homebrew-Intel-Bottle-Pool-v0.3.6-standard.zip"
cp "$project_dir/VALIDATION.md" "$project_dir/HANDOVER.md" "$project_dir/QUICKSTART.txt" \
  "$project_dir/RELEASE_NOTES.md" "$project_dir/IMPORT_PROVENANCE.md" "$project_dir/PARITY_REPORT.md" "$dist_dir/"
cp "$project_dir/validation/release-verification.json" "$project_dir/validation/tests.json" \
  "$project_dir/validation/workflow-smoke.json" "$project_dir/validation/parity.json" "$dist_dir/"
(cd "$dist_dir" && shasum -a 256 \
  Homebrew-Intel-Bottle-Pool-v0.3.6-standard.dmg Homebrew-Intel-Bottle-Pool-v0.3.6-standard.zip \
  Homebrew-Intel-Bottle-Pool-v0.3.6-standard-source.zip VALIDATION.md HANDOVER.md QUICKSTART.txt RELEASE_NOTES.md \
  app-notarization.json dmg-notarization.json app-notarization-log.json dmg-notarization-log.json \
  release-verification.json tests.json workflow-smoke.json IMPORT_PROVENANCE.md \
  PARITY_REPORT.md parity.json > SHA256SUMS.txt)
(cd "$dist_dir" && shasum -a 256 -c SHA256SUMS.txt)
