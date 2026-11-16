"""Milestone 4 · Effective ownership.

Instructions: https://kube.ar/graphrag/project/follow-the-money/effective-ownership

Hold 60% of a company that holds 30% of another, and you own 18% of it. Through two chains, add
them up. Through a majority at every step, you control it even with a small share. Move the
registers into a graph database and answer these with queries: exact shares in Quezal, intervals
from the bands Companies House publishes, control, and the communities shells cluster in. Then
let a model write queries, and check them before they run.

Start Neo4j with `docker compose up -d`, then check your work with `uv run trail check 4`.
One check calls your LLM; the rest don't.

Fast path: Cypher with variable-length paths and reduce(), networkx for communities.
Deep path: the same functions over a graph layer you write on PostgreSQL or SQLite.
"""

from __future__ import annotations

from typing import Any

from trail.registers import Registers

# Your Cypher templates by name: "effective_ownership" ($owner, $company) returns one row with a
# `share` column (0 to 1); "parents_up" ($lei) returns rows with an `id` column, the chain of
# GLEIF parents from the entity's direct parent to the top.
TEMPLATES: dict[str, str] = {}


def store(regs: Registers) -> Any:
    """Load the registers into your store, replacing what was there, and return a handle to it.

    Suggested model: (:Company {id, name, source}) for GLEIF entities (id: LEI), UK companies (id:
    company number) and Quezal companies; (:Person {id, name}) for Quezal people; (:Agent {id, name});
    PARENT (child → direct parent, with percentage when GLEIF has it), OWNED_BY (UK company → active
    corporate owner in the slice, with lo and hi from its share band), HOLDS (Quezal holder →
    company, with percent), SAME_AS (LEI → company number), DIRECTOR_OF, REGISTERED_BY.
    """
    raise NotImplementedError


def store_summary(board: Any) -> dict[str, int]:
    """Counted in the store: companies, people, agents, parent, owned_by, holds, same_as, director_of."""
    raise NotImplementedError


def ask_template(board: Any, name: str, **params) -> list[dict]:
    """Run TEMPLATES[name] with these parameters and return the rows as dicts."""
    raise NotImplementedError


def effective_ownership(board: Any, owner: str, company: str) -> float:
    """The share of `company` that `owner` owns in Quezal, through every chain of stakes: multiply
    along each chain, add the chains. Chains don't visit a company twice. No chain: 0.0."""
    raise NotImplementedError


def controlled_by(board: Any, owner: str) -> set[str]:
    """The Quezal companies `owner` controls: more than 50% of the votes, counting its own stake and
    the stakes of companies it already controls."""
    raise NotImplementedError


def band_ownership(board: Any, owner: str, company: str) -> tuple[float, float] | None:
    """How much of UK company `company` UK company `owner` owns, as an interval, from Companies House.

    Follow OWNED_BY up from `company` to `owner`; multiply the bands' lows along a chain and their
    highs; add the chains and cap the high at 1.0. None when no chain leads there.
    """
    raise NotImplementedError


def validate_query(query: str) -> bool:
    """Is a model-written query safe to run? Read-only, only labels and relationships your store has,
    and ending in a LIMIT of at most 1000. Harmless queries that aren't your templates must pass too."""
    raise NotImplementedError


def generated_query(board: Any, question: str, llm: Any) -> list[dict]:
    """Ask the LLM for one Cypher query that answers the question, validate it, run it, return the rows
    (each with an `id` column). Return [] when the query doesn't pass validate_query."""
    raise NotImplementedError


def communities(board: Any) -> list[set[str]]:
    """Communities in Quezal's company network, as sets of company ids: every Quezal company in exactly
    one. Build the network from stakes between companies; try adding shared directors and see what
    happens to the groups that hide a controller."""
    raise NotImplementedError
