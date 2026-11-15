"""Checks for agent 8, the final batch."""

from __future__ import annotations

from types import ModuleType

from .agent import needs_llm, run_pack, summary
from .core import NotStarted, Result, attempt, tally

L_END = ("agentic-graphrag", "agentic-graphrag-end-to-end", "Agentic GraphRAG end to end")


def run(module: ModuleType) -> list[Result]:
    table = Result("Which pieces carry the decisions", L_END)
    hard = Result("Your best agent on the hard pack", L_END)
    final = Result("Your best agent on the final batch", L_END)
    try:
        fixtures = [
            ({"full": 0.75, "without memory": 0.5, "without policy": 0.75, "without plan": 0.25},
             [("plan", 0.5), ("memory", 0.25)]),
            ({"full": 0.5, "without gate": 0.5}, []),
            ({"full": 1.0, "without b": 0.5, "without a": 0.5}, [("a", 0.5), ("b", 0.5)]),
        ]  # fmt: skip
        right = 0
        for scores, want in fixtures:
            got = attempt(table, module.ablation, scores)
            ok = got is not None and [(p, round(d, 6)) for p, d in got] == want
            right += ok
            if not ok:
                table.fail(f"ablation({scores}) = {got}, want {want}")
        tally(table, right, len(fixtures), "tables")
    except NotStarted:
        table.started = table.passed = False
    llm = needs_llm(hard)
    if llm is None:
        final.started = final.passed = False
        final.notes = list(hard.notes)
        return [table, hard, final]
    for r, pack, n in ((hard, "hard", 12), (final, "final", 8)):
        try:
            runs = run_pack(r, module.screen, pack, llm)
            decided, accepted, correct, credits = summary(runs)
            r.score = f"{decided}/{n} decided, {accepted} accepted, {correct} correct, {credits} credits"
            if decided < n:
                r.fail(f"Every request in the {pack} pack must end in a decision.")
            if pack == "final":
                r.notes.append("The final batch's decisions are hashed: you learn how many were right, never which.")
        except NotStarted:
            r.started = r.passed = False
    return [table, hard, final]
