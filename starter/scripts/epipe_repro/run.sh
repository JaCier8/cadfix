#!/bin/bash
# Usage (from starter/): docker build -t cadfix-epipe scripts/epipe_repro &&
#   docker run --rm -v "$PWD":/app cadfix-epipe bash /app/scripts/epipe_repro/run.sh [N]
# Prints, per mode, how many of N runs exited non-zero and how many printed EPIPE.
N=${1:-20}
export CADFIX_TASK_DIR=/app/harbor_tasks/judge/hinge-lid-l2-seed0/environment/task PYTHONPATH=/app
cd /repro
for mode in normal sigterm-first server-dies; do
  fail=0; epipe=0
  for i in $(seq "$N"); do
    export CADFIX_OUT_DIR=$(mktemp -d)
    out=$(timeout 120 bun repro.mjs "$mode" 2>&1); rc=$?
    [ $rc -ne 0 ] && fail=$((fail+1))
    grep -q EPIPE <<<"$out" && { epipe=$((epipe+1)); [ $epipe -eq 1 ] && echo "$out" | grep -v '^\s*$' | tail -6; }
  done
  echo "mode=$mode runs=$N nonzero_exit=$fail epipe=$epipe"
done
