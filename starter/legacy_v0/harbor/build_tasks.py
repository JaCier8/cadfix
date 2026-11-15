"""Turn generated FitFix tasks into Harbor task folders.

  python harbor/build_tasks.py --tasks tasks --out harbor_tasks

Layout per task (Harbor conventions):
  task.toml                 - MCP server (stdio) registered for the agent
  instruction.md            - prompt for the agent
  environment/Dockerfile    - python + geometry libs + fitfix package + PUBLIC task files (/task)
  tests/test.sh             - grader with its OWN copy of fitfix, pristine parts and hidden/ -> /logs/verifier/reward.txt
  solution/solve.sh         - reference run (heuristic solver through the same tools); `harbor run -a oracle` uses it
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TASK_TOML = """schema_version = "1.4"

[metadata]
name = "fitfix-{name}"
description = "Fix a 3D-printed enclosure so a USB-C plug fits through its front wall."

[verifier]
timeout_sec = 300.0

[agent]
timeout_sec = 1200.0

[environment]
build_timeout_sec = 900.0

[[environment.mcp_servers]]
name = "fitfix"
transport = "stdio"
command = "python3"
args = ["-m", "fitfix.server"]
"""

DOCKERFILE = """FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir manifold3d trimesh numpy scipy "mcp<2"
COPY fitfix /opt/fitfix/fitfix
COPY task /task
ENV PYTHONPATH=/opt/fitfix FITFIX_TASK_DIR=/task FITFIX_OUT_DIR=/output
RUN mkdir -p /output && python3 -c "from fitfix.env import FitFixEnv; FitFixEnv('/task', '/output')"
WORKDIR /app
"""

TEST_SH = """#!/bin/bash
# Grade with the verifier's own code and pristine task files, never with anything the agent could have edited.
mkdir -p /logs/verifier
cd /tests
PYTHONPATH=/tests python3 -m fitfix.grader /tests/task /output/enclosure.stl --out /logs/verifier/grade.json > /dev/null 2>/logs/verifier/grader_stderr.txt
python3 -c "import json; print(json.load(open('/logs/verifier/grade.json')).get('reward', 0.0))" > /logs/verifier/reward.txt 2>/dev/null || echo 0 > /logs/verifier/reward.txt
cat /logs/verifier/reward.txt
"""

SOLVE_SH = """#!/bin/bash
python3 -m fitfix.solve
"""


def build(task_dir: Path, out_root: Path):
    name = task_dir.name
    t = out_root / f"fitfix-{name}"
    if t.exists():
        shutil.rmtree(t)
    (t / "environment").mkdir(parents=True)
    (t / "tests").mkdir()
    (t / "solution").mkdir()
    (t / "task.toml").write_text(TASK_TOML.format(name=name))
    shutil.copy(ROOT / "harbor" / "instruction.md", t / "instruction.md")
    # environment: public files only
    (t / "environment" / "Dockerfile").write_text(DOCKERFILE)
    shutil.copytree(ROOT / "fitfix", t / "environment" / "fitfix", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(task_dir, t / "environment" / "task", ignore=shutil.ignore_patterns("hidden"))
    # tests: grader code + pristine task incl. hidden/
    shutil.copytree(ROOT / "fitfix", t / "tests" / "fitfix", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(task_dir, t / "tests" / "task")
    (t / "tests" / "test.sh").write_text(TEST_SH)
    (t / "solution" / "solve.sh").write_text(SOLVE_SH)
    for f in (t / "tests" / "test.sh", t / "solution" / "solve.sh"):
        f.chmod(0o755)
    return t


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "tasks"))
    ap.add_argument("--out", default=str(ROOT / "harbor_tasks"))
    a = ap.parse_args()
    for td in sorted(Path(a.tasks).iterdir()):
        if (td / "task.json").exists():
            print(build(td, Path(a.out)))
