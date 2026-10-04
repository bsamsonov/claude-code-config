# cc-cost: where the tokens actually go

`scripts/cc_cost.py` (wrapper: `bin/cc-cost`) estimates token and dollar spend from the
transcripts Claude Code already writes to `~/.claude/projects/<project>/<session>.jsonl`
— one record per model response, subagents included. No instrumentation, and the
accounting itself costs zero tokens. The dollar figure is the API-price equivalent: on a
subscription it is not a bill, but it shows precisely where the budget goes.

## What is in a record

- `message.usage`:
  - `input_tokens` — **IN**: fresh input not covered by cache (full price);
  - `output_tokens` — **OUT**;
  - `cache_creation.{ephemeral_5m,ephemeral_1h}_input_tokens` — **cWRITE**: written to
    the cache for the first time (×1.25 for 5-minute TTL / ×2.0 for 1-hour TTL of the
    input price);
  - `cache_read_input_tokens` — **cREAD**: read from cache (a per-model rate, 2.5–10% of
    the input price as of 2026-09);
  - `server_tool_use.{web_search_requests,web_fetch_requests}`.
- `message.model` → price group by model version (e.g. `opus-5.5`, `opus`, `sonnet-5`, `fable-5.1`), see `PRICING` / `MODEL_RULES`.
- `attributionSkill` — which subagent or skill produced the record. This is what makes
  per-skill accounting possible.
- `isSidechain` — true for nested subagent turns.

Full request input = `IN + cWRITE + cREAD`; the three never overlap. A token is written
to cache once and then read on every following step — so `cREAD ≫ cWRITE ≫ IN` is the
healthy picture.

## Three axes

```bash
cc-cost --since 7d --by-model              # which models cost what
cc-cost --since 7d --by-skill              # which subagent/skill costs what
cc-cost --skill deep-research              # where a skill lives, by project
cc-cost --project my-repo --by-skill       # which subagents work in one project
cc-cost --top 10                           # the most expensive sessions
```

`--since` filters by each record's own timestamp; file mtime is only a coarse
pre-filter, so `rsync`/`touch`/resumed sessions don't distort the result.

Note: Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30), so
history beyond that is gone unless you raise the setting or back the folder up.

## What the data showed

A breakdown of all my sessions over the available 30-day history, by share of cost
(measured in mid-2026 at the prices of that time):

| Component | Share of $ | What it is |
|---|---|---|
| **cWRITE** (cache write) | ~38% | writing context into the cache (×1.25–×2.0) |
| **cREAD** (cache read) | ~32% | re-reading cached context |
| **OUT** (output) | ~29% | generated answers |
| **IN** (uncached input) | ~2% | fresh input not covered by cache |

The surprise: the most expensive line is not output but **cache writes**. Less than 2%
of the money is plain input — almost everything is cached, and every time context is
rebuilt (a `/clear` followed by re-opening big files, a changed tool/MCP set, a new
subagent's cold start) it is written to cache again at a premium.

It also showed that the economy variant of the research skill cost roughly a third of
the regular one for a similar volume of work — which is how
`skills/deep-research-economy` earned its place.

## Levers that follow from it

1. **Minimise cache rewrites.** A stable tool set and a stable context beat frequent
   rebuilds. Every subagent spawn is a cold start that pays cWRITE for its whole
   system prompt and tool list — hence narrow agents (`bin/agent-context` measures it)
   and batching several related sections per research subagent.
2. **Keep long cached contexts on cheaper models.** Every token of a long context is
   re-read on every step, so the per-model cache-read rate multiplies quickly.
3. **Shorter answers on Opus** — output is its most expensive line per token.
4. **Balance `/clear`.** Too rarely — cREAD grows every step; too often — each restart
   pays cWRITE again.
5. **Push bulk reading out of the window entirely** — `skills/research-via-opencode`
   and `skills/code-via-opencode` hand it to a separately billed model pool.
