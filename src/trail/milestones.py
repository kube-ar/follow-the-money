"""The project's milestones: where your code goes, where its checks live, where to read about it."""

from __future__ import annotations

from dataclasses import dataclass

SITE = "https://kube.ar"
PROJECT = "follow-the-money"


@dataclass(frozen=True)
class Milestone:
    id: str
    course: str  # the course on the site this milestone closes a chapter of
    slug: str
    title: str
    module: str  # your code
    reference: str  # the reference solution, relative to the repo root
    checks: str  # the module with `run(module)`
    extra: tuple[str, ...] = ()  # files next to your module that the reference also replaces

    @property
    def file(self) -> str:
        return "src/" + self.module.replace(".", "/") + ".py"

    def url(self, lang: str = "en") -> str:
        prefix = "" if lang == "en" else f"/{lang}"
        return f"{SITE}{prefix}/{self.course}/project/{PROJECT}/{self.slug}"


def _m(mid: str, slug: str, title: str, name: str) -> Milestone:
    return Milestone(mid, "graphrag", slug, title, f"trail.graphrag.{name}", f"reference/graphrag/{name}.py",
                     f"trail.checks.m{mid}")  # fmt: skip


def _d(n: int, slug: str, title: str) -> Milestone:
    name = f"d{n}_{slug.replace('-', '_')}"
    return Milestone(f"d{n}", "agentic-graphrag", slug, title, f"trail.agent.{name}", f"reference/agent/{name}.py",
                     f"trail.checks.d{n}")  # fmt: skip


MILESTONES = {
    m.id: m
    for m in [
        _m("1", "who-owns-whom", "Who owns whom", "m1_who_owns_whom"),
        _m("2", "three-sources", "One company, three sources", "m2_three_sources"),
        _m("3", "reading-the-gazette", "Reading the Gazette", "m3_reading_the_gazette"),
        _m("4", "effective-ownership", "Effective ownership", "m4_effective_ownership"),
        _m("5", "screening", "Screening a supplier", "m5_screening"),
        *[
            _d(n, slug, title)
            for n, slug, title in (
                (1, "the-first-screening", "The first screening"),
                (2, "the-risk-policy", "The risk policy"),
                (3, "what-we-cleared-before", "What we cleared before"),
                (4, "one-branch-per-owner", "One branch per owner"),
                (5, "the-registry-desk", "The registry desk"),
                (6, "decision-review", "Decision review"),
                (7, "cost-and-clearance", "Cost and clearance"),
                (8, "the-final-batch", "The final batch"),
            )
        ],  # fmt: skip
    ]
}


def lesson_url(course: str, slug: str, lang: str = "en") -> str:
    prefix = "" if lang == "en" else f"/{lang}"
    return f"{SITE}{prefix}/{course}/{slug}"
