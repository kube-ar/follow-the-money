"""Build the frozen slice of real registers that ships in data/registers/.

Maintainers only: learners never need to run this. It reads bulk files you download yourself
(see data/registers/SOURCES.md for the URLs) and keeps only the corporate groups listed in
tools/groups.txt, the UK companies they contain, the companies that own those (up the Companies
House ownership chain), and the entities on the UK Sanctions List.

Privacy: no natural person's name, birth date, nationality or address leaves this script.
An individual with significant control becomes "an individual" with a control band.

    uv run python tools/build_slice.py --raw ../ftm-raw
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "registers"
COMPANIES_HOUSE = "RA000585"
UK_PLACES = ("england", "wales", "scotland", "northern ireland", "united kingdom", "uk", "great britain",
             "companies house", "cardiff", "edinburgh", "belfast")  # fmt: skip
MAX_HOPS = 4  # how far up the Companies House ownership chain to follow


def groups() -> list[str]:
    lines = (ROOT / "tools" / "groups.txt").read_text(encoding="utf-8").splitlines()
    return [ln.split("#")[0].strip() for ln in lines if ln.split("#")[0].strip()]


def uk_number(raw: str) -> str | None:
    """Companies House numbers are 8 characters: digits padded with zeros, or a 2-letter prefix and 6 digits."""
    s = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    s = re.sub(r"^(COMPANIESHOUSE|COMPANYNO|COMPANYNUMBER|NO|REGNO)", "", s)
    if re.fullmatch(r"\d{1,8}", s):
        return s.zfill(8)
    m = re.fullmatch(r"([A-Z]{2})(\d{1,6})", s)
    return m.group(1) + m.group(2).zfill(6) if m else None


def is_uk(identification: dict) -> bool:
    text = " ".join(str(identification.get(k, "")) for k in ("country_registered", "place_registered")).lower()
    return any(p in text for p in UK_PLACES)


def iso(day_month_year: str) -> str:
    return datetime.strptime(day_month_year, "%d/%m/%Y").date().isoformat() if day_month_year else ""


# --- GLEIF -------------------------------------------------------------------------------------


def read_relationships(raw: Path) -> list[dict]:
    rows = []
    with zipfile.ZipFile(raw / "gleif-rr.csv.zip") as z, z.open(z.namelist()[0]) as f:
        for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
            kind = {"IS_DIRECTLY_CONSOLIDATED_BY": "direct", "IS_ULTIMATELY_CONSOLIDATED_BY": "ultimate"}.get(
                row["Relationship.RelationshipType"]
            )
            if kind is None or row["Relationship.RelationshipStatus"] != "ACTIVE":
                continue
            unit = row["Relationship.Quantifiers.1.QuantifierUnits"]
            rows.append({
                "child_lei": row["Relationship.StartNode.NodeID"],
                "parent_lei": row["Relationship.EndNode.NodeID"],
                "type": kind,
                "registration_status": row["Registration.RegistrationStatus"],
                "start_date": row["Relationship.Period.1.startDate"][:10],
                "percentage": row["Relationship.Quantifiers.1.QuantifierAmount"] if unit == "PERCENTAGE" else "",
                "accounting_standard": row["Relationship.Qualifiers.1.QualifierCategory"],
                "validation_source": row["Registration.ValidationSources"],
            })  # fmt: skip
    return rows


def fetch_entities(raw: Path, leis: list[str]) -> dict[str, dict]:
    cache = raw / "gleif-l1-slice.json"
    have = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    missing = [x for x in leis if x not in have]
    for i in range(0, len(missing), 200):
        url = "https://api.gleif.org/api/v1/lei-records?page[size]=200&filter[lei]=" + ",".join(missing[i : i + 200])
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.api+json", "User-Agent": "slice-builder"})
        with urllib.request.urlopen(req, timeout=60) as r:
            for rec in json.load(r)["data"]:
                have[rec["id"]] = rec["attributes"]
        time.sleep(1.1)
    cache.write_text(json.dumps(have), encoding="utf-8")
    return {x: have[x] for x in leis if x in have}


def entity_row(lei: str, a: dict) -> dict:
    e, reg = a["entity"], a["registration"]
    names = [{"name": n["name"], "type": n.get("type"), "language": n.get("language")} for n in e.get("otherNames", [])]
    trans = [{"name": n["name"], "type": n.get("type")} for n in e.get("transliteratedOtherNames", [])]
    return {
        "lei": lei,
        "legal_name": e["legalName"]["name"],
        "language": e["legalName"].get("language") or "",
        "other_names": json.dumps(names, ensure_ascii=False) if names else "",
        "transliterated_names": json.dumps(trans, ensure_ascii=False) if trans else "",
        "country": e["legalAddress"]["country"],
        "city": e["legalAddress"].get("city") or "",
        "jurisdiction": e.get("jurisdiction") or "",
        "legal_form": (e.get("legalForm") or {}).get("id") or "",
        "registration_authority": (e.get("registeredAt") or {}).get("id") or "",
        "registration_number": e.get("registeredAs") or "",
        "category": e.get("category") or "",
        "entity_status": e.get("status") or "",
        "registration_status": reg.get("status") or "",
        "created_on": (e.get("creationDate") or "")[:10],
        "last_update": (reg.get("lastUpdateDate") or "")[:10],
    }


# --- Companies House ---------------------------------------------------------------------------


def psc_lines(raw: Path):
    with zipfile.ZipFile(raw / "ch-psc-snapshot.zip") as z, z.open(z.namelist()[0]) as f:
        yield from io.TextIOWrapper(f, encoding="utf-8")


def corporate_index(raw: Path) -> dict[str, list[str]]:
    """company number → UK company numbers of its corporate owners (active and ceased), from one pass."""
    owners: dict[str, list[str]] = defaultdict(list)
    for line in psc_lines(raw):
        if '"kind":"corporate-entity' not in line:
            continue
        rec = json.loads(line)
        d = rec.get("data", {})
        if not d.get("kind", "").startswith("corporate-entity"):
            continue
        ident = d.get("identification") or {}
        number = uk_number(ident.get("registration_number", "")) if is_uk(ident) else None
        if number:
            owners[rec["company_number"]].append(number)
    return owners


def psc_row(rec: dict) -> dict | None:
    d, number = rec.get("data", {}), rec["company_number"]
    kind = d.get("kind", "")
    self_link = (d.get("links") or {}).get("self", "")
    psc_id = hashlib.sha1(self_link.encode()).hexdigest()[:12] if self_link else ""
    row = {"company_number": number, "psc_id": psc_id, "kind": "", "name": "", "registration_number": "",
           "country_registered": "", "legal_form": "", "natures_of_control": "|".join(d.get("natures_of_control", [])),
           "notified_on": d.get("notified_on", ""), "ceased_on": d.get("ceased_on", ""), "statement": ""}  # fmt: skip
    if kind.startswith("corporate-entity"):
        ident = d.get("identification") or {}
        row.update(kind="corporate", name=d.get("name", ""), registration_number=ident.get("registration_number", ""),
                   country_registered=ident.get("country_registered", "") or ident.get("place_registered", ""),
                   legal_form=ident.get("legal_form", ""))  # fmt: skip
    elif kind.startswith("legal-person"):
        ident = d.get("identification") or {}
        row.update(kind="legal-person", name=d.get("name", ""), legal_form=ident.get("legal_form", ""))
    elif kind.startswith("individual"):
        row.update(kind="individual")  # the person stays anonymous: no name, birth date, nationality or address
    elif "statement" in kind:
        row.update(kind="statement", statement=d.get("statement", ""))
    elif kind in ("super-secure-person-with-significant-control", "exemptions"):
        row.update(kind=kind.split("-person")[0])
    else:
        return None
    return row


def read_companies(raw: Path, numbers: set[str]) -> dict[str, dict]:
    out = {}
    with zipfile.ZipFile(raw / "ch-basic-company-data.zip") as z, z.open(z.namelist()[0]) as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
        header = [h.strip() for h in next(reader)]
        for values in reader:
            row = dict(zip(header, values))
            number = row.get("CompanyNumber", "").strip()
            if number not in numbers:
                continue
            previous = []
            for i in range(1, 11):
                name = row.get(f"PreviousName_{i}.CompanyName", "").strip()
                if name:
                    previous.append({"name": name, "until": iso(row.get(f"PreviousName_{i}.CONDATE", "").strip())})
            out[number] = {
                "company_number": number,
                "name": row["CompanyName"].strip(),
                "category": row["CompanyCategory"].strip(),
                "status": row["CompanyStatus"].strip(),
                "country_of_origin": row["CountryOfOrigin"].strip(),
                "incorporated_on": iso(row["IncorporationDate"].strip()),
                "dissolved_on": iso(row["DissolutionDate"].strip()),
                "post_town": row["RegAddress.PostTown"].strip(),
                "postcode": row["RegAddress.PostCode"].strip(),
                "sic": row["SICCode.SicText_1"].strip(),
                "previous_names": json.dumps(previous, ensure_ascii=False) if previous else "",
            }
    return out


# --- UK Sanctions List -------------------------------------------------------------------------


def read_sanctions(raw: Path) -> list[dict]:
    root = ET.parse(raw / "uk-sanctions-list.xml").getroot()
    rows = []
    for d in root.iter("Designation"):
        if d.findtext("IndividualEntityShip") != "Entity":
            continue  # entities only: no designated individuals, no ships
        names, primary = [], ""
        for n in d.iter("Name"):
            text = " ".join(n.findtext(f"Name{i}") or "" for i in range(1, 7)).strip()
            if n.findtext("NameType") == "Primary Name" and not primary:
                primary = text
            elif text:
                names.append(text)
        non_latin = [n.text.strip() for n in d.iter("NameNonLatinScript") if n.text]
        numbers = [n.text.strip() for n in d.iter("BusinessRegistrationNumber") if n.text]
        countries = sorted({n.text.strip() for n in d.iter("AddressCountry") if n.text})
        types = [n.text.strip() for n in d.iter("TypeOfEntity") if n.text]
        rows.append({
            "unique_id": d.findtext("UniqueID"),
            "name": primary,
            "aliases": json.dumps(names, ensure_ascii=False) if names else "",
            "non_latin_names": json.dumps(non_latin, ensure_ascii=False) if non_latin else "",
            "regime": d.findtext("RegimeName") or "",
            "designated_on": iso(d.findtext("DateDesignated") or ""),
            "source": d.findtext("DesignationSource") or "",
            "entity_type": "; ".join(types),
            "registration_numbers": json.dumps(numbers, ensure_ascii=False) if numbers else "",
            "countries": json.dumps(countries, ensure_ascii=False) if countries else "",
            "parent_companies": "; ".join(n.text.strip() for n in d.iter("ParentCompany") if n.text),
            "subsidiaries": "; ".join(n.text.strip() for n in d.iter("Subsidiary") if n.text),
            "last_updated": iso(d.findtext("LastUpdated") or ""),
        })  # fmt: skip
    return rows


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{path.relative_to(ROOT)}: {len(rows)} rows")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, required=True, help="folder with the downloaded bulk files")
    raw = p.parse_args().raw.resolve()

    rels = read_relationships(raw)
    children = defaultdict(list)
    for r in rels:
        if r["type"] == "direct":
            children[r["parent_lei"]].append(r["child_lei"])
    members: set[str] = set()
    for root_lei in groups():
        stack = [root_lei]
        while stack:
            n = stack.pop()
            if n not in members:
                members.add(n)
                stack += children.get(n, [])
    entities = fetch_entities(raw, sorted(members))
    keep_rels = [r for r in rels if r["child_lei"] in members]
    for r in keep_rels:  # an ultimate parent outside the walked groups still needs its record
        members.add(r["parent_lei"])
    entities = fetch_entities(raw, sorted(members))
    write(OUT / "gleif" / "entities.csv", [entity_row(x, a) for x, a in sorted(entities.items())])
    write(OUT / "gleif" / "relationships.csv", sorted(keep_rels, key=lambda r: (r["child_lei"], r["type"])))

    uk = {uk_number(a["entity"].get("registeredAs", "")) for a in entities.values()
          if (a["entity"].get("registeredAt") or {}).get("id") == COMPANIES_HOUSE}  # fmt: skip
    uk.discard(None)
    print(f"{len(uk)} UK companies from GLEIF; indexing corporate owners in the PSC snapshot…")
    owners = corporate_index(raw)
    numbers, frontier = set(uk), set(uk)
    for _ in range(MAX_HOPS):
        frontier = {o for n in frontier for o in owners.get(n, [])} - numbers
        numbers |= frontier
    print(f"{len(numbers)} UK companies after following owners up {MAX_HOPS} hops; reading their PSC records…")
    pscs = []
    for line in psc_lines(raw):
        if line[19:27] in numbers and line.startswith('{"company_number":"'):
            row = psc_row(json.loads(line))
            if row:
                pscs.append(row)
    companies = read_companies(raw, numbers)
    pscs = [p for p in pscs if p["company_number"] in companies]  # dissolved companies aren't in the company file
    write(OUT / "companies_house" / "companies.csv", [companies[n] for n in sorted(companies)])
    write(
        OUT / "companies_house" / "psc.csv", sorted(pscs, key=lambda r: (r["company_number"], r["kind"], r["psc_id"]))
    )
    write(OUT / "uk_sanctions" / "entities.csv", read_sanctions(raw))


if __name__ == "__main__":
    main()
