"""Milestone 1 · Who owns whom: a reference solution. Spoilers: `trail use-reference 1` copies it."""

from __future__ import annotations

import re

import networkx as nx

from trail.registers import Registers
from trail.vectors import VectorIndex

UK = ("england", "wales", "scotland", "northern ireland", "united kingdom", "uk", "great britain")


def _number(raw: str) -> str | None:
    s = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if re.fullmatch(r"\d{1,8}", s):
        return s.zfill(8)
    m = re.fullmatch(r"([A-Z]{2})(\d{1,6})", s)
    return m.group(1) + m.group(2).zfill(6) if m else None


def build_graph(regs: Registers) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for e in regs.gleif.values():
        g.add_node(e.lei, source="gleif", name=e.legal_name)
    for r in regs.relationships:
        if r.type == "direct":
            g.add_edge(r.child_lei, r.parent_lei, key="PARENT")
    for c in regs.companies.values():
        g.add_node(c.company_number, source="companies_house", name=c.name)
    for p in regs.psc:
        if p.kind == "corporate" and p.active:
            owner = _number(p.registration_number) if any(u in p.country_registered.lower() for u in UK) else None
            target = owner if owner in regs.companies else f"owner:{p.psc_id}"
            if target not in g:
                g.add_node(target, source="psc", name=p.name)
            g.add_edge(p.company_number, target, key="CONTROLLED_BY", psc=p.psc_id)
    q = regs.quezal
    for c in q.companies.values():
        g.add_node(c.id, source="quezal", name=c.name)
    for pid, name in q.people.items():
        g.add_node(pid, source="quezal-person", name=name)
    for h in q.holdings:
        if not h.until and h.since <= q.snapshot:
            g.add_edge(h.holder_id, h.company_id, key="HOLDS", percent=h.percent)
    for e in regs.gleif.values():
        if e.registration_authority == "RA000585" and _number(e.registration_number) in regs.companies:
            g.add_edge(e.lei, _number(e.registration_number), key="SAME_AS")
    return g


def _edges(g, kind: str) -> list[tuple[str, str]]:
    return [(a, b) for a, b, k in g.edges(keys=True) if k == kind]


def graph_summary(graph) -> dict[str, int]:
    count = {s: 0 for s in ("gleif", "companies_house", "quezal", "quezal-person")}
    for _, data in graph.nodes(data=True):
        if data.get("source") in count:
            count[data["source"]] += 1
    return {
        "gleif_entities": count["gleif"],
        "gleif_parent_links": len(_edges(graph, "PARENT")),
        "uk_companies": count["companies_house"],
        "uk_corporate_owners": len(_edges(graph, "CONTROLLED_BY")),
        "quezal_companies": count["quezal"],
        "quezal_people": count["quezal-person"],
        "quezal_stakes": len(_edges(graph, "HOLDS")),
        "same_company_links": len(_edges(graph, "SAME_AS")),
    }


def ultimate_parent(graph, lei: str) -> str:
    up = dict(_edges(graph, "PARENT"))
    seen = {lei}
    while lei in up and up[lei] not in seen:
        lei = up[lei]
        seen.add(lei)
    return lei


def group(graph, lei: str) -> set[str]:
    parents = nx.DiGraph(_edges(graph, "PARENT"))
    return {lei} | (nx.ancestors(parents, lei) if lei in parents else set())  # children point at parents


def ownership_loops(graph) -> list[list[str]]:
    held_by = nx.DiGraph(_edges(graph, "PARENT") + [(b, a) for a, b in _edges(graph, "HOLDS")])
    return [list(c) for c in nx.simple_cycles(held_by)]


_INDEX: tuple[list[str], VectorIndex] | None = None


def vector_group(regs: Registers, lei: str, k: int) -> set[str]:
    global _INDEX
    if _INDEX is None:
        leis = sorted(regs.gleif)
        lines = [f"{regs.gleif[x].legal_name}, {regs.gleif[x].city}, {regs.gleif[x].country}" for x in leis]
        _INDEX = (leis, VectorIndex(lines))
    leis, index = _INDEX
    return {leis[i] for i in index.search(f"Companies in the {regs.gleif[lei].legal_name} group", k)}
