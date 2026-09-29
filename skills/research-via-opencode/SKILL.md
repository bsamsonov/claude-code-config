---
name: research-via-opencode
description: |
  Hands web research off to external models via an OpenCode Go subscription
  (opencode-go) so the Claude 5-hour window is NOT spent on it. Claude only plans the
  sub-questions, distributes them to parallel opencode agents and synthesises the result.
  Use when the user says: "research via opencode", "use my opencode-go limits",
  "hand it to opencode subagents", "don't burn the window, research it", and also when
  the Claude window is nearly exhausted (the hook shows >70–80%) and the task is a
  large web research job.
  For ordinary research inside the Claude window — skills deep-research / deep-research-economy.
---

# Skill: Research via OpenCode Go

## Why

`opencode` is installed locally and authorised under an **OpenCode Go** subscription
— a separate wallet from Claude with its own dollar limits per 5 h / week / month.
That lets the most expensive part of research — reading dozens of web pages — move
out of the Claude window into separate processes.

Division of labour:
- **Claude** — decomposing the topic, choosing models, orchestration, critical review
  and the final synthesis.
- **opencode agents** — searching, reading sources, draft markdown files.

Key rule: **agents write to files, Claude reads only the results.**
Never pull an agent's full output into context — read the produced `.md` selectively
(`head`, `grep`, the relevant sections).

## Infrastructure

- `bin/oc-research` — a wrapper over `opencode run --agent researcher`.
- `opencode/opencode.jsonc` → agent `researcher` + permissions (web allowed, writes
  only to `research/**`, `docs/**`, `*.md`; `rm`, `sudo`, `git push/commit` denied —
  no interactive prompts, which would hang a headless run).
- `opencode/prompts/researcher.md` — the researcher's system prompt.

Liveness check: `opencode models | grep opencode-go | head -3`

## Usage

```bash
oc-research "topic"                                          # qwen3.7-plus → research/<slug>.md
oc-research -m mimo-v2.6-flash -o research/01-x.md "topic"   # harvest
oc-research -m glm-5.2 -v high "controversial topic"         # variant = reasoning effort
oc-research -m hy3 -d /path/to/proj "topic"
```

The agent's full log stays next to the output: `research/<slug>.log`.

## Choosing a model

The Go limit is in dollars, so the unit of account is **requests**, not "expensive /
cheap by eye". One research run ≈ 20 model calls (plan, 6–8 searches, fetches,
writing). Hence "runs per month".

Numbers below: Go plan, requests per 5 hours as published in the
[OpenCode Go docs](https://opencode.ai/docs/go), **as of 2026-09**. The catalogue changes
every few weeks — re-check with `opencode models opencode-go` and the docs.

| Tier | Models | Req/5h | ~Runs/month | When |
|---|---|---|---|---|
| **Harvest** | `mimo-v2.6-flash`, `mimo-v2.5`, `deepseek-v4.1-flash`, `deepseek-v4-flash`, `longcat-2.0` | 11 000–30 000 | thousands | Bulk page reading, link triage, quote extraction. Practically free — don't economise here. |
| **Workhorse** ⭐ | `qwen3.7-plus`, `hy3`, `gpt-6-luna`, `minimax-m2.7`, `minimax-m3`, `mimo-v2.6-pro` | 3 200–4 300 | ~800–1 000 | **Default.** The bulk of research tasks. |
| **Hard topic** | `kimi-k2.6`, `deepseek-v4-pro`, `glm-5.2`, `hy4-preview` | 880–1 350 | ~215–340 | Only when the workhorse produced mush: conflicting sources, analysis needed rather than a retelling. 3–4× the cost. |
| **Code** | `kimi-k2.7-code` | 1 350 | ~340 | Research over a repository. |
| **🚫 Not for research** | `kimi-k3`, `qwen3.8-max`, `grok-4.7`, `glm-5.3` | 110–220 | **~25–55** | 20–40× the cost of the workhorse. A single hard question, not a pipeline. Fan-out with them is impossible. |

Rules:
- Default is `qwen3.7-plus`. Raise the tier **only after an actual bad result**,
  never pre-emptively.
- Different directions of one research job can go to different workhorse models —
  that also protects against a shared hallucination of a single model.
- Synthesis is done by Claude, so a "smart expensive model for conclusions" is not
  needed in the pipeline. That is exactly why the 🚫 tier is almost never justified.
- Before taking a 🚫 model, ask: is this question worth 1/25 of the monthly limit?
  Usually not.

## Procedure

1. **Plan.** Split the topic into 3–6 independent directions. One direction = one
   agent. Directions must not overlap, or you get three retellings of the same thing.
2. **Directory.** `mkdir -p research`. Number the files: `research/01-<topic>.md`.
3. **Fan-out.** Launch the agents **in the background** (`run_in_background: true`),
   one Bash call per direction, all in one block — they run in parallel. On the
   workhorse tier the limit is no obstacle; the constraint is practical: 3–5 agents,
   otherwise accepting the results gets hard. No fan-out on the 🚫 tier at all.
4. **Waiting.** Don't poll aggressively. Do other work meanwhile; a notification
   arrives on completion.
5. **Acceptance.** For each file check:
   - there is a `## Sources` section with real URLs;
   - findings contain specifics (numbers, versions, names), not filler;
   - no contradictions between files from different agents.
   Verify suspicious claims yourself — Go models hallucinate noticeably more often
   than Sonnet, especially in dates, numbers and version names.
6. **Synthesis.** Combine into `research/00-summary.md`: overall picture, contradictions
   between sources, conclusions, open questions. Claude does this step — it is the most
   valuable and the cheapest in tokens.

## Mistakes to avoid

- Handing an agent the whole topic in one line — you get a shallow overview.
  Phrase narrowly: "compare X and Y on criteria A, B, C", not "tell me about X".
- Running long jobs in the foreground — blocks for minutes.
- Trusting numbers and dates without checking at least one URL from the list.
- Committing agent drafts mixed with the final document.

## Diagnostics

- Empty output file → see `research/<slug>.log`, usually a permission or the limit.
- `429` / provider refusal → the 5 h limit is spent; switch model or wait.
- The agent asks for confirmation → add the pattern to `permission.bash` of the
  `researcher` agent in `~/.config/opencode/opencode.jsonc`.
