#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"
python3 release_checks.py verify-release 'dist/Homebrew Pool.app'
python3 verify_distribution.py
python3 -m unittest discover -s tests -v
repo=StefanAlMare/Homebrew-Intel-Bottle-Pool
[ "$(gh api "repos/$repo/actions/workflows" --jq .total_count)" = 0 ] || {
  echo 'Workflow configuration changed; stop before push/release.' >&2; exit 1;
}
commit=$(git rev-parse HEAD)
git push origin HEAD:refs/heads/fix/provenance-v0.3.5
# Explicit tag source: never publish stable or main by accident.
git tag -a v0.3.5 "$commit" -m 'Homebrew Intel Bottle Pool v0.3.5'
git push origin refs/tags/v0.3.5
gh release create v0.3.5 --repo "$repo" --verify-tag \
  --title 'Homebrew Intel Bottle Pool v0.3.5' --notes-file RELEASE_NOTES.md \
  dist/Homebrew-Intel-Bottle-Pool-v0.3.5.dmg \
  dist/Homebrew-Intel-Bottle-Pool-v0.3.5.zip \
  dist/Homebrew-Intel-Bottle-Pool-v0.3.5-source.zip \
  dist/SHA256SUMS.txt dist/VALIDATION.md dist/QUICKSTART.txt dist/RELEASE_NOTES.md \
  dist/app-notarization.json dist/dmg-notarization.json \
  dist/app-notarization-log.json dist/dmg-notarization-log.json
verify_dir=$(mktemp -d "$project_dir/build/github-download-XXXXXX")
gh release download v0.3.5 --repo "$repo" --dir "$verify_dir"
cmp dist/SHA256SUMS.txt "$verify_dir/SHA256SUMS.txt"
(cd "$verify_dir" && shasum -a 256 -c SHA256SUMS.txt)
gh release view v0.3.5 --repo "$repo" --json url,tagName,isDraft,assets
