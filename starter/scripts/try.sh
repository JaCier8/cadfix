#!/usr/bin/env bash
# Usage: scripts/try.sh LEVEL SEED OPS_JSON_FILE
# Runs evaluate.py twice on the same ops:
#   1. --hide-score report -> stdout (the text to paste to the model: no reward, S3 only as volume and %)
#   2. full report (kept out of stdout) -> one line appended to gonogo_log.csv in the repo root:
#      timestamp, level, seed, ops file name, reward, S1 pass, volume/V_ref
# The ops file can live anywhere; it is mounted read-only into the container. Needs the cadfix-dev image.
set -euo pipefail

if [ $# -ne 3 ]; then
    echo "usage: $0 LEVEL SEED OPS_JSON_FILE   (format: gonogo/README.md)" >&2
    exit 2
fi
level=$1 seed=$2 ops=$3
[ -f "$ops" ] || { echo "ops file not found: $ops" >&2; exit 2; }
root=$(cd "$(dirname "$0")/.." && pwd)
ops_abs=$(cd "$(dirname "$ops")" && pwd)/$(basename "$ops")
log=$root/gonogo_log.csv

evaluate() {
    docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$root":/app -v "$ops_abs":/tmp/ops.json:ro \
        cadfix-dev python -m scenarios.hinge_lid.evaluate --level "$level" --seed "$seed" \
        --ops /tmp/ops.json --out output/hinge_lid "$@"
}

# 1. what the model sees
evaluate --hide-score

# 2. private record: parse the full report, V_ref from the seed's params.json
full=$(evaluate)
params=$root/output/hinge_lid/$level/seed_$(printf %04d "$seed")/params.json
line=$(FULL="$full" python3 - "$params" "$level" "$seed" "$(basename "$ops")" <<'EOF'
import csv, io, json, os, re, sys
from datetime import datetime
params, level, seed, ops_name = sys.argv[1:]
text = os.environ["FULL"]
m = re.search(r"^REWARD\s+([\d.]+)", text, re.M)
reward = m.group(1) if m else "ERROR"            # an op error prints no reward line
m = re.search(r"^S1 opening\s+(PASS|FAIL)", text, re.M)
s1 = m.group(1) if m else "ERROR"
m = re.search(r"removed ([\d.]+) mm3, added ([\d.]+) mm3", text)
if m:
    v_ref = json.load(open(params))["feasibility"]["V_ref_mm3"]
    ratio = f"{(float(m.group(1)) + float(m.group(2))) / v_ref:.3f}"
else:
    ratio = ""
buf = io.StringIO()
csv.writer(buf, lineterminator="").writerow(
    [datetime.now().isoformat(timespec="seconds"), level, seed, ops_name, reward, s1, ratio])
print(buf.getvalue())
EOF
)
[ -f "$log" ] || echo "timestamp,level,seed,ops_file,reward,s1_pass,volume_over_vref" > "$log"
echo "$line" >> "$log"
echo "(logged to $(basename "$log"))" >&2
