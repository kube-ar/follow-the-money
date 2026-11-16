"""Agent 7 · Cost and clearance.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/cost-and-clearance

A screening agent that works costs money and reads who owns what. Give each step the cheapest
model that's good enough, count the cost per correct decision, hide ownership data from junior
desks entirely, and answer an auditor and an erasure request from what you already keep.

Check your work with `uv run trail check d7`: everything here is deterministic.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk

RESTRICTED = {"junior": {"ch_control", "quezal_holders", "board"}, "senior": set()}


def route_model(step: str, bars: dict[str, float], models: dict[str, tuple[float, float]]) -> str:
    """The cheapest model whose quality meets the step's bar. models: name → (quality, cost per call). A step
    with no bar takes the cheapest model; if none meets the bar, the best one."""
    raise NotImplementedError


def cost_per_correct(runs: list[tuple[float, bool]]) -> float:
    """Total cost of the runs (cost, correct) divided by the correct decisions; inf when none is correct."""
    raise NotImplementedError


def restricted(desk: Desk, role: str) -> Any:
    """The desk as a role sees it: an object with tools() and call(name, arguments). The role's RESTRICTED
    tools are invisible: not listed, and a call fails exactly like a call to a tool that doesn't exist."""
    raise NotImplementedError


def audit(desks: list[Desk], entity: str) -> list[tuple[str, int, str]]:
    """Every successful lookup of who owns `entity` (gleif_parent, ch_control, quezal_holders on its id),
    as (request id, step, tool), in the order of the desks."""
    raise NotImplementedError


def erase(people: list[dict], person: str) -> list[dict]:
    """The people table (trail.desk.records(regs)["qz_people"]) after an erasure request: that person's row
    keeps only its id; every other row stays as it was."""
    raise NotImplementedError
