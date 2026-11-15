"""Agent 3 · What we cleared before: a reference solution. Spoilers: `trail use-reference d3` copies it."""

from __future__ import annotations

import json
from typing import Any

import networkx as nx

from trail.desk import Desk, Request
from trail.llm import Conversation
from trail.registers import Registers
from trail.requests import load_history


def new_memory() -> nx.MultiDiGraph:
    return nx.MultiDiGraph()


def remember(memory: nx.MultiDiGraph, fact: dict, valid_from: str, recorded_at: str) -> None:
    """A fact is an edge from subject to object; both of its dates and its source sit on the edge."""
    memory.add_edge(fact["subject"], fact["object"], predicate=fact["predicate"], value=fact.get("value"),
                    source=fact.get("source", ""), valid_from=valid_from, recorded_at=recorded_at)  # fmt: skip


def _current(memory, company: str, valid_at: str, known_at: str) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if company not in memory:
        return latest
    for holder, _, d in memory.in_edges(company, data=True):
        if d["predicate"] != "holds" or d["valid_from"] > valid_at or d["recorded_at"] > known_at:
            continue
        best = latest.get(holder)
        if best is None or (d["valid_from"], d["recorded_at"]) > (best["valid_from"], best["recorded_at"]):
            latest[holder] = d
    return latest


def believed(memory, company: str, valid_at: str, known_at: str) -> dict[str, float]:
    return {h: d["value"] for h, d in _current(memory, company, valid_at, known_at).items() if d["value"]}


def why(memory, company: str, valid_at: str, known_at: str) -> list[str]:
    return sorted({d["source"] for d in _current(memory, company, valid_at, known_at).values() if d["value"]})


def stale(history: list[dict], regs: Registers) -> list[str]:
    q, truth = regs.quezal, regs.quezal.truth or {}
    memory = new_memory()
    for h in q.holdings:
        remember(memory, {"subject": h.holder_id, "predicate": "holds", "object": h.company_id, "value": h.percent,
                          "source": "register"}, h.since, q.snapshot)  # fmt: skip
    changes: dict[str, list[str]] = {}
    for g in truth.get("articles", {}).values():
        c = g["claim"]
        if c["kind"] in ("stake", "rename"):
            changes.setdefault(c["company"], []).append(c["date"])
    out = []
    for h in history:
        c, day = h["entity"], h["decided_on"]
        then = believed(memory, c, day, q.snapshot)
        now = believed(memory, c, q.snapshot, q.snapshot)
        if then != now or any(d > day for d in changes.get(c, [])):
            out.append(h["id"])
    return out


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


SYSTEM = """You are a compliance analyst screening a supplier. Every lookup costs credits. Before you look
anything up, ask `past_decisions` whether we screened this company before: an old approval is a starting
point, not an answer, because owners change. Check what changed since, then decide."""


def screen(request: Request, llm: Any) -> Desk:
    desk = Desk(request)
    history = load_history()
    extra = [{"name": "past_decisions", "description": "Our earlier decisions about a company, by its id or name. Free.",
              "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
                             "additionalProperties": False}}]  # fmt: skip

    def run(name: str, args: dict) -> Any:
        if name == "past_decisions":
            q = str(args.get("query", "")).lower()
            return [h for h in history if q and (q == h["entity"].lower() or q in h["name"].lower())]
        return desk.call(name, args)

    convo = Conversation(llm, desk.tools() + extra, system=SYSTEM)
    turn = convo.send(f"Screen this supplier: {request.name} ({request.country}), a contract of £{request.value:,}.")
    for _ in range(30):
        if turn.done or desk.decision is not None:
            break
        results = {c.id: run(c.name, c.arguments) for c in turn.tool_calls}
        if desk.decision is not None:
            break
        turn = convo.reply({k: v if isinstance(v, str) else json.dumps(v) for k, v in results.items()},
                           errors={k for k, v in results.items() if isinstance(v, dict) and "error" in v})  # fmt: skip
    return desk
