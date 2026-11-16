"""Agent 8 · The final batch: a reference solution. Spoilers: `trail use-reference d8` copies it.

It reuses the planned screening of d4's reference, loaded from reference/agent (never from the folder it sits
in: after `trail use-reference d8`, that folder holds your own d4)."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

from trail.desk import Desk, Request
from trail.registers import ROOT

D4 = ROOT / "reference" / "agent" / "d4_one_branch_per_owner.py"


def ablation(scores: dict[str, float]) -> list[tuple[str, float]]:
    full = scores["full"]
    drops = [(k.removeprefix("without "), round(full - v, 10)) for k, v in scores.items()
             if k.startswith("without ") and v < full]  # fmt: skip
    return sorted(drops, key=lambda x: (-x[1], x[0]))


def screen(request: Request, llm: Any) -> Desk:
    spec = importlib.util.spec_from_file_location("d4_for_d8", D4)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.screen(request, llm)
