#!/bin/bash
# Verifier. Runs in a separate container (task.toml); /output is copied over from the agent's container.
# Grades with the verifier's OWN code and task copy (/tests) and pristine parts, never with files the agent could
# change. Always writes a reward: a crash or a missing submission gives 0.
mkdir -p /logs/verifier /output
cd /tests
PYTHONPATH=/tests python3 -m cadfix.grade --task-dir /tests/task --pristine /tests/pristine --submitted /output \
    --level L1 --out /logs/verifier/grade.json --reward-file /logs/verifier/reward.txt \
    2> /logs/verifier/grader_stderr.txt
[ -s /logs/verifier/reward.txt ] || echo 0 > /logs/verifier/reward.txt
cp /output/actions.jsonl /output/episode.json /logs/verifier/ 2>/dev/null
echo "reward: $(cat /logs/verifier/reward.txt)"
exit 0
