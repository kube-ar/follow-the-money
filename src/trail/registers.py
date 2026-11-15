"""Load the registers: three real ones (a frozen slice) and the fictional Quezal register.

    from trail.registers import load
    regs = load()                      # the real slice + Quezal's practice register
    regs.gleif["213800LH1BZH3DI6G760"].legal_name     # 'BP P.L.C.'
    regs.quezal.companies["QZ-601800"].name

Every source keeps its own ids, as it does in the real world: a GLEIF entity has an LEI, a
Companies House company a company number, a designation a UK Sanctions List id, a Quezal company
a QZ- number. Nothing here links them for you: that's the work.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QUEZAL = DATA / "quezal"


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _json(value: str, default):
    return json.loads(value) if value else default


# --- GLEIF -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GleifEntity:
    lei: str
    legal_name: str
    language: str
    other_names: tuple[str, ...]  # previous, alternative-language and trading names
    transliterated_names: tuple[str, ...]
    country: str  # ISO code of the legal address
    city: str
    jurisdiction: str
    legal_form: str
    registration_authority: str  # RA000585 is Companies House
    registration_number: str
    category: str
    entity_status: str
    registration_status: str  # ISSUED, LAPSED (not renewed), …
    created_on: str
    last_update: str

    @property
    def names(self) -> tuple[str, ...]:
        return (self.legal_name, *self.other_names, *self.transliterated_names)


@dataclass(frozen=True)
class GleifRelationship:
    child_lei: str
    parent_lei: str
    type: str  # direct | ultimate (as GLEIF reports it: the parent that consolidates at the top)
    registration_status: str
    start_date: str
    percentage: float | None  # accounting consolidation, when the entity reported it
    accounting_standard: str
    validation_source: str


# --- Companies House ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChCompany:
    company_number: str
    name: str
    category: str
    status: str
    country_of_origin: str
    incorporated_on: str
    dissolved_on: str
    post_town: str
    postcode: str
    sic: str
    previous_names: tuple[str, ...]


BAND = re.compile(r"ownership-of-shares-(\d+)-to-(\d+)-percent|ownership-of-shares-more-than-(\d+)-percent")


@dataclass(frozen=True)
class Psc:
    """A person with significant control, as Companies House records it.

    kind: corporate (a company), legal-person (a government body, a society…), individual (a
    natural person, kept anonymous here), statement (no PSC, or not identified yet), exemptions.
    """

    company_number: str
    psc_id: str
    kind: str
    name: str
    registration_number: str
    country_registered: str
    legal_form: str
    natures_of_control: tuple[str, ...]
    notified_on: str
    ceased_on: str
    statement: str

    @property
    def active(self) -> bool:
        return not self.ceased_on

    @property
    def share_band(self) -> tuple[float, float] | None:
        """The ownership band as fractions, e.g. (0.75, 1.0); None when the record gives no share band.

        Companies House bands are "more than 25% up to 50%", "more than 50% up to 75%" and
        "75% or more": the bounds here are those numbers, so 25-to-50 is (0.25, 0.50).
        """
        for n in self.natures_of_control:
            m = BAND.search(n)
            if m and m.group(1):
                return int(m.group(1)) / 100, int(m.group(2)) / 100
            if m and m.group(3):
                return int(m.group(3)) / 100, 1.0
        return None


# --- UK Sanctions List -------------------------------------------------------------------------


@dataclass(frozen=True)
class Designation:
    unique_id: str
    name: str
    aliases: tuple[str, ...]
    non_latin_names: tuple[str, ...]
    regime: str
    designated_on: str
    source: str
    entity_type: str
    registration_numbers: tuple[str, ...]
    countries: tuple[str, ...]
    parent_companies: str
    subsidiaries: str
    last_updated: str

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases, *self.non_latin_names)


# --- Quezal (fictional) ------------------------------------------------------------------------


@dataclass(frozen=True)
class QzCompany:
    id: str
    name: str
    form: str
    sector: str
    incorporated_on: str
    status: str
    struck_off_on: str
    agent_id: str
    previous_names: tuple[str, ...]


@dataclass(frozen=True)
class QzHolding:
    holder_id: str  # a QZ- company or a QP- person
    company_id: str
    percent: float
    since: str
    until: str


@dataclass(frozen=True)
class QzListing:
    id: str
    name: str
    aliases: tuple[str, ...]
    designated_on: str
    reason: str

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class Article:
    id: str
    published_on: str
    headline: str
    body: str


@dataclass(eq=False)  # compared and hashed by identity: one object per loaded register
class Quezal:
    name: str
    path: Path
    snapshot: str
    companies: dict[str, QzCompany]
    people: dict[str, str]  # id → name
    agents: dict[str, dict]
    holdings: list[QzHolding]
    directors: list[tuple[str, str, str]]  # (person, company, since)
    watchlist: list[QzListing]
    gazette: list[Article]

    @property
    def truth(self) -> dict | None:
        path = self.path / "truth.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@dataclass(eq=False)
class Registers:
    gleif: dict[str, GleifEntity]
    relationships: list[GleifRelationship]
    companies: dict[str, ChCompany]
    psc: list[Psc]
    sanctions: dict[str, Designation]
    quezal: Quezal
    hidden: set[str] = field(default_factory=set)  # fields a check blanked on purpose


def load_quezal(name: str | Path = "practice") -> Quezal:
    """A Quezal register by name (a folder in data/quezal) or by path."""
    path = Path(name) if Path(name).is_absolute() else QUEZAL / name
    if not path.exists():
        raise FileNotFoundError(f"No Quezal register {name!r} in {QUEZAL}")
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    companies = {
        r["id"]: QzCompany(r["id"], r["name"], r["form"], r["sector"], r["incorporated_on"], r["status"],
                           r["struck_off_on"], r["agent_id"], tuple(p["name"] for p in _json(r["previous_names"], [])))
        for r in _rows(path / "companies.csv")
    }  # fmt: skip
    gazette = []
    for line in (path / "gazette.jsonl").read_text(encoding="utf-8").splitlines():
        a = json.loads(line)
        gazette.append(Article(a["id"], a["published_on"], a["headline"], a["body"]))
    return Quezal(
        name=str(name),
        path=path,
        snapshot=meta["snapshot"],
        companies=companies,
        people={r["id"]: r["name"] for r in _rows(path / "people.csv")},
        agents={r["id"]: r for r in _rows(path / "agents.csv")},
        holdings=[
            QzHolding(r["holder_id"], r["company_id"], float(r["percent"]), r["since"], r["until"])
            for r in _rows(path / "shareholdings.csv")
        ],  # fmt: skip
        directors=[(r["person_id"], r["company_id"], r["since"]) for r in _rows(path / "directors.csv")],
        watchlist=[
            QzListing(r["id"], r["name"], tuple(_json(r["aliases"], [])), r["designated_on"], r["reason"])
            for r in _rows(path / "watchlist.csv")
        ],  # fmt: skip
        gazette=gazette,
    )


@cache
def load(quezal: str = "practice") -> Registers:
    reg = DATA / "registers"
    gleif = {}
    for r in _rows(reg / "gleif" / "entities.csv"):
        other = tuple(n["name"] for n in _json(r["other_names"], []))
        trans = tuple(n["name"] for n in _json(r["transliterated_names"], []))
        gleif[r["lei"]] = GleifEntity(r["lei"], r["legal_name"], r["language"], other, trans, r["country"], r["city"],
                                      r["jurisdiction"], r["legal_form"], r["registration_authority"],
                                      r["registration_number"], r["category"], r["entity_status"],
                                      r["registration_status"], r["created_on"], r["last_update"])  # fmt: skip
    relationships = [
        GleifRelationship(r["child_lei"], r["parent_lei"], r["type"], r["registration_status"], r["start_date"],
                          float(r["percentage"]) if r["percentage"] else None, r["accounting_standard"],
                          r["validation_source"])
        for r in _rows(reg / "gleif" / "relationships.csv")
    ]  # fmt: skip
    companies = {
        r["company_number"]: ChCompany(r["company_number"], r["name"], r["category"], r["status"],
                                       r["country_of_origin"], r["incorporated_on"], r["dissolved_on"], r["post_town"],
                                       r["postcode"], r["sic"], tuple(p["name"] for p in _json(r["previous_names"], [])))
        for r in _rows(reg / "companies_house" / "companies.csv")
    }  # fmt: skip
    psc = [
        Psc(r["company_number"], r["psc_id"], r["kind"], r["name"], r["registration_number"], r["country_registered"],
            r["legal_form"], tuple(n for n in r["natures_of_control"].split("|") if n), r["notified_on"],
            r["ceased_on"], r["statement"])
        for r in _rows(reg / "companies_house" / "psc.csv")
    ]  # fmt: skip
    sanctions = {
        r["unique_id"]: Designation(r["unique_id"], r["name"], tuple(_json(r["aliases"], [])),
                                    tuple(_json(r["non_latin_names"], [])), r["regime"], r["designated_on"], r["source"],
                                    r["entity_type"], tuple(_json(r["registration_numbers"], [])),
                                    tuple(_json(r["countries"], [])), r["parent_companies"], r["subsidiaries"],
                                    r["last_updated"])
        for r in _rows(reg / "uk_sanctions" / "entities.csv")
    }  # fmt: skip
    return Registers(gleif, relationships, companies, psc, sanctions, load_quezal(quezal))
