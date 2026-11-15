"""Build Harbor task folders from cadfix tasks (public task dir + private pristine dir).

  python -m cadfix.harbor.build --level L1,L2,L3 --seeds 0-9 [--tasks output/tasks] [--out harbor_tasks]
  python -m cadfix.harbor.build --judge            # harbor_tasks/judge: L1, L2, L3 seed 0 (one dataset)

Per task (Harbor conventions):
  task.toml               MCP server `cadfix` (stdio, in the agent's container), timeouts, verifier in a SEPARATE
                          container that only receives /output (artifact) from the agent's container
  instruction.md          rendered from the public task files (scenarios/hinge_lid/instruction.py)
  environment/Dockerfile  python 3.11 + locked deps + the cadfix package + the PUBLIC task (/task); every layer
                          except the last COPY is identical across tasks (and to the dev image), so Docker caches them
  tests/test.sh           the verifier's OWN grader code (tests/cadfix) + its own task copy + pristine parts and
                          private values (tests/pristine) -> /logs/verifier/reward.txt (always written)
  solution/solve.sh       the reference solver (tools only, over MCP stdio): `harbor run -a oracle`

The scenario-specific parts (instruction renderer, reference solver) are looked up by the task's `scenario`.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")

TASK_TOML = """schema_version = "1.4"
artifacts = ["/output"]

[metadata]
name = "{name}"
description = "{description}"
scenario = "{scenario}"
level = "{level}"
seed = {seed}

[verifier]
timeout_sec = 900.0
environment_mode = "separate"

[agent]
timeout_sec = 3600.0

[environment]
build_timeout_sec = 2400.0
cpus = 2
memory_mb = 4096

[[environment.mcp_servers]]
name = "cadfix"
transport = "stdio"
command = "python3"
args = ["-m", "cadfix.env.server"]
"""

DOCKERFILE = """# cadfix task image. Everything above `COPY task /task` is the same for every task (and the same as the
# repo's dev image), so Docker builds the heavy layers once.
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

RUN apt-get update \\
 && apt-get install -y --no-install-recommends libgl1 libx11-6 libexpat1 \\
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_NO_CACHE_DIR=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1 \\
    PIP_ROOT_USER_ACTION=ignore \\
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

COPY requirements.lock .
RUN pip install --retries 5 -r requirements.lock

# the generic environment code (MCP server, checks, ops); no scenario generator, no reference data
COPY cadfix /opt/cadfix/cadfix
ENV PYTHONPATH=/opt/cadfix CADFIX_TASK_DIR=/task CADFIX_OUT_DIR=/output
RUN mkdir -p /output && python3 -c "import cadfix.env.server, cadfix.checks"

# public task files: task.json, spec.json, parts/*.step
COPY task /task
"""

TEST_SH = """#!/bin/bash
# Verifier. Runs in a separate container (task.toml); /output is copied over from the agent's container.
# Grades with the verifier's OWN code and task copy (/tests) and pristine parts, never with files the agent could
# change. Always writes a reward: a crash or a missing submission gives 0.
mkdir -p /logs/verifier /output
cd /tests
PYTHONPATH=/tests python3 -m cadfix.grade --task-dir /tests/task --pristine /tests/pristine --submitted /output \\
    --level {level} --out /logs/verifier/grade.json --reward-file /logs/verifier/reward.txt \\
    2> /logs/verifier/grader_stderr.txt
[ -s /logs/verifier/reward.txt ] || echo 0 > /logs/verifier/reward.txt
cp /output/actions.jsonl /output/episode.json /logs/verifier/ 2>/dev/null
echo "reward: $(cat /logs/verifier/reward.txt)"
exit 0
"""

SOLVE_SH = """#!/bin/bash
# Reference run: the reference solver plays through the same MCP tools an agent gets (it starts
# `python3 -m cadfix.env.server` over stdio) and never reads task data directly.
python3 /solution/reference.py --mcp --task-dir /task --out-dir /output
"""

SCENARIOS = {"hinge_lid": {"instruction": "scenarios.hinge_lid.instruction", "reference": "scenarios/hinge_lid/reference.py",
                           "description": "Fix a 3D-printed box whose hinged lid jams while opening (hinge_lid {level})."}}


def build_task(task_root: Path, out: Path, name: str | None = None) -> Path:
    """task_root: <tasks>/<L>/seed_NNNN with task/ and pristine/."""
    import importlib
    task = json.loads((task_root / "task" / "task.json").read_text())
    level, seed, scen = task["level"], int(task["seed"]), task["scenario"]
    sc = SCENARIOS[scen]
    name = name or f"cadfix-{scen.replace('_', '-')}-{level.lower()}-seed{seed:04d}"
    if out.exists():
        shutil.rmtree(out)
    (out / "environment").mkdir(parents=True)
    (out / "tests").mkdir()
    (out / "solution").mkdir()
    (out / "task.toml").write_text(TASK_TOML.format(name=name, description=sc["description"].format(level=level),
                                                    scenario=scen, level=level, seed=seed))
    render = importlib.import_module(sc["instruction"]).render_dir
    (out / "instruction.md").write_text(render(task_root / "task", "/task", "/output"))
    env = out / "environment"
    (env / "Dockerfile").write_text(DOCKERFILE)
    shutil.copy(ROOT / "requirements.lock", env / "requirements.lock")
    shutil.copytree(ROOT / "cadfix", env / "cadfix", ignore=IGNORE)
    shutil.copytree(task_root / "task", env / "task", ignore=IGNORE)
    tests = out / "tests"
    shutil.copytree(ROOT / "cadfix", tests / "cadfix", ignore=IGNORE)
    shutil.copytree(task_root / "task", tests / "task", ignore=shutil.ignore_patterns("parts"))
    shutil.copytree(task_root / "pristine", tests / "pristine", ignore=IGNORE)
    (tests / "test.sh").write_text(TEST_SH.format(level=level))
    shutil.copy(ROOT / sc["reference"], out / "solution" / "reference.py")
    (out / "solution" / "solve.sh").write_text(SOLVE_SH)
    for f in (tests / "test.sh", out / "solution" / "solve.sh"):
        f.chmod(0o755)
    return out


def validate(task_dir: Path) -> str:
    """Parse task.toml with Harbor's own TaskConfig model (if harbor is installed)."""
    try:
        import tomllib

        from harbor.models.task.config import TaskConfig
    except ImportError:
        return "harbor not installed: task.toml not validated"
    cfg = TaskConfig.model_validate(tomllib.loads((task_dir / "task.toml").read_text()))
    return f"valid ({len(cfg.environment.mcp_servers)} MCP server, verifier {cfg.verifier.environment_mode})"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", default="L1,L2,L3")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--tasks", default="output/tasks")
    ap.add_argument("--gen", default="output/hinge_lid")
    ap.add_argument("--out", default="harbor_tasks")
    ap.add_argument("--judge", action="store_true", help="build harbor_tasks/judge (L1, L2, L3 seed 0)")
    ap.add_argument("--validate", action="store_true", help="validate every task.toml with harbor's TaskConfig")
    a = ap.parse_args(argv)
    from scenarios.hinge_lid import generator as gen
    from scenarios.hinge_lid import task as hl_task
    out_root = Path(a.out)
    cases = [(lv, 0) for lv in gen.LEVELS] if a.judge else \
        [(lv, s) for lv in gen.parse_levels(a.level) for s in gen.parse_seeds(a.seeds)]
    for level, seed in cases:
        root = hl_task.ensure_task(level, seed, a.gen, a.tasks)
        dest = out_root / "judge" / f"hinge-lid-{level.lower()}-seed0" if a.judge else \
            out_root / level / f"seed_{seed:04d}"
        build_task(root, dest)
        print(dest, validate(dest) if a.validate else "")


if __name__ == "__main__":
    main()
