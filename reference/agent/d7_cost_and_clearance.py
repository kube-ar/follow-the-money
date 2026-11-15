"""Agent 7 · Cost and clearance: a reference solution. Spoilers: `trail use-reference d7` copies it."""

from __future__ import annotations

from typing import Any

from trail.desk import Desk

RESTRICTED = {"junior": {"ch_control", "quezal_holders"}, "senior": set()}
OWNERSHIP = ("gleif_parent", "ch_control", "quezal_holders")


def route_model(step: str, bars: dict[str, float], models: dict[str, tuple[float, float]]) -> str:
    bar = bars.get(step, 0.0)
    good = [(cost, -quality, name) for name, (quality, cost) in models.items() if quality >= bar]
    if good:
        return min(good)[2]
    return max(models, key=lambda n: models[n][0])


def cost_per_correct(runs: list[tuple[float, bool]]) -> float:
    correct = sum(1 for _, ok in runs if ok)
    return sum(c for c, _ in runs) / correct if correct else float("inf")


class _Restricted:
    def __init__(self, desk: Desk, hidden: set[str]):
        self.desk, self.hidden = desk, hidden

    def tools(self) -> list[dict]:
        return [t for t in self.desk.tools() if t["name"] not in self.hidden]

    def call(self, name: str, arguments: dict | None = None) -> Any:
        if name in self.hidden:
            # Invisible, not "denied": the same answer as for a tool that doesn't exist.
            return self.desk._record(name, dict(arguments or {}), 0, False, {"error": f"no tool {name!r}"})
        return self.desk.call(name, arguments)


def restricted(desk: Desk, role: str) -> _Restricted:
    return _Restricted(desk, RESTRICTED.get(role, set()))


def audit(desks: list[Desk], entity: str) -> list[tuple[str, int, str]]:
    out = []
    for desk in desks:
        for a in desk.log:
            target = a.arguments.get("lei") or a.arguments.get("number") or a.arguments.get("id")
            if a.ok and a.tool in OWNERSHIP and target == entity:
                out.append((desk.request.id, a.step, a.tool))
    return out


def erase(people: list[dict], person: str) -> list[dict]:
    return [{"id": p["id"]} if p["id"] == person else dict(p) for p in people]
