"""Checks for milestone 1, who owns whom."""

from __future__ import annotations

from types import ModuleType

from .. import answers
from ..registers import load
from .core import NotStarted, Result, attempt, tally

KS = (5, 10, 25, 50, 100)
VECTOR_GROUPS = ("213800LH1BZH3DI6G760", "549300LCJ1UJXHYBWI24", "353800V2V8PUY9TK3E06", "549300WSX3VBUFFJOO66")

L_SILOS = ("graphrag", "data-silos", "Data silos")
L_GRAPH = ("graphrag", "what-is-a-graph", "What is a graph?")
L_VECTOR = ("graphrag", "knowledge-graph-vs-vector-database", "Knowledge graph vs vector database")


def groups_to_check(regs) -> list[str]:
    """Every group's top, plus every entity in the middle of a chain with at least three below it."""
    tops = sorted({answers.ultimate_parent(regs, x) for x in regs.gleif})
    middles = sorted(x for x in regs.gleif if x not in tops and len(answers.group(regs, x)) >= 4)
    return tops + middles


def run(module: ModuleType) -> list[Result]:
    regs = load()
    summary = Result("Every register is in the graph", L_SILOS)
    top = Result("The top of every chain", L_GRAPH)
    grp = Result("Everything under a parent", L_GRAPH)
    loop = Result("Ownership loops", L_GRAPH)
    vector = Result("The vector search baseline", L_VECTOR)
    results = [summary, top, grp, loop, vector]
    try:
        graph = attempt(summary, module.build_graph, regs)
    except NotStarted:
        for r in results:
            r.started = r.passed = False
        return results

    try:  # 1. the counts
        got = attempt(summary, module.graph_summary, graph) if graph is not None else None
        want = answers.graph_summary(regs)
        if got is not None:
            right = 0
            for key, value in want.items():
                right += got.get(key) == value
                if got.get(key) != value:
                    summary.fail(f"{key}: {got.get(key)}, want {value}")
            tally(summary, right, len(want), "counts")
    except NotStarted:
        summary.started = summary.passed = False

    try:  # 2. the top of every chain
        right = 0
        for lei in sorted(regs.gleif):
            got = attempt(top, module.ultimate_parent, graph, lei)
            want = answers.ultimate_parent(regs, lei)
            right += got == want
            if got != want and got is not None:
                top.fail(f"{regs.gleif[lei].legal_name}: {got}, want {want} ({regs.gleif[want].legal_name})")
        tally(top, right, len(regs.gleif), "entities")
        disagree = answers.gleif_disagreements(regs)
        top.notes.append(f"GLEIF's own ultimate-parent records name a different top for {len(disagree)} of them. "
                         "The milestone page asks you why.")  # fmt: skip
    except NotStarted:
        top.started = top.passed = False

    try:  # 3. everything under a parent
        leis = groups_to_check(regs)
        right = 0
        for lei in leis:
            got = attempt(grp, module.group, graph, lei)
            want = answers.group(regs, lei)
            ok = got is not None and set(got) == want
            right += ok
            if not ok and got is not None:
                grp.fail(f"{regs.gleif[lei].legal_name}: {len(set(got) - want)} extra, {len(want - set(got))} missing")
        tally(grp, right, len(leis), "groups")
    except NotStarted:
        grp.started = grp.passed = False

    try:  # 4. loops
        got = attempt(loop, module.ownership_loops, graph)
        if got is not None:
            mine = {answers.canonical_loop(list(c)) for c in got}
            want = answers.loops(regs)
            for c in sorted(want - mine):
                loop.fail(f"missing loop: {' → '.join(c)}")
            for c in sorted(mine - want):
                loop.fail(f"not a loop in the registers: {' → '.join(c)}")
            tally(loop, len(want & mine), len(want), "loops") if mine <= want else tally(loop, 0, len(want), "loops")
    except NotStarted:
        loop.started = loop.passed = False

    try:  # 5. a vector search asked for a whole group
        rows = []
        for lei in VECTOR_GROUPS:
            want, line = answers.group(regs, lei), []
            for k in KS:
                got = attempt(vector, module.vector_group, regs, lei, k)
                if got is None:
                    break
                hit = len(set(got) & want)
                line.append(f"{hit / len(got) if got else 0:.2f}/{hit / len(want):.2f}")
            rows.append((regs.gleif[lei].legal_name, line))
        if any(len(line) < len(KS) for _, line in rows):
            vector.passed = False
        if vector.passed:
            vector.score = f"ran on {len(VECTOR_GROUPS)} groups"
            vector.notes.append("precision/recall at k = " + ", ".join(str(k) for k in KS))
            for name, line in rows:
                vector.notes.append(f"{name[:28]:28}  " + "  ".join(line))
    except NotStarted:
        vector.started = vector.passed = False
    return results
