"""Agent 1 · The first screening.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/the-first-screening

The map answered questions about registers it already had. An analyst has to go and look things
up: search, follow the owners, check the lists, read the news, and decide. Build the simplest
agent that can work a request at the compliance desk, then read its runs and name what went wrong.

Check your work with `uv run trail check d1`. The second check needs an LLM.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk, Request

FAILURES = ("context amnesia", "relationship blindness", "temporal ignorance", "reasoning paralysis", "tool chaos")


def screen(request: Request, llm: Any) -> Desk:
    """Work one request at a fresh Desk(request) with `llm` (trail.llm.get_llm()) until the agent calls
    `decide` or runs out of turns, and return the desk. trail.llm.Conversation runs the tool calls."""
    raise NotImplementedError


def failures(desk: Desk) -> list[str]:
    """Which of FAILURES the run shows, in FAILURES' order, by these rules on desk.log:

    context amnesia: the same tool called twice with the same arguments.
    relationship blindness: no call that asks who is above the supplier (gleif_parent, ch_control,
      quezal_holders).
    temporal ignorance: a Quezal supplier (country QZ) and no look at the Gazette, which reports
      what the register doesn't show yet.
    reasoning paralysis: no decision at the end.
    tool chaos: three or more calls that failed.
    """
    raise NotImplementedError
