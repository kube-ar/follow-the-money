"""Agent 6 · Decision review: a reference solution. Spoilers: `trail use-reference d6` copies it."""

from __future__ import annotations

import networkx as nx

from trail.desk import SOURCE_WORDS, TOOL_SOURCE, Desk

DIAGNOSES = ("grounding", "knowledge", "retrieval", "reasoning", "none")
SOURCES = {k for k in TOOL_SOURCE.values() if k != "questionnaire"}


def _cited(decision: dict | None) -> set[str]:
    text = " ".join((decision or {}).get("reasons", [])).lower()
    return {kind for kind, words in SOURCE_WORDS.items() if any(w in text for w in words)}


def execution_graph(desk: Desk) -> nx.DiGraph:
    g = nx.DiGraph()
    previous = None
    for a in desk.log:
        node = ("call", a.step)
        g.add_node(node, step=a.step, tool=a.tool, arguments=a.arguments, spent=a.spent, cost=a.cost, ok=a.ok)
        if previous:
            g.add_edge(previous, node, type="NEXT")
        previous = node
    if desk.decision:
        g.add_node(("decision",), **desk.decision)
        cited = _cited(desk.decision)
        for a in desk.log:
            if a.ok and TOOL_SOURCE.get(a.tool) in cited:
                g.add_edge(("decision",), ("call", a.step), type="CITES")
    return g


def wasted_credits(graph: nx.DiGraph) -> int:
    cited = ({v for _, v, d in graph.out_edges(("decision",), data=True) if d["type"] == "CITES"}
             if ("decision",) in graph else set())  # fmt: skip
    return sum(d["cost"] for n, d in graph.nodes(data=True)
               if n[0] == "call" and d["ok"] and TOOL_SOURCE.get(d["tool"]) in SOURCES and n not in cited)  # fmt: skip


def diagnose(desk: Desk) -> str:
    verdict = desk.verdict()
    if verdict.get("correct"):
        return "none"
    d = desk.decision
    cited = _cited(d)
    if d and ((cited - {"questionnaire"}) - desk.consulted() or "questionnaire" in cited):
        return "grounding"
    if d and "P6" in verdict["reason"]:
        return "knowledge"
    ok = {a.tool for a in desk.log if a.ok}
    owners = bool(ok & {"gleif_parent", "ch_control", "quezal_holders"})
    lists = bool(ok & {"sanctions_search", "watchlist_search"})
    news = "gazette" in ok or desk.request.country.upper() != "QZ"
    if not (owners and lists and news):
        return "retrieval"
    return "reasoning"


FIXES = {"grounding": "constraint", "knowledge": "prompt", "retrieval": "retrieval", "reasoning": "fine-tune",
         "none": "none"}  # fmt: skip


def choose_fix(diagnosis: str) -> str:
    return FIXES[diagnosis]


def safe_to_ship(before: dict[str, bool], after: dict[str, bool], max_forgetting: int = 0) -> bool:
    forgotten = sum(1 for rid, ok in before.items() if ok and not after.get(rid, False))
    return sum(after.values()) > sum(before.values()) and forgotten <= max_forgetting
