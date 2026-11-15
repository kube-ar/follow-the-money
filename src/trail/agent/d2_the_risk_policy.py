"""Agent 2 · The risk policy.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/the-risk-policy

What the agent knows decides what it does. Put the risk policy in a graph the agent reads and
can't rewrite, give it one `describe` tool that works for every kind of id in every register,
and teach it to ignore designations that only look like its supplier.

Check your work with `uv run trail check d2`. The last check needs an LLM.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk, Request
from trail.registers import Registers

# How `describe` reads each kind of record: a regex its id matches, the table in trail.desk.records(regs)
# that holds it, the key column, the fields that identify it, and its context: name → [table,
# their column, our column, the column to list]. A new kind of record must need only a new entry here.
SPEC: dict[str, dict] = {}


def policy_graph() -> Any:
    """The policy (trail.desk.POLICY) as a graph: a node per rule, owned by "compliance", with a GOVERNS
    edge to each decision it bears on. P1 governs reject; P2, P3 and P4 escalate; P5 approve; P6 and
    P7 govern all three."""
    raise NotImplementedError


def rules_for(graph: Any, decision: str) -> list[str]:
    """The ids of the rules that govern a decision, sorted. An unknown decision: []."""
    raise NotImplementedError


def rule_text(graph: Any, rule_id: str) -> str:
    raise NotImplementedError


def update_rule(graph: Any, rule_id: str, text: str, actor: str) -> bool:
    """Change a rule's text. Only its owner may: return False and change nothing for anyone else."""
    raise NotImplementedError


def describe(regs: Registers, node_id: str, spec: dict = SPEC) -> dict:
    """{"type", "id", the identifying fields, "context": {name: sorted ids}} for any id the spec knows,
    or {"error": ...}. Generic: the code reads the spec, it doesn't know any kind of record by name."""
    raise NotImplementedError


def relevant_designations(regs: Registers, entity: str, hits: list[dict]) -> list[str]:
    """Of the designations a sanctions search returned (rows like the desk's sanctions_search), the ids
    that really designate `entity`: a name or alias that is one of its names (case, punctuation,
    legal forms and spaces aside), or a registration number it has, and no country that contradicts it."""
    raise NotImplementedError


def screen(request: Request, llm: Any, distract: bool = False) -> Desk:
    """Your agent from d1, now reading the policy graph and using `describe`; the desk in distract mode
    when asked (its sanctions search then also returns the nearest near misses)."""
    raise NotImplementedError
