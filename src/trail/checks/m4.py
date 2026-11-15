"""Checks for milestone 4, effective ownership."""

from __future__ import annotations

from collections import defaultdict
from types import ModuleType

import networkx as nx

from .. import answers
from ..registers import Registers, load
from .core import NotStarted, Result, attempt, tally

L_DB = ("graphrag", "choosing-a-graph-database", "Graph database or PostgreSQL?")
L_PATTERNS = ("graphrag", "graph-retrieval-patterns", "GraphRAG retrieval patterns")
L_ENRICH = ("graphrag", "graph-enrichment", "Graph enrichment")
L_METHODS = ("graphrag", "graphrag-methods-compared", "GraphRAG methods compared")

BAD_QUERIES = [
    "MATCH (n) DETACH DELETE n",
    "MATCH (c:Company) SET c.name = 'nobody' RETURN c LIMIT 10",
    "CREATE (x:Company {id: 'QZ-000000'}) RETURN x LIMIT 1",
    "MATCH (c:Company) RETURN c",
    "MATCH (c:Company) RETURN c LIMIT 100000",
    "MATCH (s:Spaceship) RETURN s LIMIT 5",
    "MATCH (c:Company)-[:OWNS_YACHT]->(y) RETURN c LIMIT 5",
    "CALL dbms.components() YIELD name RETURN name LIMIT 1",
    "LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row LIMIT 1",
]


def official_counts(regs: Registers) -> dict[str, int]:
    q = regs.quezal
    owned = sum(1 for p in regs.psc if p.kind == "corporate" and p.active and answers.is_uk(p.country_registered)
                and answers.uk_number(p.registration_number) in regs.companies)  # fmt: skip
    return {"companies": len(regs.gleif) + len(regs.companies) + len(q.companies), "people": len(q.people),
            "agents": len(q.agents), "parent": len(answers.direct_parents(regs)), "owned_by": owned,
            "holds": len(answers.holdings(q)), "same_as": len(answers.uk_links(regs)),
            "director_of": len(q.directors)}  # fmt: skip


def ownership_pairs(regs: Registers) -> list[tuple[str, str]]:
    """Every (Quezal company, company it reaches through stakes), and a few with no chain at all."""
    g = answers.holdings_graph(regs.quezal)
    pairs = [(a, b) for a in sorted(regs.quezal.companies) if a in g for b in sorted(nx.descendants(g, a))]
    loners = [c for c in sorted(regs.quezal.companies) if c not in g or not g.out_degree(c)][:5]
    return pairs + [(a, pairs[i][0]) for i, a in enumerate(loners)]


def band_pairs(regs: Registers) -> list[tuple[str, str]]:
    links = answers.psc_links(regs)
    up = defaultdict(set)
    for p in regs.psc:
        if p.active and p.psc_id in links and p.share_band:
            up[p.company_number].add(links[p.psc_id])
    pairs = []
    for company in sorted(up):
        frontier, seen = set(up[company]), set()
        for _ in range(3):
            seen |= frontier
            frontier = {o for f in frontier for o in up.get(f, ())} - seen
        pairs += [(o, company) for o in sorted(seen)]
    return pairs[::7][:50] + [("00003543", "01003142")]  # every 7th, and one backwards (no chain)


def run(module: ModuleType) -> list[Result]:
    regs = load()
    stored = Result("The registers are in your store", L_DB)
    guard = Result("Model-written queries are checked first", L_PATTERNS)
    chains = Result("Parent chains from a template", L_PATTERNS)
    share = Result("Effective ownership, chain by chain", L_PATTERNS)
    control = Result("Control through a majority at each step", L_PATTERNS)
    bands = Result("Ownership bands as intervals", L_PATTERNS)
    groups = Result("Communities keep each hidden group together", L_ENRICH)
    generated = Result("Model-written queries answer", L_METHODS)
    results = [stored, guard, chains, share, control, bands, groups, generated]

    try:
        right = total = 0
        for query in BAD_QUERIES:
            total += 1
            ok = attempt(guard, module.validate_query, query) is False
            right += ok
            if not ok:
                guard.fail(f"let through: {query}")
        for name, query in getattr(module, "TEMPLATES", {}).items():
            total += 1
            ok = attempt(guard, module.validate_query, query) is True
            right += ok
            if not ok:
                guard.fail(f"rejected your own template {name!r}")
        tally(guard, right, total, "queries judged right")
    except NotStarted:
        guard.started = guard.passed = False

    try:
        board = attempt(stored, module.store, regs)
    except NotStarted:
        for r in (stored, chains, share, control, bands, groups, generated):
            r.started = r.passed = False
        return results
    if board is None:
        for r in (chains, share, control, bands, groups, generated):
            r.passed = False
        stored.notes.append("Is Neo4j running? `docker compose up -d`, then wait ~20 seconds.")
        return results

    checks = [(_summary, stored), (_chains, chains), (_share, share), (_control, control), (_bands, bands),
              (_groups, groups)]  # fmt: skip
    for check, r in checks:
        try:
            check(module, regs, board, r)
        except NotStarted:
            r.started = r.passed = False
    try:
        _generated(module, regs, board, generated)
    except NotStarted:
        generated.started = generated.passed = False
    return results


def _summary(module, regs, board, r: Result) -> None:
    got = attempt(r, module.store_summary, board)
    if got is None:
        return
    want = official_counts(regs)
    for k, v in want.items():
        if got.get(k) != v:
            r.fail(f"{k}: {got.get(k, 'missing')}, want {v}")
    tally(r, sum(got.get(k) == v for k, v in want.items()), len(want), "counts")


def _chains(module, regs, board, r: Result) -> None:
    up = answers.direct_parents(regs)
    leis = [x for x in sorted(regs.gleif) if x in up][::40]
    right = 0
    for lei in leis:
        rows = attempt(r, module.ask_template, board, "parents_up", lei=lei)
        want, node = set(), lei
        while node in up and up[node] not in want:
            node = up[node]
            want.add(node)
        ok = rows is not None and {row.get("id") for row in rows} == want
        right += ok
        if not ok and rows is not None:
            r.fail(f"parents_up({lei}): {len(rows)} rows, want {len(want)}")
    tally(r, right, len(leis), "chains")


def _share(module, regs, board, r: Result) -> None:
    pairs = ownership_pairs(regs)
    right = 0
    for owner, company in pairs:
        got = attempt(r, module.effective_ownership, board, owner, company)
        want = answers.effective_ownership(regs.quezal, owner, company)
        ok = isinstance(got, (int, float)) and abs(got - want) < 1e-6
        right += ok
        if not ok and got is not None:
            r.fail(f"{owner} in {company}: {got}, want {want}")
    tally(r, right, len(pairs), "pairs")


def _control(module, regs, board, r: Result) -> None:
    owners = sorted({h.holder_id for h in answers.holdings(regs.quezal) if h.holder_id.startswith("QZ-")})
    right = 0
    for owner in owners:
        got = attempt(r, module.controlled_by, board, owner)
        want = set(answers.controlled(regs.quezal, owner))
        ok = got is not None and set(got) == want
        right += ok
        if not ok and got is not None:
            r.fail(f"{owner}: {len(set(got) - want)} extra, {len(want - set(got))} missing")
    tally(r, right, len(owners), "owners")


def _bands(module, regs, board, r: Result) -> None:
    pairs = band_pairs(regs)
    right = 0
    for owner, company in pairs:
        got = attempt(r, module.band_ownership, board, owner, company, none_ok=True)
        want = answers.band_ownership(regs, owner, company)
        ok = (got is None and want is None) or (got is not None and want is not None and
                                                all(abs(a - b) < 1e-6 for a, b in zip(got, want)))  # fmt: skip
        right += ok
        if not ok:
            r.fail(f"{owner} in {company}: {got}, want {want}")
    tally(r, right, len(pairs), "pairs")


def _groups(module, regs, board, r: Result) -> None:
    got = attempt(r, module.communities, board)
    if got is None:
        return
    got = [set(c) for c in got]
    every = [c for group in got for c in group if c.startswith("QZ-")]
    problems = []
    if sorted(every) != sorted(regs.quezal.companies):
        problems.append("every Quezal company must be in exactly one community")
    if len(got) < 10:
        problems.append(f"{len(got)} communities: one big group says nothing")
    schemes = regs.quezal.truth["schemes"]
    together = 0
    for s in schemes:
        members = {s["controller"], s["target"], *s["shells"]}
        homes = [c for c in got if members & c]
        together += len(homes) == 1
        if len(homes) != 1:
            problems.append(f"a hidden group is split over {len(homes)} communities")
    for c in got:
        if sum(s["controller"] in c for s in schemes) > 1:
            problems.append("two hidden groups share one community")
    for p in problems:
        r.fail(p)
    tally(r, together if not problems else 0, len(schemes), "hidden groups kept whole")


QUESTIONS = [
    ("Which companies hold shares directly in Quezal company {target}?", "target"),
    ("Which entities are direct GLEIF children of 213800LH1BZH3DI6G760?", "bp"),
    ("Which UK companies have 01003142 as a corporate owner?", "owned"),
]


def _generated(module, regs, board, r: Result) -> None:
    from ..llm import LLMError, get_llm

    try:
        llm = get_llm()
    except LLMError as e:
        r.started = r.passed = False
        r.notes.append(f"Needs an LLM: {e}. Then run `uv run trail llm`.")
        return
    target = regs.quezal.truth["schemes"][0]["target"]
    links = answers.psc_links(regs)
    want = {
        "target": {h.holder_id for h in answers.holdings(regs.quezal) if h.company_id == target},
        "bp": {c for c, p in answers.direct_parents(regs).items() if p == "213800LH1BZH3DI6G760"},
        "owned": {p.company_number for p in regs.psc if p.active and links.get(p.psc_id) == "01003142"},
    }
    right = 0
    try:
        for question, key in QUESTIONS:
            rows = attempt(r, module.generated_query, board, question.format(target=target), llm)
            ok = rows is not None and {row.get("id") for row in rows} == want[key]
            right += ok
            if not ok and rows is not None:
                r.fail(f"{question.format(target=target)}: {len(rows)} rows, want {len(want[key])}")
    except LLMError as e:
        r.fail(f"the LLM call failed: {e}")
        return
    r.score = f"{right}/{len(QUESTIONS)} questions"
    r.passed = right >= 2
    r.notes.append(f"LLM: {llm.provider.name} {llm.model}, {llm.usage.calls} calls ({llm.usage.cached} cached)")
