# Choosing a subagent

Rule: pick the NARROWEST agent whose tools are enough. An agent's starting context
(system prompt + tool descriptions + MCP) is paid for on every call, so every extra
tool is a direct cost against the window.

The ladder:

1. `lightweight-agent` (WebSearch, WebFetch, Read, Write, Edit) — web research,
   gathering information, processing and writing files. The default choice.
2. `codebase-agent` (Bash, Read, Write, Edit, Grep, Glob) — work inside the repository:
   reading code and git history, searching the project, writing documentation. No web.
3. `general-purpose` — ONLY when the full toolset is really needed: MCP tools,
   web and repository at the same time, launching its own subagents.

Model:

- Give subagents `model: sonnet` by default (in the agent file or via the `model`
  parameter). Without it, a subagent inherits the parent's model (Opus) — the most
  expensive option and almost never needed.
- Opus for a subagent only for architectural decisions and subtle analysis, where
  reasoning quality matters more than price. Mechanical work (collecting facts,
  reading code, generating documentation from a template) — Sonnet.

Economy:

- Don't spawn agents for what I can do myself in 2-3 tool calls: every spawn starts
  cold and re-discovers context I already have.
- With several agents, give each one the same ready-made template/brief instead of
  letting each re-research the shared inputs.
- Ask the agent for a short report (5-10 lines), not a retelling of the result.

Measure, don't guess: `bin/agent-context <agent>` prints how many input tokens an
agent's starting context actually costs.

# The 5-hour window

- Requests to wait for a new 5-hour window and continue ("continue when the new window
  starts", "wait for the limit reset") — follow the `resume-after-window` skill: find
  the reset time, add a buffer of minutes, start a background `sleep` with
  `run_in_background`.
- Without an explicit request, do NOT resume work automatically in a new window (even
  if the work was interrupted by the limit) — wait for an explicit command.
