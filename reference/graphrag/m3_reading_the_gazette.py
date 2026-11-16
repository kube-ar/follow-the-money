"""Milestone 3 · Reading the Gazette: a reference solution. Spoilers: `trail use-reference 3` copies it."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import networkx as nx

from trail.registers import Article, Registers

SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
KINDS = ("stake", "rename", "director")


def lexical_graph(regs: Registers) -> nx.DiGraph:
    g = nx.DiGraph()
    for a in regs.quezal.gazette:
        g.add_node(a.id, kind="article", published_on=a.published_on)
        previous = None
        for i, sentence in enumerate(SENTENCE.split(a.body)):
            chunk = f"{a.id}#{i}"
            g.add_node(chunk, kind="chunk", text=sentence)
            g.add_edge(chunk, a.id, type="PART_OF")
            if previous:
                g.add_edge(previous, chunk, type="NEXT")
            previous = chunk
    return g


def lexical_summary(graph) -> dict[str, int]:
    kinds = [d.get("kind") for _, d in graph.nodes(data=True)]
    return {"articles": kinds.count("article"), "sentences": kinds.count("chunk"),
            "next": sum(1 for *_, d in graph.edges(data=True) if d.get("type") == "NEXT")}  # fmt: skip


def _surfaces(regs: Registers) -> dict[str, set[str]]:
    """Every way the press may write a name: in full, without the legal form, or its first words."""
    out: dict[str, set[str]] = defaultdict(set)
    for c in regs.quezal.companies.values():
        out[c.name].add(c.id)
        base = c.name.removesuffix(c.form).strip()
        words = base.split()
        for n in range(1, len(words) + 1):
            out[" ".join(words[:n])].add(c.id)
    for pid, name in regs.quezal.people.items():
        out[name].add(pid)
    return out


def _related(regs: Registers) -> dict[str, set[str]]:
    rel: dict[str, set[str]] = defaultdict(set)
    for h in regs.quezal.holdings:
        rel[h.holder_id].add(h.company_id)
        rel[h.company_id].add(h.holder_id)
    return rel


def find_entities(regs: Registers, article: Article) -> list[tuple[int, int, str]]:
    text, surfaces = article.body, _surfaces(regs)
    spans: list[tuple[int, int, set[str]]] = []
    for surface in sorted(surfaces, key=len, reverse=True):
        for m in re.finditer(re.escape(surface), text):
            after = text[m.end() : m.end() + 2]
            if re.match(r" [A-Z]", after) and surface not in (n for n in regs.quezal.people.values()):
                continue  # "Harrow" inside "Harrow Point …": a longer name continues here
            if all(m.end() <= s or m.start() >= e for s, e, _ in spans):
                spans.append((m.start(), m.end(), surfaces[surface]))
    sure = {next(iter(ids)) for _, _, ids in spans if len(ids) == 1}
    related = _related(regs)
    out = []
    for start, end, ids in sorted(spans, key=lambda s: s[0]):
        if len(ids) > 1:
            ids = (ids & sure) or {i for i in ids if related[i] & sure}  # a full name later on, or the register
        if len(ids) == 1:
            out.append((start, end, next(iter(ids))))
    return out


SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "buyer": {"type": "string"},
                    "seller": {"type": "string"},
                    "company": {"type": "string"},
                    "percent": {"type": "number"},
                    "new_name": {"type": "string"},
                    "person": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["kind", "buyer", "seller", "company", "percent", "new_name", "person", "date"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

PROMPT = """Read this news item from the Quezal Gazette, published on {published}.

{body}

List its claims. kind is "stake" (someone holds or takes a percentage of a company), "rename"
(a company will use a new name) or "director" (someone joins a board). Fill only the fields of
the claim's kind:
- stake: buyer is who now holds or takes the shares, seller who gives them up, company the
  company whose shares they are, percent the stake.
- rename: company is the company as the item names it now, new_name the name it will use.
- director: person is who joins the board, company the company whose board it is.
Copy names exactly as the text writes them; use "" for fields that don't apply and 0 for a missing
percent. Only list what the item reports as news: background ("Founded in 2011, X works in
shipping") is not a claim. date is when the fact happened (YYYY-MM-DD): for "since <month year>"
use the first day of that month; if the item gives no other date, use the publication date."""


def read_article(regs: Registers, article: Article, llm: Any) -> list[dict]:
    answer = llm.json(PROMPT.format(published=article.published_on, body=article.body), SCHEMA)
    spans = find_entities(regs, article)
    by_text = {article.body[s:e]: i for s, e, i in spans}
    surfaces = _surfaces(regs)

    def ident(name: str) -> str | None:
        name = name.strip()
        if not name:
            return None
        if name in by_text:
            return by_text[name]
        ids = surfaces.get(name, set())
        return next(iter(ids)) if len(ids) == 1 else None

    out = []
    for c in answer.get("claims", []):
        claim: dict = {"kind": c["kind"], "date": c.get("date") or article.published_on}
        if c["kind"] == "stake":
            claim |= {"buyer": ident(c["buyer"]), "seller": ident(c["seller"]), "company": ident(c["company"]),
                      "percent": float(c["percent"])}  # fmt: skip
        elif c["kind"] == "rename":
            claim |= {"company": ident(c["company"]), "new_name": c["new_name"].strip()}
        else:
            claim |= {"person": ident(c["person"]), "company": ident(c["company"])}
        out.append(claim)
    return out


def not_in_register(regs: Registers, claims: dict[str, dict]) -> set[str]:
    q = regs.quezal
    out = set()
    for aid, c in claims.items():
        if c["kind"] == "stake":
            shown = any(h.holder_id == c["buyer"] and h.company_id == c["company"] and abs(h.percent - c["percent"]) < 0.01
                        and h.since <= q.snapshot for h in q.holdings)  # fmt: skip
            if not shown:
                out.add(aid)
        elif c["kind"] == "rename" and q.companies[c["company"]].name != c["new_name"]:
            out.add(aid)
    return out
