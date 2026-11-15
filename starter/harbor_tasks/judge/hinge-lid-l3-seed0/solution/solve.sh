#!/bin/bash
# Reference run: the reference solver plays through the same MCP tools an agent gets (it starts
# `python3 -m cadfix.env.server` over stdio) and never reads task data directly.
python3 /solution/reference.py --mcp --task-dir /task --out-dir /output
