#!/usr/bin/env bash
# Open the 3D viewer of any run (builds it in Docker only when needed).
#   scripts/view.sh results/reference/L3/seed_0000 | jobs/viz_oracle | jobs/viz_nop/<trial> | (nothing = latest)
# Extra args go to cadfix.show (--rebuild, --task T). CADFIX_NO_OPEN=1: only print the path.
set -euo pipefail
cd "$(dirname "$0")/.."
f=$(docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/app cadfix-dev python -m cadfix.show --no-open --print "$@")
echo "$f"
[ -n "${CADFIX_NO_OPEN:-}" ] && exit 0
if command -v xdg-open >/dev/null; then xdg-open "$f"; else open "$f"; fi
