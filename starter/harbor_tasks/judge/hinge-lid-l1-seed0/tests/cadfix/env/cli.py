"""Call environment tools from a shell, in-process (same Env as the MCP server):

  python3 -m cadfix.env.cli get_task submit                 # tool names in order, no arguments
  python3 -m cadfix.env.cli 'measure {"part_a": "lid", "part_b": "enclosure", "joint_angle_deg": 60}'

Uses CADFIX_TASK_DIR (default /task) and CADFIX_OUT_DIR (default /output); prints one JSON result per call.
"""
from __future__ import annotations

import json
import os
import sys

from cadfix.env.env import Env


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    env = Env(os.environ.get("CADFIX_TASK_DIR", "/task"), os.environ.get("CADFIX_OUT_DIR", "/output"))
    for item in argv:
        tool, _, args = item.partition(" ")
        res = env.call(tool, **(json.loads(args) if args.strip() else {}))
        print(json.dumps({"tool": tool, "result": res}, default=str)[:2000])


if __name__ == "__main__":
    main()
