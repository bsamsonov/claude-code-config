---
name: atomic-commit
description: |
  Splits the current working-tree changes into several atomic commits by meaning, with
  clean conventional-commit messages. Each commit is one logical unit.
  Use when the user says "commit and split unrelated changes", "make atomic commits",
  "split into separate commits", "commit by meaning", "several commits",
  "atomic commits", "split into commits", and also for a plain "commit the changes"
  when the working tree mixes unrelated edits.
  This is about HOW to slice and word commits; for pushing to GitHub — the github-push skill.
---

# Skill: Atomic commits

## Purpose

A clean history where every commit is self-contained and reflects one change: easier
review, precise reverts, meaningful blame. This skill turns a mixed pile of edits into a
tidy sequence of commits.

## Step 1 — Inspect the changes

```bash
git -C "$PWD" status
git -C "$PWD" diff --stat
git -C "$PWD" diff            # working tree
git -C "$PWD" diff --staged   # if something is already staged
```

Read the actual diffs, not just file names — one file can hold unrelated edits. If there
are few changes and they are about one thing — don't invent a split, make one commit.
Splitting for the sake of splitting hurts.

## Step 2 — Group by meaning

Signs of **different** commits:
- different subsystems / folders / features;
- bug fix vs new functionality vs refactoring vs documentation;
- functional change vs formatting/renaming;
- a change plus an unrelated config tweak.

Signs of **one** commit: a code change + its tests; an API change + updating all callers;
a feature + its entry in the relevant doc.

Show the user the proposed commit plan (one line per commit) **before** committing if
there are more than two or three groups or any ambiguity. For obvious cases, commit
right away and show the result.

## Step 3 — Stage and commit group by group

Stage by file when groups live in different files:
```bash
git add path/to/file_a path/to/file_b
git commit -m "<message>"
```

When **one file** mixes groups — stage by hunk:
```bash
git add -p path/to/file
```
`git add -p` is interactive. If the environment does not allow interaction, apply a
prepared hunk patch with `git apply --cached`, or honestly tell the user this file will
have to be committed whole.

Commit groups in a sensible order: the foundation first (refactoring/infrastructure)
that later commits rely on, then the features on top.

## Message format — Conventional Commits

`<type>(<scope>): <short imperative description>`

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`, `perf`, `build`, `ci`.
Scope is optional: the module/area (`auth`, `ingestion`, `chunker`).

**Example 1:**
Changes: JWT authentication added + a pagination bug fixed in the user list.
- `feat(auth): add JWT-based authentication`
- `fix(users): correct off-by-one in pagination`

**Example 2:**
Changes: variables renamed across a module + a new endpoint.
- `refactor(billing): rename ambiguous variables for clarity`
- `feat(billing): add invoice export endpoint`

Subject up to ~70 characters, imperative mood ("add", not "added"). If the change needs
a "why" — add a body after a blank line.

If the repository already has its own message style (check `git log --oneline -15`) and
it is not conventional — **follow the repository's style**, don't impose yours.

## Finish

After committing show `git log --oneline -<N>` with the new commits. Don't push without a
separate request — pushing is the `github-push` skill or an explicit command.
