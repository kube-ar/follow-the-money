"""Agent 2 · The risk policy: a reference solution. Spoilers: `trail use-reference d2` copies it."""

from __future__ import annotations

import json
import re
from typing import Any

import networkx as nx

from trail.desk import POLICY, Desk, Request, key, records
from trail.llm import Conversation
from trail.registers import Registers

SPEC: dict[str, dict] = {
    "Entity": {"match": r"^[A-Z0-9]{18}\d{2}$", "table": "gleif", "key": "lei",
               "identify": ["legal_name", "country", "registration_number"],
               "context": {"children": ["gleif", "parent", "lei", "lei"]}},
    "Company": {"match": r"^(\d{8}|[A-Z]{2}\d{6})$", "table": "companies", "key": "number",
                "identify": ["name", "status"], "context": {"owners": ["control", "number", "number", "owner"]}},
    "QuezalCompany": {"match": r"^QZ-\d{6}$", "table": "qz_companies", "key": "id", "identify": ["name", "form", "sector"],
                      "context": {"holders": ["holdings", "company", "id", "holder"],
                                  "holds": ["holdings", "holder", "id", "company"]}},
    "Person": {"match": r"^QP-\d{4}$", "table": "qz_people", "key": "id", "identify": ["name"],
               "context": {"holds": ["holdings", "holder", "id", "company"]}},
    "Designation": {"match": r"^[A-Z]{3}\d{4}$", "table": "designations", "key": "id", "identify": ["name", "regime"],
                    "context": {}},
}  # fmt: skip
GOVERNS = {"P1": ["reject"], "P2": ["escalate"], "P3": ["escalate"], "P4": ["escalate"], "P5": ["approve"],
           "P6": ["approve", "reject", "escalate"], "P7": ["approve", "reject", "escalate"]}  # fmt: skip
COUNTRIES = {"russia": "RU", "switzerland": "CH", "united arab emirates": "AE", "united kingdom": "GB", "iran": "IR",
             "netherlands": "NL", "austria": "AT", "cyprus": "CY", "united states": "US", "china": "CN"}  # fmt: skip


def policy_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    for decision in ("approve", "reject", "escalate"):
        g.add_node(("decision", decision), kind="decision")
    for rule in POLICY:
        node = ("rule", rule["id"])
        g.add_node(node, kind="rule", text=rule["rule"], owner="compliance", version=1)
        for decision in GOVERNS[rule["id"]]:
            g.add_edge(node, ("decision", decision), type="GOVERNS")
    return g


def rules_for(graph: nx.DiGraph, decision: str) -> list[str]:
    target = ("decision", decision)
    if target not in graph:
        return []
    return sorted(u[1] for u, _, d in graph.in_edges(target, data=True) if d["type"] == "GOVERNS")


def rule_text(graph: nx.DiGraph, rule_id: str) -> str:
    return graph.nodes[("rule", rule_id)]["text"]


def update_rule(graph: nx.DiGraph, rule_id: str, text: str, actor: str) -> bool:
    node = graph.nodes.get(("rule", rule_id))
    if node is None or actor != node["owner"]:
        return False  # the guardrail lives here, in code: no prompt can talk its way past it
    node["text"], node["version"] = text, node["version"] + 1
    return True


def describe(regs: Registers, node_id: str, spec: dict = SPEC) -> dict:
    tables = records(regs)
    for type_name, t in spec.items():
        if not re.match(t["match"], node_id):
            continue
        record = next((r for r in tables[t["table"]] if str(r[t["key"]]) == node_id), None)
        if record is None:
            return {"error": f"no {type_name} {node_id!r}"}
        context = {rel: sorted(str(r[out]) for r in tables[table] if r[theirs] == record[ours])
                   for rel, (table, theirs, ours, out) in t["context"].items()}  # fmt: skip
        return {"type": type_name, "id": node_id, **{f: record[f] for f in t["identify"]}, "context": context}
    return {"error": f"no kind of record matches {node_id!r}"}


def _plain(name: str) -> str:
    return key(name).replace(" ", "")


def relevant_designations(regs: Registers, entity: str, hits: list[dict]) -> list[str]:
    if entity in regs.gleif:
        e = regs.gleif[entity]
        names, numbers, country = set(map(_plain, e.names)), {re.sub(r"\D", "", e.registration_number)}, e.country
    elif entity in regs.companies:
        c = regs.companies[entity]
        names, numbers, country = set(map(_plain, (c.name, *c.previous_names))), set(), "GB"
    elif entity in regs.quezal.companies:
        names, numbers, country = {_plain(regs.quezal.companies[entity].name)}, set(), "QZ"
    else:
        return []
    numbers.discard("")
    out = []
    for h in hits:
        countries = {COUNTRIES.get(c.lower()) for c in h.get("countries", [])} - {None}
        if countries and country not in countries:
            continue
        by_name = any(_plain(n) in names for n in [h["name"], *h.get("aliases", [])] if _plain(n))
        by_number = any(
            n and n in re.sub(r"\D", "", x) for x in h.get("registration_numbers", []) for n in numbers if len(n) >= 6
        )
        if by_name or by_number:
            out.append(h["id"])
    return out


SYSTEM = """You are a compliance analyst screening a supplier. Every lookup costs credits. Read the rules with
`read_rules` before you decide: a decision is accepted only if it follows them. `describe` (free) looks up any
id in any register. A sanctions search returns names that only look alike too: a designation counts only if
its name or registration number really is your supplier's, and its country doesn't contradict it."""


def screen(request: Request, llm: Any, distract: bool = False) -> Desk:
    desk = Desk(request, distract=distract)
    graph = policy_graph()
    extra = [
        {"name": "read_rules", "description": "The policy's rules, from the policy graph. Free.",
         "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
        {"name": "describe", "description": "Look up any id: an LEI, a UK company number, a QZ- or QP- id, a designation. Free.",
         "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"],
                        "additionalProperties": False}},
    ]  # fmt: skip

    def run(name: str, args: dict) -> Any:
        if name == "read_rules":
            return [{"id": r["id"], "rule": rule_text(graph, r["id"]), "governs": GOVERNS[r["id"]]} for r in POLICY]
        if name == "describe":
            return describe(desk.regs, str(args.get("id", "")))
        return desk.call(name, args)

    tools = [t for t in desk.tools() if t["name"] != "policy"] + extra
    convo = Conversation(llm, tools, system=SYSTEM)
    turn = convo.send(f"Screen this supplier: {request.name} ({request.country}), a contract of £{request.value:,}.")
    for _ in range(30):
        if turn.done or desk.decision is not None:
            break
        results = {c.id: run(c.name, c.arguments) for c in turn.tool_calls}
        if desk.decision is not None:
            break
        turn = convo.reply({k: v if isinstance(v, str) else json.dumps(v) for k, v in results.items()},
                           errors={k for k, v in results.items() if isinstance(v, dict) and "error" in v})  # fmt: skip
    return desk
