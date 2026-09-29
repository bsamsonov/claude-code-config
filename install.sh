#!/usr/bin/env bash
# Symlinks this configuration into ~/.claude (and helper scripts into ~/.local/bin).
# Never overwrites: an existing file with the same name is left alone and reported.
# settings.json and CLAUDE.md are NOT touched — merge them by hand from the examples.
#
# Usage:
#   ./install.sh                 # hooks, agents, commands, skills, scripts, bin
#   ./install.sh --with-opencode # also link opencode/ into ~/.config/opencode
#   ./install.sh --dry-run       # only show what would be done
set -euo pipefail

REPO="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
BIN_DIR="$HOME/.local/bin"
DRY=0
OPENCODE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --with-opencode) OPENCODE=1 ;;
    *) sed -n '2,10p' "$0"; exit 2 ;;
  esac
done

linked=0
skipped=0
link() { # link <source> <target>
  local src="$1" dst="$2"
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
    return
  fi
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    echo "  skip (exists): $dst"
    skipped=$((skipped + 1))
    return
  fi
  if [ "$DRY" = 1 ]; then
    echo "  [dry] $dst -> $src"
  else
    mkdir -p "$(dirname "$dst")"
    ln -s "$src" "$dst"
    echo "  link: $dst"
  fi
  linked=$((linked + 1))
}

echo "Claude Code config dir: $CLAUDE_DIR"
for f in "$REPO"/hooks/* "$REPO"/agents/*.md "$REPO"/commands/*.md "$REPO"/scripts/*; do
  rel="${f#"$REPO"/}"
  link "$f" "$CLAUDE_DIR/$rel"
done
for d in "$REPO"/skills/*/; do
  name="$(basename "$d")"
  link "${d%/}" "$CLAUDE_DIR/skills/$name"
done

echo "Helper scripts: $BIN_DIR"
for f in "$REPO"/bin/*; do
  link "$f" "$BIN_DIR/$(basename "$f")"
done

if [ "$OPENCODE" = 1 ]; then
  echo "OpenCode: $HOME/.config/opencode"
  link "$REPO/opencode/opencode.jsonc" "$HOME/.config/opencode/opencode.jsonc"
  for f in "$REPO"/opencode/prompts/*.md; do
    link "$f" "$HOME/.config/opencode/prompts/$(basename "$f")"
  done
fi

echo
echo "Done: $linked linked, $skipped skipped."
cat <<EOF

Next steps (manual, on purpose):
  1. Merge the "hooks" and "statusLine" blocks of settings.example.json
     into $CLAUDE_DIR/settings.json.
  2. Optionally copy the sections you like from CLAUDE.md into $CLAUDE_DIR/CLAUDE.md.
  3. Restart Claude Code and run /hooks to confirm the hooks are registered.
EOF
