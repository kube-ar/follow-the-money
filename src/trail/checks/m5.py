"""Checks for milestone 5, screening a supplier."""

from __future__ import annotations

import json
import re
import unicodedata
from types import ModuleType

from .. import answers
from ..registers import Registers, load
from .core import NotStarted, Result, attempt, tally

L_EVAL = ("graphrag", "evaluating-graphrag", "Evaluating GraphRAG")
FORMS = re.compile(
    r"\b(plc|p l c|limited|ltd|llc|ibc|foundation|holdings ltd|gmbh|s a|sa|n v|nv|b v|bv|a s|as|spa|s p a|dmcc|pjsc)\b"
)
BAR = 0.9
UNKNOWN = [("Varnholt Bunker Supply GmbH", "DE"), ("Quillon Head Dairy Supplies Ltd", "GB"),
           ("Tessaro Quantum Instruments GmbH", "DE")]  # fmt: skip
LAYER_FIXTURES = [
    ({"matching": 0.99, "linking": 0.95, "extraction": 0.6, "answers": 0.7}, "extraction"),
    ({"answers": 0.5, "extraction": 0.5, "matching": 0.9}, "matching"),
    ({"linking": 0.95, "answers": 0.95}, None),
    ({"answers": 0.5}, "answers"),
    ({"matching": 0.97, "linking": 0.9}, None),
    ({"extraction": 0.69, "linking": 0.2}, "linking"),
]
BARS = {"matching": 0.97, "linking": 0.9, "extraction": 0.7, "answers": 0.9}


def _key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(FORMS.sub(" ", s).split())


def _typo(name: str) -> str:
    words = name.split()
    i = max(range(len(words)), key=lambda n: (not FORMS.fullmatch(words[n].lower().strip(".")), len(words[n])))
    w = words[i]
    if len(w) < 7:
        return name
    j = len(w) // 2
    words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
    return " ".join(words)


def questions(regs: Registers) -> list[dict]:
    """The screening gold set: name as typed, country, accepted entity ids, status."""
    same = {}
    for lei, n in answers.uk_links(regs):
        same[lei] = same[n] = {lei, n}
    index: dict[tuple[str, str], set[str]] = {}

    def put(country: str, name: str, eid: str) -> None:
        index.setdefault((country, _key(name)), set()).update(same.get(eid, {eid}))

    for e in regs.gleif.values():
        for n in e.names:
            put(e.country, n, e.lei)
    for c in regs.companies.values():
        for n in (c.name, *c.previous_names):
            put("GB", n, c.company_number)
    for c in regs.quezal.companies.values():
        put("QZ", c.name, c.id)

    out: list[dict] = []

    def ask(name: str, country: str, eid: str, why: str) -> None:
        ids = index.get((country, _key(name)), set())
        if why != "typo" and ids != same.get(eid, {eid}):
            return  # this spelling could mean two companies: not a fair question
        out.append({"name": name, "country": country, "ids": sorted(same.get(eid, {eid})), "why": why,
                    "status": answers.sanction_status(regs, eid)})  # fmt: skip

    linked = sorted(lei for lei, _ in answers.uk_links(regs))
    for lei in linked[::55]:
        ask(regs.gleif[lei].legal_name.lower().replace(".", ""), "GB", lei, "spelling")
    renamed = [n for n in sorted(regs.companies) if regs.companies[n].previous_names]
    for n in renamed[::60][:4]:
        ask(regs.companies[n].previous_names[0], "GB", n, "previous name")

    def plain(s: str) -> str:
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

    abroad = sorted((x for x in regs.gleif.values() if x.country not in ("GB", "RU") and not x.legal_name.isascii()
                     and len(plain(x.legal_name)) > 0.9 * len(x.legal_name)), key=lambda x: x.lei)  # fmt: skip
    for e in abroad[::25][:4]:
        ask(plain(e.legal_name), e.country, e.lei, "accents")
    typos = [lei for lei in linked[7::23] if _typo(regs.gleif[lei].legal_name) != regs.gleif[lei].legal_name]
    for lei in typos[:3]:
        ask(_typo(regs.gleif[lei].legal_name), "GB", lei, "typo")
    for lei, name, country in [("549300LCJ1UJXHYBWI24", "PJSC LUKOIL", "RU"),
                               ("5299007PQV6X4DPL9Y20", "Lukoil International GmbH", "AT"),
                               ("5493008CGNE47EJ89474", "Eiger Shipping SA", "CH"),
                               ("5493007XYP6TMCO8L243", "LME Trading DMCC", "AE")]:  # fmt: skip
        ask(name, country, lei, "sanctions")
    truth = regs.quezal.truth
    for s in truth["schemes"]:
        ask(regs.quezal.companies[s["target"]].name, "QZ", s["target"], "hidden owner")
        ask(regs.quezal.companies[s["controller"]].name.upper(), "QZ", s["controller"], "on the watch list")
    for pair in truth["near_duplicates"][:2]:
        for cid in pair:
            ask(regs.quezal.companies[cid].name, "QZ", cid, "near duplicate")
    for name, country in UNKNOWN:
        listed = any(_key(n) == _key(name) for d in regs.sanctions.values() for n in d.names)
        listed |= any(_key(n) == _key(name) for w in regs.quezal.watchlist for n in w.names)
        out.append({"name": name, "country": country, "ids": [], "why": "in no register",
                    "status": "listed" if listed else "no listing found"})  # fmt: skip
    return out


def run(module: ModuleType) -> list[Result]:
    regs = load()
    screening = Result("Screening answers", L_EVAL)
    practice = Result("Hidden controllers, practice register", L_EVAL)
    final = Result("Hidden controllers, final register", L_EVAL)
    layers = Result("Read it from the bottom", L_EVAL)
    results = [screening, practice, final, layers]

    try:
        qs = questions(regs)
        right = 0
        for q in qs:
            got = attempt(screening, module.screen, regs, q["name"], q["country"])
            if got is None:
                continue
            entity_ok = (got.get("entity") in q["ids"]) if q["ids"] else got.get("entity") is None
            ok = entity_ok and got.get("status") == q["status"]
            right += ok
            if not ok:
                screening.fail(f"{q['name']!r} ({q['country']}, {q['why']}): {got.get('entity')}, {got.get('status')!r}; "
                               f"want {q['ids'][0] if q['ids'] else None}, {q['status']!r}")  # fmt: skip
        screening.score = f"{right}/{len(qs)} suppliers"
        screening.passed = right >= BAR * len(qs) and not any("raised" in d for d in screening.details)
        if not screening.passed:
            screening.details.insert(0, f"Needs at least {BAR:.0%} right: the company and its status.")
    except NotStarted:
        screening.started = screening.passed = False

    try:
        listed = {c for c in answers.watchlist_matches(regs.quezal).values() if c}
        want = answers.hidden_controllers(regs.quezal, listed)
        got = attempt(practice, module.hidden_controllers, regs)
        if got is not None:
            got = {tuple(p) for p in got}
            for c, t in sorted(want - got):
                practice.fail(f"missed: {c} controls {t}")
            for c, t in sorted(got - want):
                practice.fail(f"not hidden control: {c} over {t}")
            tally(practice, len(want & got), len(want), "found") if got <= want else tally(
                practice, 0, len(want), "found"
            )
        final_regs = load("final")
        hashes = set(json.loads((final_regs.quezal.path / "answers.sha256.json").read_text())["hidden_controllers"])
        got = attempt(final, module.hidden_controllers, final_regs)
        if got is not None:
            mine = {answers.pair_hash(c, t) for c, t in got}
            found, wrong = len(mine & hashes), len(mine - hashes)
            final.score = f"{found}/{len(hashes)} found, {wrong} wrong"
            final.passed = found == len(hashes) and wrong == 0
            if not final.passed:
                final.details.append("The answers are hashed: you learn how many, never which.")
    except NotStarted:
        practice.started = practice.passed = final.started = final.passed = False

    try:
        right = 0
        for scores, want in LAYER_FIXTURES:
            got = attempt(layers, module.bottom_up, scores, BARS, none_ok=True)
            right += got == want
            if got != want:
                layers.fail(f"bottom_up({scores}) = {got!r}, want {want!r}")
        tally(layers, right, len(LAYER_FIXTURES), "fixtures")
    except NotStarted:
        layers.started = layers.passed = False
    return results
