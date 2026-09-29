#!/usr/bin/env bash
# Moves Claude Code chat history and memory from an old storage entry to a new
# one after a project folder was relocated.
# Path encoding used by Claude Code: every non-alphanumeric character -> '-'.
#
# Usage:
#   migrate-claude-storage.sh <OLD_PATH> <NEW_PATH>      # by real project paths
#   migrate-claude-storage.sh --enc <OLD_ENC> <NEW_ENC>  # by encoded entry names
# Options:
#   --dry-run     only print what would be done
#   --root <dir>  storage root (default: ~/.claude/projects)
#
# Behaviour:
#   target missing -> plain rename of the entry
#   target exists  -> safe merge, nothing is overwritten: sessions are moved
#                     (UUIDs never collide), memory files are added, MEMORY.md
#                     indexes are merged by unique lines; the source is removed
#                     only once it is empty.
set -euo pipefail

ROOT="${HOME}/.claude/projects"
DRY=0
MODE=path
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --enc) MODE=enc; shift ;;
    --root) ROOT="$2"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
[ "${#args[@]}" -eq 2 ] || { sed -n '2,12p' "$0"; exit 2; }

enc() { printf '%s' "$1" | sed 's#[^a-zA-Z0-9]#-#g'; }
if [ "$MODE" = path ]; then
  OLD=$(enc "${args[0]}"); NEW=$(enc "${args[1]}")
else
  OLD="${args[0]}"; NEW="${args[1]}"
fi
SRC="$ROOT/$OLD"
DST="$ROOT/$NEW"
echo "Source: $SRC"
echo "Target: $DST"
[ -d "$SRC" ] || { echo "  ! source not found — nothing to migrate"; exit 0; }

run() { if [ "$DRY" = 1 ]; then echo "  [dry] $*"; else eval "$@"; fi; }

if [ ! -e "$DST" ]; then
  echo "  -> target missing: plain rename"
  run "mv -- \"$SRC\" \"$DST\""
  exit 0
fi

echo "  -> target exists: safe merge (no overwrites)"
shopt -s nullglob

# 1. Sessions: *.jsonl transcripts and <uuid>/ session folders.
for f in "$SRC"/*.jsonl; do run "mv -n -- \"$f\" \"$DST/\""; done
for d in "$SRC"/*/; do
  bn=$(basename "$d")
  [ "$bn" = memory ] && continue
  if [ -e "$DST/$bn" ]; then echo "  ~ skip (exists): $bn"; else run "mv -- \"$d\" \"$DST/\""; fi
done

# 2. Memory.
if [ -d "$SRC/memory" ]; then
  if [ ! -d "$DST/memory" ]; then
    run "mv -- \"$SRC/memory\" \"$DST/memory\""
  else
    for m in "$SRC"/memory/*; do
      bn=$(basename "$m")
      if [ "$bn" = MEMORY.md ]; then
        # Merge the index: append bullet lines that are not there yet.
        if [ "$DRY" = 1 ]; then
          echo "  [dry] merge MEMORY.md"
        else
          {
            echo ""
            echo "<!-- merged from $OLD $(date +%F) -->"
            grep -h '^- ' "$m" 2>/dev/null | while IFS= read -r line; do
              grep -qxF -- "$line" "$DST/memory/MEMORY.md" || printf '%s\n' "$line"
            done
          } >> "$DST/memory/MEMORY.md"
        fi
      elif [ -e "$DST/memory/$bn" ]; then
        run "cp -n -- \"$m\" \"$DST/memory/${bn%.md}__from_${OLD##*-}.md\""
      else
        run "mv -n -- \"$m\" \"$DST/memory/\""
      fi
    done
  fi
fi

# 3. Remove the source only if it is empty now.
if [ "$DRY" = 1 ]; then
  echo "  [dry] rm -rf source if empty"
elif find "$SRC" -type f | grep -q .; then
  echo "  ! files left in source, NOT removing: $SRC"
else
  rm -rf -- "$SRC"
fi
echo "  done"
