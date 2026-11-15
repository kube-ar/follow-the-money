"""Milestone 5 · Screening a supplier: a reference solution. Spoilers: `trail use-reference 5` copies it.

It reuses the matching and the open-world status from milestone 2 (loaded from the same folder)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from rapidfuzz import fuzz

from trail.registers import Registers

HERE = Path(__file__).resolve().parent
STATUSES = ("listed", "owned by a listed entity", "no listing found")
LAYERS = ("matching", "linking", "extraction", "answers")
_M2 = None
_MATCHES: dict[int, set] = {}


def _m2():
    global _M2
    if _M2 is None:
        spec = importlib.util.spec_from_file_location("m2_for_m5", HERE / "m2_three_sources.py")
        _M2 = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = _M2
        spec.loader.exec_module(_M2)
    return _M2


def _matches(regs: Registers) -> set:
    if id(regs) not in _MATCHES:
        _MATCHES[id(regs)] = _m2().match(regs)
    return _MATCHES[id(regs)]


def _candidates(regs: Registers, country: str) -> list[tuple[str, tuple[str, ...]]]:
    country = country.upper()
    out = [(e.lei, e.names) for e in regs.gleif.values() if e.country == country]
    if country == "GB":
        out += [(c.company_number, (c.name, *c.previous_names)) for c in regs.companies.values()]
    if country == "QZ":
        out += [(c.id, (c.name,)) for c in regs.quezal.companies.values()]
    return out


def _resolve(regs: Registers, name: str, country: str) -> str | None:
    key = _m2().key
    one = {}  # a company in GLEIF and Companies House is one candidate, named by its LEI
    for a, b in _matches(regs):
        if a in regs.gleif and b in regs.companies:
            one[b] = a
    best: dict[str, float] = {}
    for i, names in _candidates(regs, country):
        score = max(100.0 if key(n) == key(name) else fuzz.ratio(key(n), key(name)) for n in names)
        best[one.get(i, i)] = max(best.get(one.get(i, i), 0.0), score)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] < 92:
        return None
    if len(ranked) > 1 and ranked[1][1] > ranked[0][1] - 3:
        return None  # two companies fit about as well: don't guess
    return ranked[0][0]


def _top(regs: Registers, entity: str) -> str:
    up = {r.child_lei: r.parent_lei for r in regs.relationships if r.type == "direct"}
    seen = {entity}
    while entity in up and up[entity] not in seen:
        entity = up[entity]
        seen.add(entity)
    return entity


def screen(regs: Registers, name: str, country: str) -> dict:
    m2, key = _m2(), _m2().key
    entity = _resolve(regs, name, country)
    evidence = []
    if entity is None:
        on_list = [d.unique_id for d in regs.sanctions.values() if any(key(n) == key(name) for n in d.names)]
        on_list += [w.id for w in regs.quezal.watchlist if any(key(n) == key(name) for n in w.names)]
        status = "listed" if on_list else "no listing found"
        evidence.append("No register in the slice has this name in this country.")
        evidence += [f"{x} lists the name." for x in on_list]
        return {"entity": None, "top": None, "status": status, "evidence": evidence}
    status = m2.sanction_status(regs, _matches(regs), entity)
    top = _top(regs, entity) if entity in regs.gleif else entity
    evidence.append(f"{entity} is the closest name in {country.upper()}.")
    if top != entity:
        evidence.append(f"GLEIF: the chain of parents ends at {top}.")
    evidence.append(f"Status: {status}.")
    return {"entity": entity, "top": top, "status": status, "evidence": evidence}


def hidden_controllers(regs: Registers) -> set[tuple[str, str]]:
    m2 = _m2()
    q = regs.quezal
    listed = {b for a, b in _matches(regs) if a.startswith("QFA-")}
    holders = {h.holder_id for h in q.holdings if not h.until and h.since <= q.snapshot}
    direct = {(h.holder_id, h.company_id) for h in q.holdings if h.percent > 50 and not h.until}
    out = set()
    for controller in listed:
        for company in m2._controlled(regs, controller):
            if company not in holders and (controller, company) not in direct:
                out.add((controller, company))
    return out


def bottom_up(scores: dict[str, float], bars: dict[str, float]) -> str | None:
    for layer in LAYERS:
        if layer in scores and scores[layer] < bars.get(layer, 0.0):
            return layer
    return None
