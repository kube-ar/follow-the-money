"""Checks for milestone 3, reading the Gazette."""

from __future__ import annotations

import re
from types import ModuleType

from ..registers import load
from .core import NotStarted, Result, attempt, needs_llm, tally

SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
L_LEXICAL = ("graphrag", "lexical-graph", "Lexical graph")
L_LINKING = ("graphrag", "entity-linking", "Entity linking")
L_EXTRACT = ("graphrag", "llm-knowledge-graph-extraction", "LLM knowledge graph extraction")
L_TEMPORAL = ("graphrag", "temporal-knowledge-graph-extraction", "Temporal knowledge graph extraction")


def claim_key(c: dict) -> tuple:
    kind = c.get("kind")
    if kind == "stake":
        pct = c.get("percent")
        return kind, c.get("buyer"), c.get("company"), round(float(pct), 2) if isinstance(pct, (int, float)) else pct
    if kind == "rename":
        return kind, c.get("company"), (c.get("new_name") or "").strip().lower()
    return kind, c.get("person"), c.get("company")


def run(module: ModuleType) -> list[Result]:
    regs = load()
    q = regs.quezal
    truth = q.truth
    lexical = Result("The Gazette as a lexical graph", L_LEXICAL)
    linking = Result("Companies and people found and linked", L_LINKING)
    claims = Result("Claims read with your LLM", L_EXTRACT)
    lag = Result("What the register doesn't show yet", L_TEMPORAL)
    results = [lexical, linking, claims, lag]

    try:
        graph = attempt(lexical, module.lexical_graph, regs)
        got = attempt(lexical, module.lexical_summary, graph) if graph is not None else None
        sentences = sum(len(SENTENCE.split(a.body)) for a in q.gazette)
        want = {"articles": len(q.gazette), "sentences": sentences, "next": sentences - len(q.gazette)}
        if got is not None:
            right = sum(got.get(k) == v for k, v in want.items())
            for k, v in want.items():
                if got.get(k) != v:
                    lexical.fail(f"{k}: {got.get(k)}, want {v}")
            tally(lexical, right, len(want), "counts")
    except NotStarted:
        lexical.started = lexical.passed = False

    try:
        gold_total = predicted = correct = 0
        for a in q.gazette:
            gold = [(m["start"], m["end"], m["entity"]) for m in truth["articles"][a.id]["mentions"]]
            got = attempt(linking, module.find_entities, regs, a)
            if got is None:
                continue
            gold_total += len(gold)
            used: set[int] = set()  # each gold mention counts once: a second span on it is a false positive
            for start, end, eid in got:
                predicted += 1
                on = [i for i, (s, e, who) in enumerate(gold) if s < end and start < e and eid == who]
                hit = next((i for i in on if i not in used), None)
                if hit is not None:
                    used.add(hit)
                    correct += 1
                elif len(linking.details) < 5:
                    why = "is linked twice: count each mention once" if on else f"isn't {eid}"
                    linking.details.append(f"{a.id}: {a.body[start:end]!r} {why}")
        precision = correct / predicted if predicted else 0.0
        recall = correct / gold_total if gold_total else 0.0
        linking.score = f"precision {precision:.2f}, recall {recall:.2f} over {gold_total} mentions"
        linking.passed = precision >= 0.9 and recall >= 0.8 and not any("raised" in d for d in linking.details)
        if linking.passed:
            linking.details.clear()
        else:
            linking.details.insert(0, "Needs precision ≥ 0.90 (a wrong link is worse than none) and recall ≥ 0.80.")
    except NotStarted:
        linking.started = linking.passed = False

    try:
        gold = {aid: g["claim"] for aid, g in truth["articles"].items()}
        got = attempt(lag, module.not_in_register, regs, gold)
        if got is not None:
            want = set(truth["pending"])
            got = set(got)
            for aid in sorted(want - got):
                lag.fail(f"{aid} isn't in the register yet: {next(a.body for a in q.gazette if a.id == aid)[:90]}…")
            for aid in sorted(got - want):
                lag.fail(f"{aid} is already in the register")
            tally(lag, len(q.gazette) - len(want ^ got), len(q.gazette), "items")
    except NotStarted:
        lag.started = lag.passed = False

    _claims(module, regs, claims)
    return results


def _claims(module, regs, r: Result) -> None:
    from ..llm import LLMError

    llm = needs_llm(r)
    if llm is None:
        return
    q, truth = regs.quezal, regs.quezal.truth
    tp = fp = fn = 0
    dated = months = 0
    try:
        for a in q.gazette:
            got = attempt(r, module.read_article, regs, a, llm)
            if got is None:
                continue
            gold = truth["articles"][a.id]["claim"]
            have = {claim_key(c) for c in got}
            want = {claim_key(gold)}
            tp, fp, fn = tp + len(want & have), fp + len(have - want), fn + len(want - have)
            for c in got:
                if claim_key(c) == claim_key(gold) and c.get("date"):
                    dated += 1
                    months += str(c["date"])[:7] == gold["date"][:7]
    except NotStarted:
        return
    except LLMError as e:
        r.fail(f"the LLM call failed: {e}")
        return
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    r.score = f"F1 {f1:.2f} (precision {precision:.2f}, recall {recall:.2f}) over {len(q.gazette)} items"
    if f1 < 0.7:
        r.fail("Needs F1 ≥ 0.70 on (kind, who, company, percent or new name), with register ids.")
    if dated:
        r.notes.append(f"dates in the right month (when it happened, not when it was published): {months}/{dated}")
    r.notes.append(f"LLM: {llm.provider.name} {llm.model}, {llm.usage.calls} calls ({llm.usage.cached} cached)")
