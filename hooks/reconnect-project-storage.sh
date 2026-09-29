#!/usr/bin/env bash
# SessionStart hook: if the current project folder was moved and its chat
# history / memory were orphaned, safely re-attach them to the new path.
#
# Background: Claude Code keys per-project storage by path —
# ~/.claude/projects/<encoded-cwd>/, where every non-alphanumeric character is
# replaced with '-'. Move the folder and the new path gets a fresh, empty entry
# while the old one (sessions + memory/) is silently left behind.
#
# Deliberately conservative:
#   1. cwd comes from $CLAUDE_PROJECT_DIR, falling back to $PWD.
#   2. If the entry for the current path already has sessions or memory — exit.
#   3. Look for entries whose name ends with -<basename(cwd)> and hold data.
#   4. Act only if there is exactly ONE such candidate and the target does not
#      exist: a plain rename. Never merge, never overwrite — merging is done by
#      hand with scripts/migrate-claude-storage.sh (see skill move-project).
set -euo pipefail

ROOT="${HOME}/.claude/projects"
CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$ROOT" ] || exit 0

enc() { printf '%s' "$1" | sed 's#[^a-zA-Z0-9]#-#g'; }
has_data() { ls "$1"/*.jsonl >/dev/null 2>&1 || [ -d "$1/memory" ]; }

NEW_ENC=$(enc "$CWD")
DST="$ROOT/$NEW_ENC"
if [ -d "$DST" ] && has_data "$DST"; then
  exit 0
fi

base=$(enc "$(basename "$CWD")")
mapfile -t candidates < <(ls -1 "$ROOT" 2>/dev/null \
  | grep -E -- "-${base}\$" | grep -vxF -- "$NEW_ENC" || true)

orphans=()
for c in "${candidates[@]:-}"; do
  [ -n "$c" ] && has_data "$ROOT/$c" && orphans+=("$c")
done

if [ "${#orphans[@]}" -eq 1 ] && [ ! -e "$DST" ]; then
  mv -- "$ROOT/${orphans[0]}" "$DST"
  echo "[reconnect] re-attached project history: ${orphans[0]} -> $NEW_ENC" >&2
fi
exit 0
