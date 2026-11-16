"""Agent 6 · Decision review.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/decision-review

Every screening leaves a record at the desk. Turn it into an execution graph you can query,
diagnose a wrong decision with four checks in order, pick the fix by code from the diagnosis, and
only ship a changed agent if it gets more right without forgetting what it used to get right.

Check your work with `uv run trail check d6`: everything here is deterministic.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk

DIAGNOSES = ("grounding", "knowledge", "retrieval", "reasoning", "none")


def execution_graph(desk: Desk) -> Any:
    """A node per desk call (step, tool, arguments, spent, cost, ok), NEXT between consecutive calls, and,
    if there was a decision, a node for it with CITES edges to the calls whose kind of source (trail.desk.
    TOOL_SOURCE) its reasons name (trail.desk.sources_cited)."""
    raise NotImplementedError


def wasted_credits(graph: Any) -> int:
    """Credits spent on successful source calls whose kind of source the decision never cites. With no
    decision, every source call's credits."""
    raise NotImplementedError


def diagnose(desk: Desk) -> str:
    """The first of four checks that fails, in this order (or "none" when the decision was correct):

    grounding: the reasons cite a kind of source the desk never returned, or cite the questionnaire.
    knowledge: the officer refused the decision under P6 (it doesn't cite a register and a list).
    retrieval: the run never asked who is above the supplier, never searched a list, or (for a Quezal
      supplier) never read the Gazette.
    reasoning: it had all that and still decided wrong, or never decided."""
    raise NotImplementedError


def choose_fix(diagnosis: str) -> str:
    """grounding → "constraint", knowledge → "prompt", retrieval → "retrieval", reasoning → "fine-tune",
    none → "none"."""
    raise NotImplementedError


def safe_to_ship(before: dict[str, bool], after: dict[str, bool], max_forgetting: int = 0) -> bool:
    """Ship the changed agent only if it gets more requests right and forgets (stops getting right) at most
    `max_forgetting` of the ones the old agent got right. Both map request id → correct."""
    raise NotImplementedError
