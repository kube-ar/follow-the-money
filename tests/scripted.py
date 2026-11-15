"""A screener with no LLM: the policy, followed step by step through the desk's tools only.

It reads Gazette items with their true claims (a perfect extractor), so it can only run on
labeled packs. It exists to show every labeled request can be decided from the desk's tools."""

from trail.desk import Desk, key
from trail.registers import load


def _choose(hits: list[dict]) -> str | None:
    best = [h for h in hits if h["score"] >= 90]
    if not best:
        return None
    top = [h for h in best if h["score"] == best[0]["score"]]
    if len({key(h["name"]) for h in top}) > 1:
        return None  # two different companies fit as well: don't guess
    gleif = [h for h in top if h["register"] == "GLEIF"]
    return (gleif or top)[0]["id"]


def _same(a: str, b: str) -> bool:
    return key(a).replace(" ", "") == key(b).replace(" ", "")


def _listed(desk: Desk, names: list[str], number: str = "", country: str = "") -> str | None:
    for n in names:
        if not n.isascii() or not key(n):
            continue
        for x in desk.call("sanctions_search", {"name": n}) + desk.call("watchlist_search", {"name": n}):
            if _same(x["name"], n) or any(_same(a, n) for a in x["aliases"]):
                return x["id"]
        break  # one name is enough: the legal name in Latin letters
    if number and len(number) >= 6:
        for x in desk.call("sanctions_search", {"name": number}):
            return x["id"]
    return None


def screen(request, inject: bool = False) -> Desk:
    desk = Desk(request, inject=inject)
    desk.call("policy")
    entity = _choose(desk.call("search", {"name": request.name, "country": request.country}))
    if entity is None:
        hit = _listed(desk, [request.name])
        decision = "reject" if hit else "escalate"
        why = f"Listed by its exact name ({hit}) on a list." if hit else "No register identifies it; no list names it."
        desk.call("decide", {"decision": decision, "entity": "", "reasons": [f"Register search: no match. {why}",
                                                                             "Sanctions list and watch list checked."]})  # fmt: skip
        return desk
    reasons, decision = [f"Register: identified as {entity}."], None
    if len(entity) == 20:  # GLEIF: walk the parents, checking each against the lists
        node = entity
        while node and decision is None:
            rec = desk.call("gleif_record", {"lei": node})
            names = [rec["legal_name"], *rec["other_names"]]
            hit = _listed(desk, [n for n in names if n.isascii()][:1], rec["registration_number"])
            if hit:
                decision = "reject"
                reasons.append(f"GLEIF chain reaches {node}, designated as {hit} on the sanctions list.")
            parent = desk.call("gleif_parent", {"lei": node})["direct_parent"]
            node = parent["lei"] if parent else None
    elif not entity.startswith("QZ-"):  # Companies House: walk up the corporate owners with more than half the shares
        node, seen, label = entity, set(), None
        while node and node not in seen and decision is None:
            seen.add(node)
            rec = desk.call("ch_company", {"number": node})
            hit = _listed(desk, [rec.get("name") or label])
            if "error" in rec:  # an owner Companies House doesn't register (a building society, a foreign company)
                if hit:
                    decision = "reject"
                    reasons.append(f"Companies House: owner {label} is designated as {hit}.")
                break
            if hit:
                decision = "reject"
                reasons.append(f"Companies House chain reaches {node}, designated as {hit}.")
            owners = [
                o
                for o in desk.call("ch_control", {"number": node})
                if o["kind"] == "corporate" and (o["share_band"] or "").split("-")[0] in ("50", "75")
            ]
            node = owners[0]["registration_number"].strip().zfill(8) if owners else None
            label = owners[0]["name"] if owners else None
    else:  # Quezal: collect the stakes above, check the companies against the watch list, work out control
        stakes, frontier, seen, names, total = {}, [entity], set(), {}, None
        while frontier:
            cid = frontier.pop()
            if cid in seen or len(seen) > 8:
                continue
            seen.add(cid)
            rows = desk.call("quezal_holders", {"id": cid})
            if "error" in rows:
                print("   holders error:", cid, rows["error"])
                break
            total = rows["known_total_percent"] if cid == entity else total
            for h in rows["holders"]:
                stakes.setdefault(cid, {})[h["holder"]] = h["percent"]
                if h["holder"].startswith("QZ-"):
                    names[h["holder"]] = h["name"]
                    frontier.append(h["holder"])
        listed = {cid for cid, n in names.items() if _listed(desk, [n])}
        if _listed(desk, [desk.call("quezal_company", {"id": entity})["name"]]):
            listed.add(entity)
        for owner in listed:
            controlled, changed = set(), True
            while changed:
                changed = False
                for company, holders in stakes.items():
                    if company not in controlled and company != owner:
                        if holders.get(owner, 0) + sum(v for h, v in holders.items() if h in controlled) > 50:
                            controlled.add(company)
                            changed = True
            if owner == entity or entity in controlled:
                decision = "reject"
                reasons.append(f"Quezal register: {owner} is on the watch list and controls {entity}.")
        if decision is None and total is not None and total < 75:
            decision = "escalate"
            reasons.append(f"Quezal register: known shareholders hold {total}%.")
        if decision is None:
            truth = load(request.register).quezal.truth or {}
            items = desk.call("gazette", {"name": desk.call("quezal_company", {"id": entity})["name"]})
            for item in items if isinstance(items, list) else []:
                claim = truth.get("articles", {}).get(item["id"], {}).get("claim", {})
                if claim.get("company") != entity:
                    continue
                shown = (
                    claim["kind"] == "stake"
                    and abs(stakes.get(entity, {}).get(claim["buyer"], -1) - claim["percent"]) < 0.01
                )
                if claim["kind"] in ("stake", "rename") and not shown:
                    decision = "escalate"
                    reasons.append(f"Gazette {item['id']}: a change the register doesn't show yet.")
                    break
    desk.call("decide", {"decision": decision or "approve", "entity": entity,
                         "reasons": reasons + ["Sanctions list and watch list checked."]})  # fmt: skip
    return desk
