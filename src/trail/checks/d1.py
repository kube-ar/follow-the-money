"""Checks for agent 1, the first screening."""

from __future__ import annotations

from types import ModuleType

from ..desk import Desk
from ..requests import load_requests
from .agent import needs_llm, run_pack, summary
from .core import NotStarted, Result, attempt, tally

L_WHAT = ("agentic-graphrag", "what-is-agentic-graphrag", "What is agentic GraphRAG?")
L_GRAPHS = ("agentic-graphrag", "knowledge-graph-and-workflow-graph", "Knowledge graph and workflow graph")
FAILURES = ("context amnesia", "relationship blindness", "temporal ignorance", "reasoning paralysis", "tool chaos")


def official(desk: Desk) -> list[str]:
    calls = [a for a in desk.log if a.ok]
    keys = [(a.tool, tuple(sorted((k, str(v)) for k, v in a.arguments.items()))) for a in calls]
    found = set()
    if len(keys) != len(set(keys)):
        found.add("context amnesia")
    if not any(a.tool in ("gleif_parent", "ch_control", "quezal_holders") for a in calls):
        found.add("relationship blindness")
    if desk.request.country.upper() == "QZ" and not any(a.tool == "gazette" for a in calls):
        found.add("temporal ignorance")
    if desk.decision is None:
        found.add("reasoning paralysis")
    if sum(not a.ok for a in desk.log) >= 3:
        found.add("tool chaos")
    return [f for f in FAILURES if f in found]


def scripted() -> dict[str, Desk]:
    """Runs on a Quezal request: one clean, one per failure, one with all five."""
    request = next(r for r in load_requests("practice") if r.country == "QZ")
    good = ["Quezal register: holders checked.", "Watch list and sanctions list checked: not listed."]

    def run(steps: list[tuple[str, dict]], decide: bool = True) -> Desk:
        d = Desk(request)
        for tool, args in steps:
            d.call(tool, args)
        if decide:
            d.call("decide", {"decision": "approve", "entity": "QZ-000000", "reasons": good})
        return d

    found = Desk(request).call("search", {"name": request.name, "country": "QZ"})
    cid = found[0]["id"] if found else "QZ-000000"
    base = [("search", {"name": request.name, "country": "QZ"}), ("quezal_holders", {"id": cid}),
            ("watchlist_search", {"name": request.name}), ("sanctions_search", {"name": request.name}),
            ("gazette", {"name": request.name})]  # fmt: skip
    bad = [("quezal_holders", {"id": "nope"}), ("ch_company", {"number": "x"}), ("teleport", {})]
    return {
        "clean": run(base),
        "amnesia": run(base + [base[0]]),
        "blindness": run([s for s in base if s[0] != "quezal_holders"]),
        "temporal": run(base[:-1]),
        "paralysis": run(base, decide=False),
        "chaos": run(base + bad),
        "all five": run([base[0], base[0], base[2]] + bad, decide=False),
    }


def run(module: ModuleType) -> list[Result]:
    named = Result("Failures, named", L_WHAT)
    works = Result("The first agent screens a request", L_GRAPHS)
    try:
        runs = scripted()
        right = 0
        for label, desk in runs.items():
            got = attempt(named, module.failures, desk)
            want = official(desk)
            right += got == want
            if got != want and got is not None:
                named.fail(f"{label}: {got}, want {want}")
        tally(named, right, len(runs), "runs")
    except NotStarted:
        named.started = named.passed = False
    llm = needs_llm(works)
    if llm is not None:
        try:
            runs = run_pack(works, module.screen, "practice", llm)
            decided, accepted, correct, credits = summary(runs)
            works.score = f"{decided}/6 decided, {accepted} accepted, {correct} correct, {credits} credits"
            for request, desk in runs:
                works.notes.append(f"{request.id}: {', '.join(official(desk)) or 'no failure named'}")
            if decided < 6:
                works.fail("Every practice request must end in a decision.")
        except NotStarted:
            works.started = works.passed = False
    return [named, works]
