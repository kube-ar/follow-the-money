"""Milestone 3 · Reading the Gazette.

Instructions: https://kube.ar/graphrag/project/follow-the-money/reading-the-gazette

Registers lag. The Quezal Gazette reports deals before the register shows them, deals that were
agreed but never completed, and old stakes years after the fact. Turn the Gazette into a lexical
graph, find the companies and people it names, read its claims with an LLM, and say which claims
the register doesn't show yet.

Check your work with `uv run trail check 3`. Reading the claims needs an LLM (`.env`, then
`uv run trail llm`); everything else runs without one.

Fast path: a sentence regex, a dictionary of name variants, `llm.json` with a schema.
Deep path: a review queue for claims the linker isn't sure about, and dates read as intervals.
"""

from __future__ import annotations

import re
from typing import Any

from trail.registers import Article, Registers

SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")  # where one sentence ends and the next begins
KINDS = ("stake", "rename", "director")


def lexical_graph(regs: Registers) -> Any:
    """The Gazette as a lexical graph: an article node per item, a chunk node per sentence (split
    with SENTENCE), PART_OF from each chunk to its article, NEXT between consecutive chunks of an item."""
    raise NotImplementedError


def lexical_summary(graph: Any) -> dict[str, int]:
    """Counted from the graph: {"articles": ..., "sentences": ..., "next": ...}."""
    raise NotImplementedError


def find_entities(regs: Registers, article: Article) -> list[tuple[int, int, str]]:
    """Every mention of a Quezal company or person in article.body, as (start, end, id).

    The press shortens names: "Harrow Point Capital LLC", "Harrow Point Capital", or just
    "Harrow Point", which fits several companies. Use the rest of the article (a later full
    name) and the register (who holds what) to decide; leave out a mention you can't decide.
    """
    raise NotImplementedError


def read_article(regs: Registers, article: Article, llm: Any) -> list[dict]:
    """The claims the item makes, read with `llm` (trail.llm.get_llm()), with ids from the register.

    {"kind": "stake", "buyer": id, "seller": id or None, "company": id, "percent": float, "date": "YYYY-MM-DD"}
    {"kind": "rename", "company": id, "new_name": str, "date": ...}
    {"kind": "director", "person": id, "company": id, "date": ...}

    The date is when the fact happened, not when the item was published: an old stake reported
    today keeps its old date (the first day of the month when only the month is known).
    """
    raise NotImplementedError


def not_in_register(regs: Registers, claims: dict[str, dict]) -> set[str]:
    """Ids of the items (article id → its claim) whose claim the register doesn't show yet.

    A stake is shown when the register has that holder with that percent in that company; a
    rename when the register already uses the new name. Board appointments don't count.
    """
    raise NotImplementedError
