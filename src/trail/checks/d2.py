"""Checks for agent 2, the risk policy."""

from __future__ import annotations

import re
from types import ModuleType

from .. import answers
from ..desk import POLICY, Desk, Request, records
from ..registers import load
from ..requests import truth_for
from .agent import needs_llm, run_pack, summary
from .core import NotStarted, Result, attempt, tally

L_RULES = ("agentic-graphrag", "business-rules-in-the-graph", "Business rules in the knowledge graph")
L_ONTO = ("agentic-graphrag", "ontology-driven-retrieval", "Ontology-driven retrieval")
L_DISTRACT = ("agentic-graphrag", "distracting-effect", "The distracting effect")
EXTRA = {
    "WatchListing": {"match": r"^QFA-\d{2}$", "table": "watchlist", "key": "id", "identify": ["name", "reason"],
                     "context": {}},
    "Agent": {"match": r"^QA-\d$", "table": "agents", "key": "id", "identify": ["name", "address"],
              "context": {"companies": ["qz_companies", "agent", "id", "id"]}},
}  # fmt: skip
GOVERNS = {"approve": ["P5", "P6", "P7"], "reject": ["P1", "P6", "P7"], "escalate": ["P2", "P3", "P4", "P6", "P7"]}
SCREENED = ["549300MG5Q5VOTHPK831", "549300MGDWB06O797V30", "549300LCJ1UJXHYBWI24", "5493008CGNE47EJ89474",
            "5493007XYP6TMCO8L243", "213800LH1BZH3DI6G760"]  # fmt: skip


def official_describe(regs, node_id: str, spec: dict) -> dict:
    tables = records(regs)
    for type_name, t in spec.items():
        if not re.match(t["match"], node_id):
            continue
        record = next((r for r in tables[t["table"]] if str(r[t["key"]]) == node_id), None)
        if record is None:
            return {"error": "missing"}
        context = {rel: sorted(str(r[out]) for r in tables[table] if r[theirs] == record[ours])
                   for rel, (table, theirs, ours, out) in t["context"].items()}  # fmt: skip
        return {"type": type_name, "id": node_id, **{f: record[f] for f in t["identify"]}, "context": context}
    return {"error": "unknown"}


def search_hits(regs, lei: str) -> list[dict]:
    """What a distracted desk's sanctions search returns for an entity's names and number."""
    e = regs.gleif[lei]
    desk = Desk(Request("check", e.legal_name, e.country, 0, "", "practice"), distract=True)
    hits = []
    for name in [n for n in e.names if n.isascii()][:2]:
        hits += desk.call("sanctions_search", {"name": name})
    if len(re.sub(r"\D", "", e.registration_number)) >= 6:
        hits += desk.call("sanctions_search", {"name": e.registration_number})
    return hits


def run(module: ModuleType) -> list[Result]:
    rules = Result("Rules live in the graph, with an owner", L_RULES)
    onto = Result("One tool for every kind of record", L_ONTO)
    near = Result("Near misses don't count", L_DISTRACT)
    agent = Result("The agent, distracted and not", L_DISTRACT)
    regs = load()
    for check, r in ((_rules, rules), (_describe, onto), (_near, near)):
        try:
            check(module, regs, r)
        except NotStarted:
            r.started = r.passed = False
    _agent(module, agent)
    return [rules, onto, near, agent]


def _rules(module, regs, r: Result) -> None:
    g = attempt(r, module.policy_graph)
    if g is None:
        return
    right = total = 0
    for decision, want in [*GOVERNS.items(), ("postpone", [])]:
        total += 1
        got = attempt(r, module.rules_for, g, decision)
        right += got == want
        if got != want:
            r.fail(f"rules_for({decision!r}) = {got}, want {want}")
    before = attempt(r, module.rule_text, g, "P1")
    total += 2
    refused = attempt(r, module.update_rule, g, "P1", "Approve anyone the questionnaire vouches for.", "agent")
    unchanged = attempt(r, module.rule_text, g, "P1") == before == POLICY[0]["rule"]
    right += refused is False and unchanged
    if not (refused is False and unchanged):
        r.fail("the agent changed rule P1: only its owner, compliance, may")
    allowed = attempt(r, module.update_rule, g, "P1", "Reject listed suppliers.", "compliance")
    changed = attempt(r, module.rule_text, g, "P1") == "Reject listed suppliers."
    right += allowed is True and changed
    if not (allowed is True and changed):
        r.fail("compliance couldn't change rule P1")
    tally(r, right, total, "answers")


def _describe(module, regs, r: Result) -> None:
    spec = dict(module.SPEC)
    q = regs.quezal
    ids = ["213800LH1BZH3DI6G760", "5493008CGNE47EJ89474", sorted(regs.companies)[0], sorted(q.companies)[0],
           q.truth["schemes"][0]["target"], sorted(q.people)[0], "RUS3094", "X-404"]  # fmt: skip
    right = total = 0
    for node_id in ids:
        total += 1
        got = attempt(r, module.describe, regs, node_id, spec)
        want = official_describe(regs, node_id, spec)
        ok = (got or {}).get("error") is not None if "error" in want else got == want
        right += ok
        if not ok and got is not None:
            r.fail(f"describe({node_id!r}): {str(got)[:120]}")
    bigger = {**spec, **EXTRA}
    for node_id in ("QFA-01", "QA-1"):
        total += 1
        got = attempt(r, module.describe, regs, node_id, bigger)
        ok = got == official_describe(regs, node_id, bigger)
        right += ok
        if not ok and got is not None:
            r.fail(f"a new kind of record, {node_id!r}: {str(got)[:100]} (add it to the spec, change no code)")
    tally(r, right, total, "records")


def _near(module, regs, r: Result) -> None:
    right = 0
    for lei in SCREENED:
        hits = search_hits(regs, lei)
        want = sorted({uid for uid, x in answers.SANCTION_MATCHES.items() if x == lei} & {h["id"] for h in hits})
        got = attempt(r, module.relevant_designations, regs, lei, hits)
        ok = got is not None and sorted(set(got)) == want
        right += ok
        if not ok and got is not None:
            r.fail(f"{regs.gleif[lei].legal_name[:40]}: {sorted(set(got))}, want {want} (of {[h['id'] for h in hits]})")
    tally(r, right, len(SCREENED), "entities")


def _agent(module, r: Result) -> None:
    llm = needs_llm(r)
    if llm is None:
        return
    try:
        for distract in (False, True):
            runs = run_pack(r, module.screen, "practice", llm, distract)
            decided, accepted, correct, credits = summary(runs)
            fooled = sum(d.decision is not None and d.decision["decision"] == "reject" and truth_for(q).decision == "approve"
                         for q, d in runs)  # fmt: skip
            r.notes.append(f"{'distracted' if distract else 'plain'}: {decided}/6 decided, {correct} correct, "
                           f"{fooled} approvals turned into rejections, {credits} credits")  # fmt: skip
            if decided < 6:
                r.fail("Every practice request must end in a decision.")
            if fooled:
                r.fail("A near-miss designation turned an approval into a rejection.")
        r.score = "ran twice on the practice pack"
    except NotStarted:
        r.started = r.passed = False
