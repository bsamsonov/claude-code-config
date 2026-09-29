---
name: translate-ru
description: |
  Translates files, folders, articles by URL or pasted text into Russian, carefully
  preserving markdown, links, code blocks, identifier names and established technical
  terms. Use when the user says "translate into Russian", "make a translation",
  "translate the article/document/README/ADR", "translate this page",
  "translate all untranslated files", or asks to localise technical documentation.
  This is translation of TECHNICAL material: code is not translated, terms are kept.
---

# Skill: Translate into Russian

Goal: the translation **reads like native Russian**, yet does not break markdown, does
not touch code and keeps terms precise. Translate the meaning, not word for word:
reorder, split long English sentences. Tone — businesslike but alive.

## What to translate and what not

**Translate:** prose, headings, list items, table text, alt text, the visible text of
links `[like this](url)`, code comments (on request).

**Never touch:** ``` code blocks and inline code; URLs in links and images; names of
identifiers, classes, functions, flags, env variables; terminal commands, paths, package
names; heading anchors/ids; frontmatter keys (values are fine).

## Terms

Don't force a translation of what lives in English in the industry: `embedding`,
`pull request`, `retrieval`, `reranking`, `prompt`, `chunk`, `endpoint`, `deployment`,
`pipeline`, etc.

- An established Russian equivalent exists («контекстное окно») → use it.
- The term is more common in English → keep it; on the **first** occurrence of an
  important term an explanation in brackets is fine: «reranking (переранжирование)»,
  then just the term.
- No clumsy calques like «эмбеддинги были зачанкованы».

## Modes (detect from the request)

- **A. File.** "Translate file X" with no details → create `X.ru.md`, keep the original.
  "In place" / "replace" → overwrite. Unclear — ask once.
- **B. Folder / several files.** Translate each `.md` → `*.ru.md` (or replace — as
  clarified). Skip already translated ones (`*.ru.md` exists or the file is already
  Russian). At the end — a short list: what was translated, what skipped and why.
- **C. Article by URL.** WebFetch → extract the main text (no menu/footer/ads) → clean
  markdown in the current folder named by slug (`build-long-running-agents.ru.md`), with
  the first line `> Источник: <url>`.
- **D. Text in chat.** Return the translation in the reply, no file (unless asked).

## Self-check (before reporting)

Markdown intact (headings, lists, tables, links)? Code blocks untouched? No gaps or
untranslated English tails? Long constructions rephrased rather than calqued? Found a
problem — fix it quietly, then report.
