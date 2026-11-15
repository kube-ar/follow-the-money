"""Agent 3 · What we cleared before.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/what-we-cleared-before

"We cleared this group in June" is only worth something if you know what was true in June and
what changed since. Give the agent a memory where every fact has two dates (when it was true,
and when you learned it), ask it what it believed then, and find the past approvals that have
gone stale.

Check your work with `uv run trail check d3`. The last check needs an LLM.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk, Request
from trail.registers import Registers


def new_memory() -> Any:
    """An empty memory (a graph is a good fit)."""
    raise NotImplementedError


def remember(memory: Any, fact: dict, valid_from: str, recorded_at: str) -> None:
    """Store a fact like {"subject": "QZ-…" or "QP-…", "predicate": "holds", "object": "QZ-…", "value": 40.0,
    "source": "register" or "gazette:G-012"}. valid_from: the day it became true; recorded_at: the day you
    learned it (both YYYY-MM-DD). A later fact about the same holder and company replaces the earlier one
    from its valid_from on; a value of 0 means the holder sold out."""
    raise NotImplementedError


def believed(memory: Any, company: str, valid_at: str, known_at: str) -> dict[str, float]:
    """Who held what in `company` on day `valid_at`, as far as you knew on day `known_at`: holder → percent,
    leaving out holders at 0."""
    raise NotImplementedError


def why(memory: Any, company: str, valid_at: str, known_at: str) -> list[str]:
    """The sources behind believed(...), sorted and without repeats: "register", "gazette:G-012", …"""
    raise NotImplementedError


def stale(history: list[dict], regs: Registers) -> list[str]:
    """Ids of the past decisions (trail.requests.load_history()) whose company changed after the decision:
    a stake the register shows from a later date, or a Gazette claim (a stake or a new name) dated after
    it. Read the Gazette's claims with your milestone 3 reader, or from regs.quezal.truth while you build."""
    raise NotImplementedError


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: (item, score) best first; ties by item. Score: the sum of 1/(k + rank)."""
    raise NotImplementedError


def screen(request: Request, llm: Any) -> Desk:
    """Your agent, now with a `past_decisions` tool over the history and your memory, so it can say "we
    approved them in June, and their owners changed since"."""
    raise NotImplementedError
