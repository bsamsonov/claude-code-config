---
description: Wake this session up at a given time and run a task
argument-hint: <HH:MM> [what to do on wake-up]
allowed-tools: Bash
---

Arguments: `$ARGUMENTS` — the first word is `HH:MM` (local time), the rest is the task.
If there is no task, on wake-up just say hello and tell the time.

## What to do in this turn

1. Start the wait with a single `Bash` call with `run_in_background: true`.
   The delay is computed inside the command — don't spend a separate turn on `date`:

   ```bash
   T="<HH:MM>"; s=$(( $(date -d "$T" +%s) - $(date +%s) )); \
   [ $s -le 0 ] && s=$(( s + 86400 )); \
   echo "wake at $T, in ${s}s"; sleep $s; date '+WAKE-UP %H:%M:%S'
   ```

   Set the tool `timeout` to 600000 (the maximum). The background task outlives this
   limit — it is detached from the turn; the timeout has no effect here.

2. **Write the task down in this very turn**, in one line, e.g.
   `deferred until 07:00 — task: <text>`. The completion notification carries only
   the task id, no context, and this line is the only trace.

3. End the turn, stating the wake-up time. While `sleep` runs, no tokens are spent
   at all — neither in this session nor in others.

## On wake-up

Read the background task output, make sure it contains `WAKE-UP`, and **run the task**
from step 2 right away, without asking again.

## Limitation

`sleep` is a child of the CLI process: closing the terminal or rebooting kills the
alarm. Laptop suspend also eats sleep time (the counter stops — it wakes up later).
If the wait is long and the session may not survive — warn the user and suggest an
external timer instead of a background sleep:

```bash
systemd-run --user --on-calendar='*-*-* <HH:MM>:00' --unit=claude-wake \
  --working-directory=<project_dir> \
  claude --resume <session_id> -p "<task>"
```

Cancel: `systemctl --user stop claude-wake.timer`.
