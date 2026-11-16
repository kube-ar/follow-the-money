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


KEYS = ("match", "table", "key", "identify", "context")


def spec_problems(spec, tables: dict[str, list[dict]]) -> list[str]:
    """What's wrong with a SPEC's shape: five keys per entry, and tables and columns that exist."""
    if not isinstance(spec, dict) or not spec:
        return ["SPEC has no entries: one per kind of record, each with the keys match, table, key, identify and "
                "context, like the Entity entry the file starts with"]  # fmt: skip
    out = []
    for name, t in spec.items():
        if not isinstance(t, dict) or set(t) != set(KEYS):
            have = sorted(t) if isinstance(t, dict) else type(t).__name__
            out.append(f"SPEC[{name!r}] has {have}: every entry has exactly the keys match, table, key, identify and "
                       "context (see the Entity entry)")  # fmt: skip
            continue
        try:
            re.compile(t["match"])
        except (re.error, TypeError):
            out.append(f"SPEC[{name!r}]['match'] isn't a regex")
        if not isinstance(t["table"], str) or t["table"] not in tables:
            out.append(f"SPEC[{name!r}]['table'] is {t['table']!r}: one of {sorted(tables)}")
            continue
        columns = set(tables[t["table"]][0]) if tables[t["table"]] else set()
        fields = [t["key"], *t["identify"]] if isinstance(t["identify"], (list, tuple)) else []
        if not t["identify"] or not fields or not all(isinstance(f, str) for f in fields):
            out.append(f"SPEC[{name!r}]: 'key' is a column name and 'identify' a list of at least one column name")
        elif columns and not set(fields) <= columns:
            out.append(f"SPEC[{name!r}]: {t['table']} has no column {sorted(set(fields) - columns)[0]!r} "
                       f"(it has {sorted(columns)})")  # fmt: skip
        if not isinstance(t["context"], dict):
            out.append(
                f"SPEC[{name!r}]['context'] maps a name to [table, their column, our column, the column to list]"
            )
            continue
        for rel, link in t["context"].items():
            ok = (isinstance(link, (list, tuple)) and len(link) == 4 and all(isinstance(x, str) for x in link)
                  and link[0] in tables)  # fmt: skip
            theirs = set(tables[link[0]][0]) if ok and tables[link[0]] else set()
            if not ok or (theirs and not {link[1], link[3]} <= theirs) or (columns and link[2] not in columns):
                out.append(f"SPEC[{name!r}]['context'][{rel!r}] is {link!r}: [table, their column, our column, the "
                           "column to list], with tables and columns from trail.desk.records(regs)")  # fmt: skip
    return out


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
    spec = getattr(module, "SPEC", None)
    problems = spec_problems(spec, records(regs))
    if problems:  # the official reading below needs these keys: say what's missing instead of failing inside it
        for p in problems:
            r.fail(p)
        r.score = f"SPEC: {len(problems)} problems"
        return
    spec = dict(spec)
    q = regs.quezal
    ids = ["213800LH1BZH3DI6G760", "5493008CGNE47EJ89474", sorted(regs.companies)[0], sorted(q.companies)[0],
           q.truth["schemes"][0]["target"], sorted(q.people)[0], "RUS3094", "X-404"]  # fmt: skip
    right = total = 0
    for node_id in ids:
        total += 1
        got = attempt(r, module.describe, regs, node_id, spec)
        want = official_describe(regs, node_id, spec)
        if "error" in want and node_id != "X-404":  # every kind of record here needs an entry in SPEC
            r.fail(f"describe({node_id!r}): no entry in SPEC matches this kind of record")
            continue
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
