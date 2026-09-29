---
name: deep-research
description: |
  Runs a deep, structured study of any topic:
  plan → systematic web search → Markdown documents in the current directory →
  optional upload to Google Drive.
  Use when the user says "research this in depth", "investigate", "deep analysis",
  "study the topic", "deep research", "deep dive", "detailed research",
  "gather information", "research and document".
  This is the DEFAULT variant. If the user EXPLICITLY asks for an economical /
  budget / token-saving mode ("economically", "save tokens", "save the window") —
  use the deep-research-economy skill instead.
---

# Skill: Deep Research

## Reader profile (optional — customise)

Research lands better when it is tailored to the reader. Describe yours here, or delete
this section for neutral output. **If the fields below still contain `<...>` placeholders,
ignore this whole section and write for a general technical reader.**

```
Background: <your current role, stack and strongest experience>
Goal:       <the role or skill you are growing towards>
```

For a topic that touches the reader's goal:

- Explain through analogies with what the reader already knows; point out which
  existing experience transfers directly.
- Match the depth to the goal (e.g. engineering and architecture rather than theory
  from scratch, or the reverse).
- Include a gap analysis against the target role.
- Add `NN_career_path.md` (what to learn next, in which order) and `NN_reading_list.md`
  (courses, books, articles, hands-on projects suited to the reader's background).

## Step 0 — Save the task

Create all files **in the current directory** (unless the user named another one).
Create `00_TASK.md`: the exact wording of the request + today's date.

## Step 1 — Plan

Create `01_research_plan.md`: goal (2-3 sentences), numbered research questions,
stages with checkboxes, a table of expected files (`02_overview.md` … `NN_summary.md`).

**Show the plan to the user and get confirmation before researching.**

## Step 2 — Research

Principles: real WebSearch/WebFetch, not just training data; depth before breadth
(finish a section fully, then the next); diverse sources no older than 1-2 years;
before creating a file, check what has already been written.

Query templates: `"<topic>" best practices 2026`, `... architecture patterns enterprise`,
`... comparison vs alternatives`, `... real world case studies`,
`site:docs.anthropic.com OR site:cloud.google.com OR site:docs.aws.amazon.com "<topic>"`.

### Delegating to subagents

| Section | Strategy |
|--------|-----------|
| Small/trivial OR extremely complex (needs deep synthesis) | do it yourself |
| Well-bounded, clear plan | subagent `research-lite` |
| Several independent sections | parallel `research-lite` |

**No more than 3 subagents at a time** (otherwise a 5-hour limit hit loses all progress):
batch of 2-3 → wait → check results → next batch.

Brief for `research-lite` (the state/resume protocol is built into the agent — do NOT
pass shell instructions):

```
Research the section "<topic>" and write the result to "<path>/<NN_section>.md".
Questions (1 question = 1 H2): 1) … 2) … 3) …
State folder: "<path>/.work/<NN_section>/".
At least 3 sources per section, no older than 1-2 years, cite URLs.
Follow your built-in protocol START → LOOP → FINISH (resume via state.json).
```

The main agent checks the result, fills gaps itself if needed, deletes `.work/<NN_section>/`.

**Fallback** (if `research-lite` is unavailable) — a general-purpose subagent on Sonnet;
add the protocol to the brief: on start check `state.json` (exists → continue from
`sections_remaining`); write content straight into the output file one H2 at a time,
after each H2 overwrite `state.json` (`sections_done`/`sections_remaining`/`status`);
start the file with `**Status:** In progress`, finish with `Done` and append `## Sources`.

### Recovering after an interruption

Read `01_research_plan.md`, then for each section:
- `.work/<sec>/state.json` with `status:"done"` OR a file with `**Status:** Done` → skip;
- `state.json` with `status:"in_progress"` → relaunch the subagent with the same brief
  (it continues from state.json by itself);
- nothing → start from scratch.

## Step 3 — Documents

One file per plan section (not one huge file). Template: H1, date, short summary
(2-3 conclusions), detailed analysis (H2/H3), practical recommendations, `## Sources`
with URLs. Tables for comparisons, mermaid/ASCII for diagrams; synthesise and analyse,
don't retell. The result must answer every question of the plan.

## Step 4 — README.md

A table of contents of all documents with descriptions + 3-5 key conclusions + date and status.

## Step 5 — Google Drive (optional)

If the [`gdrive-upload`](https://github.com/borissamsonov77/gdrive-upload-skill) skill is
installed, upload the results **without asking** (unless the user opted out in advance):
research folder → `gdrive:AI_Projects/<folder basename>`.

Finally report: where the results are, the list of documents, 3-5 key conclusions.
