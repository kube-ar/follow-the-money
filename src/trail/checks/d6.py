"""Checks for agent 6, decision review."""

from __future__ import annotations

from types import ModuleType

from ..desk import SOURCE_WORDS, TOOL_SOURCE, Desk
from ..requests import load_requests, truth_for
from .core import NotStarted, Result, attempt, tally

L_EXEC = ("agentic-graphrag", "execution-graph", "Execution graph")
L_DIAG = ("agentic-graphrag", "agent-failure-diagnosis", "Agent failure diagnosis")
L_EVOLVE = ("agentic-graphrag", "self-evolving-agents", "Self-evolving agents")
L_SAFE = ("agentic-graphrag", "safe-agent-evolution", "Safe agent evolution")
SOURCES = {k for k in TOOL_SOURCE.values() if k != "questionnaire"}


def scripted() -> dict[str, tuple[Desk, str]]:
    """Runs on a Quezal request the policy rejects, each ending a different way, with the diagnosis it deserves."""
    request = next(q for q in load_requests("practice") if q.country == "QZ" and truth_for(q).decision == "reject")
    entity = truth_for(request).entity
    good = [
        "Quezal register: a listed company controls it through two shareholders.",
        "Watch list: the controller is listed.",
    ]

    def gather(desk, owners=True, lists=True, news=True):
        desk.call("search", {"name": request.name, "country": "QZ"})
        if owners:
            desk.call("quezal_holders", {"id": entity})
        if lists:
            desk.call("watchlist_search", {"name": request.name})
        if news:
            desk.call("gazette", {"name": request.name})
        return desk

    runs = {}
    d = gather(Desk(request))
    d.call("decide", {"decision": "reject", "entity": entity, "reasons": good})
    runs["correct"] = (d, "none")
    d = gather(Desk(request), lists=False)
    d.call(
        "decide",
        {"decision": "reject", "entity": entity, "reasons": ["Register: owners checked.", "Sanctions list: listed."]},
    )
    runs["cites a list it never searched"] = (d, "grounding")
    d = gather(Desk(request))
    d.call("decide", {"decision": "reject", "entity": entity, "reasons": ["Quezal register: something is off."]})
    runs["one kind of source"] = (d, "knowledge")
    d = gather(Desk(request), owners=False)
    d.call(
        "decide",
        {"decision": "approve", "entity": entity, "reasons": ["Register: found it.", "Watch list: not listed."]},
    )
    runs["never asked who is above"] = (d, "retrieval")
    d = gather(Desk(request))
    d.call("decide", {"decision": "approve", "entity": entity, "reasons": good})
    runs["had it all, decided wrong"] = (d, "reasoning")
    runs["never decided"] = (gather(Desk(request)), "reasoning")
    return runs


def official_waste(desk: Desk) -> int:
    text = " ".join((desk.decision or {}).get("reasons", [])).lower()
    cited = {k for k, words in SOURCE_WORDS.items() if any(w in text for w in words)}
    return sum(
        a.cost for a in desk.log if a.ok and TOOL_SOURCE.get(a.tool) in SOURCES and TOOL_SOURCE[a.tool] not in cited
    )


def run(module: ModuleType) -> list[Result]:
    graph = Result("An execution graph you can query", L_EXEC)
    diag = Result("Four checks, in order", L_DIAG)
    fix = Result("The fix, chosen by code", L_EVOLVE)
    ship = Result("Ship only what doesn't forget", L_SAFE)
    runs = scripted()
    try:
        right = 0
        for label, (desk, _) in runs.items():
            g = attempt(graph, module.execution_graph, desk)
            got = attempt(graph, module.wasted_credits, g) if g is not None else None
            want = official_waste(desk)
            right += got == want
            if got != want and got is not None:
                graph.fail(f"{label}: wasted {got} credits, want {want}")
        tally(graph, right, len(runs), "runs")
    except NotStarted:
        graph.started = graph.passed = False
    try:
        right = 0
        for label, (desk, want) in runs.items():
            got = attempt(diag, module.diagnose, desk)
            right += got == want
            if got != want and got is not None:
                diag.fail(f"{label}: {got!r}, want {want!r}")
        tally(diag, right, len(runs), "runs")
    except NotStarted:
        diag.started = diag.passed = False
    try:
        want = {"grounding": "constraint", "knowledge": "prompt", "retrieval": "retrieval", "reasoning": "fine-tune",
                "none": "none"}  # fmt: skip
        right = sum(attempt(fix, module.choose_fix, d) == f for d, f in want.items())
        tally(fix, right, len(want), "diagnoses")
    except NotStarted:
        fix.started = fix.passed = False
    try:
        before = {"a": True, "b": True, "c": False, "d": False}
        fixtures = [({"a": True, "b": True, "c": True, "d": False}, 0, True),
                    ({"a": True, "b": False, "c": True, "d": True}, 0, False),
                    ({"a": True, "b": False, "c": True, "d": True}, 1, True),
                    ({"a": True, "b": True, "c": False, "d": False}, 0, False)]  # fmt: skip
        right = 0
        for after, limit, want_ok in fixtures:
            got = attempt(ship, module.safe_to_ship, before, after, limit)
            right += got is want_ok
            if got is not want_ok:
                ship.fail(f"safe_to_ship({after}, max_forgetting={limit}) = {got}, want {want_ok}")
        tally(ship, right, len(fixtures), "releases")
    except NotStarted:
        ship.started = ship.passed = False
    return [graph, diag, fix, ship]
