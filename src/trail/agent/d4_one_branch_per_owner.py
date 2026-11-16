"""Agent 4 · One branch per owner.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/one-branch-per-owner

Stop improvising. Plan the screening as a workflow graph before calling anything, fan out one
branch per owner so each is checked against the lists side by side, and check a decision's
meaning (not just its shape) before it's recorded.

Check your work with `uv run trail check d4`. The last check needs an LLM.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk, Request

KINDS = ("reasoning", "execution", "decision", "validation")
PROBLEMS = ("bad-decision", "unknown-entity", "too-few-sources", "unconsulted-source", "questionnaire-cited",
            "stakes-over-100", "approve-without-list")  # fmt: skip


def compound_success(per_step: float, steps: int) -> float:
    """The chance a run of `steps` steps succeeds when each one succeeds with probability per_step."""
    raise NotImplementedError


def plan(request: Request) -> list[dict]:
    """The screening as steps {"id", "kind" (one of KINDS), "tools": [desk tools], "needs": [step ids]}, made
    without calling a tool. All four kinds appear; only execution steps hold tools, three at most each. Include
    a step with id "owners" (who is above the supplier) and one with id "decide"."""
    raise NotImplementedError


def expand(steps: list[dict], owners: list[str]) -> list[dict]:
    """The plan with one execution step per owner, id "owner:<id>", checking that owner against the lists
    (needs "owners"); "decide" now also needs every owner step. The other steps stay as they were."""
    raise NotImplementedError


def phases(steps: list[dict]) -> list[list[str]]:
    """The steps in phases: each phase holds the steps whose needs earlier phases met, sorted by id."""
    raise NotImplementedError


def validate_decision(desk: Desk, decision: dict) -> list[str]:
    """The PROBLEMS a decision {"decision", "entity", "reasons", "owners": [{"id", "percent"}]} has, in PROBLEMS'
    order. Uses trail.desk.sources_cited(reasons) for what the reasons cite (the officer's own word rules) and
    desk.consulted() for what was looked up.

    bad-decision: not approve, reject or escalate. unknown-entity: an entity no register has (empty is fine).
    too-few-sources: the reasons don't cite a register and a list. unconsulted-source: they cite a kind of
    source the desk never returned. questionnaire-cited: they cite the questionnaire. stakes-over-100: the
    owners' percents add up to more than 100. approve-without-list: an approval with no list consulted."""
    raise NotImplementedError


def screen(request: Request, llm: Any) -> Desk:
    """The planned screening: run the plan's phases, fan out one branch per owner, ask the LLM for the
    decision as structured output, validate it, retry once with the problems listed, then decide."""
    raise NotImplementedError
