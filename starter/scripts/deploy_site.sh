#!/usr/bin/env bash
# Publish site/ (built by scripts/build_site.py) to the gh-pages branch of origin -> GitHub Pages.
#   python3 scripts/build_site.py && scripts/deploy_site.sh
# The branch holds only the built site (one force-pushed commit), so ~60 MB of viewers never enter main's history.
# First time only, point Pages at the branch:
#   gh api -X PUT repos/<owner>/<repo>/pages -f build_type=legacy -f 'source[branch]=gh-pages' -f 'source[path]=/'
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f site/index.html ] || { echo "site/ missing: run python3 scripts/build_site.py first" >&2; exit 1; }
url=$(git remote get-url origin)
rev=$(git rev-parse --short HEAD)
name=$(git config user.name); email=$(git config user.email)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cp -r site/. "$tmp/"
git -C "$tmp" init -q -b gh-pages
git -C "$tmp" add -A
git -C "$tmp" -c user.name="$name" -c user.email="$email" commit -qm "site from $rev"
git -C "$tmp" push -qf "$url" gh-pages
echo "pushed gh-pages ($rev) to $url"
