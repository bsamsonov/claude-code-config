---
name: move-project
description: >-
  Moves a project folder to a new location AND immediately repairs the link to its
  Claude Code chat history and memory (which are otherwise lost, because the storage
  is keyed by the project path). Use when the user says "move the project",
  "relocate this folder", "put the project into a group", "I'm sorting my projects",
  and for any reorganisation of project folders, so memory and history are not lost.
---

# move-project — relocate a project without losing history and memory

## Why

Claude Code keeps each project's chat history and memory in
`~/.claude/projects/<encoded-path>/`, where the path is encoded by replacing **every
non-alphanumeric character with `-`** (so `/`, `_`, `.`, space → `-`).

When a project folder moves, its path changes → Claude creates a new empty entry and
the old one (with history and memory) is orphaned. This skill moves the folder and
at the same time moves/merges its storage entry.

Inside a storage entry:
- `<uuid>.jsonl` — session transcripts (**chat history**);
- `<uuid>/` — session data (tool results, subagents);
- `memory/` — **memory** (`MEMORY.md` + fact files).

## Engine

All the logic lives in `~/.claude/scripts/migrate-claude-storage.sh`:

```
migrate-claude-storage.sh <OLD_PATH> <NEW_PATH>      # by real paths
migrate-claude-storage.sh --enc <OLD_ENC> <NEW_ENC>  # by encoded entry names
  --dry-run    only show what would be done
  --root <dir> storage root (default ~/.claude/projects)
```

Behaviour:
- no target → a plain rename of the entry;
- target exists → **safe merge without overwriting**: sessions are moved (UUIDs never
  collide), memory files are added, `MEMORY.md` indexes are merged by unique lines;
- the source is removed only if it ends up empty.

## Procedure

1. **Backup** (once per reorganisation session):
   ```bash
   tar czf ~/claude-projects-backup-$(date +%Y%m%d_%H%M%S).tar.gz -C ~/.claude projects
   ```
   Keep it outside `~/.claude` — transcripts may contain secrets and must never end up
   in a dotfiles repository.
2. **Dry run** — check the mapping is right:
   ```bash
   ~/.claude/scripts/migrate-claude-storage.sh --dry-run "$OLD" "$NEW"
   ```
3. **Move the folder**, then repair the storage:
   ```bash
   mv "$OLD" "$NEW"
   ~/.claude/scripts/migrate-claude-storage.sh "$OLD" "$NEW"
   ```
4. **Check skill references.** Some skills contain hard-coded absolute paths. Find and
   update them:
   ```bash
   grep -rl "$OLD" ~/.claude/skills
   ```
5. **Check that no orphans are left** — entries whose folder no longer exists:
   ```bash
   ls -1 ~/.claude/projects | while read s; do
     real=$(printf '%s' "$s" | sed 's#^-##; s#-#/#g')   # approximate!
     [ -d "/$real" ] || echo "possible orphan: $s"
   done
   ```

## Caveats

- The encoding is **lossy** (different names can map to the same encoded path), so when
  guessing the target always check against a folder that really exists, never
  reconstruct the path from the entry name. The orphan check above is only a hint.
- If the orphan's original folder was deleted (not moved) — there is nowhere to move it;
  leave it or delete it by hand.
- Related automation: the `SessionStart` hook `hooks/reconnect-project-storage.sh`
  re-attaches orphaned history by itself when a project is opened and the target entry
  is still empty (plain rename only, never a merge).
