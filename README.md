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

| # | Milestone | Course chapter | Needs |
|---|---|---|---|
| 1 | [Who owns whom](https://kube.ar/graphrag/project/follow-the-money/who-owns-whom): three registers in one graph, chains, groups, loops | GraphRAG · Why a graph | Python only |
| 2 | [One company, three sources](https://kube.ar/graphrag/project/follow-the-money/three-sources): FollowTheMoney, matching across registers, open-world sanctions | GraphRAG · Designing the graph | Python only |
| 3 | [Reading the Gazette](https://kube.ar/graphrag/project/follow-the-money/reading-the-gazette): a lexical graph, linked names, LLM-read claims, what the register doesn't show yet | GraphRAG · Building the graph | a model (one check) |
| 4 | [Effective ownership](https://kube.ar/graphrag/project/follow-the-money/effective-ownership): Neo4j, shares along chains, control, ownership bands, communities | GraphRAG · Storing and querying | Neo4j, and a model (one check) |
| 5 | [Screening a supplier](https://kube.ar/graphrag/project/follow-the-money/screening): a gold set, hidden controllers, a final register you never see the answers to | GraphRAG · Measuring quality | Python only |

Then the due-diligence agent (the [Agentic GraphRAG](https://kube.ar/agentic-graphrag) course): an
agent that doesn't get the registers. It gets a request (a supplier's name as someone typed it, a
country, and the supplier's own questionnaire) and works it at the compliance desk (`trail.desk`),
where every lookup costs credits. It decides approve, reject or escalate, and the compliance officer
accepts the decision only if it follows the risk policy. The agent part stands on its own: it needs no
code from the GraphRAG milestones and no Neo4j.

| # | Milestone | Course chapter | Needs |
|---|---|---|---|
| d1 | [The first screening](https://kube.ar/agentic-graphrag/project/follow-the-money/the-first-screening): a baseline agent, and its failures named | Agentic GraphRAG · Overview | a model (the last check) |
| d2 | [The risk policy](https://kube.ar/agentic-graphrag/project/follow-the-money/the-risk-policy): rules in a graph, one `describe`, near-miss designations | What the agent knows | a model (the last check) |
| d3 | [What we cleared before](https://kube.ar/agentic-graphrag/project/follow-the-money/what-we-cleared-before): a memory with two dates, stale approvals | Agent memory | a model (the last check) |
| d4 | [One branch per owner](https://kube.ar/agentic-graphrag/project/follow-the-money/one-branch-per-owner): a workflow graph, a fan-out per owner, meaning checks | How the agent acts | a model (the last check) |
| d5 | [The registry desk](https://kube.ar/agentic-graphrag/project/follow-the-money/the-registry-desk): 55 tools, retrieval, chaining by type, a planted instruction | Agent tools | a model (the last check) |
| d6 | [Decision review](https://kube.ar/agentic-graphrag/project/follow-the-money/decision-review): execution graph, diagnosis, safe shipping | Evaluation and self-improvement | Python only |
| d7 | [Cost and clearance](https://kube.ar/agentic-graphrag/project/follow-the-money/cost-and-clearance): routing, cost per correct decision, access, audit, erasure | Running in production | Python only |
| d8 | [The final batch](https://kube.ar/agentic-graphrag/project/follow-the-money/the-final-batch): your best agent on the hard pack and a hidden batch, and an ablation | Putting it together | a model (two checks) |

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

Python 3.12 or newer. What else each milestone needs is in the tables above: milestones 1, 2 and
5, d6 and d7 are Python only; milestones 3 and 4 and d1 to d5 have one check that calls a model, d8
two; milestone 4 also needs Neo4j. The first run of milestone 1's vector baseline (and of d5's tool
search, if you use `trail.vectors`) downloads a small embedding model (about 30 MB), so it needs
the network once.

### A model, for the checks that call one

Use whichever provider you have a key for: Claude (`anthropic`), OpenAI, Fireworks or OpenRouter.

```sh
cp .env.example .env     # then set TRAIL_LLM_PROVIDER, TRAIL_LLM_MODEL and that provider's key
uv run trail llm         # checks the setup: a text answer, a JSON answer and one tool call
```

`.env` is gitignored: never commit a key. The CLI reads it when it starts, so its settings reach
every check (the Neo4j ones too). In your code, `from trail.llm import get_llm` gives you
`llm.text(prompt)` and `llm.json(prompt, schema)` on whichever provider `.env` names, and
`from trail.llm import Conversation` runs a conversation with tools, which the agent milestones
use. The agent milestones need a model that calls tools: `trail llm` tells you if yours doesn't.

**What it costs.** An agent check runs your agent on a whole pack of requests (6 to 20
screenings), each a conversation of several turns: dozens of calls per check. The default Claude
model (`claude-opus-5-5`) is the most capable and the most expensive; a smaller model costs much
less (set `TRAIL_LLM_MODEL`). After a run that used a model, `check` prints a line like
`LLM use: <calls> calls (<n> answers from the cache), <tokens> tokens in, <tokens> out`, so you
see the cost before your provider's bill does. Plain answers (`llm.text` and `llm.json`, as in
milestones 3 and 4, or a decision asked as structured output in d4) are cached in `.trail-cache/llm`,
so rerunning a check costs nothing while the prompt stays the same; set `TRAIL_LLM_CACHE=0` to always
call the provider. Conversations with tools aren't cached: every agent run is a new one.

**Working on the plain functions first?** `uv run trail check d4 --no-llm` skips the checks that
call a model (they show as not started, with a note), so you don't pay for agent runs while you
fix a pure function. The milestone is complete once you run it without the flag.

### Neo4j, for milestone 4

```sh
docker compose up -d     # Docker must be running; give Neo4j about 20 seconds to start
```

The browser is at http://localhost:7474 (user `neo4j`, password `NEO4J_PASSWORD` from `.env`).

## How a milestone works

1. Finish the chapter on the site and open its milestone page.
2. Write your code in the milestone's file, for example `src/trail/graphrag/m1_who_owns_whom.py`.
   The docstrings say exactly what each function must return.
3. Run the checks:

```sh
uv run trail check 1             # links to the lessons in English
uv run trail check 1 --lang es   # ...or in Spanish
uv run trail check d4 --no-llm   # ...without the checks that call a model
```

Each check says what's right, what isn't, and which lesson explains it.

**Each milestone starts from the data** (the registers, or the request packs for the agent). No
milestone imports another one's code, and the checks of one never read what an earlier one
produced: you can start any milestone with the ones before it still empty.

**Fast or deep.** Every milestone can be built two ways. The fast path uses a library (networkx,
FollowTheMoney, a fuzzy matcher, Neo4j) and gets you to a working result in a few hours. The deep
path writes the same piece yourself. The checks are the same either way.

**Stuck, or skipping ahead?** `uv run trail check 1 --reference` shows what passing looks like.
`uv run trail use-reference 1` swaps your file for the reference solution (yours is kept as
`.mine.py`; `--undo` puts it back): a working version of a milestone you skipped, to read or to
compare with yours.

## Troubleshooting

- **`docker compose up -d` says it can't connect to the Docker daemon.** Docker isn't running:
  start Docker Desktop (or the Docker service), then run it again. `trail check 4` says "Is Neo4j
  running?" until Neo4j answers, which takes about 20 seconds after the container starts.
- **Neo4j refuses the password** ("authentication failure"). Neo4j keeps the password it was
  first started with in its data volume, so changing `NEO4J_PASSWORD` later has no effect. Put the
  old one back in `.env`, or start over with `docker compose down -v` (it deletes the stored graph,
  which `store()` rebuilds anyway) and `docker compose up -d`.
- **The first run of milestone 1 (or d5) stops while downloading `minishlab/potion-base-8M`.** The
  embedding model comes from Hugging Face the first time and is cached after that: run it once with
  the network on (and through your proxy, if you have one).
- **`trail llm` says the tool call failed, or that the model answered without calling the tool.**
  That model doesn't do tool calling (function calling), which every agent milestone needs. Pick
  one whose page at your provider lists tool use, set it as `TRAIL_LLM_MODEL`, and run `trail llm`
  again.
- **"Needs an LLM: Set TRAIL_LLM_PROVIDER in .env".** There's no `.env` yet: `cp .env.example .env`
  and fill in one provider.

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
