# Follow the Money

Who really controls a company? The answer is spread over registers that never talk to each
other. GLEIF knows which entity consolidates which, worldwide. Companies House knows who has
significant control of each UK company. A sanctions list knows who is designated. None of them
can see the others, and each spells the same company its own way.

In this project you connect them. First as a **knowledge graph** that answers what no single
register can (the [Knowledge Graphs & GraphRAG](https://kube.ar/graphrag) course). Later as an
**agent** that screens a supplier on its own and says approve, reject or escalate, with
evidence (the [Agentic GraphRAG](https://kube.ar/agentic-graphrag) course).

The registers are real: a frozen slice of public open data (see
[data/registers/SOURCES.md](data/registers/SOURCES.md)). Next to them sits Quezal, a fictional
offshore jurisdiction with exact stakes and a few groups built to hide who controls them. Its
truth is known, so the checks can measure how much you find.

## Milestones

Each milestone closes a chapter of a course on [kube.ar](https://kube.ar). The instructions live
on the site, next to the lessons they use. This repo holds the code, the data and the checks.

| # | Milestone | Course chapter | Status |
|---|---|---|---|
| 1 | [Who owns whom](https://kube.ar/graphrag/project/follow-the-money/who-owns-whom): three registers in one graph, chains, groups, loops | GraphRAG · Why a graph | ready |
| 2 | [One company, three sources](https://kube.ar/graphrag/project/follow-the-money/three-sources): FollowTheMoney, matching across registers, open-world sanctions | GraphRAG · Designing the graph | ready |
| 3 | [Reading the Gazette](https://kube.ar/graphrag/project/follow-the-money/reading-the-gazette): a lexical graph, linked names, LLM-read claims, what the register doesn't show yet | GraphRAG · Building the graph | ready (one check needs an LLM) |
| 4 | [Effective ownership](https://kube.ar/graphrag/project/follow-the-money/effective-ownership): Neo4j, shares along chains, control, ownership bands, communities | GraphRAG · Storing and querying | ready (Neo4j; one check needs an LLM) |
| 5 | [Screening a supplier](https://kube.ar/graphrag/project/follow-the-money/screening): a gold set, hidden controllers, a final register you never see the answers to | GraphRAG · Measuring quality | ready |

Then the due-diligence agent (the [Agentic GraphRAG](https://kube.ar/agentic-graphrag) course): an
agent that doesn't get the registers. It gets a request (a supplier's name as someone typed it, a
country, and the supplier's own questionnaire) and works it at the compliance desk (`trail.desk`),
where every lookup costs credits. It decides approve, reject or escalate, and the compliance officer
accepts the decision only if it follows the risk policy.

| # | Milestone | Course chapter | Status |
|---|---|---|---|
| d1 | [The first screening](https://kube.ar/agentic-graphrag/project/follow-the-money/the-first-screening): a baseline agent, and its failures named | Agentic GraphRAG · Overview | ready (needs an LLM) |
| d2 | [The risk policy](https://kube.ar/agentic-graphrag/project/follow-the-money/the-risk-policy): rules in a graph, one `describe`, near-miss designations | What the agent knows | ready |
| d3 | [What we cleared before](https://kube.ar/agentic-graphrag/project/follow-the-money/what-we-cleared-before): a memory with two dates, stale approvals | Agent memory | ready |
| d4 | [One branch per owner](https://kube.ar/agentic-graphrag/project/follow-the-money/one-branch-per-owner): a workflow graph, a fan-out per owner, meaning checks | How the agent acts | ready |
| d5 | [The registry desk](https://kube.ar/agentic-graphrag/project/follow-the-money/the-registry-desk): 55 tools, retrieval, chaining by type, a planted instruction | Agent tools | ready |
| d6 | [Decision review](https://kube.ar/agentic-graphrag/project/follow-the-money/decision-review): execution graph, diagnosis, safe shipping | Evaluation and self-improvement | ready |
| d7 | [Cost and clearance](https://kube.ar/agentic-graphrag/project/follow-the-money/cost-and-clearance): routing, cost per correct decision, access, audit, erasure | Running in production | ready |
| d8 | [The final batch](https://kube.ar/agentic-graphrag/project/follow-the-money/the-final-batch): your best agent on the hard pack and a hidden batch, and an ablation | Putting it together | ready (needs an LLM) |

`uv run trail requests` lists the request packs: `practice` (6), `standard` (12) and `hard` (12),
with the decision the policy calls for, and `final` (8), whose decisions are stored only as hashes.

## Setup

1. Click **Use this template** on GitHub to get your own copy, and clone it.
2. Install [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync
uv run trail sources                      # what's in each register
uv run trail find "eiger shipping"        # ids whose names contain the words
uv run trail show 5493008CGNE47EJ89474    # everything the registers say about one id
```

Python 3.12 or newer. Milestones 1, 2 and 5, and the parts of the agent milestones that don't run the
agent, need no API key and no database; milestone 4 runs
Neo4j (`docker compose up -d`). The first run downloads a small embedding model (about 30 MB),
so it needs the network once.

### An LLM, from milestone 3 on

Two checks call a language model. Use whichever provider you have a key for: Claude
(`anthropic`), OpenAI, Fireworks or OpenRouter.

```sh
cp .env.example .env     # then set TRAIL_LLM_PROVIDER, TRAIL_LLM_MODEL and that provider's key
uv run trail llm         # checks the setup with two tiny calls
```

`.env` is gitignored: never commit a key. In your code, `from trail.llm import get_llm` gives
you `llm.text(prompt)` and `llm.json(prompt, schema)` on whichever provider `.env` names.

## How a milestone works

1. Finish the chapter on the site and open its milestone page.
2. Write your code in the milestone's file, for example `src/trail/graphrag/m1_who_owns_whom.py`.
   The docstrings say exactly what each function must return.
3. Run the checks:

```sh
uv run trail check 1             # links to the lessons in English
uv run trail check 1 --lang es   # ...or in Spanish
```

Each check says what's right, what isn't, and which lesson explains it.

**Fast or deep.** Every milestone can be built two ways. The fast path uses a library (networkx,
FollowTheMoney, a fuzzy matcher, Neo4j) and gets you to a working result in a few hours. The deep
path writes the same piece yourself. The checks are the same either way.

**Stuck, or skipping ahead?** `uv run trail check 1 --reference` shows what passing looks like.
`uv run trail use-reference 1` swaps your file for the reference solution (yours is kept as
`.mine.py`; `--undo` puts it back).

## The data

| Folder | What | Licence |
|---|---|---|
| `data/registers/gleif` | 1,492 legal entities in 34 corporate groups, and their parent relationships | CC0 |
| `data/registers/companies_house` | 580 UK companies and who has significant control of them | OGL v3 |
| `data/registers/uk_sanctions` | 1,676 designated entities | OGL v3 |
| `data/quezal/practice` | Quezal's register, its Gazette and its watch list, with `truth.json` (the checks read it; you shouldn't) | CC BY 4.0 |
| `data/quezal/final` | Another Quezal register from a seed the code doesn't contain. Its answers are hashed: you learn how many you found, never which (a hash stops accidents, not a determined cheat) | CC BY 4.0 |

The real registers are a snapshot from November 2026: companies have changed since, and nothing
in them says a company did anything wrong. No personal data: people with significant control
appear only as "an individual" and a control band. Everyone named in Quezal is fictional.

Want another Quezal? `uv run trail generate --seed 7` writes one to `data/quezal/mine/`.

Maintainers: `tools/build_slice.py` rebuilds the real slice from bulk files (sources in
`data/registers/SOURCES.md`); `trail.requests.build_all()` rebuilds the request packs. Learners never
need either.

## License

Code: MIT. Data: see the table above and [LICENSE](LICENSE).
