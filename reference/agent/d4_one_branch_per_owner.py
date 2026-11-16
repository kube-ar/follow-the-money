"""Agent 4 · One branch per owner: a reference solution. Spoilers: `trail use-reference d4` copies it.

The plan does the lookups in code and turns what they returned into a short list of facts: the supplier,
its owners and the owners' owners, who controls it, what the lists say about each of them, what the Gazette
reports. The model makes one decision, under the policy: approve, reject or escalate. Its answer can only name
an id the desk returned (an enum in the schema), its meaning is checked before the officer sees it, what code
can fix, code fixes, and what disagrees with the facts goes back to the model once. The fewer things the model
has to get right, the less a small model gets wrong.
"""

from __future__ import annotations

import re
from typing import Any

from trail.desk import DECISIONS, Desk, Request, key, sources_cited

KINDS = ("reasoning", "execution", "decision", "validation")
PROBLEMS = ("bad-decision", "unknown-entity", "too-few-sources", "unconsulted-source", "questionnaire-cited",
            "stakes-over-100", "approve-without-list")  # fmt: skip
MATCH = 90  # a search hit this close is the supplier; below it, the registers don't identify it
LISTED = 95  # a list entry this close to a name is that name; closer ones than 85 never come back
UP = 6  # how many levels of Quezal holders the owners step climbs, at most
KEEP = 12  # credits the climb leaves for the lists and the Gazette


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
    branches = [{"id": f"owner:{o}", "kind": "execution", "tools": ["gleif_record", "sanctions_search", "watchlist_search"],
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


def is_lei(x: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{18}\d{2}", x))


def rows(result: Any, inner: str | None = None) -> list[dict]:
    """A tool's rows, or [] when it answered with an error."""
    if inner and isinstance(result, dict):
        result = result.get(inner, [])
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []


# ── The steps of the plan: each one calls only its own tools and writes what it found into `notes` ──


def _frame(desk: Desk, request: Request, notes: dict) -> None:
    notes["policy"] = desk.call("policy")
    notes["country"] = request.country.upper().strip()


def _identify(desk: Desk, request: Request, notes: dict) -> None:
    hits = rows(desk.call("search", {"name": request.name, "country": notes["country"]}))
    notes["hits"] = hits
    close = [h for h in hits if h["score"] >= MATCH]
    notes["entity"] = close[0]["id"] if close else ""
    # A UK company is in GLEIF and at Companies House: the number is what ch_control asks for.
    notes["uk_number"] = next((h["id"] for h in close if h["register"] == "Companies House"), "")


def _record(desk: Desk, request: Request, notes: dict) -> None:
    e = notes["entity"]
    if e.startswith("QZ-"):
        notes["record"] = desk.call("quezal_company", {"id": e})
    elif is_lei(e):
        notes["record"] = desk.call("gleif_record", {"lei": e})
    elif e:
        notes["record"] = desk.call("ch_company", {"number": e})


def _owners(desk: Desk, request: Request, notes: dict) -> None:
    """Who owns the supplier, by its register. On Quezal, climb: the holders, then the holders of every company
    among them, until no company is left above (or the credits run low), and work out in code who controls it."""
    e, notes["owners"] = notes["entity"], []
    if is_lei(e):
        parents = desk.call("gleif_parent", {"lei": e})
        for kind in ("direct_parent", "ultimate_parent_reported"):
            p = parents.get(kind) if isinstance(parents, dict) else None
            if p and p["lei"] not in [o["id"] for o in notes["owners"]]:
                notes["owners"].append({"id": p["lei"], "name": p["name"], "how": f"GLEIF {kind.replace('_', ' ')}"})
    if notes["uk_number"]:
        for o in rows(desk.call("ch_control", {"number": notes["uk_number"]})):
            if o["kind"] in ("corporate", "legal-person") and (o["share_band"] or "").startswith(("50", "75")):
                notes["owners"].append({"id": o.get("registration_number") or o["name"], "name": o["name"],
                                        "how": f"Companies House owner, {o['share_band']} of the shares"})  # fmt: skip
    if e.startswith("QZ-"):
        stakes: dict[str, dict[str, float]] = {}
        names: dict[str, str] = {}
        level = [e]
        for _ in range(UP):
            above = []
            for company in level:
                if company != e and desk.remaining < KEEP:
                    break
                held = desk.call("quezal_holders", {"id": company})
                if company == e and isinstance(held, dict):
                    notes["holders"] = held
                for h in rows(held, "holders"):
                    stakes.setdefault(company, {})[h["holder"]] = h["percent"]
                    names[h["holder"]] = h["name"]
                    if h["holder"].startswith("QZ-") and h["holder"] not in stakes and h["holder"] not in above:
                        above.append(h["holder"])
            level = above
        notes["stakes"], notes["names"] = stakes, names
        for owner in sorted(names):
            if owner.startswith("QZ-") and e in controlled(stakes, owner):
                notes["owners"].append(
                    {"id": owner, "name": names[owner], "how": control_story(stakes, owner, e, names)}
                )


def controlled(stakes: dict[str, dict[str, float]], owner: str) -> set[str]:
    """Companies `owner` controls: more than 50% of the votes, its own plus those of companies it already controls."""
    out: set[str] = set()
    changed = True
    while changed:
        changed = False
        for company, holders in stakes.items():
            if company not in out and company != owner:
                if holders.get(owner, 0.0) + sum(v for h, v in holders.items() if h in out) > 50:
                    out.add(company)
                    changed = True
    return out


def control_story(stakes: dict[str, dict[str, float]], owner: str, target: str, names: dict[str, str]) -> str:
    """How `owner` controls `target`, in one line: its own stake and the stakes of the companies it controls."""
    mine = controlled(stakes, owner)
    parts = [f"{stakes[target][owner]:g}% directly"] if owner in stakes.get(target, {}) else []
    for h, v in sorted(stakes.get(target, {}).items()):
        if h in mine:
            parts.append(f"{v:g}% through {h} {names.get(h, '')} (which it controls)")
    total = sum(v for h, v in stakes.get(target, {}).items() if h == owner or h in mine)
    return f"controls the supplier on Quezal's register: {' + '.join(parts)} = {total:g}% of the votes"


def _lists(desk: Desk, request: Request, notes: dict) -> None:
    notes["lists"] = {
        "sanctions": rows(desk.call("sanctions_search", {"name": request.name})),
        "watchlist": rows(desk.call("watchlist_search", {"name": request.name})),
    }


def _news(desk: Desk, request: Request, notes: dict) -> None:
    """The Gazette often names a company by its first word ("Larkspur issued new shares…"). Search that word, then
    link each item in code: it's about the supplier when it names the supplier in full, or names it only by the
    short form while no item names another company that starts the same way ("Velden Shoal Capital IBC")."""
    notes["news"], notes["other_news"] = [], 0
    if notes["country"] != "QZ":
        return
    words = request.name.split()
    short = words[0] if len(words[0]) >= 4 or len(words) == 1 else " ".join(words[:2])
    notes["short"], supplier = short, key(request.name)
    items = rows(desk.call("gazette", {"name": short}))
    named = {a["id"]: [key(m) for m in re.findall(rf"\b{re.escape(short)}(?: [A-Z][\w&.-]*)*", a["text"])]
             for a in items}  # fmt: skip
    others = {n for ns in named.values() for n in ns if n != supplier and not supplier.startswith(n)}
    for a in items:
        full = supplier in key(a["text"])
        if full or (named[a["id"]] and not others):
            notes["news"].append(dict(a, full=full))
        else:
            notes["other_news"] += 1


def _owner_branch(desk: Desk, owner: dict, notes: dict) -> None:
    """One owner against the lists: by name, and a GLEIF owner also by its other names and registration number."""
    names, number = [owner["name"]], ""
    if is_lei(owner["id"]):
        rec = desk.call("gleif_record", {"lei": owner["id"]})
        if isinstance(rec, dict) and "error" not in rec:
            names = [n for n in [rec["legal_name"], *rec["other_names"]] if n.isascii()][:1] or names
            number = rec.get("registration_number") or ""
    found = {"sanctions": [], "watchlist": []}
    for n in names:
        found["sanctions"] += rows(desk.call("sanctions_search", {"name": n}))
        found["watchlist"] += rows(desk.call("watchlist_search", {"name": n}))
    if len(re.sub(r"\D", "", number)) >= 6:
        found["sanctions"] += rows(desk.call("sanctions_search", {"name": number}))
    owner["lists"] = found


STEPS = {"frame": _frame, "identify": _identify, "record": _record, "owners": _owners, "lists": _lists,
         "news": _news}  # fmt: skip


# ── The decision ──────────────────────────────────────────────────────────────

SYSTEM = """You are a careful compliance analyst. You get the facts a screening gathered and you decide under the
policy. Use only these facts. Apply the rules in order: the first one that fits decides.
- P1 reject: the supplier, or an owner or controller of it, is on the UK Sanctions List or Quezal's watch list.
- P2 escalate: no register identifies the supplier.
- P3 escalate: a Quezal supplier whose known shareholders hold less than 75%.
- P4 escalate: the Gazette reports a change for the supplier that its register doesn't show yet: a stake bought or
  agreed, or a new name, in the supplier itself. A report of something the register already shows is not a change,
  and neither is a stake the supplier takes in another company.
- P5 approve: none of the above.
A list entry counts when it is the same company: the same name (legal forms and punctuation aside) or the same
registration number. A different company with a similar name doesn't count."""


def _hits(found: dict) -> str:
    out = [f"sanctions list {h['id']} {h['name']} (score {h['score']}, registration numbers "
           f"{' '.join(h['registration_numbers']).split() or 'none'})" for h in found.get("sanctions", [])]  # fmt: skip
    out += [f"watch list {h['id']} {h['name']} (score {h['score']}): {h['reason']}" for h in found.get("watchlist", [])]
    return "; ".join(dict.fromkeys(out)) or "no entry"


def facts(desk: Desk, request: Request, notes: dict) -> str:
    """What the plan found, as short lines a model can read, each naming the source it came from."""
    lines = [f"Supplier: {request.name} ({notes['country']})."]
    e = notes["entity"]
    if e:
        hit = next(h for h in notes["hits"] if h["id"] == e)
        lines.append(f"Register search: {hit['register']} identifies it as {e}, {hit['name']} (score {hit['score']}).")
        rec = notes.get("record")
        if isinstance(rec, dict) and "error" not in rec:
            shown = {k: v for k, v in rec.items() if k in ("status", "form", "registration_number", "previous_names")}
            lines.append(f"Register record: {shown}.")
    else:
        near = ", ".join(f"{h['name']} ({h['score']})" for h in notes["hits"]) or "nothing"
        lines.append(f"Register search: no register identifies it (closest: {near}).")
    held = notes.get("holders")
    if isinstance(held, dict):
        holders = "; ".join(f"{h['holder']} {h['name']} {h['percent']:g}% since {h['since']}" for h in held["holders"])
        lines.append(f"Quezal register, shareholders as of {held['as_of']}: {holders or 'none'}. Known shareholders "
                     f"hold {held['known_total_percent']:g}% in all.")  # fmt: skip
    for o in notes["owners"]:
        lines.append(f"Register, owner {o['id']} {o['name']}: {o['how']}.")
    if e and not notes["owners"]:
        lines.append("Register: no owner or controller that is a company.")
    lines.append(f"Lists, the supplier's name: {_hits(notes.get('lists', {}))}.")
    for o in notes["owners"]:
        lines.append(f"Lists, owner {o['id']} {o['name']}: {_hits(o.get('lists', {}))}.")
    if notes["country"] == "QZ":
        news = notes.get("news", [])
        short = notes.get("short", request.name)
        for a in news:
            names = ("names the supplier in full" if a["full"] else
                     f'names it as "{short}", and no other company starting with "{short}" appears in the Gazette')  # fmt: skip
            lines.append(f"Gazette {a['id']} ({a['published_on']}, {names}): {' '.join(a['text'].split())[:400]}")
        if not news:
            lines.append("Gazette: no item is about the supplier.")
        if notes.get("other_news"):
            lines.append(f'Gazette: {notes["other_news"]} more items name other companies starting with "{short}".')
    return "\n".join(lines)


def decision_schema(notes: dict) -> dict:
    """The decision's shape, with the supplier's id as an enum of the ids the search returned (or empty)."""
    ids = sorted({h["id"] for h in notes["hits"]})
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": list(DECISIONS)},
            "entity": {"type": "string", "enum": [*ids, ""]},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "owners": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"},
                       "percent": {"type": "number"}}, "required": ["id", "percent"], "additionalProperties": False}},
        },
        "required": ["decision", "entity", "reasons", "owners"],
        "additionalProperties": False,
    }  # fmt: skip


def listed_names(notes: dict) -> list[str]:
    """The supplier and owners whose lists came back with an entry close enough to be them."""
    out = []
    for who, found in [("the supplier", notes.get("lists", {}))] + [
        (o["id"], o.get("lists", {})) for o in notes["owners"]
    ]:
        if any(h["score"] >= LISTED for h in found.get("sanctions", []) + found.get("watchlist", [])):
            out.append(who)
    return out


def contradictions(notes: dict, decision: dict) -> list[str]:
    """Where the decision disagrees with what the registers and lists returned, in words the model can act on.
    Only what the facts settle: whether a list entry is really the same company stays the model's call."""
    d, found = decision.get("decision"), []
    if d == "approve" and listed_names(notes):
        found.append(f"a list has an entry for {', '.join(listed_names(notes))}: check whether it is the same company "
                     "before approving (P1)")  # fmt: skip
    held = notes.get("holders")
    if d == "approve" and isinstance(held, dict) and held["known_total_percent"] < 75:
        found.append(f"known shareholders hold {held['known_total_percent']:g}%, under 75%: P3 escalates")
    if d == "approve" and not notes["entity"]:
        found.append("no register identifies the supplier: P2 escalates, unless a list names it (P1)")
    if d == "reject" and not listed_names(notes):
        found.append("no list returned an entry close to the supplier or any of its owners: P1 needs one")
    return found


def repaired(desk: Desk, notes: dict, decision: dict) -> dict:
    """What code can fix without guessing: an id written with a name around it, and reasons that mention the
    questionnaire or a source the desk never returned (dropped, as long as a register and a list are left)."""
    fixed = dict(decision)
    ids = {h["id"] for h in notes["hits"]}
    entity = str(fixed.get("entity") or "")
    if entity and entity not in ids:
        inside = [i for i in ids if i in entity]
        fixed["entity"] = inside[0] if len(inside) == 1 else entity
    consulted = desk.consulted()
    kept = [r for r in fixed.get("reasons", []) if sources_cited([r]) <= consulted]
    if {"register", "list"} <= sources_cited(kept):
        fixed["reasons"] = kept
    return fixed


def screen(request: Request, llm: Any) -> Desk:
    desk = Desk(request)
    notes: dict[str, Any] = {}
    steps = plan(request)
    for phase in phases(steps):
        for step in phase:
            if step in STEPS:
                STEPS[step](desk, request, notes)
            if step == "owners":  # one branch per owner, as soon as the owners are known
                steps = expand(steps, [o["id"] for o in notes["owners"]])
    for owner in notes["owners"]:
        _owner_branch(desk, owner, notes)
    consulted = sorted(desk.consulted() - {"questionnaire"})
    words = {"register": "a register (GLEIF, Companies House, the Quezal register)",
             "list": "a list (the sanctions list, the watch list)", "news": "the Gazette"}  # fmt: skip
    prompt = (f"{facts(desk, request, notes)}\n\nDecide approve, reject or escalate, give the supplier's id (empty if "
              "no register identifies it), and three or four reasons, one fact each, naming its source: "
              f"{'; '.join(words[c] for c in consulted)}. Those are the only sources consulted: name no other, and "
              "never mention what the supplier says about itself.")  # fmt: skip
    schema = decision_schema(notes)
    decision = repaired(desk, notes, llm.json(prompt, schema, system=SYSTEM))
    problems = validate_decision(desk, decision) + contradictions(notes, decision)
    if problems:
        retry = f"{prompt}\n\nYour last answer was {decision}. It had these problems: {problems}. Fix them."
        decision = repaired(desk, notes, llm.json(retry, schema, system=SYSTEM))
    desk.call("decide", {k: decision[k] for k in ("decision", "entity", "reasons")})
    return desk
