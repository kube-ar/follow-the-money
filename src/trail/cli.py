"""`trail`: run checks, look things up in the registers, generate a new Quezal register.

trail sources                 what's in each register, and where it came from
trail show 213800LH1BZH3DI6G760   everything the registers say about an id (LEI, company number, QZ- id)
trail find "eiger shipping"   ids whose names contain the words
trail check 1                 run milestone 1's checks on your code
trail check 1 --reference     ...on the reference solution, to see what passing looks like
trail use-reference 1         replace your file with the reference (yours is kept as .mine.py)
trail use-reference 1 --undo
trail generate --seed 7       a brand-new Quezal register in data/quezal/mine/
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import shutil
import sys
from pathlib import Path

from .milestones import MILESTONES
from .registers import QUEZAL, ROOT, load


def _milestone(mid: str):
    if mid not in MILESTONES:
        sys.exit(f"No milestone {mid!r}. Available: {', '.join(MILESTONES)}")
    return MILESTONES[mid]


def cmd_sources(args) -> None:
    r = load()
    q = r.quezal
    print(f"""
GLEIF (CC0)                 {len(r.gleif):5} legal entities, {len(r.relationships)} parent relationships
Companies House (OGL v3)    {len(r.companies):5} UK companies, {len(r.psc)} records of people with significant control
UK Sanctions List (OGL v3)  {len(r.sanctions):5} designated entities
Quezal (fictional)          {len(q.companies):5} companies, {len(q.people)} people, {len(q.holdings)} stakes, {len(q.gazette)} Gazette items, {len(q.watchlist)} watch-list entries
                            register as of {q.snapshot} · data/quezal/{q.name}

Sources, dates and licences: data/registers/SOURCES.md
""")


def cmd_show(args) -> None:
    r, key = load(), args.id.strip()
    found = False
    if key in r.gleif:
        found = True
        print(r.gleif[key])
        for rel in r.relationships:
            if key in (rel.child_lei, rel.parent_lei):
                print("  ", rel)
    if key in r.companies:
        found = True
        print(r.companies[key])
        for p in r.psc:
            if p.company_number == key:
                print("  ", p)
    if key in r.sanctions:
        found = True
        print(r.sanctions[key])
    q = r.quezal
    if key in q.companies or key in q.people:
        found = True
        print(q.companies.get(key) or f"Person {key}: {q.people[key]}")
        for h in q.holdings:
            if key in (h.holder_id, h.company_id):
                print("  ", h)
    if not found:
        sys.exit(f"No id {key!r} in the registers. Try `trail find <words>`.")


def cmd_find(args) -> None:
    r, words = load(), args.words.lower().split()

    def hit(*names: str) -> bool:
        return any(all(w in n.lower() for w in words) for n in names)

    for e in r.gleif.values():
        if hit(*e.names):
            print(f"GLEIF            {e.lei}  {e.legal_name} ({e.country})")
    for c in r.companies.values():
        if hit(c.name, *c.previous_names):
            print(f"Companies House  {c.company_number}  {c.name}")
    for d in r.sanctions.values():
        if hit(*d.names):
            print(f"UK Sanctions     {d.unique_id}  {d.name}")
    for c in r.quezal.companies.values():
        if hit(c.name):
            print(f"Quezal           {c.id}  {c.name}")


def cmd_check(args) -> None:
    m = _milestone(args.milestone)
    if args.reference:
        path = ROOT / m.reference
        spec = importlib.util.spec_from_file_location(f"reference_{m.id}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses in the module look themselves up here
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(m.module)
    checks = importlib.import_module(m.checks)
    from .checks.core import report

    print(f"Running milestone {m.id} on {'the reference solution' if args.reference else m.file}…")
    ok = report(m, checks.run(module), args.lang)
    sys.exit(0 if ok else 1)


def cmd_use_reference(args) -> None:
    m = _milestone(args.milestone)
    mine_dir, ref_dir = (ROOT / m.file).parent, (ROOT / m.reference).parent
    pairs = [(ROOT / m.file, ROOT / m.reference)] + [(mine_dir / f, ref_dir / f) for f in m.extra]

    def backup(path: Path) -> Path:
        return path.with_name(path.stem + ".mine" + path.suffix)

    if args.undo:
        if not backup(pairs[0][0]).exists():
            sys.exit(f"No backup at {backup(pairs[0][0]).relative_to(ROOT)}")
        for mine, _ in pairs:
            if backup(mine).exists():
                shutil.move(backup(mine), mine)
        print(f"Restored your files for milestone {m.id}")
        return
    if backup(pairs[0][0]).exists():
        sys.exit(f"{backup(pairs[0][0]).relative_to(ROOT)} already exists: run with --undo first, or remove it")
    for mine, ref in pairs:
        if mine.exists():
            shutil.copy(mine, backup(mine))
        shutil.copy(ref, mine)
    names = ", ".join(str(p.relative_to(ROOT)) for p, _ in pairs)
    print(f"Replaced {names} with the reference; yours are kept as *.mine.* (--undo puts them back).")


def cmd_generate(args) -> None:
    from .quezal.generate import build, export

    folder = Path(args.out) if args.out else QUEZAL / "mine" / f"seed-{args.seed}"
    if folder.exists() and any(folder.iterdir()) and not (folder / "meta.json").exists():
        sys.exit(f"{folder} exists and isn't a Quezal register: pick another --out")
    export(build(args.seed), folder)
    name = folder.relative_to(QUEZAL).as_posix() if folder.is_relative_to(QUEZAL) else str(folder)
    print(f"wrote {folder} · load it with load({name!r})")


def cmd_llm(args) -> None:
    from .llm import LLMError, get_llm

    try:
        llm = get_llm()
        print(f"Provider {llm.provider.name}, model {llm.model}" + (f", effort {llm.effort}" if llm.effort else ""))
        print("text:", llm.text("Reply with the single word: ready").strip()[:80])
        answer = llm.json(
            "Does owning 30% of a company that owns 60% of another mean owning 18% of it? Answer in the JSON format given.",
            schema={
                "type": "object",
                "properties": {"answer": {"type": "boolean"}, "why": {"type": "string"}},
                "required": ["answer", "why"],
                "additionalProperties": False,
            },
        )
        print("json:", answer)
        print(f"OK: {llm.usage.calls} calls, {llm.usage.input_tokens} tokens in, {llm.usage.output_tokens} out.")
    except LLMError as e:
        sys.exit(f"LLM setup problem: {e}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="trail", description="Follow the Money: checks and registers.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sources", help="what's in each register")
    p.set_defaults(fn=cmd_sources)

    p = sub.add_parser("show", help="everything the registers say about one id")
    p.add_argument("id")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("find", help="ids whose names contain all the words")
    p.add_argument("words")
    p.set_defaults(fn=cmd_find)

    p = sub.add_parser("check", help="run a milestone's checks")
    p.add_argument("milestone")
    p.add_argument("--reference", action="store_true", help="check the reference solution instead of your code")
    p.add_argument("--lang", default="en", choices=["en", "es"], help="language of the links to the lessons")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("use-reference", help="swap your file for the reference solution")
    p.add_argument("milestone")
    p.add_argument("--undo", action="store_true", help="put your own file back")
    p.set_defaults(fn=cmd_use_reference)

    p = sub.add_parser("llm", help="check your LLM provider setup (.env) with two tiny calls")
    p.set_defaults(fn=cmd_llm)

    p = sub.add_parser("generate", help="build a new Quezal register")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", help="folder to write (default: data/quezal/mine/seed-<seed>)")
    p.set_defaults(fn=cmd_generate)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
