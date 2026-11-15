"""Milestone 2 · One company, three sources: a reference solution. Spoilers: `trail use-reference 2`."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from trail.registers import Registers

STATUSES = ("listed", "owned by a listed entity", "no listing found")
UK = ("england", "wales", "scotland", "northern ireland", "united kingdom", "uk", "great britain")
COUNTRIES = {"russia": "RU", "switzerland": "CH", "united arab emirates": "AE", "united kingdom": "GB",
             "netherlands": "NL", "cyprus": "CY", "austria": "AT", "singapore": "SG", "iran": "IR", "china": "CN",
             "hong kong": "HK", "turkey": "TR", "india": "IN", "belarus": "BY", "kazakhstan": "KZ"}  # fmt: skip
FORMS = (r"\b(PUBLIC JOINT STOCK COMPANY|JOINT STOCK COMPANY|LIMITED LIABILITY COMPANY|PUBLIC LIMITED COMPANY|PJSC|OJSC"
         r"|JSC|PAO|OAO|AO|OOO|LLC|LIMITED|LTD|PLC|P L C|INC|GMBH|AG|SA|S A|BV|B V|NV|N V"
         r"|SPA|S P A|SRL|DMCC|FZE|FZCO|IBC|THE|OIL COMPANY|IN LIQUIDATION)\b")  # fmt: skip


def _number(raw: str) -> str | None:
    s = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if re.fullmatch(r"\d{1,8}", s):
        return s.zfill(8)
    m = re.fullmatch(r"([A-Z]{2})(\d{1,6})", s)
    return m.group(1) + m.group(2).zfill(6) if m else None


def key(name: str) -> str:
    """A comparison key: accents off, punctuation and legal forms out, spaces gone."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode() or name
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(FORMS, " ", s)
    return "".join(s.split())


# --- FtM ---------------------------------------------------------------------------------------


def to_ftm(regs: Registers) -> list[dict]:
    out: list[dict] = []

    def add(eid: str, schema: str, dataset: str, **props) -> str:
        clean = {k: [str(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if x not in (None, "")]
                 for k, v in props.items()}  # fmt: skip
        out.append({"id": eid, "schema": schema, "properties": {k: v for k, v in clean.items() if v},
                    "datasets": [dataset]})  # fmt: skip
        return eid

    for e in regs.gleif.values():
        add(f"gleif-{e.lei}", "Company", "gleif", name=e.legal_name, alias=list(e.other_names) + list(e.transliterated_names),
            leiCode=e.lei, registrationNumber=e.registration_number, jurisdiction=e.jurisdiction.lower(),
            country=e.country.lower(), status=e.entity_status)  # fmt: skip
    for r in regs.relationships:
        if r.type == "direct":
            add(f"gleif-own-{r.child_lei}", "Ownership", "gleif", owner=f"gleif-{r.parent_lei}", asset=f"gleif-{r.child_lei}",
                percentage=r.percentage, startDate=r.start_date, role="direct accounting consolidation",
                recordId=r.child_lei, publisher="GLEIF")  # fmt: skip
    for c in regs.companies.values():
        add(f"gb-coh-{c.company_number}", "Company", "companies_house", name=c.name, previousName=list(c.previous_names),
            registrationNumber=c.company_number, jurisdiction="gb", incorporationDate=c.incorporated_on,
            status=c.status)  # fmt: skip
    for p in regs.psc:
        if p.kind not in ("corporate", "legal-person"):
            continue  # individuals stay anonymous; statements aren't owners
        number = _number(p.registration_number) if any(u in p.country_registered.lower() for u in UK) else None
        owner = f"gb-coh-{number}" if number in regs.companies else add(
            f"psc-owner-{p.psc_id}", "Company" if p.kind == "corporate" else "LegalEntity", "companies_house",
            name=p.name, registrationNumber=p.registration_number, legalForm=p.legal_form)  # fmt: skip
        band = p.share_band
        add(f"psc-own-{p.psc_id}", "Ownership", "companies_house", owner=owner, asset=f"gb-coh-{p.company_number}",
            percentage=f"{band[0] * 100:g}-{band[1] * 100:g}" if band else None, startDate=p.notified_on,
            endDate=p.ceased_on, role="person with significant control", recordId=p.psc_id,
            publisher="Companies House")  # fmt: skip
    q = regs.quezal
    for c in q.companies.values():
        add(f"qz-{c.id}", "Company", "quezal", name=c.name, registrationNumber=c.id, jurisdiction="qz",
            incorporationDate=c.incorporated_on, status=c.status, sector=c.sector)  # fmt: skip
    for pid, name in q.people.items():
        add(f"qz-{pid}", "Person", "quezal", name=name)
    for h in q.holdings:
        if not h.until and h.since <= q.snapshot:
            add(f"qz-own-{h.holder_id}-{h.company_id}", "Ownership", "quezal", owner=f"qz-{h.holder_id}",
                asset=f"qz-{h.company_id}", percentage=f"{h.percent:g}", startDate=h.since,
                recordId=f"{h.holder_id}/{h.company_id}", publisher="Quezal company register")  # fmt: skip
    for d in regs.sanctions.values():
        eid = add(f"uk-{d.unique_id}", "Organization", "uk_sanctions", name=d.name,
                  alias=list(d.aliases) + list(d.non_latin_names), registrationNumber=list(d.registration_numbers))  # fmt: skip
        add(f"uk-sanction-{d.unique_id}", "Sanction", "uk_sanctions", entity=eid, authority="UK FCDO",
            authorityId=d.unique_id, program=d.regime, listingDate=d.designated_on, recordId=d.unique_id)  # fmt: skip
    for w in q.watchlist:
        eid = add(f"qfa-{w.id}", "Organization", "quezal", name=w.name, alias=list(w.aliases))
        add(f"qfa-sanction-{w.id}", "Sanction", "quezal", entity=eid, authority="Quezal Financial Authority",
            authorityId=w.id, reason=w.reason, listingDate=w.designated_on, recordId=w.id)  # fmt: skip
    return out


# --- Matching ----------------------------------------------------------------------------------


def match(regs: Registers) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    # GLEIF ↔ Companies House: the number when there is one, else a name the register knows (current or previous).
    by_name: dict[str, set[str]] = defaultdict(set)
    current: dict[str, str] = {}
    for c in regs.companies.values():
        current[key(c.name)] = c.company_number
        for n in (c.name, *c.previous_names):
            by_name[key(n)].add(c.company_number)
    for e in regs.gleif.values():
        if e.registration_authority != "RA000585":
            continue
        number = _number(e.registration_number)
        if number in regs.companies:
            pairs.add((e.lei, number))
            continue
        for n in e.names:  # the current name first, then a unique previous one
            if key(n) in current:
                pairs.add((e.lei, current[key(n)]))
                break
            if len(by_name.get(key(n), ())) == 1:
                pairs.add((e.lei, next(iter(by_name[key(n)]))))
                break
    # Designations: a registration number that GLEIF also has, or an exact name key with no country conflict.
    gleif_keys: dict[str, set[str]] = defaultdict(set)
    for e in regs.gleif.values():
        for n in e.names:
            gleif_keys[key(n)].add(e.lei)
    for d in regs.sanctions.values():
        countries = {COUNTRIES.get(c.lower()) for c in d.countries} - {None}
        numbers = " ".join(d.registration_numbers)
        for e in regs.gleif.values():
            if e.registration_number and len(e.registration_number) >= 6 and e.registration_number in numbers:
                pairs.add((d.unique_id, e.lei))
        for n in d.names:
            for lei in gleif_keys.get(key(n), ()) if len(key(n)) >= 6 else ():
                if not countries or regs.gleif[lei].country in countries:
                    pairs.add((d.unique_id, lei))
    # Quezal's watch list against Quezal's register.
    qz = {key(c.name): c.id for c in regs.quezal.companies.values()}
    for w in regs.quezal.watchlist:
        for n in w.names:
            if key(n) in qz:
                pairs.add((w.id, qz[key(n)]))
                break
    return pairs


# --- Open world --------------------------------------------------------------------------------


def _controlled(regs: Registers, owner: str) -> set[str]:
    stakes: dict[str, dict[str, float]] = defaultdict(dict)
    for h in regs.quezal.holdings:
        if not h.until and h.since <= regs.quezal.snapshot:
            stakes[h.company_id][h.holder_id] = stakes[h.company_id].get(h.holder_id, 0) + h.percent
    out, changed = set(), True
    while changed:
        changed = False
        for company, holders in stakes.items():
            if company not in out and company != owner:
                if holders.get(owner, 0) + sum(v for h, v in holders.items() if h in out) > 50:
                    out.add(company)
                    changed = True
    return out


def sanction_status(regs: Registers, matches: set[tuple[str, str]], entity: str) -> str:
    same: dict[str, set[str]] = defaultdict(set)
    listed: set[str] = set()
    for a, b in matches:
        if a in regs.sanctions or a.startswith("QFA-"):
            listed.add(b)
        else:
            same[a] |= {a, b}
            same[b] |= {a, b}
    listed |= {x for b in list(listed) for x in same.get(b, ())}
    up: dict[str, set[str]] = defaultdict(set)
    for r in regs.relationships:
        if r.type == "direct":
            up[r.child_lei].add(r.parent_lei)
    for p in regs.psc:
        band = p.share_band
        if p.kind == "corporate" and p.active and band and band[0] >= 0.5:
            number = _number(p.registration_number) if any(u in p.country_registered.lower() for u in UK) else None
            if number in regs.companies:
                up[p.company_number].add(number)
    for holder in regs.quezal.companies:
        for company in _controlled(regs, holder):
            up[company].add(holder)
    if entity in listed:
        return "listed"
    seen, stack = {entity}, [entity]
    while stack:
        node = stack.pop()
        for owner in {o for i in same.get(node, {node}) for o in up.get(i, ())}:
            if owner in listed:
                return "owned by a listed entity"
            if owner not in seen:
                seen.add(owner)
                stack.append(owner)
    return "no listing found"
