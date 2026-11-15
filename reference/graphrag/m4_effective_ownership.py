"""Milestone 4 · Effective ownership: a reference solution. Spoilers: `trail use-reference 4` copies it."""

from __future__ import annotations

import os
import re
from typing import Any

import networkx as nx
from neo4j import GraphDatabase

from trail.registers import Registers

UK = ("england", "wales", "scotland", "northern ireland", "united kingdom", "uk", "great britain")
LABELS = {"Company", "Person", "Agent"}
RELS = {"PARENT", "OWNED_BY", "HOLDS", "SAME_AS", "DIRECTOR_OF", "REGISTERED_BY"}
WRITES = re.compile(r"(?<![:\w])(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|CALL|FOREACH)\b", re.I)

TEMPLATES = {
    "effective_ownership": """
        MATCH p = (o {id: $owner})-[:HOLDS*1..8]->(c:Company {id: $company})
        WHERE size(nodes(p)) = size(apoc_free_unique(nodes(p)))
        RETURN sum(reduce(s = 1.0, r IN relationships(p) | s * r.percent / 100.0)) AS share
        LIMIT 1""",
    "parents_up": """
        MATCH p = (c:Company {id: $lei})-[:PARENT*1..20]->(top:Company)
        UNWIND nodes(p)[1..] AS n
        RETURN DISTINCT n.id AS id
        LIMIT 1000""",
}
# Neo4j 5 matches a relationship once per path, but a path may still come back to a node it
# passed (a loop of holdings). Keep the paths whose nodes are all different:
TEMPLATES["effective_ownership"] = TEMPLATES["effective_ownership"].replace(
    "size(nodes(p)) = size(apoc_free_unique(nodes(p)))",
    "all(i IN range(0, size(nodes(p)) - 2) WHERE NOT nodes(p)[i] IN nodes(p)[i + 1 ..])",
)


class Board:
    def __init__(self, driver):
        self.driver = driver

    def q(self, query: str, **params) -> list[dict]:
        with self.driver.session() as s:
            return [r.data() for r in s.run(query, **params)]


_DRIVER = None


def _driver():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "trail-password"))
    return GraphDatabase.driver(uri, auth=auth)


def _number(raw: str) -> str | None:
    s = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if re.fullmatch(r"\d{1,8}", s):
        return s.zfill(8)
    m = re.fullmatch(r"([A-Z]{2})(\d{1,6})", s)
    return m.group(1) + m.group(2).zfill(6) if m else None


def store(regs: Registers) -> Board:
    global _DRIVER
    _DRIVER = _DRIVER or _driver()
    b = Board(_DRIVER)
    b.q("MATCH (n) DETACH DELETE n")
    b.q("CREATE INDEX company_id IF NOT EXISTS FOR (c:Company) ON (c.id)")
    b.q("CREATE INDEX person_id IF NOT EXISTS FOR (p:Person) ON (p.id)")
    q = regs.quezal
    companies = ([{"id": e.lei, "name": e.legal_name, "source": "gleif"} for e in regs.gleif.values()]
                 + [{"id": c.company_number, "name": c.name, "source": "companies_house"} for c in regs.companies.values()]
                 + [{"id": c.id, "name": c.name, "source": "quezal"} for c in q.companies.values()])  # fmt: skip
    b.q("UNWIND $rows AS r CREATE (:Company {id: r.id, name: r.name, source: r.source})", rows=companies)
    b.q("UNWIND $rows AS r CREATE (:Person {id: r.id, name: r.name})",
        rows=[{"id": k, "name": v} for k, v in q.people.items()])  # fmt: skip
    b.q("UNWIND $rows AS r CREATE (:Agent {id: r.id, name: r.name})", rows=list(q.agents.values()))

    def link(rel: str, rows: list[dict], start: str = "Company", end: str = "Company") -> None:
        b.q(f"UNWIND $rows AS r MATCH (a:{start} {{id: r.a}}), (z:{end} {{id: r.z}}) CREATE (a)-[x:{rel}]->(z) "
            "SET x += r.props", rows=rows)  # fmt: skip

    link("PARENT", [{"a": r.child_lei, "z": r.parent_lei, "props": {"percentage": r.percentage}}
                    for r in regs.relationships if r.type == "direct"])  # fmt: skip
    owned = []
    for p in regs.psc:
        if p.kind == "corporate" and p.active and any(u in p.country_registered.lower() for u in UK):
            n = _number(p.registration_number)
            if n in regs.companies:
                band = p.share_band
                owned.append({"a": p.company_number, "z": n,
                              "props": {"lo": band[0] if band else None, "hi": band[1] if band else None}})  # fmt: skip
    link("OWNED_BY", owned)
    held = [h for h in q.holdings if not h.until and h.since <= q.snapshot]
    for start in ("Company", "Person"):
        prefix = "QZ-" if start == "Company" else "QP-"
        link("HOLDS", [{"a": h.holder_id, "z": h.company_id, "props": {"percent": h.percent}}
                       for h in held if h.holder_id.startswith(prefix)], start=start)  # fmt: skip
    link("SAME_AS", [{"a": e.lei, "z": _number(e.registration_number), "props": {}} for e in regs.gleif.values()
                     if e.registration_authority == "RA000585" and _number(e.registration_number) in regs.companies])  # fmt: skip
    link("DIRECTOR_OF", [{"a": p, "z": c, "props": {"since": s}} for p, c, s in q.directors], start="Person")
    link("REGISTERED_BY", [{"a": c.id, "z": c.agent_id, "props": {}} for c in q.companies.values()], end="Agent")
    return b


def store_summary(board: Board) -> dict[str, int]:
    def nodes(label: str) -> int:
        return board.q(f"MATCH (n:{label}) RETURN count(n) AS n")[0]["n"]

    def rels(rel: str) -> int:
        return board.q(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS n")[0]["n"]

    return {"companies": nodes("Company"), "people": nodes("Person"), "agents": nodes("Agent"),
            "parent": rels("PARENT"), "owned_by": rels("OWNED_BY"), "holds": rels("HOLDS"),
            "same_as": rels("SAME_AS"), "director_of": rels("DIRECTOR_OF")}  # fmt: skip


def ask_template(board: Board, name: str, **params) -> list[dict]:
    return board.q(TEMPLATES[name], **params)


def effective_ownership(board: Board, owner: str, company: str) -> float:
    rows = ask_template(board, "effective_ownership", owner=owner, company=company)
    return round(rows[0]["share"] or 0.0, 6) if rows else 0.0


def controlled_by(board: Board, owner: str) -> set[str]:
    stakes: dict[str, dict[str, float]] = {}
    for r in board.q("MATCH (h)-[x:HOLDS]->(c:Company) RETURN h.id AS h, c.id AS c, x.percent AS p"):
        stakes.setdefault(r["c"], {})[r["h"]] = stakes.get(r["c"], {}).get(r["h"], 0) + r["p"]
    out, changed = set(), True
    while changed:
        changed = False
        for company, holders in stakes.items():
            if company not in out and company != owner:
                if holders.get(owner, 0) + sum(v for h, v in holders.items() if h in out) > 50:
                    out.add(company)
                    changed = True
    return out


def band_ownership(board: Board, owner: str, company: str) -> tuple[float, float] | None:
    rows = board.q("""
        MATCH p = (c:Company {id: $company})-[:OWNED_BY*1..8]->(o:Company {id: $owner})
        WHERE all(r IN relationships(p) WHERE r.lo IS NOT NULL)
          AND all(i IN range(0, size(nodes(p)) - 2) WHERE NOT nodes(p)[i] IN nodes(p)[i + 1 ..])
        RETURN count(p) AS n,
               sum(reduce(s = 1.0, r IN relationships(p) | s * r.lo)) AS lo,
               sum(reduce(s = 1.0, r IN relationships(p) | s * r.hi)) AS hi""", company=company, owner=owner)  # fmt: skip
    if not rows or not rows[0]["n"]:
        return None
    return round(rows[0]["lo"], 6), round(min(rows[0]["hi"], 1.0), 6)


def validate_query(query: str) -> bool:
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "''", query)  # ignore string literals
    if WRITES.search(text) or not re.search(r"\bMATCH\b", text, re.I) or not re.search(r"\bRETURN\b", text, re.I):
        return False
    limit = re.search(r"\bLIMIT\s+(\d+)\s*;?\s*$", text, re.I)
    if not limit or int(limit.group(1)) > 1000:
        return False
    labels = set(re.findall(r"\(\s*\w*\s*:\s*(\w+)", text))
    rels = {r for group in re.findall(r"\[\s*\w*\s*:\s*([\w|:]+)", text) for r in re.split(r"[|:]", group) if r}
    return labels <= LABELS and rels <= RELS


SCHEMA_TEXT = """Nodes: (:Company {id, name, source}) where source is gleif, companies_house or quezal;
(:Person {id, name}); (:Agent {id, name}).
Relationships: (:Company)-[:PARENT {percentage}]->(:Company) child to direct parent (GLEIF);
(:Company)-[:OWNED_BY {lo, hi}]->(:Company) UK company to corporate owner; (:Company|Person)-[:HOLDS {percent}]->(:Company)
Quezal stakes; (:Company)-[:SAME_AS]->(:Company) LEI to UK company number; (:Person)-[:DIRECTOR_OF]->(:Company);
(:Company)-[:REGISTERED_BY]->(:Agent)."""


def generated_query(board: Board, question: str, llm: Any) -> list[dict]:
    answer = llm.json(
        f"Write one read-only Cypher query for Neo4j 5 that answers the question. Return the ids in a column "
        f"named id, and end the query with LIMIT 100.\n\n{SCHEMA_TEXT}\n\nQuestion: {question}",
        {"type": "object", "properties": {"cypher": {"type": "string"}}, "required": ["cypher"],
         "additionalProperties": False},
    )  # fmt: skip
    query = answer["cypher"].strip().rstrip(";")
    return board.q(query) if validate_query(query) else []


def communities(board: Board) -> list[set[str]]:
    g = nx.Graph()
    for r in board.q("MATCH (h:Company)-[:HOLDS]->(c:Company) RETURN h.id AS a, c.id AS b"):
        g.add_edge(r["a"], r["b"])
    for r in board.q("MATCH (c:Company {source: 'quezal'}) RETURN c.id AS id"):
        g.add_node(r["id"])
    return [set(c) for c in nx.community.louvain_communities(g, seed=7)]
