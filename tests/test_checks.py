"""The reference solutions pass their checks, the starters are 'not started', and wrong answers fail."""

import importlib
import importlib.util
import os
import shutil
import sys
import types

import pytest

from trail.milestones import MILESTONES
from trail.registers import ROOT


def load(path):
    spec = importlib.util.spec_from_file_location(f"ref_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def reference(mid):
    return load(ROOT / MILESTONES[mid].reference)


def neo4j_up() -> bool:
    try:
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "trail-password"))
        with GraphDatabase.driver(uri, auth=auth) as driver:
            driver.verify_connectivity()
        return True
    except Exception:
        return False


def failing(mid, module) -> set[str]:
    results = importlib.import_module(MILESTONES[mid].checks).run(module)
    return {r.name for r in results if not r.passed and r.started}


def patched(mid, **overrides):
    ref = reference(mid)
    module = types.SimpleNamespace(**{n: getattr(ref, n) for n in dir(ref) if not n.startswith("__")})
    for k, v in overrides.items():
        setattr(module, k, v)
    return module, ref


@pytest.mark.parametrize("mid", sorted(MILESTONES))
def test_reference_passes(mid):
    if mid == "4" and not neo4j_up():
        pytest.skip("needs Neo4j: docker compose up -d")
    assert failing(mid, reference(mid)) == set()  # LLM checks are "not started" without an LLM (as in CI)


UPSTREAM = os.environ.get("GITHUB_REPOSITORY", "") == "kube-ar/follow-the-money" or os.environ.get("TRAIL_UPSTREAM")


@pytest.mark.skipif(not UPSTREAM, reason="your copy has your code in the starter files, not the stubs")
@pytest.mark.parametrize("mid", sorted(MILESTONES))
def test_starter_is_not_started(mid):
    m = MILESTONES[mid]
    results = importlib.import_module(m.checks).run(load(ROOT / m.file))
    assert all(not r.started for r in results)


def test_m1_catches_a_walk_that_trusts_gleif_ultimate_records():
    from trail import answers
    from trail.registers import load as regs_load

    reported = {r.child_lei: r.parent_lei for r in regs_load().relationships if r.type == "ultimate"}
    module, ref = patched("1", ultimate_parent=lambda g, lei: reported.get(lei, lei))
    assert "The top of every chain" in failing("1", module)
    assert answers.gleif_disagreements(regs_load())


def test_m2_catches_fuzzy_designations_and_a_closed_world():
    from rapidfuzz import fuzz

    ref = reference("2")

    def fuzzy(regs):
        pairs = {p for p in ref.match(regs) if p[0] not in regs.sanctions}
        for d in regs.sanctions.values():
            for e in regs.gleif.values():
                if any(fuzz.token_sort_ratio(a.upper(), b.upper()) >= 88 for a in d.names[:2] for b in e.names[:2]):
                    pairs.add((d.unique_id, e.lei))
        return pairs

    def closed(regs, matches, entity):
        status = ref.sanction_status(regs, matches, entity)
        return "clean" if status == "no listing found" else status

    assert "Designations, without false alarms" in failing("2", patched("2", match=fuzzy)[0])
    assert "Not listed isn't clean" in failing("2", patched("2", sanction_status=closed)[0])


def test_m3_catches_a_lag_read_from_dates():
    def by_date(regs, claims):
        published = {a.id: a.published_on for a in regs.quezal.gazette}
        return {aid for aid, c in claims.items() if c["kind"] != "director" and published[aid] > regs.quezal.snapshot}

    assert "What the register doesn't show yet" in failing("3", patched("3", not_in_register=by_date)[0])


def test_m3_reads_claims_with_a_fake_llm():
    """The reference's LLM path, with a model that answers from the truth: claims come back with register ids."""
    from trail.checks.m3 import claim_key
    from trail.registers import load as regs_load

    ref, regs = reference("3"), regs_load()
    truth = regs.quezal.truth["articles"]

    class FakeLLM:
        def __init__(self, article):
            self.article = article

        def json(self, prompt, schema, system=None):
            gold = truth[self.article.id]
            text = {m["entity"]: m["text"] for m in gold["mentions"]}
            c = gold["claim"]
            row = {"kind": c["kind"], "buyer": text.get(c.get("buyer"), ""), "seller": text.get(c.get("seller"), ""),
                   "company": text.get(c.get("company"), ""), "percent": c.get("percent") or 0,
                   "new_name": c.get("new_name", ""), "person": text.get(c.get("person"), ""), "date": c["date"]}  # fmt: skip
            return {"claims": [row]}

    right = sum(claim_key(ref.read_article(regs, a, FakeLLM(a))[0]) == claim_key(truth[a.id]["claim"])
                for a in regs.quezal.gazette)  # fmt: skip
    assert right / len(regs.quezal.gazette) > 0.9


@pytest.mark.skipif(not neo4j_up(), reason="needs Neo4j: docker compose up -d")
def test_m4_catches_shortest_chains_and_direct_control():
    def shortest(board, owner, company):
        rows = board.q("MATCH p = shortestPath((o {id: $o})-[:HOLDS*1..8]->(c:Company {id: $c})) "
                       "RETURN reduce(s = 1.0, r IN relationships(p) | s * r.percent / 100.0) AS share", o=owner, c=company)  # fmt: skip
        return round(rows[0]["share"], 6) if rows else 0.0

    def direct(board, owner):
        return {
            r["c"]
            for r in board.q("MATCH (o {id: $o})-[x:HOLDS]->(c:Company) WHERE x.percent > 50 RETURN c.id AS c", o=owner)
        }

    assert "Effective ownership, chain by chain" in failing("4", patched("4", effective_ownership=shortest)[0])
    assert "Control through a majority at each step" in failing("4", patched("4", controlled_by=direct)[0])


@pytest.mark.skipif(not neo4j_up(), reason="needs Neo4j: docker compose up -d")
def test_m4_validates_model_written_queries_before_running_them():
    from trail.registers import load as regs_load

    ref = reference("4")
    board = ref.store(regs_load())

    class FakeLLM:
        def __init__(self, cypher):
            self.cypher = cypher

        def json(self, prompt, schema, system=None):
            return {"cypher": self.cypher}

    rows = ref.generated_query(board, "?", FakeLLM("MATCH (c:Company {source: 'quezal'}) RETURN c.id AS id LIMIT 500"))
    assert len(rows) > 100
    assert ref.generated_query(board, "?", FakeLLM("MATCH (n) DETACH DELETE n")) == []
    assert ref.store_summary(board)["companies"] > 2000  # the bad query never ran


def test_m5_catches_direct_majorities_counted_as_hidden():
    ref = reference("5")

    def everything(regs):
        listed = {b for a, b in ref._matches(regs) if a.startswith("QFA-")}
        return {(c, t) for c in listed for t in ref._m2()._controlled(regs, c)}

    assert "Hidden controllers, practice register" in failing("5", patched("5", hidden_controllers=everything)[0])


def test_d1_catches_a_failure_rule_left_out():
    ref = reference("d1")

    def four(desk):
        return [f for f in ref.failures(desk) if f != "temporal ignorance"]

    assert "Failures, named" in failing("d1", patched("d1", failures=four)[0])


def test_d2_catches_near_misses_taken_at_face_value():
    def everything(regs, entity, hits):
        return [h["id"] for h in hits]

    assert "Near misses don't count" in failing("d2", patched("d2", relevant_designations=everything)[0])


def test_d3_catches_a_memory_that_only_reads_the_register():
    from trail import answers

    def register_only(history, regs):
        return [h["id"] for h in history if any(s.since > h["decided_on"] for s in answers.holdings(regs.quezal)
                                                if s.company_id == h["entity"])]  # fmt: skip

    assert "Past approvals gone stale" in failing("d3", patched("d3", stale=register_only)[0])


def test_d5_catches_a_gate_that_lets_everything_through():
    assert "Text the supplier wrote can't drive an action" in failing(
        "d5", patched("d5", allowed=lambda *a: "allow")[0]
    )


@pytest.mark.skipif(not neo4j_up(), reason="needs Neo4j: docker compose up -d")
def test_d4_decides_through_structured_output_with_a_fake_llm():
    from trail.requests import load_requests, truth_for

    ref = reference("d4")
    request = load_requests("practice")[2]  # a Quezal company a listed one controls
    truth = truth_for(request)

    class FakeLLM:
        calls = 0

        def json(self, prompt, schema, system=None):
            FakeLLM.calls += 1
            if FakeLLM.calls == 1:  # first answer: two problems, so the reference retries
                return {"decision": "reject", "entity": truth.entity, "reasons": ["Something is off."], "owners": []}
            return {"decision": "reject", "entity": truth.entity, "owners": [],
                    "reasons": ["Quezal register: a watch-listed company controls it.", "Watch list: listed."]}  # fmt: skip

    desk = ref.screen(request, FakeLLM())
    assert FakeLLM.calls == 2 and desk.verdict()["correct"]


def test_d2_catches_an_empty_spec():
    """With no entries, describe answers "unknown" for everything; the check says what an entry needs."""
    onto = run_checks("d2", patched("d2", SPEC={})[0])["One tool for every kind of record"]
    assert not onto.passed and "SPEC has no entries" in onto.details[0]


def test_d2_explains_a_spec_with_other_key_names():
    """A SPEC that names its keys its own way fails with a message, not a KeyError inside the checker."""
    spec = {"Entity": {"regex": r"^[A-Z0-9]{18}\d{2}$", "source": "gleif", "id": "lei", "fields": ["legal_name"],
                       "links": {}}}  # fmt: skip
    onto = run_checks("d2", patched("d2", SPEC=spec)[0])["One tool for every kind of record"]
    assert onto.started and not onto.passed
    assert "exactly the keys match, table, key, identify and context" in onto.details[0]


def run_checks(mid, module) -> dict:
    return {r.name: r for r in importlib.import_module(MILESTONES[mid].checks).run(module)}


def test_m2_catches_a_status_that_ignores_the_thresholds():
    """Anyone above counts, whatever their share: the listings the check makes up catch it."""
    from collections import defaultdict

    from trail import answers

    def anyone_above(regs, matches, entity):
        listed = {b for a, b in matches if a in regs.sanctions or a.startswith("QFA-")}
        same = defaultdict(set)
        for a, b in matches:
            if a in regs.gleif and b in regs.companies:
                same[a] |= {a, b}
                same[b] |= {a, b}
        listed |= {x for b in list(listed) for x in same[b]}
        links, up = answers.psc_links(regs), defaultdict(set)
        for child, parent in answers.direct_parents(regs).items():
            up[child].add(parent)
        for p in regs.psc:
            if p.active and p.psc_id in links:  # any band, 25-50% too
                up[p.company_number].add(links[p.psc_id])
        for h in answers.holdings(regs.quezal):  # any stake, a minority one too
            up[h.company_id].add(h.holder_id)
        if entity in listed:
            return "listed"
        seen, stack = {entity}, [entity]
        while stack:
            node = stack.pop()
            for owner in {o for i in same[node] | {node} for o in up[i]}:
                if owner in listed:
                    return "owned by a listed entity"
                if owner not in seen:
                    seen.add(owner)
                    stack.append(owner)
        return "no listing found"

    status = run_checks("2", patched("2", sanction_status=anyone_above)[0])["Not listed isn't clean"]
    assert not status.passed
    assert any(d.startswith(("07282059", "QZ-618835")) for d in status.details)


def test_m3_counts_each_mention_once():
    """Every span twice: recall can't pass 1, and the second copy of each is a wrong link."""
    ref = reference("3")

    def twice(regs, article):
        return ref.find_entities(regs, article) * 2

    assert "Companies and people found and linked" in failing("3", patched("3", find_entities=twice)[0])


def test_m4_catches_a_validator_that_knows_only_its_templates():
    """It rejects everything it didn't write; harmless queries a model might write must pass too."""
    ref = reference("4")

    def no_store(regs):
        raise NotImplementedError  # the guard is checked before the store: no Neo4j needed here

    module = patched("4", validate_query=lambda q: q in ref.TEMPLATES.values(), store=no_store)[0]
    assert "Model-written queries are checked first" in failing("4", module)


def test_d4_keeps_execution_steps_to_three_tools():
    """Three tools fit one question asked of three registers; a fourth means the step does too much."""
    from trail.requests import load_requests

    ref = reference("d4")

    def wide(request):
        return [
            dict(s, tools=[*s["tools"], "watchlist_search"]) if s["id"] == "owners" else s for s in ref.plan(request)
        ]

    assert max(len(s["tools"]) for s in ref.plan(load_requests("practice")[0])) == 3  # the reference uses all three
    assert "A plan that's a workflow graph" in failing("d4", patched("d4", plan=wide)[0])


def _approve(desk, read=True):
    if read:
        desk.call("questionnaire")
    desk.call("search", {"name": desk.request.name, "country": desk.request.country})
    desk.call("sanctions_search", {"name": desk.request.name})
    desk.call(
        "decide",
        {"decision": "approve", "entity": "", "reasons": ["Register: searched.", "Sanctions list: not listed."]},
    )
    return desk


def test_d5_blames_the_instruction_only_for_approvals_it_caused(monkeypatch):
    """An agent that approves everything is wrong, but not because of the instruction; one that obeys it is fooled."""
    from scripted import screen as careful

    from trail.checks import d5
    from trail.desk import Desk
    from trail.requests import load_requests, truth_for

    monkeypatch.setattr(d5, "needs_llm", lambda r: "a model")
    name = "The agent, with an instruction planted in the questionnaire"

    def careless(request, llm, inject=False):
        return _approve(Desk(request, inject=inject))

    def obedient(request, llm, inject=False):
        return _approve(Desk(request, inject=True)) if inject else careful(request)

    agent = run_checks("d5", patched("d5", screen=careless)[0])[name]
    assert "An instruction in a questionnaire got a supplier approved." not in agent.details
    assert any("without the instruction too" in n for n in agent.notes)
    agent = run_checks("d5", patched("d5", screen=obedient)[0])[name]
    assert "An instruction in a questionnaire got a supplier approved." in agent.details
    request = next(q for q in load_requests("practice") if truth_for(q).decision != "approve")
    injected = _approve(Desk(request, inject=True))
    assert d5.fooled(request, injected, careful(request))
    assert not d5.fooled(request, injected, _approve(Desk(request)))  # it approves without the instruction too
    assert not d5.fooled(request, _approve(Desk(request, inject=True), read=False), careful(request))  # never read it
    # a wrong approval that doesn't come back on a second run with the instruction is variance, not the instruction
    assert not d5.fooled(request, injected, careful(request), careful(request))
    assert d5.fooled(request, injected, careful(request), _approve(Desk(request, inject=True)))

    flaky = iter([True, False])  # obeys the first time only: a fluke

    def once(request, llm, inject=False):
        if inject and truth_for(request).decision != "approve" and next(flaky, False):
            return _approve(Desk(request, inject=True))
        return careful(request)

    agent = run_checks("d5", patched("d5", screen=once)[0])[name]
    assert "An instruction in a questionnaire got a supplier approved." not in agent.details
    assert any("variance" in n for n in agent.notes)


@pytest.mark.parametrize("mid", sorted(MILESTONES))
def test_a_reference_works_next_to_milestones_you_skipped(mid, tmp_path):
    """As after `trail use-reference`: the reference sits in your folder, next to files that may still be stubs.
    A reference that needs another milestone loads that one from reference/, so a stub beside it changes nothing."""
    from trail.registers import load as regs_load

    m = MILESTONES[mid]
    mine = ROOT / m.file
    for sibling in mine.parent.glob("*.py"):  # the worst case: every other milestone of the course not started
        (tmp_path / sibling.name).write_text('raise NotImplementedError("a milestone you skipped")\n')
    shutil.copy(ROOT / m.reference, tmp_path / mine.name)
    spec = importlib.util.spec_from_file_location(f"copied_{mid}", tmp_path / mine.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if mid == "5":
        assert module.screen(regs_load(), "BP P.L.C.", "GB")["status"] in module.STATUSES
    if mid == "d8":
        from trail.requests import load_requests, truth_for

        request = load_requests("practice")[2]

        class FakeLLM:
            def json(self, prompt, schema, system=None):
                return {"decision": "reject", "entity": truth_for(request).entity, "owners": [],
                        "reasons": ["Quezal register: a watch-listed company controls it.", "Watch list: listed."]}  # fmt: skip

        assert module.screen(request, FakeLLM()).decision is not None


def test_no_llm_skips_the_model_checks(monkeypatch):
    """`trail check --no-llm`: a model check is not started, with a note, even when a model is set up."""
    from trail.checks import core

    monkeypatch.setattr(core, "NO_LLM", True)
    monkeypatch.setenv("TRAIL_LLM_PROVIDER", "anthropic")
    r = core.Result("a model check", None)
    assert core.needs_llm(r) is None
    assert not r.started and core.SKIPPED in r.notes


def test_a_failed_model_call_reaches_the_check():
    """attempt() doesn't swallow an LLMError: the check says the call failed instead of scoring a miss."""
    from trail.checks.core import Result, attempt
    from trail.llm import LLMError

    def read(article, llm):
        raise LLMError("the key in ANTHROPIC_API_KEY was rejected")

    r = Result("claims", None)
    with pytest.raises(LLMError):
        attempt(r, read, None, None)


def test_d4_fails_a_decision_the_officer_refuses(monkeypatch):
    """The plan milestone is about checking a decision before the officer sees it: a refused one fails it."""
    from trail import board
    from trail.desk import Desk

    monkeypatch.setenv("TRAIL_LLM_PROVIDER", "anthropic")  # configured, but never called below
    monkeypatch.setattr(board, "reachable", lambda: None)  # this agent never asks the board

    def screen(request, llm, mention_questionnaire=False):
        desk = Desk(request)
        desk.call("search", {"name": request.name, "country": request.country})
        desk.call("sanctions_search", {"name": request.name})
        reasons = ["The register search returned it.", "The sanctions list has no entry."]
        if mention_questionnaire:
            reasons.append("The questionnaire isn't evidence, so we ignored it.")  # any mention cites it (P7)
        desk.call("decide", {"decision": "escalate", "entity": "", "reasons": reasons})
        return desk

    refused = run_checks("d4", patched("d4", screen=lambda r, llm: screen(r, llm, True))[0])["The planned screening"]
    assert not refused.passed and "0 accepted" in refused.score and any("refused" in d for d in refused.details)
    clean = run_checks("d4", patched("d4", screen=screen)[0])["The planned screening"]
    assert clean.passed and "6 accepted" in clean.score


def _gathered(ref, request):
    from trail.desk import Desk

    desk, notes = Desk(request), {}
    for phase in ref.phases(ref.plan(request)):
        for step in phase:
            if step in ref.STEPS:
                ref.STEPS[step](desk, request, notes)
    for owner in notes["owners"]:
        ref._owner_branch(desk, owner, notes)
    return desk, notes


@pytest.mark.skipif(not neo4j_up(), reason="needs Neo4j: docker compose up -d")
def test_d4_reference_gathers_what_each_rule_needs():
    """On every request of every pack, with no model, the reference's plan returns the facts the policy's answer
    rests on: a listed owner however far up the chain (P1), no identification (P2), the known stake (P3), a Gazette
    item about the supplier (P4), and no list or stake problem for an approval. Inside the budget."""
    from trail.desk import DECISIONS
    from trail.requests import load_requests, truth_for

    ref = reference("d4")
    for pack in ("practice", "standard", "hard", "final"):
        for request in load_requests(pack):
            truth = truth_for(request)
            want = truth.decision or next(d for d in DECISIONS if truth.right(d))
            desk, notes = _gathered(ref, request)
            held = notes.get("holders") or {}
            listed, low = bool(ref.listed_names(notes)), held.get("known_total_percent", 100) < 75
            assert listed == (want == "reject"), request.name
            if want == "approve":
                assert notes["entity"] and not low, request.name
            if truth.rule == "P2":
                assert not notes["entity"], request.name
            if truth.rule == "P3":
                assert low, request.name
            if truth.rule == "P4":
                assert ref.about_the_supplier(notes)[0], request.name
            assert desk.spent <= desk.budget, request.name


@pytest.mark.skipif(not neo4j_up(), reason="needs Neo4j: docker compose up -d")
def test_d4_reference_repairs_and_catches_what_code_can_see():
    from trail.requests import load_requests

    ref = reference("d4")
    request = load_requests("practice")[2]  # Low Cay Fuels: a watch-listed company controls it, two levels up
    desk, notes = _gathered(ref, request)
    assert [o["id"] for o in notes["owners"]] == ["QZ-601800"] and "54%" in notes["owners"][0]["how"]
    decision = {"decision": "reject", "entity": "Low Cay Fuels LLC (QZ-877779)", "owners": [],
                "reasons": ["Quezal register: QZ-601800 controls it.", "Watch list: QFA-01.",
                            "The questionnaire says it is independent."]}  # fmt: skip
    fixed = ref.repaired(desk, notes, decision)
    assert fixed["entity"] == "QZ-877779" and len(fixed["reasons"]) == 2
    assert ref.validate_decision(desk, fixed) == [] and ref.contradictions(notes, fixed) == []
    assert ref.contradictions(notes, {**fixed, "decision": "approve"})
    schema = ref.decision_schema(notes)
    assert "QZ-877779" in schema["properties"]["entity"]["enum"] and "" in schema["properties"]["entity"]["enum"]


def test_the_board_is_read_only_and_bounded():
    """What a model writes for the board is checked before it runs: no Neo4j needed for that."""
    from trail.board import problem, sources

    ok = "MATCH (h)-[x:HOLDS*1..3]->(c:Company {id: 'QZ-877779'}) RETURN h.id LIMIT 10"
    assert problem(ok, 50) is None and sources(ok) == {"register"}
    assert "read-only" in problem("MATCH (n) DETACH DELETE n RETURN 1 LIMIT 1", 50)
    assert "LIMIT" in problem("MATCH (c:Company) RETURN c.id", 50)
    assert "Designation" in problem("MATCH (d:Designation) RETURN d LIMIT 5", 50)  # the lists stay at the desk
    assert sources("MATCH (a:Article)-[:MENTIONS]->(c:Company) RETURN a.id LIMIT 5") == {"news", "register"}


def test_the_officer_counts_what_a_board_query_read(monkeypatch):
    from trail import board
    from trail.desk import Desk
    from trail.requests import load_requests

    monkeypatch.setattr(board, "run", lambda regs, register, query, params, max_rows: [{"id": "QZ-1"}])
    desk = Desk(load_requests("practice")[2])
    desk.call("board", {"query": "MATCH (a:Article) RETURN a.id LIMIT 5"})
    assert desk.consulted() == {"news"} and desk.spent == desk.COSTS["board"]
    assert "board" not in {t["name"] for t in desk.tools()} and "board" in {t["name"] for t in desk.tools(board=True)}


def test_the_board_keeps_the_mentions_the_linker_cant_resolve():
    """A short name that fits several companies stays linked to all of them, unsure; a full name is sure.
    Milestone 3's linker, as the desk loads it."""
    from trail.board import mentions
    from trail.registers import load

    final = load("final")
    larkspur = next(a for a in final.quezal.gazette if a.id == "G-020")  # "Larkspur issued new shares…": nine Larkspurs
    assert mentions(final, larkspur).get("QZ-248304") is False
    practice = load("practice")
    velden = {a.id: a for a in practice.quezal.gazette}
    assert mentions(practice, velden["G-002"]).get("QZ-102501") is False  # "…holds 51% of Velden Shoal": which one?
    assert mentions(practice, velden["G-024"]).get("QZ-102501") is True  # "Velden Shoal Partners", in full


def test_d4_needs_a_plan_that_asks_the_board():
    ref = reference("d4")
    no_graph = [dict(s, tools=[t for t in s["tools"] if t != "board"] or ["gazette"]) for s in ref.plan(None)]
    no_graph = [dict(s, tools=[]) if s["kind"] != "execution" else s for s in no_graph]
    assert "A plan that's a workflow graph" in failing("d4", patched("d4", plan=lambda request: no_graph)[0])


def test_d7_catches_a_junior_desk_that_can_ask_the_board():
    """The ownership board shows who owns whom: a junior desk that still answers it leaks what the role hides."""
    ref = reference("d7")
    leaky = dict(ref.RESTRICTED, junior={"ch_control", "quezal_holders"})
    module = patched("d7", restricted=lambda desk, role: ref._Restricted(desk, leaky.get(role, set())))[0]
    assert "Ownership data is invisible to a junior desk" in failing("d7", module)
