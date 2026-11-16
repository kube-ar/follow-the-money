"""Milestone 1 · Who owns whom.

Instructions: https://kube.ar/graphrag/project/follow-the-money/who-owns-whom

Three registers that never heard of each other: GLEIF (who consolidates whom, worldwide),
Companies House (who controls each UK company) and Quezal's company register (exact stakes, in
a fictional offshore jurisdiction). Put them in one graph, then answer what none of them answers
alone: the top of a chain, everything under a parent, and ownership that goes around in a loop.
Then ask a vector search for a whole group and see what it misses.

Check your work with `uv run trail check 1`.

Ids. Return GLEIF entities by LEI, UK companies by company number, Quezal companies and people
by their QZ-/QP- ids.

Fast path: networkx gives you the graph, the walks and the cycles.
Deep path: dicts of adjacency sets, and the walks and the cycle finding written by you.
"""

from __future__ import annotations

from typing import Any

from trail.registers import Registers


def build_graph(regs: Registers) -> Any:
    """All three registers as nodes and edges in one graph.

    Suggested shape (any shape works, as long as the functions below can answer from it):
    nodes for GLEIF entities, UK companies, Quezal companies and people; edges like
    PARENT (child → direct parent, from GLEIF), CONTROLLED_BY (UK company → corporate owner,
    from active Companies House records), HOLDS (Quezal holder → company, with the percent) and
    SAME_AS (LEI ↔ company number, when GLEIF says the entity is registered at Companies House,
    authority RA000585, under that number).
    """
    raise NotImplementedError


def graph_summary(graph: Any) -> dict[str, int]:
    """How much of each register is in your graph, counted from the graph.

    Keys: gleif_entities, gleif_parent_links (direct), uk_companies, uk_corporate_owners (active
    corporate records), quezal_companies, quezal_people, quezal_stakes (current stakes),
    same_company_links (LEI ↔ company number pairs where both are in the registers).
    """
    raise NotImplementedError


def ultimate_parent(graph: Any, lei: str) -> str:
    """The top of the chain: follow direct parents until there's none. An entity with no parent is its own top."""
    raise NotImplementedError


def group(graph: Any, lei: str) -> set[str]:
    """`lei` and every entity under it, through direct parents (LEIs)."""
    raise NotImplementedError


def ownership_loops(graph: Any) -> list[list[str]]:
    """Every loop in the ownership edges, followed the way they point: [x, y, ..., z] where x is a child of y
    (GLEIF: child → direct parent) or holds a stake in y (Quezal: holder → company), and so on, until z leads
    back to x.

    Look at GLEIF's parent links and Quezal's stakes. Each loop once; any starting point is fine.
    """
    raise NotImplementedError


def vector_group(regs: Registers, lei: str, k: int) -> set[str]:
    """The same question as `group`, answered the way a plain vector search would.

    Write one line per GLEIF entity ("BP P.L.C., London, GB"), embed them (use
    `trail.vectors.VectorIndex`), ask "Companies in the <name of lei> group" and return the
    LEIs of the top k lines.
    """
    raise NotImplementedError
