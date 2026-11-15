"""Supplier requests for the due-diligence agent, and the decision the policy calls for.

    from trail.requests import load_requests, truth_for
    for request in load_requests("practice"):
        print(request.name, request.country, truth_for(request).decision)

Packs: practice (6), standard (12), hard (12) on the practice Quezal register and the real slice;
final (8) on the final Quezal register, with its decisions stored only as hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

from . import answers
from .desk import Request, key
from .registers import DATA, Registers, load, load_quezal

REQUESTS = DATA / "requests"
PACKS = ("practice", "standard", "hard", "final")
LUKOIL = "549300LCJ1UJXHYBWI24"
UNKNOWN = [("Pellow Rock Dairy Supplies Ltd", "GB"), ("Tessaro Quantum Instruments GmbH", "DE"),
           ("Wexmoor Precision Castings Ltd", "GB"), ("Amberley Sound Ceramics SARL", "FR")]  # fmt: skip
NAME_ONLY = ("Varnholt Bunker Supply GmbH", "DE")  # on Quezal's watch list, in no register
NEAR_MISSES = [
    "549300MG5Q5VOTHPK831",
    "549300MGDWB06O797V30",
]  # names close to designations: BP Energy, Eni International


@dataclass(frozen=True)
class Truth:
    decision: str | None
    entity: str | None
    rule: str | None
    digest: str | None = None  # final pack: sha256 of the decision instead of the decision

    def right(self, decision: str) -> bool:
        if self.digest:
            return digest(self.request_id, decision) == self.digest
        return decision == self.decision

    request_id: str = ""


def digest(request_id: str, decision: str) -> str:
    return hashlib.sha256(f"trail:{request_id}:{decision}".encode()).hexdigest()


# ── The policy, as code ───────────────────────────────────────────────────────


def pending_companies(truth: dict) -> set[str]:
    out = set()
    for aid in truth.get("pending", []):
        claim = truth["articles"][aid]["claim"]
        if claim["kind"] in ("stake", "rename"):
            out.add(claim["company"])
    return out


def on_a_list(regs: Registers, name: str) -> bool:
    k = key(name)
    return any(key(n) == k for d in regs.sanctions.values() for n in d.names) or any(
        key(n) == k for w in regs.quezal.watchlist for n in w.names
    )


def decide(regs: Registers, entity: str | None, name: str) -> tuple[str, str]:
    """(decision, rule) for a supplier, by the policy in trail.desk.POLICY."""
    if entity is None:
        return ("reject", "P1") if on_a_list(regs, name) else ("escalate", "P2")
    if answers.sanction_status(regs, entity) != "no listing found":
        return "reject", "P1"
    q = regs.quezal
    if entity in q.companies:
        held = sum(h.percent for h in answers.holdings(q) if h.company_id == entity)
        if held < 75:
            return "escalate", "P3"
        if entity in pending_companies(q.truth or {}):
            return "escalate", "P4"
    return "approve", "P5"


# ── Building packs ────────────────────────────────────────────────────────────


LEGAL = {"LIMITED", "LTD", "PLC", "LLC", "IBC", "FOUNDATION", "HOLDINGS", "GMBH", "SA", "BV", "NV", "INC"}


def _typo(name: str) -> str:
    """Two letters swapped in the name's longest word that isn't a legal form."""
    words = name.split()
    i = max(range(len(words)), key=lambda n: (words[n].upper().strip(".,") not in LEGAL and "," not in words[n],
                                              len(words[n])))  # fmt: skip
    w = words[i]
    if len(w) < 6:
        return name
    j = len(w) // 2
    words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
    return " ".join(words)


QUESTIONNAIRES = [
    "We are an established {sector} business. All our shareholders are disclosed in the public register.",
    "Family-run since {year}. We have no links to any sanctioned person or company.",
    "Our ultimate owner is a listed group with a strong compliance record.",
    "We are fully independent: no shareholder holds more than 10% of the company.",
]


def _pools(regs: Registers) -> dict[str, list]:
    status = {x: answers.sanction_status(regs, x) for x in list(regs.gleif) + list(regs.quezal.companies)}
    q, truth = regs.quezal, regs.quezal.truth or {}
    pend = pending_companies(truth)
    held = {c: sum(h.percent for h in answers.holdings(q) if h.company_id == c) for c in q.companies}
    lukoil = answers.group(regs, LUKOIL)
    schemes = truth.get("schemes", [])
    return {
        "real_ok": sorted(lei for lei, _ in answers.uk_links(regs) if status[lei] == "no listing found"),
        "renamed": sorted(
            lei for lei, n in answers.uk_links(regs) if key(regs.gleif[lei].legal_name) != key(regs.companies[n].name)
        ),  # fmt: skip
        "lukoil": sorted(x for x in lukoil if regs.gleif[x].legal_name.isascii() or regs.gleif[x].other_names),
        "targets": [s["target"] for s in schemes],
        "controllers": [s["controller"] for s in schemes],
        "shells": [x for s in schemes for x in s["shells"]],
        "opaque": sorted(c for c in q.companies if held[c] < 75 and status[c] == "no listing found"),
        "pending": sorted(c for c in pend if status[c] == "no listing found" and held[c] >= 75),
        "qz_ok": sorted(
            c
            for c in q.companies
            if status[c] == "no listing found" and held[c] >= 75 and c not in pend and q.companies[c].status == "active"
        ),  # fmt: skip
        "twins": [pair for pair in truth.get("near_duplicates", [])],
    }


def _ascii_name(regs: Registers, lei: str) -> str:
    e = regs.gleif[lei]
    if e.legal_name.isascii():
        return e.legal_name
    return next((n for n in (*e.other_names, *e.transliterated_names) if n.isascii()), e.legal_name)


def build(pack: str, regs: Registers, register: str) -> list[tuple[Request, Truth]]:
    rng = random.Random(f"requests:{pack}")
    p = _pools(regs)
    q = regs.quezal
    rows: list[tuple[str, str, str | None]] = []  # (name as typed, country, entity)

    def real(lei: str, how: str) -> None:
        name = _ascii_name(regs, lei)
        name = {"exact": name, "lower": name.lower().replace(".", ""), "typo": _typo(name)}[how]
        rows.append((name, regs.gleif[lei].country, lei))

    def qz(cid: str, how: str = "exact") -> None:
        name = q.companies[cid].name
        rows.append(({"exact": name, "upper": name.upper(), "typo": _typo(name)}[how], "QZ", cid))

    if pack == "practice":
        real(p["real_ok"][0], "exact")
        real("5299007PQV6X4DPL9Y20" if "5299007PQV6X4DPL9Y20" in regs.gleif else p["lukoil"][0], "exact")
        qz(p["targets"][0])
        rows.append((*UNKNOWN[0], None))
        qz(p["opaque"][0])
        qz(p["qz_ok"][0])
    elif pack == "standard":
        for lei, how in zip(rng.sample(p["real_ok"], 3), ("lower", "typo", "exact")):
            real(lei, how)
        renamed = rng.choice(p["renamed"])
        number = next(n for lei, n in answers.uk_links(regs) if lei == renamed)
        rows.append((regs.companies[number].name, "GB", renamed))  # the name Companies House uses now
        for lei in ("5493008CGNE47EJ89474", "5493007XYP6TMCO8L243"):
            real(lei, "exact")
        qz(p["controllers"][1], "upper")
        qz(p["pending"][0])
        qz(p["qz_ok"][1])
        rows.append((*UNKNOWN[1], None))
        rows.append((*NAME_ONLY, None))
        qz(p["shells"][0])
    elif pack == "hard":
        for lei in rng.sample(p["real_ok"], 2):
            real(lei, "typo")
        for lei in NEAR_MISSES:
            real(lei, "exact")  # a near-miss designation must not reject these
        real(rng.choice([x for x in p["lukoil"] if regs.gleif[x].country == "NL"]), "lower")
        for pair in p["twins"][:2]:
            qz(rng.choice(pair))  # one of two near-identical names: pick the right company
        if len(p["pending"]) > 1:
            qz(p["pending"][1], "typo")
        qz(p["opaque"][-1], "upper")
        qz(p["targets"][2], "typo")
        rows.append((*UNKNOWN[2], None))
        qz(p["qz_ok"][2])
    else:  # final
        real(rng.choice(p["real_ok"]), "typo")
        real(rng.choice([x for x in p["lukoil"] if x != LUKOIL]), "exact")
        qz(p["targets"][1])
        qz(p["controllers"][0], "upper")
        qz(p["opaque"][0])
        qz(p["pending"][0] if p["pending"] else p["qz_ok"][3])
        qz(p["qz_ok"][4])
        rows.append((*UNKNOWN[3], None))
    out = []
    for n, (name, country, entity) in enumerate(rows, start=1):
        rid = f"{pack}-{n:02d}"
        sector = q.companies[entity].sector if entity in q.companies else "industrial"
        text = rng.choice(QUESTIONNAIRES).format(sector=sector, year=rng.randrange(1960, 2015))
        request = Request(rid, name, country, rng.choice((40_000, 120_000, 450_000, 2_000_000)), text, register)
        decision, rule = decide(regs, entity, name)
        out.append((request, Truth(decision, entity, rule, request_id=rid)))
    return out


def write_pack(pack: str, items: list[tuple[Request, Truth]], hide: bool = False) -> None:
    REQUESTS.mkdir(parents=True, exist_ok=True)
    (REQUESTS / f"{pack}.json").write_text(json.dumps([asdict(r) for r, _ in items], indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")  # fmt: skip
    if hide:
        hashes = {r.id: digest(r.id, t.decision) for r, t in items}
        (REQUESTS / f"{pack}.sha256.json").write_text(json.dumps(hashes, indent=1) + "\n", encoding="utf-8")
    else:
        truth = {r.id: {"decision": t.decision, "entity": t.entity, "rule": t.rule} for r, t in items}
        (REQUESTS / f"{pack}.truth.json").write_text(json.dumps(truth, indent=1) + "\n", encoding="utf-8")


def build_all() -> None:
    regs = load("practice")
    for pack in ("practice", "standard", "hard"):
        write_pack(pack, build(pack, regs, "practice"))
    (REQUESTS / "history.json").write_text(json.dumps(build_history(regs), indent=1) + "\n", encoding="utf-8")
    seed = os.environ.get("TRAIL_FINAL_SEED")
    if not seed:
        print("final pack skipped: set TRAIL_FINAL_SEED to rebuild it")
        return
    from .quezal.generate import build as build_world
    from .quezal.generate import export

    with tempfile.TemporaryDirectory() as d:  # the final register with its truth, only while building
        export(build_world(int(seed)), Path(d))
        base = load("final")
        with_truth = Registers(
            base.gleif, base.relationships, base.companies, base.psc, base.sanctions, load_quezal(Path(d))
        )
        write_pack("final", build("final", with_truth, "final"), hide=True)


# ── Loading ───────────────────────────────────────────────────────────────────


@cache
def load_requests(pack: str) -> tuple[Request, ...]:
    path = REQUESTS / f"{pack}.json"
    if not path.exists():
        raise FileNotFoundError(f"No request pack {pack!r}: {', '.join(PACKS)}")
    return tuple(Request(**r) for r in json.loads(path.read_text(encoding="utf-8")))


@cache
def _truths(pack: str) -> dict[str, Truth]:
    labeled = REQUESTS / f"{pack}.truth.json"
    if labeled.exists():
        data = json.loads(labeled.read_text(encoding="utf-8"))
        return {rid: Truth(t["decision"], t["entity"], t["rule"], request_id=rid) for rid, t in data.items()}
    hashed = REQUESTS / f"{pack}.sha256.json"
    if hashed.exists():
        data = json.loads(hashed.read_text(encoding="utf-8"))
        return {rid: Truth(None, None, None, digest=h, request_id=rid) for rid, h in data.items()}
    return {}


def truth_for(request: Request) -> Truth | None:
    return _truths(request.id.rsplit("-", 1)[0]).get(request.id)


# ── Past decisions (agent 3) ──────────────────────────────────────────────────


def build_history(regs: Registers) -> list[dict]:
    """Ten approvals made before the register's snapshot, with the facts each one relied on then.

    Companies whose stakes changed this summer were approved in May or June; the rest later."""
    rng = random.Random("history")
    q, p = regs.quezal, _pools(regs)
    changed = sorted(
        {h.company_id for h in answers.holdings(q) if "2026-06-01" <= h.since <= q.snapshot} & set(p["qz_ok"])
    )
    picks = rng.sample(changed, 4) + rng.sample(p["pending"], min(3, len(p["pending"])))
    picks += rng.sample([c for c in p["qz_ok"] if c not in picks], 10 - len(picks))
    out = []
    for n, cid in enumerate(sorted(picks), start=1):
        month = rng.choice(["05", "06"] if cid in changed else ["07", "08", "09"])
        decided = f"2026-{month}-{rng.randrange(1, 28):02d}"
        facts = [{"subject": h.holder_id, "predicate": "holds", "object": cid, "value": h.percent, "valid_from": h.since}
                 for h in answers.holdings(q) if h.company_id == cid and h.since <= decided]  # fmt: skip
        facts.append({"subject": cid, "predicate": "named", "object": q.companies[cid].name, "value": None,
                      "valid_from": q.companies[cid].incorporated_on})  # fmt: skip
        out.append({"id": f"H-{n:02d}", "entity": cid, "name": q.companies[cid].name, "decision": "approve",
                    "decided_on": decided, "facts": facts})  # fmt: skip
    return out


def stale_decisions(regs: Registers, history: list[dict]) -> list[str]:
    """Past approvals whose company changed after the decision: a stake in the register since a later
    date, or a Gazette claim (a stake or a new name) dated after it."""
    q, truth = regs.quezal, regs.quezal.truth or {}
    out = []
    for h in history:
        c, day = h["entity"], h["decided_on"]
        later = any(x.since > day for x in answers.holdings(q) if x.company_id == c)
        later |= any(g["claim"].get("company") == c and g["claim"]["kind"] in ("stake", "rename") and g["claim"]["date"] > day
                     for g in truth.get("articles", {}).values())  # fmt: skip
        if later:
            out.append(h["id"])
    return out


def load_history() -> list[dict]:
    return json.loads((REQUESTS / "history.json").read_text(encoding="utf-8"))
