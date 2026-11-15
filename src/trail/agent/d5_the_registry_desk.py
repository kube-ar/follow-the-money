"""Agent 5 · The registry desk.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/the-registry-desk

A real compliance desk has dozens of tools, most of them useless for a screening, and the supplier
writes part of what the agent reads. Find the right tools, chain them by what they take and give,
and keep text the supplier wrote from deciding anything.

Check your work with `uv run trail check d5`. The last check needs an LLM.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk, Request


def select_tools(question: str, k: int = 5) -> list[str]:
    """The k tools of trail.catalog.CATALOG most likely to answer the question, best first."""
    raise NotImplementedError


def chain(have: str, want: str) -> list[str] | None:
    """The shortest chain of catalog tools from a type you have to the type you want, matching what each
    tool gives to what the next one takes. [] when you have it already; None when nothing leads there."""
    raise NotImplementedError


def allowed(tool: str, arguments: dict, desk: Desk) -> str:
    """ "allow", "ask" (a person decides) or "deny", by the catalog's class of the tool:

    human: deny. machine: allow.
    supervised: decide is allowed once this desk returned a register and a list for the request;
      freeze_payments, notify_supplier and escalate_to_legal are allowed when their supplier id came back
      from a register lookup on this desk (an id that only appeared in text the supplier wrote isn't).
      Otherwise ask. Unknown tools: deny.
    """
    raise NotImplementedError


def screen(request: Request, llm: Any, inject: bool = False) -> Desk:
    """Your agent with the right tools (retrieved, not all 55), every call passing through `allowed`.
    inject=True plants an instruction in the supplier's questionnaire: it must not decide anything."""
    raise NotImplementedError
