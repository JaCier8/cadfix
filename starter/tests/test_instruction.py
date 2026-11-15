"""instruction.md: rendered from public data, neutral (no fix words, no scan numbers), complete (every check id,
the S3 rule, the tools, where the parts are saved)."""
import json
import re

import pytest

from marks import slow_except
from scenarios.hinge_lid import generator
from scenarios.hinge_lid import instruction as hl_instruction
from scenarios.hinge_lid import task as hl_task
from test_dev_scripts import FIX_WORDS, _scan_numbers

CASES = slow_except([(lv, s) for lv in generator.LEVELS for s in (0, 1)], keep={("L1", 0), ("L2", 0)})


@pytest.fixture(scope="module")
def dirs(tmp_path_factory):
    return tmp_path_factory.mktemp("gen"), tmp_path_factory.mktemp("tasks")


@pytest.mark.parametrize("level,seed", CASES)
def test_instruction_is_neutral_and_complete(level, seed, dirs):
    gen, root = dirs
    d = hl_task.write_task(level, seed, gen_out=gen, root=root)
    info = json.loads((generator.seed_dir(gen, level, seed) / "params.json").read_text())
    text = hl_instruction.render_dir(d / "task")
    low = text.lower()
    for word in FIX_WORDS:
        assert word not in low, word
    for n in _scan_numbers(info):
        assert not re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", text), n
    spec = json.loads((d / "task" / "spec.json").read_text())
    for c in spec["checks"]:
        assert f"`{c['id']}`" in text
    full, zero = generator.S3_FACTORS[level]
    assert f"within {full:g}x of the best known fix for this task, zero at {zero:g}x" in text
    assert "`cadfix` MCP server" in text and "/output/parts/" in text and "get_task" in text
    assert ("NOT aligned" in text) == (level == "L3")
    assert "first contact" not in low and " deg:" not in low        # no measured collision angle
