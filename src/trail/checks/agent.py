"""Shared helpers for the agent checks: requests, the LLM, and running the learner's agent."""

from __future__ import annotations

from collections.abc import Callable

from ..requests import load_requests
from .core import NotStarted, Result, attempt, needs_llm


def run_pack(r: Result, fn: Callable, pack: str, llm, *extra) -> list:
    """Run the learner's agent on every request of a pack: [(request, desk)], skipping the ones that raise."""
    from ..llm import LLMError

    out = []
    try:
        for request in load_requests(pack):
            desk = attempt(r, fn, request, llm, *extra)
            if desk is not None:
                out.append((request, desk))
    except LLMError as e:
        r.fail(f"the LLM call failed: {e}")
    return out


def summary(runs: list) -> tuple[int, int, int, int]:
    decided = sum(d.decision is not None for _, d in runs)
    accepted = sum(d.verdict()["accepted"] for _, d in runs)
    correct = sum(d.verdict()["correct"] for _, d in runs)
    credits = sum(d.spent for _, d in runs)
    return decided, accepted, correct, credits


__all__ = ["NotStarted", "needs_llm", "run_pack", "summary"]
