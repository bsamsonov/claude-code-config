---
name: code-walkthrough
description: >
  Turns code (a file, a folder, a set of demos) into a readable walkthrough for an
  architect with a backend background (Java/Spring): a README with the big picture of
  the application plus a separate walkthrough file for each file/class, with the code
  itself in the text rather than just line references.
  Use when the user says: "walk me through this code", "explain how this code/demo/
  project works", "write a code walkthrough", "explain this file", "I need a walkthrough
  of the demo". This is about SPECIFIC code in the repository; for a full course over a
  whole codebase — the codebase-tutorial skill.
---

# Code Walkthrough

You explain code to a developer-architect: someone who knows backend perfectly well
(Java/Spring, DI, pipelines, queues, transactions) but does not know this particular
code and maybe not this language.

The main quality criterion is **low cognitive load while reading**. The reader should
not have to keep anything in mind beyond the current screen: the code sits next to the
explanation, the analogy next to the construct, the conclusion next to the example.

## What to produce

A `code_walkthrough/` folder next to the code being explained:

```
code_walkthrough/
  README.md              the big picture + table of contents
  <group>/<file>.md      one walkthrough per file or class
```

**One source file (or class, if a file holds several) — one `.md`.** Don't dump
everything into one document. Subfolders mirror the grouping of the sources (by
application/module), `.md` names mirror the source names.

### README.md

- the problem the code solves, in domain terms;
- what it consists of: the file tree and who calls whom;
- how it is launched and what appears on screen;
- dependencies and what is needed to get it running;
- **where the state is and how data flows between parts** — usually the main question;
- a contents table "walkthrough → source → topic";
- the through-line: how one file hooks into the next.

### Walkthrough file

```markdown
# `file_name.py` — walkthrough

**What it does:** two or three sentences.
**Main idea:** one statement the file exists for.

Run: ...

## <Block> (lines N–M)

​```python
<code fragment verbatim>
​```

Explanation: what happens here and why it is done this way.
```

Rules:

- **Code in the text is mandatory.** Line references go in the block heading, but the
  reader must not have to open the source to follow. Fragments of 3–15 lines, verbatim;
  eliding with `...` is fine, rewriting is not.
- Split a file into 4–8 meaningful blocks. Skip boilerplate (imports, `__main__`) unless
  it carries the point.
- End with a short "what breaks here" / "what to watch" list if there is something to
  say. Don't invent it for form's sake.

## Language specifics

**Don't move them into a separate section or file** — nobody reads those. Explain them
**at the point of appearance**, right under the code fragment, as a short aside:

```markdown
> **Python:** `last_request[:] = ...` mutates the same list, while
> `last_request = ...` would rebind the name. In Java — `clear()` + `addAll()`
> versus `list = new ArrayList<>()`.
```

Two to four lines, an analogy from the reader's world and where the analogy lies.
Explain only what actually gets in the way of reading this particular code. A construct
is explained once; later — a link to that walkthrough.

## General rules

1. **Read all the code before writing.** All files, plus README/HANDOFF/dependencies
   nearby. Don't guess: if the code says `client.as_agent(...)`, write `as_agent`, not
   "an agent is created".
2. **Backend analogies** — only honest ones. A "here → in Spring" table works well. No
   direct analogue — say so.
3. **Simplicity over completeness.** Don't retell line by line.
4. Walkthrough language — the language of the request. Identifiers, API and library
   names stay as in the original.
5. **Don't add a "how to present it" section** (timing, talk plan, audience questions)
   unless the user explicitly asked.

At the end — a short report: what was covered, where it is, what was left out.
