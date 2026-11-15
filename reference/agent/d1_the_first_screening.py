"""Agent 1 · The first screening: a reference solution. Spoilers: `trail use-reference d1` copies it."""

from __future__ import annotations

from typing import Any

from trail.desk import Desk, Request
from trail.llm import Conversation

FAILURES = ("context amnesia", "relationship blindness", "temporal ignorance", "reasoning paralysis", "tool chaos")
SYSTEM = """You are a compliance analyst screening a supplier before a contract is signed. You work at a desk
of lookups: registers, sanctions and watch lists, a news gazette. Every lookup costs credits from a small
budget. Read the policy first. When you're sure, call `decide` with approve, reject or escalate, the
supplier's id and your reasons, each naming its source."""


def screen(request: Request, llm: Any, max_turns: int = 30) -> Desk:
    desk = Desk(request)
    convo = Conversation(llm, desk.tools(), system=SYSTEM)
    turn = convo.send(f"Screen this supplier: {request.name} ({request.country}), a contract of £{request.value:,}.")
    for _ in range(max_turns):
        if turn.done or desk.decision is not None:
            break
        results = {call.id: desk.call(call.name, call.arguments) for call in turn.tool_calls}
        if desk.decision is not None:
            break
        errors = {cid for cid, r in results.items() if isinstance(r, dict) and "error" in r}
        turn = convo.reply(results, errors=errors)
    return desk


def failures(desk: Desk) -> list[str]:
    calls = [a for a in desk.log if a.ok]
    keys = [(a.tool, tuple(sorted((k, str(v)) for k, v in a.arguments.items()))) for a in calls]
    found = set()
    if len(keys) != len(set(keys)):
        found.add("context amnesia")
    if not any(a.tool in ("gleif_parent", "ch_control", "quezal_holders") for a in calls):
        found.add("relationship blindness")
    if desk.request.country.upper() == "QZ" and not any(a.tool == "gazette" for a in calls):
        found.add("temporal ignorance")
    if desk.decision is None:
        found.add("reasoning paralysis")
    if sum(not a.ok for a in desk.log) >= 3:
        found.add("tool chaos")
    return [f for f in FAILURES if f in found]
