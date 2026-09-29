---
name: code-via-opencode
description: |
  Hands code writing off to OpenCode Go subagents (`bin/oc-code`) so the Claude 5-hour
  window is NOT spent on it. Claude writes the interface spec and the critical parts,
  subagents write modules and tests in disposable git worktrees, Claude reviews and merges.
  Use when the user says: "implement it via opencode", "use opencode subagents for the
  code", "write the code on opencode-go", "don't burn the window, code with subagents",
  and also for a large from-scratch implementation when the Claude window must be saved.
---

# Skill: Code via OpenCode Go

## Tooling

- `bin/oc-code` — the wrapper: creates a disposable git worktree, runs
  `opencode run --agent coder`, runs the tests independently, leaves branch `oc/<slug>`.
- Agent role: `opencode/prompts/coder.md` (minimal diff, green tests).
- Agent permissions: `opencode/opencode.jsonc` → `agent.coder.permission`.

```bash
SLUG_OVERRIDE=tools oc-code -m kimi-k2.7-code -t "uv run pytest -q tests/test_tools.py" "task"
git merge --no-ff oc/tools-0731-0229      # accept
oc-code --drop oc/tools-0731-0229         # drop
```

## Division of labour (the main point)

A subagent writes **plausible** code. Modules will fit together only if the contract is
fixed in advance and from outside. Therefore:

1. **Claude writes `SPEC.md`** — exact file names, classes, signatures, JSON format,
   test command. Explicitly: "contracts are fixed and must not change, modules are
   written in parallel". That is cheaper than any later integration.
2. **Claude writes itself** only the delicate parts: where a model's mistake would not
   be caught by tests (the core of a graph/algorithm), and the scaffolding a subagent
   would trip over (e.g. a fake LLM with the right duck typing).
3. **Subagents get** modules with clear boundaries + their tests. One agent per
   non-overlapping set of files, launched in parallel, in the background.
4. **Claude accepts**: its own test run, a quick look at the interfaces, the merge.

## Known pitfalls of `oc-code` (all three were fixed after they bit)

- **A multi-line prompt broke the branch name** — the slug is taken from the first line
  only; for non-ASCII tasks it degenerates to `task`, so set `SLUG_OVERRIDE=<name>`.
- **`BASE="HEAD"` was not pinned to a SHA**: after the agent committed, `git diff HEAD`
  inside the worktree was empty, the result was treated as missing and the worktree was
  deleted together with the code. Now the base is resolved to `BASE_SHA` up front.
- **Untracked files did not count as changes**: an agent that created new files without
  committing lost all its work on cleanup. Now the wrapper commits the leftovers itself.

When running an agent on new ground — **back up the result**: a background loop
`cp -r <worktree>/*.py <worktree>/tests /tmp/backup/` every few seconds. Once it saved
47 finished tests.

## Practice

- Model (Go plan, as of 2026-09 — see the tier table in `research-via-opencode`):
  `glm-5.2` (the wrapper default), `kimi-k2.7-code` and `deepseek-v4-pro` are fine for
  modules with tests, ~900–1 350 requests per 5 h. The 🚫 tier (`kimi-k3`, `qwen3.8-max`,
  `grok-4.7`, `glm-5.3`) is not for coding pipelines.
- The repository working tree must be **clean** — commit before every run.
- Give the agent `-t` with the exact test command for **its** files, otherwise it will
  go fixing someone else's red.
- Write explicitly: "don't change files X, Y — they are done", and "at the end commit:
  git add -A && git commit".
- The agent cannot do real runs that need secrets: `.env` does not reach the worktree
  (it is untracked). Real runs are Claude's job.
- **Don't grep agent logs broadly**: `/tmp/oc*.log` contains walls of JSON with
  permission rules; one `grep` without `cut -c1-200` eats thousands of tokens.
  Read only the tail: `sed -n '/acceptance/,$p' log | cut -c1-160`.

## Acceptance (mandatory — never take the agent's word for it)

1. Your own run of the full test suite, not just the agent's files.
2. A quick look at the interfaces: `grep -n "^def \|^class " module.py`.
3. Check that tests were not weakened: no `skip`/`xfail`, asserts are meaningful.
4. Merge `--no-ff` with a clear message; don't drag the agent's report into the commit.
