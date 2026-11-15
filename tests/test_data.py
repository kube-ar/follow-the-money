"""The data: the real slice is consistent and keeps no personal data; Quezal is reproducible and sound."""

import csv
import json
import os
import tempfile
from pathlib import Path

import pytest

from trail import answers
from trail.quezal.generate import build, build_final, export, norm
from trail.registers import DATA, QUEZAL, load, load_quezal

PSC_COLUMNS = ["company_number", "psc_id", "kind", "name", "registration_number", "country_registered", "legal_form",
               "natures_of_control", "notified_on", "ceased_on", "statement"]  # fmt: skip


def test_slice_loads_and_links():
    regs = load()
    assert len(regs.gleif) > 1000 and len(regs.companies) > 500 and len(regs.sanctions) > 1000
    assert {r.child_lei for r in regs.relationships} <= set(regs.gleif)
    assert {r.parent_lei for r in regs.relationships} <= set(regs.gleif)
    assert {p.company_number for p in regs.psc} <= set(regs.companies)
    assert len(answers.uk_links(regs)) > 400


def test_no_personal_data_in_the_slice():
    with (DATA / "registers" / "companies_house" / "psc.csv").open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == PSC_COLUMNS  # no birth date, nationality, address or name fields for people
        for row in reader:
            if row["kind"] == "individual":
                assert row["name"] == row["registration_number"] == row["country_registered"] == ""
    with (DATA / "registers" / "uk_sanctions" / "entities.csv").open(encoding="utf-8") as f:
        assert "date_of_birth" not in (csv.DictReader(f).fieldnames or [])


def test_sanction_matches_are_in_the_slice():
    regs = load()
    for uid, lei in answers.SANCTION_MATCHES.items():
        assert uid in regs.sanctions and lei in regs.gleif


def test_practice_register_is_reproducible():
    with tempfile.TemporaryDirectory() as d:
        export(build(1), Path(d))
        for f in (QUEZAL / "practice").iterdir():
            assert (Path(d) / f.name).read_bytes() == f.read_bytes(), f.name


def test_final_register_ships_without_its_truth():
    folder = QUEZAL / "final"
    assert not (folder / "truth.json").exists()
    assert json.loads((folder / "meta.json").read_text())["seed"] is None
    assert len(json.loads((folder / "answers.sha256.json").read_text())["hidden_controllers"]) == 3


@pytest.mark.skipif(not os.environ.get("TRAIL_FINAL_SEED"), reason="the final register's seed is secret")
def test_final_register_is_reproducible():
    with tempfile.TemporaryDirectory() as d:
        build_final(Path(d))
        for f in (QUEZAL / "final").iterdir():
            assert (Path(d) / f.name).read_bytes() == f.read_bytes(), f.name


@pytest.mark.parametrize("seed", range(1, 31))
def test_generated_registers_are_sound(seed):
    world = build(seed)
    assert all(world.held(c.id) <= 100.001 for c in world.companies)
    assert all(len(g["mentions"]) >= 2 for g in world.truth["articles"].values())
    with tempfile.TemporaryDirectory() as d:
        export(world, Path(d))
        q = load_quezal(Path(d))
        listed = {c for c in answers.watchlist_matches(q).values() if c}
        assert answers.hidden_controllers(q, listed) == {(s["controller"], s["target"]) for s in q.truth["schemes"]}


def test_quezal_names_are_not_real_names():
    regs = load()
    real = {norm(n) for e in regs.gleif.values() for n in e.names} | {norm(c.name) for c in regs.companies.values()}
    for name in ("practice", "final"):
        q = load_quezal(name)
        assert not {norm(c.name) for c in q.companies.values()} & real


def test_request_packs_and_history_are_reproducible():
    from dataclasses import asdict

    from trail.requests import REQUESTS, build, build_history

    regs = load("practice")
    for pack in ("practice", "standard", "hard"):
        shipped = json.loads((REQUESTS / f"{pack}.json").read_text(encoding="utf-8"))
        assert [asdict(r) for r, _ in build(pack, regs, "practice")] == shipped
    assert build_history(regs) == json.loads((REQUESTS / "history.json").read_text(encoding="utf-8"))
