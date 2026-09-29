#!/usr/bin/env node
'use strict';
/**
 * Claude Code status line.
 *
 * Renders: directory | 5h limit | 7d limit | git branch
 * and mirrors the subscription rate limits into a per-session bridge file,
 * because `rate_limits` is delivered to the status line only — hooks and
 * skills read it back from $TMPDIR/claude-limits-<session_id>.json.
 *
 * Input: session JSON on stdin (see the Claude Code docs, "Customize your status line").
 *
 * settings.json:
 *   "statusLine": { "type": "command",
 *     "command": "node ~/.claude/hooks/statusline.js", "refreshInterval": 60 }
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const SEPARATOR = ' │ ';
const BRIDGE_PREFIX = 'claude-limits-';
const BRIDGE_TTL_MS = 60 * 60 * 1000; // drop bridge files of long-gone sessions
const SWEEP_EVERY_MS = 30 * 60 * 1000;

const paint = (code, text) => `\u001b[${code}m${text}\u001b[0m`;
const dim = (text) => paint('2', text);

/** Pink → yellow → orange → red as a budget gets consumed. */
function byUsage(pct, text) {
  if (pct < 50) return paint('38;2;255;125;218', text);
  if (pct < 65) return paint('33', text);
  if (pct < 80) return paint('38;2;255;140;0', text);
  return paint('31', text);
}

const toNumber = (value) =>
  value === null || value === undefined || value === '' ? null : Number(value);

/** Compact "time left" for an epoch-seconds deadline: 45m, 3h10m, 2d4h. */
function timeLeft(resetsAt) {
  const minutes = Math.max(0, Math.ceil((resetsAt * 1000 - Date.now()) / 60000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours}h${minutes % 60}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `${days}d${hours % 24}h` : `${days}d`;
}

/** "5h:23%(1h40m)" — null when the window is absent or not yet reported. */
function limitSegment(label, window) {
  const used = toNumber(window && window.used_percentage);
  if (used === null || !Number.isFinite(used)) return null;
  const segment = `${dim(label + ':')}${byUsage(used, Math.round(used) + '%')}`;
  const resetsAt = toNumber(window.resets_at);
  return resetsAt ? segment + dim(`(${timeLeft(resetsAt)})`) : segment;
}

/** Current branch, or the short SHA when HEAD is detached. */
function gitSegment(cwd) {
  const git = (...args) => {
    try {
      return execFileSync('git', args, {
        cwd,
        encoding: 'utf8',
        timeout: 1000,
        stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch {
      return '';
    }
  };
  const branch = git('branch', '--show-current');
  if (branch) return paint('36', branch);
  const sha = git('rev-parse', '--short', 'HEAD');
  return sha ? paint('31', `HEAD@${sha}`) : null;
}

/** Atomic write, so a concurrent reader never sees a half-written file. */
function writeBridge(file, payload) {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(payload));
  fs.renameSync(tmp, file);
}

/** Closed sessions never clean up after themselves; sweep them occasionally. */
function sweepStaleBridges(dir) {
  const sentinel = path.join(dir, 'claude-limits.sweep');
  try {
    if (Date.now() - fs.statSync(sentinel).mtimeMs < SWEEP_EVERY_MS) return;
  } catch {
    /* no sentinel yet — sweep now */
  }
  fs.writeFileSync(sentinel, '');
  for (const name of fs.readdirSync(dir)) {
    if (!name.startsWith(BRIDGE_PREFIX)) continue;
    const file = path.join(dir, name);
    try {
      if (Date.now() - fs.statSync(file).mtimeMs > BRIDGE_TTL_MS) fs.unlinkSync(file);
    } catch {
      /* raced with another session — ignore */
    }
  }
}

function publishLimits(data, limits) {
  const session = data.session_id;
  if (!session || !limits) return;
  const tmpDir = os.tmpdir();
  const window = (name) => limits[name] || {};
  try {
    writeBridge(path.join(tmpDir, `${BRIDGE_PREFIX}${session}.json`), {
      session_id: session,
      five_hour_used_pct: toNumber(window('five_hour').used_percentage),
      five_hour_resets_at: toNumber(window('five_hour').resets_at),
      seven_day_used_pct: toNumber(window('seven_day').used_percentage),
      seven_day_resets_at: toNumber(window('seven_day').resets_at),
      ctx_remaining_pct: toNumber(data.context_window && data.context_window.remaining_percentage),
      ts: Math.floor(Date.now() / 1000),
    });
    sweepStaleBridges(tmpDir);
  } catch {
    /* the status line must never fail because of its bridge file */
  }
}

function render(data) {
  const cwd = (data.workspace && data.workspace.current_dir) || data.cwd || process.cwd();
  const limits = data.rate_limits || {};
  const segments = [
    dim(path.basename(cwd)),
    limitSegment('5h', limits.five_hour),
    limitSegment('7d', limits.seven_day),
    gitSegment(cwd),
  ];
  publishLimits(data, data.rate_limits);
  return segments.filter(Boolean).join(SEPARATOR);
}

let stdin = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => (stdin += chunk));
process.stdin.on('end', () => {
  try {
    process.stdout.write(render(JSON.parse(stdin)));
  } catch {
    /* unparsable input or a broken pipe: print nothing rather than garbage */
  }
});
