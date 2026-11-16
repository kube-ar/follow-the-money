"""Milestone 5 · Screening a supplier.

Instructions: https://kube.ar/graphrag/project/follow-the-money/screening

Put the map to work. A buyer types a supplier's name (as they spell it) and a country; you say
which company it is, who's at the top, and whether a sanctions or watch list touches it. Then
find, without being told, the groups in Quezal built to hide who controls a company, in the
practice register and in a final one whose answers you never see. Read every miss from the
bottom: which layer broke?

Check your work with `uv run trail check 5`. No LLM needed.

Fast path: reuse your milestone 2 matching and its control rule (plain Python, no Neo4j), called
from here; if you skipped milestone 2, `trail use-reference 2` gives you a working one.
Deep path: score each candidate on several kinds of evidence and keep the reasons.
"""

from __future__ import annotations

from trail.registers import Registers

STATUSES = ("listed", "owned by a listed entity", "no listing found")


def screen(regs: Registers, name: str, country: str) -> dict:
    """{"entity": id or None, "top": id or None, "status": one of STATUSES, "evidence": [sentences]}.

    entity: the LEI, the UK company number or the QZ- id of the company the name means, in that
      country (ISO code; Quezal is "QZ"). None when no register has it.
    top: the top of its ownership chain (milestone 1), or None.
    status: as in milestone 2. A supplier that no register has can still be on a list.
    evidence: why, in sentences a person can check ("GLEIF: consolidated by 549300…").
    """
    raise NotImplementedError


def hidden_controllers(regs: Registers) -> set[tuple[str, str]]:
    """(controller, company) pairs in Quezal: a company on the watch list that controls an operating
    company (one that holds no stakes itself) without holding a majority of it directly."""
    raise NotImplementedError


def bottom_up(scores: dict[str, float], bars: dict[str, float]) -> str | None:
    """The first layer, from the bottom, whose score is under its bar; None if every layer clears it.

    Layers from the bottom: "matching" (milestone 2), "linking" (milestone 3), "extraction"
    (milestone 3) and "answers" (this milestone). A layer missing from `scores` is skipped.
    """
    raise NotImplementedError
