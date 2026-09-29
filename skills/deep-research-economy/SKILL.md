---
name: deep-research-economy
description: |
  ECONOMICAL variant of deep research — optimised for token spend and the 5-hour
  subscription window while keeping result quality close to the regular deep-research.
  Use ONLY when the user EXPLICITLY asks for an economical mode: "research economically",
  "save tokens", "save the window", "budget research", "token-saving research",
  "deep research lite", "economical deep research". If economy is NOT mentioned — use
  the regular deep-research skill instead.
---

# Skill: Deep Research (economy mode)

## Purpose

The same systematic deep research as the regular `deep-research`, but with an
architecture that minimises tokens and 5-hour-window usage. Research quality must stay
practically the same — the savings come from **where** (on which model) and **in what
chunks** content is processed, NOT from **how much real material** is read.

When to choose it: the user explicitly asked to save tokens / the window / resources.
In every other case — the regular `deep-research`.

The reader profile from `deep-research` applies here too (and is likewise ignored while
it still holds `<...>` placeholders).

---

## Economy principles (read before starting)

These principles drive every step below. They save budget without losing depth:

1. **Model tiers.** Expensive reasoning (Opus) only for the plan and the final
   synthesis. All mechanics (searching, reading pages, extracting facts, writing
   sections) runs on Sonnet subagents. Sonnet is practically indistinguishable from
   Opus here and weighs several times less in the quota.
   - *Quality caveat:* if a section needs reasoning rather than a survey (designing a
     solution, weighing trade-offs), the Sonnet subagent still **collects the
     material**, but the main agent writes the final analysis from the extract — the
     depth of reasoning stays where it is needed.

2. **Heavy web content never enters the main context.** The main agent does **not do
   WebFetch/WebSearch** itself — otherwise huge pages settle in the expensive context
   and are re-read from cache on every turn until the end of the session. All raw web
   content lives only inside Sonnet subagents and is written to disk.

3. **Fewer cold starts: batching.** Every subagent pays for its own system prompt +
   tools again (there is no cross-agent cache). So one subagent handles **2-3 related
   sections** (not 1 section = 1 subagent). Relatedness also improves coherence. More
   than 3 per batch is not allowed (the subagent's context bloats and extraction
   quality degrades).

4. **Smart fetch, not "less fetch".** WebSearch snippets are for *selecting* the best
   sources, not a substitute for reading. Then WebFetch exactly the selected URLs with
   a narrow extraction request. Fewer tokens, same or better factual depth, because the
   right pages get read rather than the first ones found.

5. **Synthesis from rich extracts + full doc on demand.** A subagent returns not 5
   bullets but a structured ~300-500-word extract per section (facts, numbers,
   contradictions, open questions, best URLs). The final synthesis works from extracts
   but may read a full section via Read when the material is thin. That removes the
   ceiling on synthesis depth.

6. **No needless Reads of large files.** Status/deduplication via `ls` and tiny
   `state.json` files, not by reading full markdown into the expensive context.

7. **Minimal thinking in mechanical subagents.** Not off entirely (needed to compare
   sources), but not extended either — this is Sonnet work.

8. **Pace within the 5-minute cache TTL.** Agree on the plan once, then avoid long
   interactive pauses: after >5 minutes idle the cache expires and the whole
   conversation is re-read at full price.

---

## Step 0: Save the original task

> **Where results go:** create all research files **in the current working directory**.
> Don't create a separate folder elsewhere unless the user named another path.

Create `00_TASK.md`:

```markdown
# Original task

<exact wording of the user's request>

**Date:** <today>
**Mode:** economy (deep-research-economy)
```

---

## Step 1: Research plan (main agent)

The first of the two places where expensive reasoning is appropriate. Create
`01_research_plan.md`:

```markdown
# Research plan: <Topic>

## Goal
<2-3 sentences>

## Research questions
1. <Key question 1>
2. <Key question 2>

## Stages
### Stage 1: <Name>
- [ ] <Subtask 1.1>

## Sections grouped into subagent batches
| Batch | Sections (related) | Output files |
|-------|--------------------|--------------|
| A     | overview + concepts | 02_overview.md, 03_concepts.md |
| B     | ...                 | ... |

## Expected documents
| File | Content |
|------|---------|
| `02_overview.md` | Overview of the topic |
| `NN_summary.md` | Conclusions and recommendations |
```

**Show the plan and get confirmation in one go** (principle 8 — don't spread it over
many pauses) before researching.

---

## Step 2: Research via Sonnet subagents

The main agent **orchestrates** but never goes to the web itself (principle 2).

### Launching subagents

- Run subagents **on Sonnet** (`model: sonnet`).
- One subagent = **a batch of 2-3 related sections** (principle 3).
- **No more than 3 subagents at a time** — the session has a 5-hour limit; launching
  many agents at once can make them all hit the limit together and lose the progress.
  Launch in batches, wait for completion, keep the extracts, then the next batch.

### Subagent prompt (short — the boilerplate lives in a file)

Don't duplicate the protocol in the prompt. Pass a reference to the protocol file:

```
Research the sections of batch <A>: <list of sections with topics and questions>.
Output files: <NN_section.md ...> in directory <path>.

Follow the protocol: ~/.claude/skills/deep-research-economy/references/subagent-protocol.md
Read it first and act on it (START → LOOP → FINISH → RETURN extract).

Questions per section:
- <NN_section_1>: 1) ... 2) ...
- <NN_section_2>: 1) ... 2) ...
```

### Before a batch — status check (principle 6, no Reads of large markdown)

Via `ls`/`state.json`, not by reading full documents:
```
.work/<NN_section>/state.json, status="done"        → skip
.work/<NN_section>/state.json, status="in_progress" → relaunch the subagent (same prompt)
.work/<NN_section>/ missing                         → new section
```

### After a batch

The main agent receives an **extract** per section (~300-500 words). Full texts are
already on disk. Check `state.json` → `status="done"`, delete `.work/<NN_section>/`.
Keep the extracts — they feed the synthesis (Step 4).

---

## Step 3: Section document standard

Template (filled in by the subagent, not the main agent):

```markdown
# <Section title>

**Research date:** YYYY-MM-DD
**Sources used:** N

## Summary
[2-3 key conclusions]

## Detailed analysis
### <Subtopic 1>
[...]

## Practical recommendations
- [Recommendation 1]

## Sources
- [Title](URL)
```

Quality standards (not relaxed compared to the regular skill):
- Always cite sources with URLs.
- Tables for comparisons, mermaid/ASCII for diagrams.
- Synthesise and analyse, don't rewrite sources.
- Each section answers its questions from the plan.

---

## Step 4: Final synthesis (main agent)

The second and last place for expensive reasoning.

- Synthesise `NN_summary.md` from the **collected extracts** (principle 5), not from
  the full sections.
- If an extract is not enough for a solid conclusion on a topic — read the relevant
  `NN_section.md` via Read (full doc on demand). An exception, not the rule.
- For "reasoning" sections (the caveat of principle 1) this is where the main agent
  writes the final analysis.

`NN_summary.md` must answer every question of the original plan.

---

## Step 5: README

Create `README.md` in the research folder: date, status, mode, a table of contents of
all documents with descriptions, and the key conclusions.

---

## Step 6: Google Drive (optional)

If the `gdrive-upload` skill is installed, upload the research folder to
`gdrive:AI_Projects/<folder basename>`. Then report: location, list of documents,
3-5 key conclusions.

---

## Typical output layout

```
research_topic/
├── .work/
│   └── 03_attack_vectors/state.json   ← { sections_done, sections_remaining, status }
├── 00_TASK.md
├── 01_research_plan.md
├── 02_overview.md
├── 03_attack_vectors.md
├── 04_enterprise_risks.md
├── 05_summary.md
└── README.md
```

---

## Agent behaviour

### Do
- Save ALL results to markdown files (subagents write as they go).
- Keep the main (expensive) context thin: plan → orchestration → synthesis.
- Delegate all web work to Sonnet subagents in batches of 2-3 related sections.
- Synthesise from extracts, reading full docs only when necessary.

### Don't
- Don't call WebFetch/WebSearch from the main agent.
- Don't run web research on Opus when Sonnet is enough.
- Don't replace reading sources with snippets alone (that would hurt quality).
- Don't make batches >3 sections and don't run >3 subagents at once.
- Don't start without a confirmed plan.
- Don't spread confirmations over many interactive pauses (cache TTL).

### Recovering after an interruption
1. Read `01_research_plan.md` — restore the plan and batches.
2. Status of every section — via `.work/<section>/state.json` (not by reading markdown):
   - `status="done"` → skip.
   - `status="in_progress"` → relaunch the subagent with the same prompt (it reads the
     protocol and `state.json` and continues from `sections_remaining`).
   - no `.work/`, but `NN_section.md` exists with `**Status:** Done` → skip.
   - nothing → the section was not started, launch it.
