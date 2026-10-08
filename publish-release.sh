#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"

# Every product gate and test runs locally before the first GitHub request.
python3 release_checks.py verify-release 'dist/Homebrew Pool.app'
python3 verify_distribution.py
python3 -m unittest discover -s tests -v
commit=$(git rev-parse HEAD)
repo=StefanAlMare/Homebrew-Intel-Bottle-Pool
tag=v0.3.5

[ "$(gh api "repos/$repo" --jq .default_branch)" = stable ] || {
  echo 'Expected default branch stable; stop without publishing.' >&2; exit 1;
}
[ "$(gh api "repos/$repo/actions/workflows" --jq .total_count)" = 0 ] || {
  echo 'Workflow configuration changed; stop before push/release.' >&2; exit 1;
}
git fetch origin refs/heads/stable:refs/remotes/origin/stable
git merge-base --is-ancestor origin/stable "$commit" || {
  echo 'stable has new changes; integrate locally and revalidate the final product.' >&2; exit 1;
}

# Never replace an existing public release or a tag for another commit.
if gh release view "$tag" --repo "$repo" --json isDraft > build/existing-release.json 2>/dev/null; then
  python3 -c 'import json; r=json.load(open("build/existing-release.json")); assert r["isDraft"], "Release is already public; review before modifying it"'
  release_exists=1
else
  release_exists=0
fi
remote_tag=$(git ls-remote origin "refs/tags/$tag")
if [ -n "$remote_tag" ]; then
  git fetch origin "refs/tags/$tag:refs/tags/$tag"
fi
if git rev-parse --verify "refs/tags/$tag" >/dev/null 2>&1; then
  [ "$(git rev-parse "$tag^{commit}")" = "$commit" ] || {
    echo 'Tag already identifies another source commit; stop without overwriting it.' >&2; exit 1;
  }
else
  git tag -a "$tag" "$commit" -m 'Homebrew Intel Bottle Pool v0.3.5'
fi

# The code and assets are already final. Upload once, then verify the draft's bytes.
git push --atomic origin "$commit:refs/heads/fix/provenance-v0.3.5" "refs/tags/$tag"
set --
for name in $(python3 package_release.py --list-assets); do
  set -- "$@" "dist/$name"
done
if [ "$release_exists" = 1 ]; then
  gh release upload "$tag" --repo "$repo" --clobber "$@"
  gh release edit "$tag" --repo "$repo" --title 'Homebrew Intel Bottle Pool v0.3.5' --notes-file RELEASE_NOTES.md
else
  gh release create "$tag" --repo "$repo" --verify-tag --draft \
    --title 'Homebrew Intel Bottle Pool v0.3.5' --notes-file RELEASE_NOTES.md "$@"
fi
verify_dir=$(mktemp -d "$project_dir/build/github-download-XXXXXX")
gh release download "$tag" --repo "$repo" --dir "$verify_dir"
cmp dist/SHA256SUMS.txt "$verify_dir/SHA256SUMS.txt"
python3 -c 'from pathlib import Path; from package_release import verify_manifest; import sys; verify_manifest(Path(sys.argv[1]))' "$verify_dir"
(cd "$verify_dir" && shasum -a 256 -c SHA256SUMS.txt)

# Update the repository landing page and make the verified release public last.
git push origin "$commit:refs/heads/stable"
[ "$(gh api "repos/$repo/commits/stable" --jq .sha)" = "$commit" ]
gh release edit "$tag" --repo "$repo" --draft=false --latest
gh release view "$tag" --repo "$repo" --json url,tagName,isDraft,assets
