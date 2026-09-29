---
name: codebase-tutorial
description: |
  Generates a tutorial/textbook over a project's real code — sequential Markdown chapters
  that let you understand a codebase from scratch, straight from the sources.
  Use when the user says "write a tutorial for this project", "a textbook over the code",
  "self-study documentation", "walk me through the project by its code",
  "explain how the project is built", "onboarding docs", "codebase tutorial",
  and also when they want material to study a project themselves or to turn it into
  an audio lecture.
  This is about the WHOLE project/codebase; for a walkthrough of specific files — the
  code-walkthrough skill.
---

# Skill: Codebase tutorial

## Purpose

Learning from your own projects: "write a tutorial straight from the code", "a
self-study textbook". The goal is not an API reference but a **narrative textbook**: read
chapter by chapter and understand how and why the project is built this way. The result
often goes on to narration, so the text must flow.

## Step 1 — Study the project before writing

Don't start writing right away. Build a map first:
- structure (`git ls-files | head -200`, directory tree, entry points);
- dependencies and stack (`pyproject.toml`/`package.json`/`pom.xml`, README, ADRs, `docs/`);
- the main data/control flow — from input to result;
- the key abstractions and where they live.

If the project already has a plan/description (`README`, `docs/`, `*_plan.md`) — build
on it, don't invent the architecture anew.

## Step 2 — Ask about audience and depth (once)

If not obvious from the request, ask briefly:
- Who is it for: the author refreshing/learning, or onboarding a newcomer?
- Depth: conceptual overview, or a detailed walk through the code?
- Will it be narrated later (then the text flows more, fewer tables and listings)?

On an explicit "just do it" — pick sensible defaults (self-study, medium depth, text
that reads well) and go.

## Step 3 — Structure

Save to `docs/tutorial/` (or the folder requested) as numbered chapters so the reading
order is obvious:

```
docs/tutorial/
├── 00_overview.md        — what the project is, why, the big picture, how to read this
├── 01_architecture.md    — components and how they connect, the main flow
├── 02_<subsystem>.md     — key parts, one per chapter
├── 03_<subsystem>.md
├── ...
└── 99_glossary.md        — terms and where to find things (if needed)
```

Every chapter:
- starts with **what** we'll look at and **why** it exists in the project;
- goes from whole to part: the component's role first, then how it is built;
- quotes **real code** in short fragments with the file (`path:line`), not made-up
  pseudo-listings;
- explains **why this way**, not only what is written — the link between the decision
  and the problem;
- ends with a mini-summary and a bridge to the next chapter.

## Principles

- **From the real code.** Every claim is verifiable against the sources. Don't write what
  isn't in the code; if something is unclear — open the file and look.
- **Narrative, not reference.** Flowing text that leads the reader, not a dry list of
  functions.
- **Explain the intent.** Why this structure, what trade-off, what would have been
  different — the most valuable part for learning.
- **Dose the code.** Short, to-the-point fragments. Long listings scare readers off;
  better to quote 5 key lines and explain them.
- Cite paths as `file_path:line` — clickable.
