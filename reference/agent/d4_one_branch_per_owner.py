"""Agent 4 · One branch per owner: a reference solution. Spoilers: `trail use-reference d4` copies it."""

from __future__ import annotations

import json
from typing import Any

from trail.desk import DECISIONS, Desk, Request, sources_cited

KINDS = ("reasoning", "execution", "decision", "validation")
PROBLEMS = ("bad-decision", "unknown-entity", "too-few-sources", "unconsulted-source", "questionnaire-cited",
            "stakes-over-100", "approve-without-list")  # fmt: skip


def compound_success(per_step: float, steps: int) -> float:
    return per_step**steps


def plan(request: Request) -> list[dict]:
    return [
        {"id": "frame", "kind": "reasoning", "tools": [], "needs": []},
        {"id": "identify", "kind": "execution", "tools": ["search"], "needs": ["frame"]},
        {"id": "record", "kind": "execution", "tools": ["gleif_record", "ch_company", "quezal_company"], "needs": ["identify"]},
        {"id": "owners", "kind": "execution", "tools": ["gleif_parent", "ch_control", "quezal_holders"], "needs": ["identify"]},
        {"id": "lists", "kind": "execution", "tools": ["sanctions_search", "watchlist_search"], "needs": ["identify"]},
        {"id": "news", "kind": "execution", "tools": ["gazette"], "needs": ["identify"]},
        {"id": "decide", "kind": "decision", "tools": [], "needs": ["record", "owners", "lists", "news"]},
        {"id": "check", "kind": "validation", "tools": [], "needs": ["decide"]},
    ]  # fmt: skip


def expand(steps: list[dict], owners: list[str]) -> list[dict]:
    branches = [{"id": f"owner:{o}", "kind": "execution", "tools": ["sanctions_search", "watchlist_search"],
                 "needs": ["owners"]} for o in owners]  # fmt: skip
    out = [dict(s, needs=s["needs"] + [b["id"] for b in branches]) if s["id"] == "decide" else dict(s) for s in steps]
    return out + branches


def phases(steps: list[dict]) -> list[list[str]]:
    done: set[str] = set()
    left = {s["id"]: set(s["needs"]) for s in steps}
    out = []
    while left:
        ready = sorted(i for i, needs in left.items() if needs <= done)
        if not ready:
            raise ValueError("the plan has a cycle")
        out.append(ready)
        done |= set(ready)
        for i in ready:
            del left[i]
    return out


def validate_decision(desk: Desk, decision: dict) -> list[str]:
    regs, found = desk.regs, set()
    if decision.get("decision") not in DECISIONS:
        found.add("bad-decision")
    entity = (decision.get("entity") or "").strip()
    if entity and entity not in regs.gleif and entity not in regs.companies and entity not in regs.quezal.companies:
        found.add("unknown-entity")
    cited = sources_cited(decision.get("reasons", []))
    if not {"register", "list"} <= cited:
        found.add("too-few-sources")
    if (cited - {"questionnaire"}) - desk.consulted():
        found.add("unconsulted-source")
    if "questionnaire" in cited:
        found.add("questionnaire-cited")
    if sum(float(o.get("percent") or 0) for o in decision.get("owners", [])) > 100.0001:
        found.add("stakes-over-100")
    if decision.get("decision") == "approve" and "list" not in desk.consulted():
        found.add("approve-without-list")
    return [p for p in PROBLEMS if p in found]


DECISION = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "entity": {"type": "string"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "owners": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"},
                   "percent": {"type": "number"}}, "required": ["id", "percent"], "additionalProperties": False}},
    },
    "required": ["decision", "entity", "reasons", "owners"],
    "additionalProperties": False,
}  # fmt: skip


def screen(request: Request, llm: Any) -> Desk:
    desk = Desk(request)
    notes: dict[str, Any] = {"policy": desk.call("policy")}
    hits = desk.call("search", {"name": request.name, "country": request.country})
    notes["search"] = hits
    entity = hits[0]["id"] if isinstance(hits, list) and hits and hits[0]["score"] >= 90 else ""
    owners: list[str] = []
    for phase in phases(plan(request))[2:]:
        for step in phase:
            if step == "record" and entity:
                notes["record"] = desk.call("quezal_company" if entity.startswith("QZ-") else
                                            "gleif_record" if len(entity) == 20 else "ch_company",
                                            {"id": entity} if entity.startswith("QZ-") else
                                            {"lei": entity} if len(entity) == 20 else {"number": entity})  # fmt: skip
            elif step == "owners" and entity:
                if entity.startswith("QZ-"):
                    rows = desk.call("quezal_holders", {"id": entity})
                    notes["owners"] = rows
                    owners = [h["name"] for h in rows.get("holders", []) if h["holder"].startswith("QZ-")]
                elif len(entity) == 20:
                    parent = desk.call("gleif_parent", {"lei": entity})
                    notes["owners"] = parent
                    owners = [parent["direct_parent"]["name"]] if parent.get("direct_parent") else []
                else:  # a UK company number: its corporate owners with more than half the shares
                    rows = desk.call("ch_control", {"number": entity})
                    notes["owners"] = rows
                    owners = [o["name"] for o in rows if o["kind"] == "corporate"
                              and (o["share_band"] or "").startswith(("50", "75"))] if isinstance(rows, list) else []  # fmt: skip
            elif step == "lists":
                notes["lists"] = desk.call("sanctions_search", {"name": request.name}) + \
                    desk.call("watchlist_search", {"name": request.name})  # fmt: skip
            elif step == "news" and request.country.upper() == "QZ":
                notes["news"] = desk.call("gazette", {"name": request.name})
    for owner in owners[:4]:  # one branch per owner
        notes[f"owner:{owner}"] = desk.call("sanctions_search", {"name": owner}) + desk.call(
            "watchlist_search", {"name": owner}
        )
    prompt = (f"Screen the supplier {request.name} ({request.country}) under this policy. Here is everything the desk "
              "returned. Decide approve, reject or escalate; give its id; list reasons that each name their source "
              "(register, sanctions list, watch list, Gazette); never cite the supplier's questionnaire.\n\n"
              + json.dumps(notes, default=str))  # fmt: skip
    decision = llm.json(prompt, DECISION, system="You are a careful compliance analyst. Use only the evidence given.")
    problems = validate_decision(desk, decision)
    if problems:
        decision = llm.json(prompt + f"\n\nYour last answer had these problems: {problems}. Fix them.", DECISION)
    desk.call("decide", {k: decision[k] for k in ("decision", "entity", "reasons")})
    return desk
