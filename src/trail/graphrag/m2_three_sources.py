"""Milestone 2 · One company, three sources.

Instructions: https://kube.ar/graphrag/project/follow-the-money/three-sources

Each register has its own words for the same things: GLEIF says "directly consolidated by",
Companies House "person with significant control", Quezal "shareholder". Map all of them onto one
shared vocabulary, FollowTheMoney (FtM), the open model investigative journalists use. Then
decide which records are the same company, and say what a sanctions list can and can't tell you.

Check your work with `uv run trail check 2`.

Fast path: `uv add followthemoney` and build entities with `model.make_entity("Company")`; a
fuzzy matcher (rapidfuzz is installed) for names.
Deep path: plain dicts, and your own name normalization and evidence rules.
"""

from __future__ import annotations

from trail.registers import Registers

STATUSES = ("listed", "owned by a listed entity", "no listing found")


def to_ftm(regs: Registers) -> list[dict]:
    """Every register as FtM entities: {"id", "schema", "properties": {name: [values]}, "datasets": [...]}.

    Schemata: Company, LegalEntity, Organization, Person, Ownership, Sanction. Property names are
    FtM's (name, alias, previousName, leiCode, registrationNumber, jurisdiction, country, owner,
    asset, percentage, startDate, endDate, entity, authority, program, recordId, …). Values are
    lists of strings; owner, asset and entity hold the id of another entity in your list.

    - A company in two registers stays two entities, one per dataset (gleif, companies_house,
      uk_sanctions, quezal). Linking them is `match`'s job.
    - A stake is an entity of its own (Ownership), not a bare edge: it carries its percentage,
      its dates and the record it came from (recordId: the PSC id, the child LEI, the Quezal
      holder and company). Individuals with significant control are anonymous: leave them out.
    - Jurisdictions and countries are lowercase ISO codes: "gb", "ru", Quezal is "qz".
    """
    raise NotImplementedError


def match(regs: Registers) -> set[tuple[str, str]]:
    """Pairs of ids that are the same company in two sources:

    (LEI, company number)              a GLEIF entity and a Companies House company
    (UK Sanctions List id, LEI or number)  a designation and the entity it designates
    (QFA- id, QZ- id)                  a Quezal watch-list entry and a Quezal company

    The check runs this twice: once with GLEIF's registration numbers blanked (so the names have
    to do the work), once on the full registers. A wrong designation match flags an innocent
    company: precision matters more than recall here.
    """
    raise NotImplementedError


def sanction_status(regs: Registers, matches: set[tuple[str, str]], entity: str) -> str:
    """One of STATUSES for an LEI, a company number or a QZ- id, given matches like `match`'s.

    listed: a designation matches it (or the same company in another register).
    owned by a listed entity: something above it is listed. "Above": a GLEIF parent, a Companies
      House corporate owner with more than 50% of the shares, a Quezal company that controls it
      (more than 50% of the votes, its own plus those of companies it controls).
    no listing found: neither. Not "clean": a list only knows who's on it.
    """
    raise NotImplementedError
