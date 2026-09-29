#!/usr/bin/env node
'use strict';
/**
 * Window guard: makes the agent aware of the 5-hour subscription window and
 * stops it from spawning subagents when the window is nearly exhausted.
 *
 * Problem: Claude Code delivers `rate_limits.five_hour` ONLY to the status line
 * command. Hooks never see it, so the model has no idea how much of the window
 * is left — it happily fans out five subagents at 95% and gets cut off mid-task.
 *
 * Solution: the status line (hooks/statusline.js) mirrors the limits into a
 * per-session "bridge" file $TMPDIR/claude-limits-<session_id>.json. This hook
 * reads that file back and turns it into agent context / a tool-call veto.
 *
 * Modes (first CLI argument):
 *   prompt   UserPromptSubmit hook. Whatever is printed to stdout is appended
 *            to the agent's context for this turn. Escalates with usage:
 *              < QUIET        silent (no context pollution)
 *              QUIET..YELLOW  compact "[5h: 57% · resets 14:20]" (~15 tokens)
 *              YELLOW..RED    warning: split work, spawn subagents sparingly
 *              >= RED         hard rules: no subagents, write HANDOFF.md, wrap up
 *   pretool  PreToolUse hook on Task. Exit code 2 blocks the subagent spawn in
 *            the RED zone (stderr is shown to the model as the reason), unless
 *            the window resets within GRACE_MIN minutes anyway.
 *
 * Fail-open: missing, unreadable or stale data never blocks and never errors.
 *
 * settings.json:
 *   "UserPromptSubmit": [{ "hooks": [{ "type": "command",
 *       "command": "node ~/.claude/hooks/window-guard.js prompt", "timeout": 5 }] }],
 *   "PreToolUse": [{ "matcher": "Task", "hooks": [{ "type": "command",
 *       "command": "node ~/.claude/hooks/window-guard.js pretool", "timeout": 5 }] }]
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const mode = process.argv[2] || 'prompt';

// Thresholds, in percent of the 5h window USED. All overridable via env.
// QUIET = 50 gives an early heads-up 20 points before YELLOW — enough runway to
// split up big work. Below it the line changes no decision and is pure noise;
// when an exact reset time is needed (skill resume-after-window), the agent
// reads the bridge file directly, which works at any percentage.
const QUIET = Number(process.env.CC_WINDOW_QUIET ?? 50);
const YELLOW = Number(process.env.CC_WINDOW_YELLOW || 70);
const RED = Number(process.env.CC_WINDOW_RED || 85);
const STALE_SEC = Number(process.env.CC_WINDOW_STALE_SEC || 300);
// If the window resets within this many minutes, don't hard-block: it is
// about to refill anyway. We still warn.
const GRACE_MIN = Number(process.env.CC_WINDOW_GRACE_MIN || 10);

// Read THIS session's own bridge file, keyed by session_id from the hook stdin.
// Per-session is required: many idle sessions are open at once and each one's
// rate_limits reflect whatever upstream it last talked to — a single shared
// file would be a race of a dozen writers with unrelated numbers.
let input = '';
const watchdog = setTimeout(() => finish(''), 2000);
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => (input += chunk));
process.stdin.on('end', () => {
  clearTimeout(watchdog);
  let session = '';
  try {
    session = JSON.parse(input).session_id || '';
  } catch {
    /* no session id → fail open below */
  }
  finish(session);
});

function readBridge(session) {
  if (!session) return null;
  try {
    const file = path.join(os.tmpdir(), `claude-limits-${session}.json`);
    const bridge = JSON.parse(fs.readFileSync(file, 'utf8'));
    const age = Math.floor(Date.now() / 1000) - (bridge.ts || 0);
    return age > STALE_SEC ? null : bridge; // stale → fail open
  } catch {
    return null;
  }
}

/** Relative time until reset: "45m", "1h20m". */
function fmtRelative(resetsAt) {
  if (!resetsAt) return '?';
  const min = Math.max(0, Math.ceil((resetsAt * 1000 - Date.now()) / 60000));
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m > 0 ? `${h}h${String(m).padStart(2, '0')}m` : `${h}h`;
}

/**
 * Absolute local "HH:MM". Preferred for the compact line: unlike the relative
 * form it does not go stale during a long turn, and the agent can schedule a
 * wake-up straight from it.
 */
function fmtAbsolute(resetsAt) {
  if (!resetsAt) return '?';
  const d = new Date(resetsAt * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function minutesToReset(resetsAt) {
  if (!resetsAt) return Infinity;
  return Math.max(0, (resetsAt * 1000 - Date.now()) / 60000);
}

function finish(session) {
  const bridge = readBridge(session);
  if (!bridge || bridge.five_hour_used_pct == null) process.exit(0);

  const used = bridge.five_hour_used_pct;
  // used_percentage arrives as a float (7.000000000000001) — round for display
  // only; the comparisons below use the raw value.
  const usedDisp = Math.round(used);
  const remaining = Math.max(0, 100 - usedDisp);
  const minLeft = minutesToReset(bridge.five_hour_resets_at);
  const level = used >= RED ? 'red' : used >= YELLOW ? 'yellow' : 'green';
  const status =
    `5h window: ${usedDisp}% used (${remaining}% left) · ` +
    `resets in ${fmtRelative(bridge.five_hour_resets_at)}`;

  if (mode === 'pretool') {
    if (level === 'red' && minLeft > GRACE_MIN) {
      process.stderr.write(
        `[window-guard] ${status}. The 5-hour window is almost exhausted — do NOT ` +
          `start subagents. Finish the current step yourself, save the work status ` +
          `to HANDOFF.md and wrap up, so nothing gets cut off mid-subagent.`
      );
      process.exit(2); // exit 2 in PreToolUse blocks the tool call
    }
    process.exit(0);
  }

  // mode === 'prompt': stdout becomes agent context.
  if (level === 'green') {
    if (used >= QUIET) {
      // Compact form with absolute time: ~15 tokens instead of ~40.
      process.stdout.write(`[5h: ${usedDisp}% · resets ${fmtAbsolute(bridge.five_hour_resets_at)}]`);
    }
  } else if (level === 'yellow') {
    process.stdout.write(
      `[⚠️ ${status}. The window is running out: split large tasks, start ` +
        `subagents sparingly, checkpoint intermediate results more often.]`
    );
  } else {
    process.stdout.write(
      `[🔴 ${status}. WINDOW LIMIT NEARLY REACHED. Rules until reset:\n` +
        `• Do NOT start subagents (Task) — they may be cut off mid-work.\n` +
        `• Finish only the current step; do not start new large tasks.\n` +
        `• Save the work status to HANDOFF.md (done, remaining, next step).\n` +
        `• Then wrap up and tell the user where you stopped.]`
    );
  }
  process.exit(0);
}
