# Claude Code config

My daily-driver configuration for [Claude Code](https://docs.claude.com/en/docs/claude-code):
hooks, a status line, subagents, slash commands, skills and a few helper scripts.

The common thread is **treating the agent's budget as an engineering resource**. A Claude
subscription is metered in 5-hour windows; most of this setup exists so the agent knows
how much budget it has left, spends it where it matters, and never gets cut off halfway
through a job with nothing saved.

## Highlights

### 1. Window guard — rate limits injected into the agent's context
Claude Code passes subscription limits (`rate_limits.five_hour`) **only** to the status
line command — hooks and the model never see them. The status line here doubles as a
sensor: it mirrors the limits into a per-session bridge file, and two hooks turn that
into behaviour:

- `UserPromptSubmit` injects an escalating note into the model's context — silent below
  50%, a 15-token `[5h: 57% · resets 14:20]` above it, a warning at 70%, hard rules at 85%;
- `PreToolUse` on `Task` **blocks subagent spawns** in the red zone (exit code 2) and tells
  the model to write `HANDOFF.md` and wrap up instead.

Fail-open, per-session, atomic writes. Full design write-up:
[docs/window-guard.md](docs/window-guard.md) ·
code: [hooks/statusline.js](hooks/statusline.js), [hooks/window-guard.js](hooks/window-guard.js)

### 2. Resuming after the reset
[skills/resume-after-window](skills/resume-after-window/SKILL.md) reads the reset time from
the same bridge and parks the session on a background `sleep` that wakes it up three
minutes after the window refills — then it continues the work.
[/wake](commands/wake.md) is the general version ("wake up at 07:00 and do X").

### 3. Offloading bulk work to a second model pool
The most token-hungry work — reading dozens of web pages, writing boilerplate modules —
does not need Claude. [skills/research-via-opencode](skills/research-via-opencode/SKILL.md)
and [skills/code-via-opencode](skills/code-via-opencode/SKILL.md) hand it to
[OpenCode](https://opencode.ai) agents on a separately billed subscription, while Claude
keeps the parts where its judgement matters: decomposition, specs, review, synthesis.

- [bin/oc-code](bin/oc-code) runs the coder agent in a **disposable git worktree** on a
  pinned base SHA, re-runs the tests itself ("never take the agent's word for it") and
  leaves a branch to merge or drop.
- [opencode/opencode.jsonc](opencode/opencode.jsonc) scopes each agent's permissions to
  allow/deny only — a headless run has nowhere to render an "ask" prompt and would hang.

### 4. Subagent economics
Every subagent pays for its system prompt and tool list on each spawn.
[CLAUDE.md](CLAUDE.md) encodes the policy (narrowest agent that has the tools, Sonnet by
default, short reports), [agents/](agents) provides the narrow agents, and
[bin/agent-context](bin/agent-context) measures what an agent's starting context actually
costs. [skills/deep-research-economy](skills/deep-research-economy/SKILL.md) applies the
same thinking to research: Opus only for the plan and the synthesis, raw web content never
enters the expensive context, 2–3 related sections per subagent, resumable via `state.json`.

### 5. Knowing where the tokens go
[scripts/cc_cost.py](scripts/cc_cost.py) parses the transcripts Claude Code already writes
and breaks spend down by project, model, **subagent/skill** and session.
Finding: cache *writes*, not output, were the biggest cost line —
see [docs/cost-analysis.md](docs/cost-analysis.md).

### 6. Moving projects without losing memory
Claude Code keys chat history and memory by the project's path, so moving a folder
silently orphans them. A `SessionStart` hook
([hooks/reconnect-project-storage.sh](hooks/reconnect-project-storage.sh)) re-attaches an
unambiguous orphan automatically; [skills/move-project](skills/move-project/SKILL.md) +
[scripts/migrate-claude-storage.sh](scripts/migrate-claude-storage.sh) handle the manual,
merge-capable case.

## Layout

The repository mirrors `~/.claude`:

| Path | What |
|---|---|
| [settings.example.json](settings.example.json) | hooks, status line, plugins, defaults |
| [settings.local.example.json](settings.local.example.json) | routing Claude Code through a local LLM gateway |
| [CLAUDE.md](CLAUDE.md) | global instructions: subagent policy, the 5-hour window, commits |
| [hooks/](hooks) | status line, window guard, storage reconnect |
| [agents/](agents) | narrow subagents: `lightweight-agent`, `codebase-agent`, `research-lite`, `plain-agent` |
| [commands/](commands) | `/wake` |
| [skills/](skills) | see below |
| [scripts/](scripts) | cost analyser, storage migration |
| [bin/](bin) | `cc-cost`, `agent-context`, `oc-research`, `oc-code` |
| [opencode/](opencode) | OpenCode agents (`researcher`, `coder`) and their prompts |
| [docs/](docs) | design notes |

## Skills

| Skill | What it does |
|---|---|
| [resume-after-window](skills/resume-after-window/SKILL.md) | Sleep until the 5-hour window resets, then continue the work |
| [research-via-opencode](skills/research-via-opencode/SKILL.md) | Fan web research out to OpenCode agents, synthesise in Claude |
| [code-via-opencode](skills/code-via-opencode/SKILL.md) | Spec in Claude, modules by OpenCode agents in worktrees, review and merge in Claude |
| [deep-research](skills/deep-research/SKILL.md) | Plan → sourced research → a folder of Markdown documents |
| [deep-research-economy](skills/deep-research-economy/SKILL.md) | The same at a fraction of the token cost |
| [architect](skills/architect/SKILL.md) | Architecture research and ADRs, no implementation code (with evals) |
| [code-walkthrough](skills/code-walkthrough/SKILL.md) | Per-file code walkthroughs for a backend architect |
| [codebase-tutorial](skills/codebase-tutorial/SKILL.md) | A narrative textbook over a real codebase |
| [atomic-commit](skills/atomic-commit/SKILL.md) | Split a messy working tree into atomic conventional commits |
| [github-push](skills/github-push/SKILL.md) | init → commit → `gh` auth → create repo → push |
| [poc-portfolio-prep](skills/poc-portfolio-prep/SKILL.md) | Turn a messy POC into a public portfolio repo, with hard gates |
| [move-project](skills/move-project/SKILL.md) | Move a project folder together with its Claude history and memory |
| [translate-ru](skills/translate-ru/SKILL.md) | Technical translation into Russian that never breaks Markdown or code |

**Personalising research.** `deep-research` has a *Reader profile* block at the top; while
it holds placeholders the skill writes for a general technical reader. Mine looks like this:

```
Background: Java backend engineer — distributed systems, solution architecture.
Goal:       AI Engineer / AI Architect.
```

With it, AI topics come back explained through distributed-systems analogies, focused on
system design and production rather than data science, with a gap analysis, a learning
path and a reading list attached.

Published separately: [gdrive-upload-skill](https://github.com/bsamsonov/gdrive-upload-skill)
— Markdown folder → Google Docs via pandoc + rclone.

## Install

```bash
git clone https://github.com/bsamsonov/claude-code-config.git
cd claude-code-config
./install.sh --dry-run        # see what would be linked
./install.sh                  # add --with-opencode for the OpenCode agents
```

The installer only creates symlinks and never overwrites existing files. `settings.json`
and `CLAUDE.md` are deliberately left for you to merge by hand from the examples.

Requirements: Claude Code, Node.js (hooks, status line), Python 3 (cost analyser).
Optional: `opencode` with an OpenCode Go subscription, `gh`.
Linux only for the scheduling parts (`/wake`, `resume-after-window` use GNU `date -d`
and `systemd-run`); the hooks and scripts are plain Node.js / Python / bash.

## Also in use (not mine, not included)

- [context7](https://github.com/upstash/context7) and `skill-creator` from the official plugin marketplace
- [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) — coding-behaviour guidelines

## License

[MIT](LICENSE)
