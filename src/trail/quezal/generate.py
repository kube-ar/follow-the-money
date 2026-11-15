"""The Quezal register: a fictional offshore jurisdiction with planted control schemes.

Real registers rarely give exact stakes, almost never show circular ownership, and never say
which structures were built to hide someone. Quezal does all three, and the truth is known, so
recall can be measured exactly. Nothing here owns, or is owned by, a real company.

Each part of the world draws from its own random stream (`_rng(seed, part)`), so adding a part
later doesn't change the parts that already exist.
"""

from __future__ import annotations

import csv
import json
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import names

GENERATOR_VERSION = 4
SNAPSHOT = date(2026, 9, 30)  # the register extract is as of this day
NEWS_FROM, NEWS_UNTIL = date(2026, 6, 1), date(2026, 11, 10)
PATTERNS = ("split", "chain", "cycle")


def _rng(seed: int, part: str) -> random.Random:
    return random.Random(f"{seed}:{part}")


@dataclass
class Company:
    id: str
    name: str
    form: str
    sector: str
    incorporated_on: str
    status: str  # active | struck off
    struck_off_on: str
    agent_id: str
    previous_names: list[dict] = field(default_factory=list)


@dataclass
class Person:
    id: str
    name: str
    nominee: bool  # a professional director who sits on many boards


@dataclass
class Holding:
    holder_id: str
    company_id: str
    percent: float
    since: str
    until: str = ""


@dataclass
class Director:
    person_id: str
    company_id: str
    since: str


@dataclass
class Listing:
    id: str
    name: str
    aliases: list[str]
    designated_on: str
    reason: str


@dataclass
class Article:
    id: str
    published_on: str
    headline: str
    body: str


@dataclass
class World:
    seed: int
    agents: list[dict]
    people: list[Person] = field(default_factory=list)
    companies: list[Company] = field(default_factory=list)
    holdings: list[Holding] = field(default_factory=list)
    directors: list[Director] = field(default_factory=list)
    watchlist: list[Listing] = field(default_factory=list)
    articles: list[Article] = field(default_factory=list)
    truth: dict = field(default_factory=dict)

    def company(self, cid: str) -> Company:
        return next(c for c in self.companies if c.id == cid)

    def name_of(self, eid: str) -> str:
        for c in self.companies:
            if c.id == eid:
                return c.name
        return next(p.name for p in self.people if p.id == eid)

    def held(self, cid: str) -> float:
        return sum(h.percent for h in self.holdings if h.company_id == cid and not h.until)


def _day(rng: random.Random, start: date, end: date) -> str:
    return (start + timedelta(days=rng.randrange((end - start).days + 1))).isoformat()


def norm(name: str) -> str:
    """The comparison key the generator uses to keep names distinct."""
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    s = re.sub(r"\b(ibc|llc|ltd|limited|holdings ltd|foundation|the)\b", " ", s)
    return " ".join(s.split())


class _Namer:
    def __init__(self, rng: random.Random):
        self.rng, self.used = rng, set()

    def company(self, nouns: list[str] | None = None, form: str | None = None) -> tuple[str, str]:
        for _ in range(500):
            base = f"{self.rng.choice(names.PLACES)} {self.rng.choice(nouns or names.NOUNS)}"
            if norm(base) not in self.used:
                self.used.add(norm(base))
                f = form or self.rng.choice(names.FORMS)
                return f"{base} {f}", f
        raise RuntimeError("ran out of company names")

    def twin(self, base_name: str, form: str) -> str:
        """A different company whose name nearly matches an existing one."""
        stem = base_name.rsplit(" ", 2 if form == "Holdings Ltd" else 1)[0]
        for extra in ("Partners", "Group", "International", "Services", "Marine"):
            if extra in stem.split():
                continue
            candidate = f"{stem} {extra}"
            if norm(candidate) not in self.used:
                self.used.add(norm(candidate))
                return f"{candidate} {form}"
        raise RuntimeError("no twin name left")


def _people(world: World) -> None:
    rng = _rng(world.seed, "people")
    seen = set()
    while len(world.people) < 34:
        name = f"{rng.choice(names.FIRST_NAMES)} {rng.choice(names.LAST_NAMES)}"
        if name in seen:
            continue
        seen.add(name)
        world.people.append(Person(f"QP-{rng.randrange(1000, 9999)}", name, nominee=len(world.people) < 5))
    ids = set()
    for p in world.people:  # ids must be unique too
        while p.id in ids:
            p.id = f"QP-{rng.randrange(1000, 9999)}"
        ids.add(p.id)


def _new_company(world: World, rng: random.Random, namer: _Namer, ids: set[str], **kw) -> Company:
    name, form = namer.company(kw.pop("nouns", None), kw.pop("form", None))
    cid = f"QZ-{rng.randrange(100000, 999999)}"
    while cid in ids:
        cid = f"QZ-{rng.randrange(100000, 999999)}"
    ids.add(cid)
    company = Company(
        id=cid,
        name=name,
        form=form,
        sector=kw.pop("sector", rng.choice(names.SECTORS)),
        incorporated_on=_day(rng, date(1998, 1, 1), date(2024, 12, 31)),
        status="active",
        struck_off_on="",
        agent_id=kw.pop("agent_id", rng.choice(world.agents)["id"]),
    )
    world.companies.append(company)
    return company


def _hold(world: World, rng: random.Random, holder: str, company: Company, percent: float) -> None:
    since = _day(rng, date.fromisoformat(company.incorporated_on), SNAPSHOT - timedelta(days=30))
    world.holdings.append(Holding(holder, company.id, round(percent, 2), since))


def _ordinary(world: World, namer: _Namer, ids: set[str]) -> None:
    """Ordinary groups: an owner, a holding company, subsidiaries; minority investors here and there."""
    rng = _rng(world.seed, "ordinary")
    owners = [p for p in world.people if not p.nominee]
    for _ in range(22):
        top = _new_company(world, rng, namer, ids, nouns=["Holdings", "Capital", "Investments", "Partners"])
        founders = rng.sample(owners, rng.choice((1, 1, 2, 3)))
        shares = [100.0] if len(founders) == 1 else ([60.0, 40.0] if len(founders) == 2 else [40.0, 35.0, 25.0])
        for person, share in zip(founders, shares):
            _hold(world, rng, person.id, top, share)
        for _ in range(rng.randint(1, 4)):
            sub = _new_company(world, rng, namer, ids)
            stake = rng.choice((100.0, 100.0, 75.0, 60.0, 51.0))
            _hold(world, rng, top.id, sub, stake)
            if stake < 100 and rng.random() < 0.7:
                _hold(world, rng, rng.choice(owners).id, sub, 100.0 - stake)
            if rng.random() < 0.3:
                grand = _new_company(world, rng, namer, ids)
                _hold(world, rng, sub.id, grand, rng.choice((100.0, 80.0)))
    for _ in range(14):  # small standalone firms owned by people
        firm = _new_company(world, rng, namer, ids)
        _hold(world, rng, rng.choice(owners).id, firm, 100.0)
    # A benign cycle: two cooperatives that hold a little of each other. A loop proves nothing.
    a = _new_company(world, rng, namer, ids, nouns=["Fishing Cooperative"], form="Foundation", sector="fishing")
    b = _new_company(world, rng, namer, ids, nouns=["Growers Cooperative"], form="Foundation", sector="property")
    _hold(world, rng, a.id, b, 10.0)
    _hold(world, rng, b.id, a, 12.0)
    for c in (a, b):
        _hold(world, rng, rng.choice(owners).id, c, 30.0)
    world.truth["benign_cycle"] = sorted([a.id, b.id])
    # Near-duplicate names: different companies whose names almost match.
    pairs = []
    for c in rng.sample([c for c in world.companies if c.form != "Foundation"], 4):
        twin = _new_company(world, rng, namer, ids)
        twin.name = namer.twin(c.name, c.form)
        twin.form = c.form
        _hold(world, rng, rng.choice(owners).id, twin, 100.0)
        pairs.append(sorted([c.id, twin.id]))
    world.truth["near_duplicates"] = pairs
    for c in rng.sample(world.companies, 8):  # some firms are struck off
        c.status, c.struck_off_on = "struck off", _day(rng, date(2019, 1, 1), SNAPSHOT)


def _schemes(world: World, namer: _Namer, ids: set[str]) -> None:
    """Planted control schemes. Each hides who controls an operating company behind shells."""
    rng = _rng(world.seed, "schemes")
    agent = world.agents[0]["id"]  # the shells share a registered agent
    nominees = [p for p in world.people if p.nominee]
    owners = [p for p in world.people if not p.nominee]
    schemes = []
    for i, pattern in enumerate(PATTERNS, start=1):
        controller = _new_company(world, rng, namer, ids, nouns=["Holdings", "Capital"], form="IBC", agent_id=agent)
        _hold(world, rng, rng.choice(owners).id, controller, 100.0)
        target = _new_company(world, rng, namer, ids, nouns=["Shipping", "Bunkering", "Terminals", "Fuels", "Freight"],
                              form="LLC", sector=rng.choice(["shipping", "fuel trading", "port services"]))  # fmt: skip

        def shell() -> Company:
            return _new_company(world, rng, namer, ids, nouns=["Ventures", "Assets", "Trading", "Resources"],
                                form="IBC", agent_id=agent)  # fmt: skip

        shells: list[Company] = []
        if pattern == "split":  # two shells, each under 30% of the target, together a majority
            a, b = shell(), shell()
            shells = [a, b]
            _hold(world, rng, controller.id, a, 60.0)
            _hold(world, rng, controller.id, b, 55.0)
            _hold(world, rng, a.id, target, 28.0)
            _hold(world, rng, b.id, target, 26.0)
        elif pattern == "chain":  # a long chain of majority stakes
            a, b, c = shell(), shell(), shell()
            shells = [a, b, c]
            _hold(world, rng, controller.id, a, 100.0)
            _hold(world, rng, a.id, b, 75.0)
            _hold(world, rng, b.id, c, 80.0)
            _hold(world, rng, c.id, target, 52.0)
        else:  # a cross-holding between two shells blurs who holds whom
            a, b = shell(), shell()
            shells = [a, b]
            _hold(world, rng, controller.id, a, 60.0)
            _hold(world, rng, a.id, b, 40.0)
            _hold(world, rng, b.id, a, 35.0)
            _hold(world, rng, controller.id, b, 30.0)
            _hold(world, rng, a.id, target, 29.0)
            _hold(world, rng, b.id, target, 24.0)
        for s in shells:  # the rest of each shell sits with outside holders, if anyone
            free = round(100.0 - world.held(s.id), 2)
            if free > 0:
                _hold(world, rng, rng.choice(owners).id, s, free)
        free = round(100.0 - world.held(target.id), 2)
        third = round(free / 3, 2)
        for person, share in zip(rng.sample(owners, 3), (third, third, round(free - 2 * third, 2))):
            _hold(world, rng, person.id, target, share)  # small outside shareholders hold the rest
        for c in [controller, target, *shells]:
            world.directors.append(Director(rng.choice(nominees).id, c.id, c.incorporated_on))
        schemes.append({"id": f"S{i}", "pattern": pattern, "controller": controller.id, "target": target.id,
                        "shells": [s.id for s in shells]})  # fmt: skip
    world.truth["schemes"] = schemes


def _directors(world: World) -> None:
    rng = _rng(world.seed, "directors")
    nominees = [p for p in world.people if p.nominee]
    owners = [p for p in world.people if not p.nominee]
    seated = {d.company_id for d in world.directors}
    for c in world.companies:
        if c.id in seated:
            continue
        pool = nominees if rng.random() < 0.35 else owners  # nominees also sit on ordinary boards
        for person in rng.sample(pool, rng.choice((1, 1, 2))):
            world.directors.append(Director(person.id, c.id, c.incorporated_on))


def _variant(rng: random.Random, name: str, form: str) -> str:
    base = name[: -len(form)].strip()
    first, *rest = base.split(" ", 1)
    options = [
        base.upper() + " LIMITED",
        base.replace(" ", "-", 1).upper(),
        base + (" Ltd" if form != "Holdings Ltd" else ""),
        (first + (rest[0].lower() if rest else "")).upper() + " " + form.upper(),
    ]
    return rng.choice(options)


def _watchlist(world: World) -> None:
    """The Quezal Financial Authority's designations: names as the authority spelled them."""
    rng = _rng(world.seed, "watchlist")
    matches = {}
    listed = [world.company(s["controller"]) for s in world.truth["schemes"]]
    for n, c in enumerate(listed, start=1):
        lid = f"QFA-{n:02d}"
        world.watchlist.append(Listing(lid, _variant(rng, c.name, c.form), [_variant(rng, c.name, c.form)],
                                       _day(rng, date(2024, 1, 1), SNAPSHOT), "financing of an embargoed fuel trade"))  # fmt: skip
        matches[lid] = c.id
    # A designated firm abroad, with no company in the register: it must match nothing.
    world.watchlist.append(Listing("QFA-04", "Varnholt Bunker Supply GmbH", [], _day(rng, date(2024, 1, 1), SNAPSHOT),
                                   "supply of fuel to embargoed vessels"))  # fmt: skip
    matches["QFA-04"] = None
    # A designation whose name is one letter away from an ordinary company's twin: a trap for loose matching.
    pair = world.truth["near_duplicates"][0]  # list the one of the pair that holds no stakes: it controls nothing
    trap = next(world.company(x) for x in pair if not any(h.holder_id == x for h in world.holdings))
    world.watchlist.append(Listing("QFA-05", trap.name.replace(trap.form, "").strip().upper() + " (IN LIQUIDATION)",
                                   [], _day(rng, date(2024, 1, 1), SNAPSHOT), "fraud"))  # fmt: skip
    matches["QFA-05"] = trap.id
    world.truth["watchlist"] = matches
    rng.shuffle(world.watchlist)


def _gazette(world: World) -> None:
    """The Quezal Gazette: short news items, written from the facts so every claim is known.

    Some report deals already in the register; some report deals the register doesn't show yet
    (after the snapshot, or agreed but not completed); some report old stakes long after the fact.
    Each item makes one claim. The truth lists its mentions (every occurrence) and its claim."""
    rng = _rng(world.seed, "gazette")
    owners = [p for p in world.people if not p.nominee]
    agents = {a["id"]: a for a in world.agents}
    items: list[tuple[str, str, str, list, dict]] = []
    used: set[tuple[str, str]] = set()

    def person(pid: str) -> Person:
        return next(p for p in world.people if p.id == pid)

    def short(c: Company) -> str:  # how the press tends to name a company: in full, without the form, or by place
        place = next((pl for pl in names.PLACES if c.name.startswith(pl + " ")), None)
        return rng.choice([c.name, c.name.replace(f" {c.form}", ""), c.name.replace(f" {c.form}", ""), place or c.name])

    def label(x) -> str:
        return x.name if isinstance(x, Person) else short(x)

    def context(c: Company) -> list[str]:
        options = [
            f"{c.name} works in {c.sector} and is registered through {agents[c.agent_id]['name']}.",
            f"Founded in {c.incorporated_on[:4]}, {c.name} works in {c.sector}.",
            "Neither side replied to the Gazette's questions.",
            "The price was not disclosed.",
        ]
        return rng.sample(options, rng.choice((1, 2)))

    def add(published: str, headline: str, lead: str, mentions: list, claim: dict, company: Company) -> None:
        text = " ".join([lead, *context(company)])
        mentions = mentions + [(company.name, company.id)]
        items.append((published, headline, text, mentions, claim))

    def stake(buyer, company: Company, percent: float, seller, when: str, wrap: str, published: str | None = None):
        b, c, s = label(buyer), short(company), label(seller) if seller else ""
        lead = wrap.format(buyer=b, company=c, pct=f"{percent:g}", seller=s, since=_month(when))
        mentions = [(b, buyer.id), (c, company.id)] + ([(s, seller.id)] if seller else [])
        claim = {"kind": "stake", "buyer": buyer.id, "seller": seller.id if seller else None, "company": company.id,
                 "percent": percent, "date": when}  # fmt: skip
        used.add((buyer.id, company.id))
        add(published or when, f"{b} and {c}", lead, mentions, claim, company)

    with_seller = [
        "{buyer} has bought a {pct}% stake in {company} from {seller}, the companies said on Tuesday.",
        "{seller} sold {pct}% of {company} to {buyer}, according to a filing seen by the Gazette.",
        "In a deal completed this week, {buyer} acquired {pct} per cent of {company}. The seller was {seller}.",
    ]
    plain = [
        "{buyer} now holds {pct}% of {company} after subscribing for new shares.",
        "{company} issued new shares to {buyer}, which takes a {pct}% stake.",
    ]
    # 1. Each scheme's target: an outside holder sells to a shell after the snapshot.
    for s in world.truth["schemes"]:
        target, shell = world.company(s["target"]), world.company(s["shells"][0])
        h = next(h for h in world.holdings if h.company_id == target.id and h.holder_id.startswith("QP-"))
        stake(shell, target, h.percent, person(h.holder_id), _day(rng, SNAPSHOT + timedelta(days=5), NEWS_UNTIL),
              rng.choice(with_seller))  # fmt: skip
    # 2. Ordinary deals before the snapshot: the register shows them.
    for h in rng.sample([h for h in world.holdings if not h.until and h.percent < 100], 12):
        buyer = world.company(h.holder_id) if h.holder_id.startswith("QZ-") else person(h.holder_id)
        h.since = _day(rng, NEWS_FROM, SNAPSHOT - timedelta(days=1))  # the register shows the stake from this deal on
        stake(buyer, world.company(h.company_id), h.percent, None, h.since, rng.choice(plain))
    # 3. Old stakes, reported long after the fact: published now, true for years.
    old = [
        h for h in world.holdings if not h.until and h.since < "2024-01-01" and (h.holder_id, h.company_id) not in used
    ]
    for h in rng.sample(old, 3):
        buyer = world.company(h.holder_id) if h.holder_id.startswith("QZ-") else person(h.holder_id)
        stake(buyer, world.company(h.company_id), h.percent, None, h.since,
              "Court papers filed this week show that {buyer} has owned {pct}% of {company} since {since}.",
              published=_day(rng, SNAPSHOT + timedelta(days=1), NEWS_UNTIL))  # fmt: skip
    # 4. Agreed before the snapshot, not completed: the register can't show it yet.
    for _ in range(2):
        h = rng.choice([h for h in world.holdings if not h.until and h.holder_id.startswith("QP-") and h.percent >= 10
                        and h.company_id not in {s["target"] for s in world.truth["schemes"]}])  # fmt: skip
        buyer = rng.choice([p for p in owners if (p.id, h.company_id) not in used and p.id != h.holder_id])
        when = _day(rng, NEWS_FROM, SNAPSHOT - timedelta(days=20))
        stake(buyer, world.company(h.company_id), h.percent, person(h.holder_id), when,
              "{buyer} has agreed to buy {pct}% of {company} from {seller}. The deal still needs approval from the "
              "Quezal Financial Authority.")  # fmt: skip
    # 5. People buy into firms after the snapshot.
    for _ in range(5):
        company = rng.choice([c for c in world.companies if c.status == "active" and world.held(c.id) <= 85])
        buyer = rng.choice([p for p in owners if (p.id, company.id) not in used])
        stake(buyer, company, float(rng.choice((5, 7.5, 10, 12))), None,
              _day(rng, SNAPSHOT + timedelta(days=1), NEWS_UNTIL), rng.choice(plain))  # fmt: skip
    # 6. Renamings announced after the snapshot: the register still has the old name.
    for c in rng.sample([c for c in world.companies if c.status == "active"], 3):
        new = f"{rng.choice(names.PLACES)} {rng.choice(names.NOUNS)} {c.form}"
        when = _day(rng, SNAPSHOT + timedelta(days=1), NEWS_UNTIL)
        lead = f"{c.name} will trade as {new} from next month, its board said."
        add(when, f"{c.name.split(' ')[0]} changes its name", lead, [(new, c.id)],
            {"kind": "rename", "company": c.id, "new_name": new, "date": when}, c)  # fmt: skip
    # 7. Board appointments: news, but no stake.
    for d in rng.sample(world.directors, 4):
        p, company = person(d.person_id), world.company(d.company_id)
        when = _day(rng, NEWS_FROM, NEWS_UNTIL)
        add(when, f"New director at {short(company)}", f"{p.name} joins the board of {company.name}.",
            [(p.name, p.id)], {"kind": "director", "person": p.id, "company": company.id, "date": when}, company)  # fmt: skip

    items.sort(key=lambda x: (x[0], x[1]))
    gold: dict[str, dict] = {}
    for n, (published, headline, text, mentions, claim) in enumerate(items, start=1):
        aid = f"G-{n:03d}"
        world.articles.append(Article(aid, published, headline, text))
        spans: list[dict] = []
        for surface, eid in sorted(set(mentions), key=lambda m: -len(m[0])):  # longest first, no overlaps
            for m in re.finditer(re.escape(surface), text):
                if all(m.end() <= s["start"] or m.start() >= s["end"] for s in spans):
                    spans.append({"text": surface, "start": m.start(), "end": m.end(), "entity": eid})
        gold[aid] = {"mentions": sorted(spans, key=lambda s: s["start"]), "claim": claim}
    world.truth["articles"] = gold


def _month(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d:%B} {d.year}"


def _pending(world: World) -> list[str]:
    """Items whose claim the register (as of the snapshot) doesn't reflect yet."""
    snapshot = SNAPSHOT.isoformat()
    out = []
    for aid, g in world.truth["articles"].items():
        c = g["claim"]
        if c["kind"] == "stake":
            shown = any(h.holder_id == c["buyer"] and h.company_id == c["company"] and abs(h.percent - c["percent"]) < 0.01
                        and h.since <= snapshot for h in world.holdings)  # fmt: skip
            out += [] if shown else [aid]
        elif c["kind"] == "rename" and world.company(c["company"]).name != c["new_name"]:
            out.append(aid)
    return sorted(out)


def build(seed: int) -> World:
    world = World(seed, agents=[{"id": f"QA-{i + 1}", "name": n, "address": a} for i, (n, a) in
                                enumerate(names.AGENTS)])  # fmt: skip
    namer, ids = _Namer(_rng(seed, "names")), set()
    _people(world)
    _ordinary(world, namer, ids)
    _schemes(world, namer, ids)
    _directors(world)
    _watchlist(world)
    _gazette(world)
    world.truth["pending"] = _pending(world)
    world.truth["snapshot"] = SNAPSHOT.isoformat()
    return world


def _csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def export(world: World, folder: Path, hide_truth: bool = False) -> None:
    """Write the register as a data release: CSVs, the Gazette as JSON lines, and the truth."""
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = SNAPSHOT.isoformat()
    _csv(folder / "agents.csv", world.agents)
    _csv(folder / "companies.csv", [{**{k: v for k, v in asdict(c).items() if k != "previous_names"},
                                    "previous_names": json.dumps(c.previous_names) if c.previous_names else ""}
                                   for c in sorted(world.companies, key=lambda c: c.id)])  # fmt: skip
    _csv(folder / "people.csv", [{"id": p.id, "name": p.name} for p in sorted(world.people, key=lambda p: p.id)])
    _csv(folder / "shareholdings.csv", [asdict(h) for h in sorted(world.holdings, key=lambda h: (h.company_id, h.holder_id))
                                        if h.since <= snapshot])  # fmt: skip
    _csv(
        folder / "directors.csv",
        [asdict(d) for d in sorted(world.directors, key=lambda d: (d.company_id, d.person_id))],
    )
    _csv(folder / "watchlist.csv", [{**asdict(w), "aliases": json.dumps(w.aliases)} for w in world.watchlist])
    with (folder / "gazette.jsonl").open("w", encoding="utf-8") as f:
        for a in world.articles:
            f.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    meta = {"jurisdiction": "Quezal (fictional, code QZ)", "snapshot": snapshot, "seed": None if hide_truth else world.seed,
            "generator_version": GENERATOR_VERSION}  # fmt: skip
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if not hide_truth:
        (folder / "truth.json").write_text(json.dumps(world.truth, indent=1) + "\n", encoding="utf-8")


def build_final(folder: Path) -> None:
    """The final register: built from a secret seed (TRAIL_FINAL_SEED), shipped without its truth.

    Only hashes of the answers ship, so you learn how many hidden controllers you found, never which."""
    import hashlib
    import os

    seed = os.environ.get("TRAIL_FINAL_SEED")
    if not seed:
        raise SystemExit("The final register's seed is secret: set TRAIL_FINAL_SEED to rebuild it.")
    world = build(int(seed))
    export(world, folder, hide_truth=True)
    pairs = sorted(f"trail:{s['controller']}>{s['target']}" for s in world.truth["schemes"])
    hashes = [hashlib.sha256(p.encode()).hexdigest() for p in pairs]
    (folder / "answers.sha256.json").write_text(json.dumps({"hidden_controllers": hashes}, indent=1) + "\n",
                                                 encoding="utf-8")  # fmt: skip
