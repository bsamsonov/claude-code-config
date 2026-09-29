---
name: poc-portfolio-prep
description: Use when the user asks to prepare a POC / pet project for public GitHub release as a job-search portfolio item — "prepare the POC for publishing", "put it in my portfolio", "make the repo presentable", "portfolio release", "make this repo public". Especially for repos that are partially in Russian, have AI-agent commit authorship, committed datasets, or personal infrastructure defaults.
---

# Preparing a POC for GitHub Portfolio Release

## Overview

Turn a working-but-messy POC (mixed Russian/English, AI-authored commits, personal infra,
committed data) into a recruiter-facing public repo. Core principles: **audit before work,
decisions before execution, English-only as a hard gate, evidence over claims.**

**Inputs:** the user's current CV (every claim the repo must back up) and, if they exist, the
release plans of a previously published POC — reuse them as templates instead of starting over.

## Process

### 1. Audit (read-only, one session)

```bash
git shortlog -sne --all                                  # authorship (AI or work-email authors = must fix)
git ls-files | wc -l; git ls-files -s | awk '{print $4}' | xargs du -b 2>/dev/null | sort -rn | head  # large tracked files
git ls-files '*.md' | xargs grep -lP '[\p{Cyrillic}]' | wc -l   # RU docs volume
git ls-files '*.py' | xargs grep -lP '[\p{Cyrillic}]'           # RU in code
git grep -ilE 'sk-|api_key|secret|token' | head                 # secret candidates (then gitleaks)
grep -rn "TODO\|FIXME\|NotImplemented" src/ packages/ 2>/dev/null | head
git ls-files | grep -iE '_refactored|_v[0-9]|_old|_new|_backup'  # duplicate/experimental code files
```

Also verify: does CI actually match the CLIs it calls (flag drift)? Do README quickstart
commands work from repo root? What do the project's own backlog notes / handoff docs say is
unfinished? Compare repo reality against every CV claim it must support.

### 2. Decisions (human checkpoint — record in a plan file, then never reopen)

Repo name (product-style, not `poc_*`; local staging folder may be `<project>_public`, the
GitHub repo gets the product name) · fresh curated history vs filter-repo (default: **fresh** —
copy curated files into a sibling `<project>_public` folder, `git init` there with the personal
identity; fixes authorship + strips data/RU from history, and untracked junk never follows) ·
license (MIT) + dataset redistribution check (research-only data → download script + tiny
committed sample, never the corpus) · extract sandboxes/side-experiments into their own small
repos and flatten the main layout · **language policy: zero Cyrillic in docs, comments,
identifiers, commits — forever** (untranslated = deleted). Exception: functional non-English
data (e.g., a RU pronunciation dictionary in a TTS tool, language test fixtures) stays —
allowlist each such file explicitly in the plan · if the project is driven by a personal
Claude Code skill, ship an English, repo-relative version of it inside the public repo (e.g.
`skills/<name>/SKILL.md`) with personal paths, private-repo notes, and personal skill
cross-references stripped — and document how to install it.

### 3. Write the two plans, commit them — to the ORIGINAL repo only

Adapt the reference plans: (a) release-preparation (hygiene → fresh repo/identity → docs
triage → README → quality gate → publish); (b) completion-roadmap (gap audit → finish broken
functionality **before** translating docs, so docs describe the finished state). Commit plans
before executing anything.

**Kitchen stays private.** Plans, audit reports, PUBLISH_PLAN — anything that mentions the old
AI authorship, personal gateway hostnames, or the fact that history was rewritten — live in the
original (private) repo or scratch dir, NEVER in the fresh public repo. The public repo must
contain zero traces of its own preparation.

### 4. Execute — one session per plan item

One focused session = one item = one branch; plans are the only context carrier; mark items
`✅ done (date, branch)` in the plan file each session. Sonnet-class model suffices once plans
exist. Human checkpoints: repo creation, final README, flipping public, CV link update.

## Hard gates (show command output, not claims)

| Gate | Check |
|---|---|
| No Cyrillic | `git grep -lP '[\p{Cyrillic}]'` → empty or ONLY the allowlisted functional-data files from the plan |
| No secrets | `gitleaks detect` clean |
| Tests/lint | project test + lint commands green |
| Reproducible | README quickstart works from a clean clone, no paid/personal keys |
| CI | green on GitHub without repo secrets |
| Attribution | commits authored by the user's verified GitHub identity |

## Common mistakes

- **Translating everything blindly.** Triage first: Tier A already-English, Tier B translate
  (portfolio value), Tier C delete (personal learning notes, session handoffs, agent-memory docs).
  And never "translate" functional non-English data (pronunciation maps, language fixtures) —
  that deletes a feature, not a doc.
- **Polishing docs before finishing code** — eval numbers and READMEs must describe final state.
- **Personal gateway/model defaults** (a local LLM gateway, private model aliases) and secrets wired
  into CI — public users can't reproduce; default to a free-tier provider, keyless CI.
- **Keeping committed datasets** whose license forbids redistribution.
- **README claims without evidence** — every CV-aligned claim needs a link to code/ADR and a
  real metrics table, screenshot, or demo GIF.
- **Committing prep artifacts into the public repo** — a release plan in `docs/plans/` that
  names the old AI author or personal infra defeats the whole cleanup. Gate: `git grep -i` for
  the old author email / gateway hostname in the public repo → empty.
- **"Honest roadmap" instead of working code** — a README that admits the reranker is
  `NotImplementedError` is still a broken portfolio piece. Finish or cut the feature; a smaller
  working repo beats a bigger stubbed one.
