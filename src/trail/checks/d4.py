"""Checks for agent 4, one branch per owner."""

from __future__ import annotations

from types import ModuleType

from ..desk import DECISIONS, SOURCE_WORDS, Desk
from ..requests import load_requests
from .agent import needs_llm, run_pack, summary
from .core import NotStarted, Result, attempt, tally

L_RELIABLE = ("agentic-graphrag", "agent-reliability", "Agent reliability")
L_WORKFLOW = ("agentic-graphrag", "agent-workflow-graph", "Agent workflow graphs")
L_OUTPUT = ("agentic-graphrag", "structured-output", "Structured output for agents")
L_PLANNING = ("agentic-graphrag", "agent-planning", "Agent planning")
DESK_TOOLS = set(Desk.COSTS) - {"decide"}
PROBLEMS = ("bad-decision", "unknown-entity", "too-few-sources", "unconsulted-source", "questionnaire-cited",
            "stakes-over-100", "approve-without-list")  # fmt: skip


def official_phases(steps):
    done, left, out = set(), {s["id"]: set(s.get("needs", [])) for s in steps}, []
    while left:
        ready = sorted(i for i, n in left.items() if n <= done)
        if not ready:
            return None
        out.append(ready)
        done |= set(ready)
        for i in ready:
            del left[i]
    return out


def official_problems(desk: Desk, d: dict) -> list[str]:
    regs, found = desk.regs, set()
    if d.get("decision") not in DECISIONS:
        found.add("bad-decision")
    e = (d.get("entity") or "").strip()
    if e and e not in regs.gleif and e not in regs.companies and e not in regs.quezal.companies:
        found.add("unknown-entity")
    text = " ".join(d.get("reasons", [])).lower()
    cited = {k for k, words in SOURCE_WORDS.items() if any(w in text for w in words)}
    if not {"register", "list"} <= cited:
        found.add("too-few-sources")
    if (cited - {"questionnaire"}) - desk.consulted():
        found.add("unconsulted-source")
    if "questionnaire" in cited:
        found.add("questionnaire-cited")
    if sum(float(o.get("percent") or 0) for o in d.get("owners", [])) > 100.0001:
        found.add("stakes-over-100")
    if d.get("decision") == "approve" and "list" not in desk.consulted():
        found.add("approve-without-list")
    return [p for p in PROBLEMS if p in found]


def run(module: ModuleType) -> list[Result]:
    compound = Result("Small errors compound", L_RELIABLE)
    planned = Result("A plan that's a workflow graph", L_PLANNING)
    fanned = Result("One branch per owner, side by side", L_WORKFLOW)
    meaning = Result("Meaning checks before the decision", L_OUTPUT)
    agent = Result("The planned screening", L_WORKFLOW)
    for check, r in ((_compound, compound), (_plan, planned), (_fan, fanned), (_meaning, meaning)):
        try:
            check(module, r)
        except NotStarted:
            r.started = r.passed = False
    llm = needs_llm(agent)
    if llm is not None:
        try:
            runs = run_pack(agent, module.screen, "practice", llm)
            decided, accepted, correct, credits = summary(runs)
            agent.score = f"{decided}/6 decided, {accepted} accepted, {correct} correct, {credits} credits"
            if decided < 6:
                agent.fail("Every practice request must end in a decision.")
        except NotStarted:
            agent.started = agent.passed = False
    return [compound, planned, fanned, meaning, agent]


def _compound(module, r: Result) -> None:
    fixtures = [((0.95, 20), 0.95**20), ((0.99, 100), 0.99**100), ((1.0, 50), 1.0), ((0.9, 1), 0.9)]
    right = 0
    for args, want in fixtures:
        got = attempt(r, module.compound_success, *args)
        ok = got is not None and abs(got - want) < 1e-9
        right += ok
        if not ok:
            r.fail(f"compound_success{args} = {got}, want {want:.4f}")
    tally(r, right, len(fixtures), "fixtures")


def _plan(module, r: Result) -> None:
    steps = attempt(r, module.plan, load_requests("practice")[0])
    if steps is None:
        return
    ids = [s.get("id") for s in steps]
    problems = []
    if len(ids) != len(set(ids)):
        problems.append("two steps share an id")
    if any(n not in ids for s in steps for n in s.get("needs", [])):
        problems.append("a step needs a step that doesn't exist")
    if official_phases(steps) is None:
        problems.append("the plan has a cycle")
    if not {"owners", "decide"} <= set(ids):
        problems.append('the plan needs steps "owners" and "decide"')
    kinds = {s.get("kind") for s in steps}
    if not {"reasoning", "execution", "decision", "validation"} <= kinds:
        problems.append(
            f"missing kinds of step: {sorted({'reasoning', 'execution', 'decision', 'validation'} - kinds)}"
        )
    for s in steps:
        tools = s.get("tools", [])
        if s.get("kind") != "execution" and tools:
            problems.append(f"{s['id']}: only execution steps hold tools")
        if len(tools) > 2:
            problems.append(f"{s['id']}: {len(tools)} tools; keep execution steps narrow (two at most)")
        if set(tools) - DESK_TOOLS:
            problems.append(f"{s['id']}: unknown tools {sorted(set(tools) - DESK_TOOLS)}")
    for p in problems:
        r.fail(p)
    r.score = f"{len(steps)} steps, {len(problems)} problems"


def _fan(module, r: Result) -> None:
    owners = ["QZ-111111", "QZ-222222", "QZ-333333"]
    fixtures = [
        [{"id": "a", "needs": []}, {"id": "b", "needs": ["a"]}, {"id": "c", "needs": ["a"]}, {"id": "d", "needs": ["b", "c"]}],
        [{"id": "x", "needs": []}, {"id": "y", "needs": []}, {"id": "z", "needs": []}],
        [{"id": "s3", "needs": ["s2"]}, {"id": "s2", "needs": ["s1"]}, {"id": "s1", "needs": []}],
    ]  # fmt: skip
    right = total = 0
    try:
        mine = attempt(r, module.plan, load_requests("practice")[0])
        if mine and official_phases(mine) is not None:
            fixtures.append(mine)
            wide = attempt(r, module.expand, mine, owners)
            if wide is not None:
                total += 1
                branches = [s for s in wide if str(s.get("id", "")).startswith("owner:")]
                decide = next((s for s in wide if s.get("id") == "decide"), {})
                order = official_phases(wide) or []
                where = {i: n for n, phase in enumerate(order) for i in phase}
                ok = (len(branches) == 3 and all(b.get("needs") == ["owners"] for b in branches)
                      and {b["id"] for b in branches} <= set(decide.get("needs", []))
                      and len({where.get(b["id"]) for b in branches}) == 1
                      and where.get("decide", -1) > where.get(branches[0]["id"], 99) if branches else False)  # fmt: skip
                right += ok
                if not ok:
                    r.fail(
                        "expand: three owner steps that need 'owners', side by side in one phase, all before 'decide'"
                    )
                fixtures.append(wide)
    except NotStarted:
        pass
    for steps in fixtures:
        total += 1
        got = attempt(r, module.phases, steps)
        want = official_phases(steps)
        right += got == want
        if got != want:
            r.fail(f"phases of {[s['id'] for s in steps]}: {got}, want {want}")
    tally(r, right, total, "plans")


def _meaning(module, r: Result) -> None:
    right = total = 0
    for name, full in (("practice", True), ("standard", False)):
        request = next(q for q in load_requests(name) if q.country == "QZ")
        desk = Desk(request)
        hits = desk.call("search", {"name": request.name, "country": "QZ"})
        cid = hits[0]["id"]
        desk.call("quezal_holders", {"id": cid})
        if full:
            desk.call("watchlist_search", {"name": request.name})
        both = ["Quezal register: the shareholders are known.", "Watch list: not listed."]
        fixtures = [
            {"decision": "approve", "entity": cid, "reasons": both, "owners": [{"id": "QP-1", "percent": 60}]},
            {"decision": "maybe", "entity": cid, "reasons": both, "owners": []},
            {"decision": "reject", "entity": "QZ-000000", "reasons": both, "owners": []},
            {"decision": "escalate", "entity": cid, "reasons": ["Quezal register: unclear."], "owners": []},
            {"decision": "reject", "entity": cid, "reasons": both + ["The Gazette reports a sale."], "owners": []},
            {"decision": "approve", "entity": cid, "reasons": both + ["The questionnaire says it's independent."], "owners": []},
            {"decision": "escalate", "entity": cid, "reasons": both, "owners": [{"id": "QZ-1", "percent": 70}, {"id": "QZ-2", "percent": 45}]},
        ]  # fmt: skip
        for d in fixtures:
            total += 1
            got = attempt(r, module.validate_decision, desk, d)
            want = official_problems(desk, d)
            right += got == want
            if got != want and got is not None:
                r.fail(f"{name} · {d['decision']}, {len(d['reasons'])} reasons: {got}, want {want}")
    tally(r, right, total, "decisions")
