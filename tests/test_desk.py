"""The compliance desk: tools, the officer's rules, and every labeled request decidable from the tools."""

import json
from types import SimpleNamespace

import openai
import pytest
from scripted import screen

from trail.desk import INJECTION, Desk
from trail.llm import get_llm
from trail.requests import PACKS, load_requests, truth_for


@pytest.mark.parametrize("pack", ["practice", "standard", "hard"])
def test_every_labeled_request_is_decidable_from_the_tools(pack):
    for request in load_requests(pack):
        desk = screen(request)
        v = desk.verdict()
        assert v["correct"], (request.id, desk.decision, v["reason"])
        assert desk.spent <= desk.budget


def test_the_planted_instruction_changes_nothing_for_a_careful_screener():
    for request in load_requests("practice"):
        assert screen(request, inject=True).verdict()["correct"]
    desk = Desk(load_requests("practice")[0], inject=True)
    assert INJECTION in desk.call("questionnaire")


def test_final_decisions_are_hashed_but_scorable():
    for request in load_requests("final"):
        truth = truth_for(request)
        assert truth.decision is None and truth.digest
        assert sum(truth.right(d) for d in ("approve", "reject", "escalate")) == 1


def test_the_officer_follows_the_policy():
    request = next(r for r in load_requests("practice") if r.country == "QZ")
    desk = Desk(request)
    desk.call("search", {"name": request.name, "country": "QZ"})
    desk.call("decide", {"decision": "approve", "entity": "", "reasons": ["Register: found.", "Watch list: clear."]})
    assert "P6" in desk.verdict()["reason"]  # cites a list it never consulted
    desk = Desk(request)
    desk.call("search", {"name": request.name, "country": "QZ"})
    desk.call("watchlist_search", {"name": request.name})
    desk.call("decide", {"decision": "approve", "entity": "", "reasons": ["Register: found.", "Watch list: clear.",
                                                                          "The questionnaire says it's independent."]})  # fmt: skip
    assert "P7" in desk.verdict()["reason"]
    assert desk.call("search", {"name": "x", "country": "GB"})["error"].startswith("the screening is over")


def test_budget_and_bad_arguments_come_back_as_errors():
    desk = Desk(load_requests("practice")[0], budget=1)
    assert "error" in desk.call("sanctions_search", {"name": "x"})
    assert "error" in desk.call("gleif_record", {"nope": 1})
    assert "error" in desk.call("teleport", {})
    assert desk.spent == 0 and all(not a.ok for a in desk.log)


def test_packs_cover_every_rule():
    rules = {truth_for(r).rule for pack in PACKS[:3] for r in load_requests(pack)}
    assert rules == {"P1", "P2", "P3", "P4", "P5"}


def test_an_agent_loop_on_a_scripted_model(monkeypatch):
    """The d1 reference's loop, on a fake OpenAI-compatible model that searches, checks, then decides."""
    import importlib.util
    import sys

    from trail.registers import ROOT

    spec = importlib.util.spec_from_file_location("d1ref", ROOT / "reference/agent/d1_the_first_screening.py")
    ref = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ref
    spec.loader.exec_module(ref)
    request = load_requests("practice")[0]
    entity = truth_for(request).entity
    plan = [("search", {"name": request.name, "country": request.country}), ("gleif_parent", {"lei": entity}),
            ("sanctions_search", {"name": request.name}),
            ("decide", {"decision": "approve", "entity": entity,
                        "reasons": ["GLEIF register: identified.", "Sanctions list: not listed."]})]  # fmt: skip
    sent = []

    class Fake:
        def __init__(self, **kw):
            def create(**body):
                sent.append(body)
                name, args = plan[len(sent) - 1]
                call = SimpleNamespace(
                    id=f"c{len(sent)}", function=SimpleNamespace(name=name, arguments=json.dumps(args))
                )
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                                       usage=None)  # fmt: skip

            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "OpenAI", Fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("TRAIL_LLM_CACHE", "0")
    desk = ref.screen(request, get_llm("openrouter", "some/model"))
    assert desk.decision["decision"] == "approve" and desk.verdict()["correct"]
    assert ref.failures(desk) == []


def test_a_malformed_decision_is_an_error_not_a_decision():
    """Models sometimes send reasons as objects: the desk says so and the screening goes on."""
    desk = Desk(load_requests("practice")[0])
    got = desk.call("decide", {"decision": "approve", "entity": "", "reasons": [{"fact": "x", "source": "GLEIF"}]})
    assert "error" in got
    assert desk.decision is None
    assert desk.verdict()["accepted"] is False


@pytest.mark.parametrize(
    ("reason", "kinds"),
    [
        ("UK Sanctions: no match.", {"list"}),
        ("Designations searched: none is this company.", {"list"}),
        ("A strange name for a leisure group.", set()),
        ("GLEIF: its parents are registered at Companies House.", {"register"}),
        ("The shareholders are known; the Gazette reports nothing.", {"register", "news"}),
        ("The questionnaire is not evidence.", {"questionnaire"}),
    ],
)
def test_sources_are_cited_by_whole_words(reason, kinds):
    """A source counts when a reason names it as a word (plus an ending), not when its letters hide in another word."""
    from trail.desk import sources_cited

    assert sources_cited([reason]) == kinds
