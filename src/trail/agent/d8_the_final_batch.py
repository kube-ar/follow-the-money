"""Agent 8 · The final batch.

Instructions: https://kube.ar/agentic-graphrag/project/follow-the-money/the-final-batch

Put it all together: the policy graph, the memory, the plan, the gated tools, the review. Run your
best agent on the hard pack and on a final batch whose decisions you never see, then take it apart
one piece at a time and see which pieces were carrying the decisions.

Check your work with `uv run trail check d8`.
"""

from __future__ import annotations

from typing import Any

from trail.desk import Desk, Request


def ablation(scores: dict[str, float]) -> list[tuple[str, float]]:
    """From accuracies like {"full": 0.75, "without memory": 0.5, "without policy": 0.75}, the pieces whose
    removal lowered it, as (piece, drop), biggest drop first; ties by name. The piece's name is what
    follows "without "."""
    raise NotImplementedError


def screen(request: Request, llm: Any) -> Desk:
    """Your best agent."""
    raise NotImplementedError
