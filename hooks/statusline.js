#!/usr/bin/env node
'use strict';
/**
 * Claude Code status line.
 *
 * Renders: model | directory | context | prompt cache (+TTL) | 5h limit | 7d limit |
 * uncommitted changes + git branch
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

/** 950 → "950", 4200 → "4.2k", 180345 → "180k", 1000000 → "1M". */
function compact(n) {
  if (n < 1000) return String(n);
  if (n < 10000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  if (n < 1e6) return Math.round(n / 1000) + 'k';
  return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
}

/** "Claude Opus 4.7 (1M context)" → "Opus 4.7 (1m)"; unknown names pass through. */
function modelSegment(model) {
  const name = (model && model.display_name) || 'Claude';
  const m = name.match(/^(?:claude-)?(?:Claude\s+)?(Opus|Sonnet|Haiku|Mythos)[\s-]+(\d+(?:[.-]\d+)?)(?:\s*\(([^)]+)\))?/i);
  if (!m) return dim(name);
  let short = `${m[1][0].toUpperCase()}${m[1].slice(1).toLowerCase()} ${m[2].replace('-', '.')}`;
  const size = m[3] && m[3].match(/(\d+)\s*([KMG])/i);
  if (size) short += ` (${size[1]}${size[2].toLowerCase()})`;
  return dim(short);
}

/** Context usage "120k/1M", or "12%" when only the percentage is known. */
function contextSegment(ctx) {
  if (!ctx) return null;
  const total = Number(ctx.total_input_tokens) || 0;
  const size = Number(ctx.context_window_size) || 0;
  const remaining = toNumber(ctx.remaining_percentage);
  let used;
  let text;
  if (total > 0 && size > 0) {
    used = (total / size) * 100;
    text = `${compact(total)}/${compact(size)}`;
  } else if (remaining !== null && Number.isFinite(remaining)) {
    used = 100 - remaining;
    text = `${Math.round(used)}%`;
  } else {
    return null;
  }
  used = Math.max(0, Math.min(100, used));
  // 250k is a quality/price cliff whatever the window size: never stay "cozy pink" past it.
  if (total >= 250000 && used < 50) return paint('33', text);
  return byUsage(used, text);
}

const TRANSCRIPT_TAIL_BYTES = 64 * 1024;

/** Last `bytes` of a file as complete lines (a partial first line is dropped). */
function tailLines(file, bytes) {
  const size = fs.statSync(file).size;
  const start = Math.max(0, size - bytes - 1); // 1 extra byte tells a clean line start
  const buf = Buffer.alloc(size - start);
  const fd = fs.openSync(file, 'r');
  try {
    fs.readSync(fd, buf, 0, buf.length, start);
  } finally {
    fs.closeSync(fd);
  }
  let text = buf.toString('utf8');
  if (start > 0) text = text.slice(text.indexOf('\n') + 1);
  return text.split('\n').filter(Boolean);
}

/**
 * Cache TTL state from the transcript — stdin exposes neither the TTL bucket
 * (ephemeral_1h vs ephemeral_5m) nor when the cache was last touched.
 * Returns { ttl: '5m' | '1h', touchedAt: ms } or null.
 */
function cacheTtlState(transcriptPath) {
  if (!transcriptPath) return null;
  let lines;
  try {
    lines = tailLines(transcriptPath, TRANSCRIPT_TAIL_BYTES);
  } catch {
    return null;
  }
  let touchedAt = null;
  let ttl = null;
  for (let i = lines.length - 1; i >= 0 && !(touchedAt && ttl); i--) {
    let rec;
    try {
      rec = JSON.parse(lines[i]);
    } catch {
      continue;
    }
    const usage = rec && rec.type === 'assistant' && rec.message && rec.message.usage;
    if (!usage || !rec.timestamp) continue;
    const read = usage.cache_read_input_tokens || 0;
    const write = usage.cache_creation_input_tokens || 0;
    if (read === 0 && write === 0) continue;
    // Every read or write refreshes the TTL, so the newest touch counts.
    if (!touchedAt) touchedAt = new Date(rec.timestamp).getTime() || null;
    // The bucket is decided by the most recent write.
    if (!ttl && write > 0 && usage.cache_creation) {
      if (usage.cache_creation.ephemeral_1h_input_tokens > 0) ttl = '1h';
      else if (usage.cache_creation.ephemeral_5m_input_tokens > 0) ttl = '5m';
    }
  }
  return touchedAt && ttl ? { ttl, touchedAt } : null;
}

/** "47m" / "40s" — time until the cache expires (the TTL bucket only sets the base). */
function ttlCountdown({ ttl, touchedAt }) {
  const ttlMs = ttl === '5m' ? 5 * 60 * 1000 : 60 * 60 * 1000;
  const leftMs = ttlMs - (Date.now() - touchedAt);
  const leftSec = leftMs / 1000;
  let left;
  if (leftSec <= 0) left = '0m';
  else if (leftSec < 60) left = Math.ceil(leftSec) + 's';
  else left = timeLeft((Date.now() + leftMs) / 1000); // 59.9 min reads as 1h, not 60m
  const share = leftMs / ttlMs;
  let color;
  if (share <= 0) color = '31';
  else if (share < 0.1) color = '38;2;255;140;0';
  else if (share < 0.25) color = '33';
  else color = '2';
  return paint(color, left);
}

/**
 * "cache 97%(47m)" — hit ratio of the latest API call,
 * read / (input + creation + read), plus the TTL countdown.
 * A 0% ratio (full miss / invalidation) is shown in bold red on purpose.
 */
function cacheSegment(usage, transcriptPath) {
  if (!usage) return null;
  const read = Number(usage.cache_read_input_tokens) || 0;
  const write = Number(usage.cache_creation_input_tokens) || 0;
  const fresh = Number(usage.input_tokens) || 0;
  if (read === 0 && write === 0) return null;
  const ratio = Math.round((read / (read + write + fresh)) * 100);
  let color;
  if (ratio === 0) color = '1;31';
  else if (ratio >= 90) color = '1;32';
  else if (ratio >= 75) color = '32';
  else if (ratio >= 50) color = '33';
  else color = '38;2;255;140;0';
  const segment = `${dim('cache')} ${paint(color, ratio + '%')}`;
  const state = cacheTtlState(transcriptPath);
  return state ? `${segment}${dim('(')}${ttlCountdown(state)}${dim(')')}` : segment;
}

/**
 * Uncommitted changes bucketed like VS Code: "2M 1A 3?" (dim) plus "1!" (red)
 * for merge conflicts; null when the tree is clean.
 */
function changeCounters(status) {
  const counts = { M: 0, A: 0, D: 0, R: 0, '?': 0, '!': 0 };
  for (const line of status.split('\n')) {
    if (!line) continue;
    const [x, y] = line;
    if (x === '?' && y === '?') counts['?']++;
    else if (x === 'U' || y === 'U' || (x === 'D' && y === 'D') || (x === 'A' && y === 'A')) counts['!']++;
    else if (x === 'D' || y === 'D') counts.D++;
    else if (x === 'R') counts.R++;
    else if (x === 'A' || x === 'C') counts.A++;
    else counts.M++;
  }
  const parts = [];
  const plain = ['M', 'A', 'D', 'R', '?'].filter((k) => counts[k]).map((k) => counts[k] + k);
  if (plain.length) parts.push(dim(plain.join(' ')));
  if (counts['!']) parts.push(paint('31', counts['!'] + '!'));
  return parts.length ? parts.join(' ') : null;
}

/** "2M 1? main": change counters, then the branch (or short SHA when detached). */
function gitSegment(cwd) {
  const git = (...args) => {
    try {
      return execFileSync('git', args, {
        cwd,
        encoding: 'utf8',
        timeout: 1000,
        stdio: ['ignore', 'pipe', 'ignore'],
      });
    } catch {
      return '';
    }
  };
  const branch = git('branch', '--show-current').trim();
  const sha = branch ? '' : git('rev-parse', '--short', 'HEAD').trim();
  if (!branch && !sha) return null; // not a repository
  const head = branch ? paint('36', branch) : paint('31', `HEAD@${sha}`);
  // Not trimmed: porcelain lines start with a meaningful space (" M file").
  const changes = changeCounters(git('status', '--porcelain'));
  return changes ? `${changes} ${head}` : head;
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
    modelSegment(data.model),
    dim(path.basename(cwd)),
    contextSegment(data.context_window),
    cacheSegment(data.context_window && data.context_window.current_usage, data.transcript_path),
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
