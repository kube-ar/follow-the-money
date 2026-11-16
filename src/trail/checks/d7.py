"""Checks for agent 7, cost and clearance."""

from __future__ import annotations

import math
from types import ModuleType

from ..desk import Desk, records
from ..registers import load
from ..requests import load_requests, truth_for
from .core import NotStarted, Result, attempt, tally

L_ROUTING = ("agentic-graphrag", "model-routing", "Model routing for agents")
L_ACCESS = ("agentic-graphrag", "knowledge-graph-access-control", "Knowledge graph access control")


def run(module: ModuleType) -> list[Result]:
    routing = Result("The cheapest model that's good enough", L_ROUTING)
    cost = Result("Cost per correct decision", L_ROUTING)
    access = Result("Ownership data is invisible to a junior desk", L_ACCESS)
    audited = Result("An auditor's question, answered from the logs", L_ACCESS)
    erased = Result("Personal data, erased on request", L_ACCESS)
    try:
        models = {"small": (0.7, 1.0), "medium": (0.85, 4.0), "large": (0.95, 15.0)}
        bars = {"plan": 0.9, "extract": 0.6, "decide": 0.8}
        fixtures = [(("plan", bars, models), "large"), (("extract", bars, models), "small"),
                    (("decide", bars, models), "medium"), (("chat", bars, models), "small"),
                    (("plan", {"plan": 0.99}, models), "large")]  # fmt: skip
        right = sum(attempt(routing, module.route_model, *args) == want for args, want in fixtures)
        tally(routing, right, len(fixtures), "steps")
    except NotStarted:
        routing.started = routing.passed = False
    try:
        fixtures = [([(2.0, True), (3.0, False), (1.0, True)], 3.0), ([(1.0, False)], math.inf), ([], math.inf)]
        right = 0
        for runs, want in fixtures:
            got = attempt(cost, module.cost_per_correct, runs)
            right += got == want
            if got != want:
                cost.fail(f"cost_per_correct({runs}) = {got}, want {want}")
        tally(cost, right, len(fixtures), "fixtures")
    except NotStarted:
        cost.started = cost.passed = False
    request = next(q for q in load_requests("practice") if q.country == "QZ" and truth_for(q).entity)
    entity = truth_for(request).entity
    try:
        right = total = 0
        junior = attempt(access, module.restricted, Desk(request), "junior")
        senior = attempt(access, module.restricted, Desk(request), "senior")
        if junior is not None and senior is not None:
            names = {t["name"] for t in junior.tools()}
            total += 1
            right += not ({"ch_control", "quezal_holders"} & names) and "search" in names
            unknown = Desk(request).call("teleport", {})["error"].replace("'teleport'", "'quezal_holders'")
            total += 1
            right += junior.call("quezal_holders", {"id": entity}) == {"error": unknown}
            total += 1
            right += "holders" in (senior.call("quezal_holders", {"id": entity}) or {})
            total += 1  # the ownership board shows who owns whom too
            query = {"query": f"MATCH (h)-[:HOLDS]->(:Company {{id: '{entity}'}}) RETURN h.id LIMIT 5"}
            right += junior.call("board", query) == {"error": unknown.replace("'quezal_holders'", "'board'")}
            if right < total:
                access.fail("a junior desk must not list ch_control or quezal_holders, must fail on them and on the "
                            "board exactly like an unknown tool, and a senior desk must still have them")  # fmt: skip
        tally(access, right, total or 1, "checks")
    except NotStarted:
        access.started = access.passed = False
    try:
        other = next(q for q in load_requests("standard") if q.country == "QZ")
        a, b = Desk(request), Desk(other)
        a.call("quezal_company", {"id": entity})
        a.call("quezal_holders", {"id": entity})
        a.call("quezal_holders", {"id": "QZ-000000"})
        b.call("watchlist_search", {"name": request.name})
        b.call("quezal_holders", {"id": entity})
        want = [(request.id, 2, "quezal_holders"), (other.id, 2, "quezal_holders")]
        got = attempt(audited, module.audit, [a, b], entity)
        ok = got == want
        if not ok:
            audited.fail(f"audit = {got}, want {want}")
        tally(audited, int(ok), 1, "questions")
    except NotStarted:
        audited.started = audited.passed = False
    try:
        people = records(load())["qz_people"]
        person = people[3]["id"]
        got = attempt(erased, module.erase, people, person)
        want = [{"id": p["id"]} if p["id"] == person else p for p in people]
        ok = got == want
        if not ok:
            erased.fail("only this person's row loses its personal data: the id stays, the rest goes")
        tally(erased, int(ok), 1, "tables")
    except NotStarted:
        erased.started = erased.passed = False
    return [routing, cost, access, audited, erased]
