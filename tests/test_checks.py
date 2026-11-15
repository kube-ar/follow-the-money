"""The reference solutions pass their checks, the starters are 'not started', and wrong answers fail."""

import importlib
import importlib.util
import os
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
