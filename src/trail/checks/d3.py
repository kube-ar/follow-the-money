"""Checks for agent 3, what we cleared before."""

from __future__ import annotations

from types import ModuleType

from ..registers import load
from ..requests import load_history, stale_decisions
from .agent import needs_llm, run_pack, summary
from .core import NotStarted, Result, attempt, tally

L_MEMORY = ("agentic-graphrag", "graph-memory", "Graph memory")
L_RETRIEVAL = ("agentic-graphrag", "memory-retrieval", "Memory retrieval")
L_CONTEXT = ("agentic-graphrag", "context-graph", "Context graph")
L_WHY = ("agentic-graphrag", "agent-memory", "Agent memory")

# A small history, told the way the registers and the Gazette tell it.
FACTS = [
    ({"subject": "QZ-A", "predicate": "holds", "object": "QZ-X", "value": 60.0, "source": "register"}, "2026-01-01", "2026-01-05"),
    ({"subject": "QP-B", "predicate": "holds", "object": "QZ-X", "value": 40.0, "source": "register"}, "2026-01-01", "2026-01-05"),
    ({"subject": "QP-B", "predicate": "holds", "object": "QZ-X", "value": 0.0, "source": "gazette:G-007"}, "2026-07-10", "2026-07-12"),
    ({"subject": "QP-C", "predicate": "holds", "object": "QZ-X", "value": 40.0, "source": "gazette:G-007"}, "2026-07-10", "2026-07-12"),
    ({"subject": "QP-D", "predicate": "holds", "object": "QZ-Y", "value": 10.0, "source": "gazette:G-021"}, "2019-03-01", "2026-10-01"),
]  # fmt: skip
QUERIES = [
    (("QZ-X", "2026-06-01", "2026-06-01"), {"QZ-A": 60.0, "QP-B": 40.0}, ["register"]),
    (("QZ-X", "2026-08-01", "2026-07-01"), {"QZ-A": 60.0, "QP-B": 40.0}, ["register"]),
    (("QZ-X", "2026-08-01", "2026-08-01"), {"QZ-A": 60.0, "QP-C": 40.0}, ["gazette:G-007", "register"]),
    (("QZ-X", "2026-06-01", "2026-08-01"), {"QZ-A": 60.0, "QP-B": 40.0}, ["register"]),
    (("QZ-Y", "2025-01-01", "2026-09-01"), {}, []),
    (("QZ-Y", "2025-01-01", "2026-10-02"), {"QP-D": 10.0}, ["gazette:G-021"]),
]  # fmt: skip


def run(module: ModuleType) -> list[Result]:
    belief = Result("What we believed, and when", L_MEMORY)
    sources = Result("Why we believed it", L_WHY)
    past = Result("Past approvals gone stale", L_CONTEXT)
    fused = Result("Reciprocal rank fusion", L_RETRIEVAL)
    agent = Result("The agent remembers", L_MEMORY)
    try:
        memory = attempt(belief, module.new_memory)
        for fact, valid, recorded in FACTS:
            attempt(belief, module.remember, memory, dict(fact), valid, recorded, none_ok=True)
        right = right_why = 0
        for (company, valid, known), want, want_why in QUERIES:
            got = attempt(belief, module.believed, memory, company, valid, known)
            right += got == want
            if got != want and got is not None:
                belief.fail(f"believed({company}, valid {valid}, known {known}) = {got}, want {want}")
            got_why = attempt(sources, module.why, memory, company, valid, known)
            right_why += got_why == want_why
            if got_why != want_why and got_why is not None:
                sources.fail(f"why({company}, valid {valid}, known {known}) = {got_why}, want {want_why}")
        tally(belief, right, len(QUERIES), "questions")
        tally(sources, right_why, len(QUERIES), "questions")
    except NotStarted:
        belief.started = belief.passed = sources.started = sources.passed = False
    try:
        regs, history = load(), load_history()
        got = attempt(past, module.stale, history, regs)
        if got is not None:
            want = stale_decisions(regs, history)
            for x in sorted(set(want) - set(got)):
                past.fail(f"{x} is stale: its company changed after the decision")
            for x in sorted(set(got) - set(want)):
                past.fail(f"{x} still holds: nothing changed after it")
            tally(past, len(history) - len(set(want) ^ set(got)), len(history), "decisions")
    except NotStarted:
        past.started = past.passed = False
    try:
        _rrf(module, fused)
    except NotStarted:
        fused.started = fused.passed = False
    llm = needs_llm(agent)
    if llm is not None:
        try:
            runs = run_pack(agent, module.screen, "standard", llm)
            decided, accepted, correct, credits = summary(runs)
            agent.score = f"{decided}/12 decided, {accepted} accepted, {correct} correct, {credits} credits"
            if decided < 12:
                agent.fail("Every request in the standard pack must end in a decision.")
        except NotStarted:
            agent.started = agent.passed = False
    return [belief, sources, past, fused, agent]


def _rrf(module, r: Result) -> None:
    a, b, c = 1 / 61 + 1 / 62, 1 / 63, 1.0
    fixtures = [
        (([["a", "b", "c"], ["b", "a", "d"]], 60), [("a", a), ("b", a), ("c", b), ("d", b)]),
        (([["x"], ["x", "y"]], 1), [("x", c), ("y", 1 / 3)]),
        (([], 60), []),
    ]
    right = 0
    for (rankings, k), want in fixtures:
        got = attempt(r, module.rrf, rankings, k)
        ok = (got is not None and [x for x, _ in got] == [x for x, _ in want]
              and all(abs(s - t) < 1e-9 for (_, s), (_, t) in zip(got, want, strict=False)))  # fmt: skip
        right += ok
        if not ok:
            r.fail(f"rrf({rankings}, k={k}) = {got}, want {want}")
    tally(r, right, len(fixtures), "fixtures")
