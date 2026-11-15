"""MCP server (stdio) exposing the FitFix tools to an agent.

Env vars: FITFIX_TASK_DIR (task folder, without hidden/), FITFIX_OUT_DIR (where the edited part is saved).
Run: python -m fitfix.server
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .env import FitFixEnv

env = FitFixEnv(os.environ.get("FITFIX_TASK_DIR", "/task"), os.environ.get("FITFIX_OUT_DIR", "/output"))
mcp = FastMCP("fitfix")


@mcp.tool()
def get_task() -> dict:
    """Task description: goal, coordinate frame, constraints (clearance band, min wall, limits) and test_fit budget."""
    return env.call("get_task")


@mcp.tool()
def list_parts() -> dict:
    """Parts in the assembly, which one is editable, and what each part is."""
    return env.call("list_parts")


@mcp.tool()
def part_info(part: str) -> dict:
    """Bounding box (mm), volume and triangle count of a part."""
    return env.call("part_info", part=part)


@mcp.tool()
def check_interference(part_a: str, part_b: str) -> dict:
    """Overlap volume between two parts and the bounding box of the overlapping region. Touching is not a collision."""
    return env.call("check_interference", part_a=part_a, part_b=part_b)


@mcp.tool()
def min_clearance(part_a: str, part_b: str) -> dict:
    """Smallest surface-to-surface distance between two parts (capped at 10 mm)."""
    return env.call("min_clearance", part_a=part_a, part_b=part_b)


@mcp.tool()
def section(part: str, axis: str, value: float) -> dict:
    """Cut a part with the plane axis=value ('x', 'y' or 'z'). Returns the 2D loops of material and holes with their
    bounding boxes, centres and shapes. Coordinates are the other two axes (x->(y,z), y->(x,z), z->(x,y))."""
    return env.call("section", part=part, axis=axis, value=value)


@mcp.tool()
def find_holes(part: str, axis: str, value: float) -> dict:
    """Like section, but only the holes (openings inside material) in the plane axis=value."""
    return env.call("find_holes", part=part, axis=axis, value=value)


@mcp.tool()
def check_printability() -> dict:
    """Thinnest wall of the editable part and where it is, compared with the required minimum."""
    return env.call("check_printability")


@mcp.tool()
def add_box(min: list[float], max: list[float]) -> dict:
    """Add material: union an axis-aligned box [min, max] (mm) to the editable part."""
    return env.call("add_box", min=min, max=max)


@mcp.tool()
def subtract_box(min: list[float], max: list[float]) -> dict:
    """Remove material: cut an axis-aligned box [min, max] (mm) out of the editable part."""
    return env.call("subtract_box", min=min, max=max)


@mcp.tool()
def add_cylinder(axis: str, center: list[float], radius: float, start: float, end: float) -> dict:
    """Add a cylinder along axis from start to end. center = the other two coords (x->(y,z), y->(x,z), z->(x,y))."""
    return env.call("add_cylinder", axis=axis, center=center, radius=radius, start=start, end=end)


@mcp.tool()
def subtract_cylinder(axis: str, center: list[float], radius: float, start: float, end: float) -> dict:
    """Cut a cylinder along axis from start to end. center = the other two coords (x->(y,z), y->(x,z), z->(x,y))."""
    return env.call("subtract_cylinder", axis=axis, center=center, radius=radius, start=start, end=end)


@mcp.tool()
def undo() -> dict:
    """Revert the last edit."""
    return env.call("undo")


@mcp.tool()
def test_fit() -> dict:
    """Full fit report (collisions, clearance per side of the USB opening, standoffs, printability). Limited budget,
    like a real test print: use it to confirm, not to search."""
    return env.call("test_fit")


@mcp.tool()
def submit() -> dict:
    """Finish the episode. The editable part as it is now gets graded."""
    return env.call("submit")


if __name__ == "__main__":
    mcp.run()
