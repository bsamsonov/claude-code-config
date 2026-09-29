---
name: resume-after-window
description: >-
  Schedules a delayed wake-up at the start of the next 5-hour subscription window and
  resumes interrupted work automatically. Finds the limit reset time, adds a buffer and
  starts a background sleep whose exit wakes the agent up.
  Use when the user says: "continue when the new window starts", "wait for the rate
  limit reset", "resume after the 5-hour window resets", "wait until the limits refresh
  and continue", "pause until the next window", and also when the window is running out,
  the work is unfinished and has to be resumed later.
---

# Resuming work after the 5-hour window resets

Mechanics: the model has no timer of its own. A delayed wake-up is a background
`sleep` whose exit produces a `<task-notification>` and starts a new turn.
Don't rely on `ScheduleWakeup` — it may be missing from the base toolset.

## Step 1. Find the reset time

Try in order, stop at the first that works:

1. **The hook line in context** — the main path. `hooks/window-guard.js` on
   `UserPromptSubmit` injects a compact line with the **absolute** time
   once the window is at least 50% used:

   ```
   [5h: 57% · resets 01:20]
   ```

   Local time, HH:MM. In the yellow (≥70%) and red (≥85%) zones the format is
   different, verbose, and the time is **relative** ("resets in 1h20m") — count from
   the moment the line was received.

2. **The bridge file** — when you need second-level precision or there is no line
   in context:

   ```bash
   cat "${TMPDIR:-/tmp}/claude-limits-<session_id>.json"
   ```

   `five_hour_resets_at` is unix seconds (there is also `seven_day_resets_at`).
   `session_id` is the name of the current transcript in
   `~/.claude/projects/<slug>/<session_id>.jsonl`.
   The status line rewrites the file about every 60 s; older than 300 s it is treated
   as stale. **Note: it is `$TMPDIR`, not necessarily `/tmp`.**

3. **Ask the user.** They can see the exact reset time in `/usage`.
   Don't make it up or estimate "roughly" — a mistake costs a burned turn.

## Step 2. Compute the delay with a buffer

```
delay_sec = (resets_at - now) + 180
```

**The buffer is minutes, not seconds.** Waking up right at the reset is dangerous:
the turn hits the limit and burns, with nothing left to retry. Default is 180 s; if
the time is only known relatively and rounded, use 300 s.

## Step 3. Start the background wait

One `Bash` call with `run_in_background: true` (NOT foreground — that would block
messages from the user; chaining short `sleep`s is forbidden by the harness):

```bash
date '+waiting since %H:%M:%S'; sleep <delay_sec>; date '+wake-up %H:%M:%S'
```

Set the tool `timeout` above `delay_sec`. Then **end the turn**, telling the user the
wake-up time — while `sleep` runs, no tokens are spent at all.

## Step 4. Before leaving — record the state

The notification brings only an id and a status, no task context. So in this same
turn briefly write into the transcript: what is done, what remains, the next step.
If the work is large — into `HANDOFF.md` next to the project (the window guard
requires the same in the red zone).

## Step 5. On wake-up

Read the task output file (`Read`), make sure the window really did reset (re-read
the bridge from step 1.2), and **continue the work** instead of asking for permission
again — it was already given when the wake-up was set.

## Limitation: lives only as long as the CLI session

The background `sleep` is a child of the CLI process. Closing the terminal kills it
too, and nobody will wake up. If the session may not survive, schedule it outside:

```bash
systemd-run --user --on-active=<N>min --unit=claude-resume \
  --working-directory=<project_dir> \
  claude --resume <session_id> -p "<what to continue>"
```

Cancel before it fires: `systemctl --user stop claude-resume.timer`,
log: `journalctl --user -u claude-resume`.

## Reference: window-guard thresholds

| Used | What happens |
|---|---|
| < 50% | nothing is injected (`CC_WINDOW_QUIET=0` — always send the compact line) |
| 50–69% | compact line `[5h: N% · resets HH:MM]` |
| 70–84% | warning: split tasks, save subagents |
| ≥ 85% | red zone: `PreToolUse` **blocks subagent spawns** (Task), requires `HANDOFF.md` |

Exception: if the reset is less than 10 min away (`CC_WINDOW_GRACE_MIN`) there is no
block — the window is about to refill anyway. Thresholds are overridable via
`CC_WINDOW_QUIET` / `_YELLOW` / `_RED` / `_GRACE_MIN`.
