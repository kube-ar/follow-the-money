"""The ownership board at the desk: the graph GraphRAG milestones 3 and 4 build, for the request's register.

A planned agent asks it in Cypher instead of climbing the registers one lookup at a time:

    desk = Desk(load_requests("practice")[2])
    desk.call("board", {"query": "MATCH (h)-[x:HOLDS]->(:Company {id: 'QZ-877779'}) RETURN h.id, x.percent LIMIT 10"})

It holds milestone 4's ownership graph (GLEIF parents, Companies House corporate owners, Quezal stakes,
directors, registered agents) and the Quezal Gazette's items, each linked to the companies and people it
names by milestone 3's entity linker. When a name fits several companies and the linker can't tell which,
the item is linked to all of them with `sure: false`. It's loaded with the course's own solutions
(reference/graphrag/), so it works whether or not you built those milestones, and it needs Neo4j:
`docker compose up -d`. Loading a register replaces whatever the database held.

The officer counts what a query reads as consulted: a query over `Company`, `Person` or `Agent` nodes read a
register, one over `Article` nodes the Gazette. The lists aren't on the board: ask the desk's list searches.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date, datetime
from typing import Any

from .registers import ROOT, Registers

M3 = ROOT / "reference" / "graphrag" / "m3_reading_the_gazette.py"
M4 = ROOT / "reference" / "graphrag" / "m4_effective_ownership.py"
LABELS = {"Company", "Person", "Agent", "Article"}
RELS = {"PARENT", "OWNED_BY", "HOLDS", "SAME_AS", "DIRECTOR_OF", "REGISTERED_BY", "MENTIONS"}
SOURCES = {"Company": "register", "Person": "register", "Agent": "register", "Article": "news"}
WRITES = re.compile(r"(?<![:\w])(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|CALL|FOREACH)\b", re.I)
SCHEMA = """Nodes: (:Company {id, name, source}) where source is gleif, companies_house or quezal; (:Person {id, name});
(:Agent {id, name}); (:Article {id, published_on, text}), a Quezal Gazette item.
Relationships: (:Company)-[:PARENT {percentage}]->(:Company) child to direct parent (GLEIF);
(:Company)-[:OWNED_BY {lo, hi}]->(:Company) UK company to corporate owner, a share band;
(:Company|Person)-[:HOLDS {percent}]->(:Company) Quezal stakes; (:Company)-[:SAME_AS]->(:Company) LEI to UK company
number; (:Person)-[:DIRECTOR_OF]->(:Company); (:Company)-[:REGISTERED_BY]->(:Agent);
(:Article)-[:MENTIONS {sure}]->(:Company|Person) who an item names: sure is false when the name fits several
companies and the linker can't tell which."""

_loaded: str | None = None


def _module(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_M3 = _M4 = None


def _strip(query: str) -> str:
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", query)


def problem(query: str, max_rows: int) -> str | None:
    """Why a query can't run on the board, or None: read-only, labels and relationships the board has,
    and a LIMIT of at most max_rows."""
    if not isinstance(query, str) or not query.strip():
        return "a Cypher query, as a string"
    text = _strip(query)
    if WRITES.search(text):
        return "the board is read-only: no CREATE, MERGE, SET, DELETE, REMOVE, DROP, LOAD, FOREACH or CALL"
    if not re.search(r"\bMATCH\b", text, re.I) or not re.search(r"\bRETURN\b", text, re.I):
        return "a query needs MATCH and RETURN"
    limit = re.search(r"\bLIMIT\s+(\d+)\s*;?\s*$", text, re.I)
    if not limit or int(limit.group(1)) > max_rows:
        return f"end the query with LIMIT n, n at most {max_rows}"
    labels = set(re.findall(r"\(\s*\w*\s*:\s*(\w+)", text))
    rels = {r for group in re.findall(r"\[\s*\w*\s*:\s*([\w|:]+)", text) for r in re.split(r"[|:]", group) if r}
    if labels - LABELS or rels - RELS:
        return f"the board has no {sorted((labels - LABELS) | (rels - RELS))}: {SCHEMA.splitlines()[0]} …"
    return None


def sources(query: str) -> set[str]:
    """The kinds of source a query reads, by the labels it names."""
    return {SOURCES[label] for label in re.findall(r":\s*(\w+)", _strip(str(query))) if label in SOURCES}


def mentions(regs: Registers, article, surfaces: dict | None = None) -> dict[str, bool]:
    """Who a Gazette item names: id → sure. Milestone 3's linker, keeping what it can't resolve: a short name that
    fits several companies, with no full name or register link in the item to pick one, names all of them."""
    global _M3
    _M3 = _M3 or _module("m3_for_the_desk", M3)
    text, surfaces = article.body, surfaces or _M3._surfaces(regs)
    spans: list[tuple[int, int, set[str]]] = []
    for surface in sorted(surfaces, key=len, reverse=True):
        for m in re.finditer(re.escape(surface), text):
            if re.match(r" [A-Z]", text[m.end() : m.end() + 2]) and surface not in regs.quezal.people.values():
                continue  # a longer name continues here
            if all(m.end() <= s or m.start() >= e for s, e, _ in spans):
                spans.append((m.start(), m.end(), surfaces[surface]))
    sure = {next(iter(ids)) for _, _, ids in spans if len(ids) == 1}
    related = _M3._related(regs)
    out: dict[str, bool] = {}
    for _, _, ids in spans:
        if len(ids) > 1:
            ids = (ids & sure) or {i for i in ids if related[i] & sure} or ids
        for i in ids:
            out[i] = out.get(i, False) or len(ids) == 1
    return out


def _board(regs: Registers, register: str):
    global _M3, _M4, _loaded
    _M4 = _M4 or _module("m4_for_the_desk", M4)
    _M3 = _M3 or _module("m3_for_the_desk", M3)
    _M4._DRIVER = _M4._DRIVER or _M4._driver()
    board = _M4.Board(_M4._DRIVER)
    if _loaded != register or board.q("MATCH (m:DeskBoard) RETURN m.register AS r") != [{"r": register}]:
        board = _M4.store(regs)
        surfaces = _M3._surfaces(regs)
        rows = [{"id": a.id, "published_on": a.published_on, "text": a.body} for a in regs.quezal.gazette]
        board.q("UNWIND $rows AS r CREATE (:Article {id: r.id, published_on: r.published_on, text: r.text})", rows=rows)
        links = [{"a": a.id, "z": i, "sure": sure} for a in regs.quezal.gazette
                 for i, sure in mentions(regs, a, surfaces).items()]  # fmt: skip
        for label, prefix in (("Company", "QZ-"), ("Person", "QP-")):
            board.q(f"UNWIND $rows AS r MATCH (a:Article {{id: r.a}}), (z:{label} {{id: r.z}}) "
                    "CREATE (a)-[:MENTIONS {sure: r.sure}]->(z)", rows=[x for x in links if x["z"].startswith(prefix)])  # fmt: skip
        board.q("CREATE (:DeskBoard {register: $register})", register=register)
        _loaded = register
    return board


def _plain(value: Any) -> Any:
    if hasattr(value, "to_native"):
        value = value.to_native()
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%d %H:%M}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def run(regs: Registers, register: str, query: str, params: dict | None, max_rows: int) -> list[dict] | dict:
    """The rows a read-only query returns on the board for this register, or {"error": ...}."""
    from neo4j.exceptions import AuthError, CypherSyntaxError, ServiceUnavailable

    why = problem(query, max_rows)
    if why:
        return {"error": why}
    if params is not None and not isinstance(params, dict):
        return {"error": "params is an object of query parameters"}
    down = reachable()  # fast when Neo4j is off; a query would retry for half a minute before failing
    if down:
        return {"error": down}
    try:
        return [_plain(row) for row in _board(regs, register).q(query, **(params or {}))]
    except (ServiceUnavailable, AuthError, OSError) as e:
        return {"error": f"the ownership board needs Neo4j: run `docker compose up -d` and check NEO4J_* in .env ({e})"}
    except CypherSyntaxError as e:
        return {"error": f"the query doesn't parse: {str(e.message or e)[:240]}"}
    except Exception as e:  # a type error in the query, a missing parameter: the model can fix those
        return {"error": f"the query failed: {str(getattr(e, 'message', None) or e)[:240]}"}


def reachable() -> str | None:
    """None when the board's Neo4j answers, else what to do about it."""
    global _M4
    try:
        _M4 = _M4 or _module("m4_for_the_desk", M4)
        _M4._DRIVER = _M4._DRIVER or _M4._driver()
        _M4._DRIVER.verify_connectivity()
        return None
    except Exception as e:  # not running, wrong password, wrong port
        return f"The ownership board needs Neo4j: run `docker compose up -d`, and check NEO4J_* in .env ({type(e).__name__})."
