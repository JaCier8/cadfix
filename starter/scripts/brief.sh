#!/usr/bin/env bash
# Usage: scripts/brief.sh LEVEL SEED
# Prints what an agent would know about one level/seed (brief.py: S3 as a rule only, no reference numbers).
# Generates the seed's parts in output/hinge_lid if they are missing. Needs the cadfix-dev image.
set -euo pipefail

if [ $# -ne 2 ]; then
    echo "usage: $0 LEVEL SEED   (LEVEL = L1, L2 or L3)" >&2
    exit 2
fi
level=$1 seed=$2
root=$(cd "$(dirname "$0")/.." && pwd)

docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$root":/app cadfix-dev \
    python -m scenarios.hinge_lid.brief --level "$level" --seed "$seed" --out output/hinge_lid
