"""Checks for milestone 2, one company, three sources."""

from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from types import ModuleType

from .. import answers
from ..registers import Registers, load
from .core import NotStarted, Result, attempt, tally

L_ALIGN = ("graphrag", "ontology-alignment", "Ontology alignment")
L_PATTERNS = ("graphrag", "schema-design-patterns", "Schema design patterns")
L_PROVENANCE = ("graphrag", "knowledge-graph-provenance", "Knowledge graph provenance")
L_RESOLUTION = ("graphrag", "entity-resolution", "Entity resolution")
L_OPEN = ("graphrag", "open-world-vs-closed-world", "Open world vs closed world")

# The FtM subset this project uses: schema → the properties it may carry (FtM's own names).
THING = {"name", "alias", "previousName", "country", "jurisdiction", "registrationNumber", "leiCode", "legalForm",
         "incorporationDate", "status", "sector", "address", "sourceUrl", "publisher"}  # fmt: skip
INTERVAL = {"startDate", "endDate", "recordId", "sourceUrl", "publisher", "summary", "description", "status", "role"}
SCHEMATA = {
    "Company": THING,
    "LegalEntity": THING,
    "Organization": THING,
    "Person": {"name", "alias", "country", "nationality"},
    "Ownership": INTERVAL | {"owner", "asset", "percentage", "ownershipType", "legalBasis", "sharesCount"},
    "Sanction": INTERVAL
    | {"entity", "authority", "authorityId", "program", "listingDate", "reason", "country", "provisions"},
}
REQUIRED = {"Ownership": ("owner", "asset", "recordId"), "Sanction": ("entity", "authority", "recordId")}
REFS = ("owner", "asset", "entity")
DATASETS = {"gleif", "companies_house", "uk_sanctions", "quezal"}
MATCH_BAR = 0.97
# How the check finds the entity that stands for each register record.
FINDS = {"GLEIF entities": 'dataset "gleif" and leiCode the LEI',
         "UK companies": 'dataset "companies_house", jurisdiction "gb" and registrationNumber the company number, '
                         'as Companies House writes it (00102498)',
         "Quezal companies": 'dataset "quezal", jurisdiction "qz" and registrationNumber the QZ- id',
         "Quezal people": 'schema Person in dataset "quezal", named as the register names them'}  # fmt: skip

# Listings made up for the status check, so that every rule of "above" decides a status at least once. The real
# lists touch none of these companies.
MADE_UP = {("AFG0002", "07042902"), ("AFG0004", "00306672"), ("QFA-04", "QZ-884347")}
PRETEND = "pretending 07042902, 00306672 and QZ-884347 are listed"
WHY = {
    "07282059": "its corporate owner 07042902 holds 25-50%, not more than half",
    "00313307": "00306672 holds 75-100% of it, and only Companies House says so",
    "01413180": "00313307 holds 50-75% of it, and 00306672 holds 75-100% of 00313307",
    "02134749": "00306672 holds 75-100% of it",
    "QZ-618835": "QZ-884347 holds 10% of it: a minority holder doesn't control it",
}
MADE_UP_ENTITIES = ["07042902", "213800ZRO677Z1T2RA74", "07282059", "00306672", "00313307", "01413180", "02134749",
                    "QZ-884347", "QZ-618835"]  # fmt: skip


def blinded(regs: Registers) -> Registers:
    """The same registers with GLEIF's registration numbers removed."""
    gleif = {k: dataclasses.replace(e, registration_number="") for k, e in regs.gleif.items()}
    return Registers(gleif, regs.relationships, regs.companies, regs.psc, regs.sanctions, regs.quezal,
                     hidden={"gleif.registration_number"})  # fmt: skip


def _prop(e: dict, name: str) -> list[str]:
    return e.get("properties", {}).get(name, [])


def _ftm_checks(regs: Registers, ents: list[dict], align: Result, stakes: Result, prov: Result) -> None:
    ids = Counter(e.get("id") for e in ents)
    by_id = {e.get("id"): e for e in ents}
    problems = []
    if any(n > 1 for n in ids.values()):
        problems.append(f"{sum(n > 1 for n in ids.values())} ids are used twice")
    for e in ents:
        schema, props = e.get("schema"), e.get("properties", {})
        if schema not in SCHEMATA:
            problems.append(f"{e.get('id')}: schema {schema!r} isn't one of {sorted(SCHEMATA)}")
            continue
        extra = set(props) - SCHEMATA[schema]
        if extra:
            problems.append(f"{e.get('id')}: {schema} has no property {sorted(extra)[0]!r} in FtM")
        if any(not isinstance(v, list) or not all(isinstance(x, str) for x in v) for v in props.values()):
            problems.append(f"{e.get('id')}: property values must be lists of strings")
        for ref in REFS:
            for target in props.get(ref, []):
                if target not in by_id:
                    problems.append(f"{e.get('id')}: {ref} points at {target!r}, which isn't in your list")
    # Which entity stands for each register record.
    lei_of, coh_of, qz_of = {}, {}, {}
    for e in ents:
        ds = set(e.get("datasets", []))
        for lei in _prop(e, "leiCode"):
            if "gleif" in ds:
                lei_of[lei] = e["id"]
        for n in _prop(e, "registrationNumber"):
            if "companies_house" in ds and "gb" in _prop(e, "jurisdiction"):
                coh_of[n] = e["id"]
            if "quezal" in ds and "qz" in _prop(e, "jurisdiction"):
                qz_of[n] = e["id"]
        if e.get("schema") == "Person" and "quezal" in ds:
            qz_of.setdefault(f"person:{_prop(e, 'name')[0] if _prop(e, 'name') else ''}", e["id"])
    coverage = [("GLEIF entities", sum(lei in lei_of for lei in regs.gleif), len(regs.gleif)),
                ("UK companies", sum(n in coh_of for n in regs.companies), len(regs.companies)),
                ("Quezal companies", sum(c in qz_of for c in regs.quezal.companies), len(regs.quezal.companies))]  # fmt: skip
    persons = sum(1 for e in ents if e.get("schema") == "Person" and "quezal" in e.get("datasets", []))
    coverage.append(("Quezal people", min(persons, len(regs.quezal.people)), len(regs.quezal.people)))
    for what, got, want in coverage:
        if got < want:
            problems.append(f"{what}: {got} of {want} have an entity (found by {FINDS[what]})")
    for p in problems[:8]:
        align.fail(p)
    align.score = f"{len(ents)} entities, {len(problems)} problems"
    if problems:
        align.passed = False

    # Stakes as entities: every relationship, PSC record and Quezal stake is an Ownership.
    owns = [e for e in ents if e.get("schema") == "Ownership"]
    pairs = defaultdict(list)
    for e in owns:
        for o in _prop(e, "owner"):
            for a in _prop(e, "asset"):
                pairs[(o, a)].append(e)
    right = total = 0
    for r in regs.relationships:
        if r.type == "direct":
            total += 1
            ok = (lei_of.get(r.parent_lei), lei_of.get(r.child_lei)) in pairs
            right += ok
            if not ok:
                stakes.fail(f"no Ownership for GLEIF: {r.child_lei} consolidated by {r.parent_lei}")
    record_ids = {x for e in owns for x in _prop(e, "recordId")}
    for p in regs.psc:
        if p.kind in ("corporate", "legal-person"):
            total += 1
            ok = p.psc_id in record_ids and any(coh_of.get(p.company_number) in _prop(e, "asset")
                                               for e in owns if p.psc_id in _prop(e, "recordId"))  # fmt: skip
            right += ok
            if not ok:
                stakes.fail(f"no Ownership with recordId {p.psc_id} on company {p.company_number}")
    for h in answers.holdings(regs.quezal):
        total += 1
        found = pairs.get((qz_of.get(h.holder_id) or _person(qz_of, regs, h.holder_id), qz_of.get(h.company_id)), [])
        ok = any(abs(float(x) - h.percent) < 1e-6 for e in found for x in _prop(e, "percentage") if _num(x))
        right += ok
        if not ok:
            stakes.fail(f"no Ownership of {h.percent:g}% in {h.company_id} held by {h.holder_id}")
    tally(stakes, right, total, "stakes")

    # Provenance: datasets on everything; record ids on every interval; sanctions name their list.
    sanctions = [e for e in ents if e.get("schema") == "Sanction"]
    missing = [e.get("id") for e in ents if not set(e.get("datasets", [])) or not set(e["datasets"]) <= DATASETS]
    missing += [e.get("id") for e in ents if e.get("schema") in REQUIRED
                and any(not _prop(e, p) for p in REQUIRED[e["schema"]])]  # fmt: skip
    listed_ids = {x for e in sanctions for x in _prop(e, "recordId") + _prop(e, "authorityId")}
    want = set(regs.sanctions) | {w.id for w in regs.quezal.watchlist}
    for uid in sorted(want - listed_ids)[:3]:
        prov.fail(f"no Sanction carries the designation {uid}")
    for eid in missing[:4]:
        prov.fail(
            f"{eid}: needs datasets from {sorted(DATASETS)} (and owner/asset/entity, authority, recordId on intervals)"
        )
    tally(
        prov, len(ents) - len(set(missing)) + len(want & listed_ids), len(ents) + len(want), "entities and designations"
    )


def _num(x: str) -> bool:
    try:
        float(x)
        return True
    except ValueError:
        return False


def _person(qz_of: dict, regs: Registers, pid: str) -> str | None:
    return qz_of.get(f"person:{regs.quezal.people.get(pid, '')}")


def _gold(regs: Registers) -> dict[str, set[tuple[str, str]]]:
    same = defaultdict(set)
    for lei, n in answers.uk_links(regs):
        same[lei].add(n)
    designations = {(uid, lei) for uid, lei in answers.SANCTION_MATCHES.items()}
    designations |= {(uid, n) for uid, lei in answers.SANCTION_MATCHES.items() for n in same[lei]}
    watch = {(lid, cid) for lid, cid in answers.watchlist_matches(regs.quezal).items() if cid}
    return {"uk": answers.uk_links(regs), "designations": designations, "watchlist": watch}


def run(module: ModuleType) -> list[Result]:
    regs = load()
    align = Result("Aligned with FollowTheMoney", L_ALIGN)
    stakes = Result("Stakes as records of their own", L_PATTERNS)
    prov = Result("Every fact says where it came from", L_PROVENANCE)
    uk = Result("One company in GLEIF and Companies House", L_RESOLUTION)
    listed = Result("Designations, without false alarms", L_RESOLUTION)
    status = Result("Not listed isn't clean", L_OPEN)
    results = [align, stakes, prov, uk, listed, status]

    try:
        ents = attempt(align, module.to_ftm, regs)
        if ents is not None:
            _ftm_checks(regs, ents, align, stakes, prov)
        else:
            stakes.passed = prov.passed = False
    except NotStarted:
        for r in (align, stakes, prov):
            r.started = r.passed = False

    gold = _gold(regs)
    try:
        got = attempt(uk, module.match, blinded(regs))
        if got is not None:
            mine = {(a, b) for a, b in got if a in regs.gleif and b in regs.companies}
            hit = len(mine & gold["uk"])
            precision, recall = hit / len(mine) if mine else 0.0, hit / len(gold["uk"])
            uk.score = f"precision {precision:.3f}, recall {recall:.3f} (registration numbers hidden)"
            uk.passed = precision >= MATCH_BAR and recall >= MATCH_BAR
            for lei, n in sorted(mine - gold["uk"])[:3]:
                uk.details.append(f"wrong: {regs.gleif[lei].legal_name} ≠ {regs.companies[n].name}")
            for lei, n in sorted(gold["uk"] - mine)[:3]:
                uk.details.append(f"missed: {regs.gleif[lei].legal_name} = {regs.companies[n].name}")
            if not uk.passed:
                uk.details.insert(0, f"Needs precision and recall of at least {MATCH_BAR}.")
        got = attempt(listed, module.match, regs)
        if got is not None:
            mine = {(a, b) for a, b in got if a in regs.sanctions or a.startswith("QFA-")}
            want = gold["designations"] | gold["watchlist"]
            ok_designations = {(a, b) for a, b in mine if a in regs.sanctions} <= gold["designations"]
            found_designations = {a for a, _ in mine & gold["designations"]} == set(answers.SANCTION_MATCHES)
            for a, b in sorted(mine - want):
                what = regs.gleif[b].legal_name if b in regs.gleif else (
                    regs.companies[b].name if b in regs.companies else b)  # fmt: skip
                listed.fail(f"false alarm: {a} matched to {what}")
            for a in sorted(set(answers.SANCTION_MATCHES) - {x for x, _ in mine & gold["designations"]}):
                listed.fail(f"missed: {a} ({regs.sanctions[a].name}) is in the GLEIF slice")
            for a, b in sorted(gold["watchlist"] - mine):
                listed.fail(f"missed: {a} is {b}")
            right = len(mine & want)
            listed.score = f"{right} right, {len(mine - want)} false alarms"
            listed.passed = ok_designations and found_designations and mine <= want and gold["watchlist"] <= mine
    except NotStarted:
        uk.started = uk.passed = listed.started = listed.passed = False

    try:
        matches = gold["uk"] | gold["designations"] | gold["watchlist"]
        lukoil = answers.group(regs, "549300LCJ1UJXHYBWI24")
        others = sorted(answers.group(regs, "213800LH1BZH3DI6G760"))[:12] + sorted(regs.companies)[:12]
        entities = sorted(lukoil) + others + sorted(regs.quezal.companies)
        right = 0
        for e in entities:
            got = attempt(status, module.sanction_status, regs, matches, e)
            want = answers.sanction_status(regs, e)
            right += got == want
            if got != want and got is not None:
                status.fail(f"{e}: {got!r}, want {want!r}" + ("" if got in answers.STATUSES else " (one of STATUSES)"))
        made_up = matches | MADE_UP
        for e in MADE_UP_ENTITIES:
            got = attempt(status, module.sanction_status, regs, made_up, e)
            want = answers.sanction_status(regs, e, made_up)
            right += got == want
            if got != want and got is not None:
                status.fail(f"{e}, {PRETEND}: {got!r}, want {want!r}" + (f" ({WHY[e]})" if e in WHY else ""))
        tally(status, right, len(entities) + len(MADE_UP_ENTITIES), "entities")
    except NotStarted:
        status.started = status.passed = False
    return results
