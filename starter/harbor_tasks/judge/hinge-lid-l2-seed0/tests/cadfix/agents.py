"""Scripted baseline agents. Generic: they only call tools through a client (`client(tool, **args)`), like an LLM
agent over MCP.

  do_nothing  - submits at once (judging baseline; Harbor's `nop` does not even start the server)
  stop_early  - one inspection call, then submits (judging baseline)
"""
from __future__ import annotations


def do_nothing(client) -> dict:
    client("submit")
    return {"ok": True}


def stop_early(client) -> dict:
    client("get_task")
    client("submit")
    return {"ok": True}


BASELINES = {"do_nothing": do_nothing, "stop_early": stop_early}
