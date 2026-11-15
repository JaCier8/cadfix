#!/bin/bash
# Verifier. Runs in a separate container (task.toml); /output is copied over from the agent's container.
# Grades with the verifier's OWN code and task copy (/tests) and pristine parts, never with files the agent could
# change. Always writes a reward: a crash or a missing submission gives 0.
mkdir -p /logs/verifier /output
cd /tests
PYTHONPATH=/tests python3 -m cadfix.grade --task-dir /tests/task --pristine /tests/pristine --submitted /output \
    --level L2 --out /logs/verifier/grade.json --reward-file /logs/verifier/reward.txt \
    2> /logs/verifier/grader_stderr.txt
[ -s /logs/verifier/reward.txt ] || echo 0 > /logs/verifier/reward.txt
cp /output/actions.jsonl /output/episode.json /logs/verifier/ 2>/dev/null
# 3D model for humans (best effort: after the reward is written, never changes it)
mkdir -p /logs/verifier/submitted && cp -r /output/parts /logs/verifier/submitted/ 2>/dev/null
PYTHONPATH=/tests timeout 300 python3 -m cadfix.viz --task-dir /tests/task --pristine /tests/pristine --submitted /output \
    --report /logs/verifier/grade.json --out /logs/verifier/viz > /logs/verifier/viz_stdout.txt 2>&1 || true
echo "reward: $(cat /logs/verifier/reward.txt)"
exit 0
