"""The official reading of the registers. The checks compare your answers with these.

Spoilers, in a way: every function here answers a question a milestone asks you. Reading it
before you've tried is like reading the reference solution.
"""

from __future__ import annotations

import re
from collections import defaultdict
from functools import cache

import networkx as nx

from .registers import Quezal, Registers

COMPANIES_HOUSE = "RA000585"
STATUSES = ("listed", "owned by a listed entity", "no listing found")
UK_PLACES = ("england", "wales", "scotland", "northern ireland", "united kingdom", "uk", "great britain")

# Designations on the UK Sanctions List that are entities in the GLEIF slice, checked by hand:
# LUKOIL by its Russian registration number (OGRN), the other two by an alias and the country.
SANCTION_MATCHES = {
    "RUS3094": "549300LCJ1UJXHYBWI24",  # PJSC Oil Company LUKOIL
    "RUS2876": "5493007XYP6TMCO8L243",  # Litasco Middle East DMCC, also LME Trading DMCC
    "RUS2638": "5493008CGNE47EJ89474",  # Rhodania Shipping SA, also Eiger Shipping SA
}


def uk_number(raw: str) -> str | None:
    s = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if re.fullmatch(r"\d{1,8}", s):
        return s.zfill(8)
    m = re.fullmatch(r"([A-Z]{2})(\d{1,6})", s)
    return m.group(1) + m.group(2).zfill(6) if m else None


def is_uk(country_registered: str) -> bool:
    return any(p in country_registered.lower() for p in UK_PLACES)


# --- Milestone 1: who owns whom ----------------------------------------------------------------


def direct_parents(regs: Registers) -> dict[str, str]:
    return {r.child_lei: r.parent_lei for r in regs.relationships if r.type == "direct"}


def ultimate_parent(regs: Registers, lei: str) -> str:
    """Walk up the direct-parent edges until there's none: the top of the chain GLEIF can show."""
    up, seen = direct_parents(regs), {lei}
    while lei in up and up[lei] not in seen:
        lei = up[lei]
        seen.add(lei)
    return lei


def group(regs: Registers, lei: str) -> set[str]:
    """The entity and everything below it through direct-parent edges."""
    down = defaultdict(list)
    for child, parent in direct_parents(regs).items():
        down[parent].append(child)
    out, stack = set(), [lei]
    while stack:
        n = stack.pop()
        if n not in out:
            out.add(n)
            stack += down[n]
    return out


def gleif_disagreements(regs: Registers) -> list[tuple[str, str, str]]:
    """(child, top by walking direct parents, ultimate parent GLEIF reports) where the two differ."""
    reported = {r.child_lei: r.parent_lei for r in regs.relationships if r.type == "ultimate"}
    return sorted((c, ultimate_parent(regs, c), u) for c, u in reported.items() if ultimate_parent(regs, c) != u)


def holdings(q: Quezal) -> list:
    return [h for h in q.holdings if not h.until and h.since <= q.snapshot]


def holdings_graph(q: Quezal) -> nx.DiGraph:
    g = nx.DiGraph()
    for h in holdings(q):
        g.add_edge(h.holder_id, h.company_id, percent=h.percent)
    return g


def canonical_loop(loop: list[str]) -> tuple[str, ...]:
    i = loop.index(min(loop))
    return tuple(loop[i:] + loop[:i])


def loops(regs: Registers) -> set[tuple[str, ...]]:
    """Ownership loops: GLEIF direct parents (child → parent) and Quezal stakes (holder → company)."""
    g = nx.DiGraph(list(direct_parents(regs).items()))
    out = {canonical_loop(c) for c in nx.simple_cycles(g)}
    out |= {canonical_loop(c) for c in nx.simple_cycles(holdings_graph(regs.quezal))}
    return out


def graph_summary(regs: Registers) -> dict[str, int]:
    corporate = [p for p in regs.psc if p.kind == "corporate" and p.active]
    return {
        "gleif_entities": len(regs.gleif),
        "gleif_parent_links": len(direct_parents(regs)),
        "uk_companies": len(regs.companies),
        "uk_corporate_owners": len(corporate),
        "quezal_companies": len(regs.quezal.companies),
        "quezal_people": len(regs.quezal.people),
        "quezal_stakes": len(holdings(regs.quezal)),
        "same_company_links": len(uk_links(regs)),
    }


# --- Milestone 2: one company, three registers -------------------------------------------------


def uk_links(regs: Registers) -> set[tuple[str, str]]:
    """(LEI, company number) for every GLEIF entity registered at Companies House and in the slice."""
    out = set()
    for e in regs.gleif.values():
        if e.registration_authority == COMPANIES_HOUSE:
            n = uk_number(e.registration_number)
            if n in regs.companies:
                out.add((e.lei, n))
    return out


def psc_links(regs: Registers) -> dict[str, str]:
    """psc_id → company number, for corporate owners that are UK companies in the slice."""
    out = {}
    for p in regs.psc:
        if p.kind == "corporate" and is_uk(p.country_registered):
            n = uk_number(p.registration_number)
            if n in regs.companies:
                out[p.psc_id] = n
    return out


def watchlist_matches(q: Quezal) -> dict[str, str | None]:
    return dict(q.truth["watchlist"]) if q.truth else {}


def _same(regs: Registers) -> dict[str, set[str]]:
    """Every id → the ids of the same company in the other registers (itself included)."""
    same: dict[str, set[str]] = defaultdict(set)
    for lei, n in uk_links(regs):
        same[lei] |= {lei, n}
        same[n] |= {lei, n}
    return same


def owners_of(regs: Registers, entity: str) -> set[str]:
    """Who controls `entity` directly, by any register: a GLEIF parent, a Companies House corporate
    owner with more than 50% of the shares, a Quezal holder that controls it."""
    out = set()
    ids = _same(regs).get(entity, {entity})
    up = direct_parents(regs)
    links = psc_links(regs)
    for i in ids:
        if i in up:
            out.add(up[i])
        for p in regs.psc:
            band = p.share_band
            if p.company_number == i and p.active and p.psc_id in links and band and band[0] >= 0.5:
                out.add(links[p.psc_id])
    if entity.startswith("QZ-"):
        for holder in regs.quezal.companies:
            if holder != entity and entity in controlled(regs.quezal, holder):
                out.add(holder)
    return out


def listed(regs: Registers) -> dict[str, str]:
    """Entity id → the designation that lists it (UK Sanctions List or Quezal's watch list)."""
    out = {}
    for uid, lei in SANCTION_MATCHES.items():
        for i in _same(regs).get(lei, {lei}):
            out[i] = uid
    for lid, cid in watchlist_matches(regs.quezal).items():
        if cid:
            out[cid] = lid
    return out


def sanction_status(regs: Registers, entity: str) -> str:
    """listed · owned by a listed entity · no listing found. Never "clean": the lists are open-world."""
    found = listed(regs)
    if entity in found:
        return "listed"
    seen, stack = {entity}, [entity]
    while stack:
        for owner in owners_of(regs, stack.pop()):
            if owner in found:
                return "owned by a listed entity"
            if owner not in seen:
                seen.add(owner)
                stack.append(owner)
    return "no listing found"


# --- Milestone 4: effective ownership ----------------------------------------------------------


def effective_ownership(q: Quezal, owner: str, company: str) -> float:
    """Multiply the stakes along each chain from owner to company, then add the chains up.

    Chains never visit a company twice, so a loop is walked at most once around."""
    g = holdings_graph(q)
    if owner not in g or company not in g:
        return 0.0
    total = 0.0
    for path in nx.all_simple_paths(g, owner, company):
        share = 1.0
        for a, b in zip(path, path[1:]):
            share *= g[a][b]["percent"] / 100
        total += share
    return round(total, 6)


@cache
def _stakes(q: Quezal) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for h in holdings(q):
        out[h.company_id][h.holder_id] = out[h.company_id].get(h.holder_id, 0.0) + h.percent
    return out


@cache
def controlled(q: Quezal, owner: str, direct_only: bool = False) -> frozenset[str]:
    """Companies `owner` controls: more than 50% of the votes, its own plus those of companies it already controls."""
    stakes, out = _stakes(q), set()
    changed = True
    while changed:
        changed = False
        for company, holders in stakes.items():
            if company in out or company == owner:
                continue
            votes = holders.get(owner, 0.0) + (0.0 if direct_only else sum(v for h, v in holders.items() if h in out))
            if votes > 50:
                out.add(company)
                changed = True
    return frozenset(out)


def band_ownership(regs: Registers, owner: str, company: str) -> tuple[float, float] | None:
    """Effective ownership of one UK company in another, as an interval, from Companies House bands.

    Follow active corporate owners (UK companies in the slice) up from `company`; multiply the
    bands along each chain (lows with lows, highs with highs) and add the chains, capping at 1."""
    links = psc_links(regs)
    up: dict[str, list[tuple[str, tuple[float, float]]]] = defaultdict(list)
    for p in regs.psc:
        if p.active and p.psc_id in links and p.share_band:
            up[p.company_number].append((links[p.psc_id], p.share_band))
    lo = hi = 0.0
    found = False

    def walk(node: str, a: float, b: float, seen: frozenset) -> None:
        nonlocal lo, hi, found
        for parent, (pl, ph) in up.get(node, []):
            if parent in seen:
                continue
            if parent == owner:
                lo, hi, found = lo + a * pl, hi + b * ph, True
            else:
                walk(parent, a * pl, b * ph, seen | {parent})

    walk(company, 1.0, 1.0, frozenset({company}))
    return (round(lo, 6), round(min(hi, 1.0), 6)) if found else None


# --- Milestone 5: screening --------------------------------------------------------------------


def hidden_controllers(q: Quezal, listed: set[str]) -> set[tuple[str, str]]:
    """Listed companies that control an operating company (it holds no stakes) without a direct majority."""
    held = holdings(q)
    holders = {h.holder_id for h in held}
    direct = {(h.holder_id, h.company_id) for h in held if h.percent > 50}
    return {(c, t) for c in listed for t in controlled(q, c) if t not in holders and (c, t) not in direct}


def pair_hash(controller: str, company: str) -> str:
    import hashlib

    return hashlib.sha256(f"trail:{controller}>{company}".encode()).hexdigest()
