---
name: github-push
description: |
  Push the current project repository to GitHub.
  Handles the full flow: git init, first commit, gh auth, repo creation, and push.
  Use when the user says "push to github", "create github repo", "push repo",
  "publish to github", "put this on GitHub".
---

# Skill: Push Project to GitHub

## Purpose

Handles the complete flow of publishing the current project to GitHub:
1. Ensure git is initialised and has at least one commit
2. Ensure `gh` CLI is authenticated
3. Create a GitHub repository if no remote exists
4. Push all commits

## Workflow

Work through the steps below **sequentially**, checking state at each step before acting.

---

### Step 1 — Check git status

```bash
git -C "$PWD" status 2>&1
```

- If output contains `not a git repository` → go to **Step 2a** (init)
- If output shows `nothing to commit` or a clean state with commits → skip to **Step 3**
- If output shows uncommitted changes → go to **Step 2b** (stage + commit)

---

### Step 2a — Initialise git (if not a repo)

```bash
cd /path/to/project
git init
```

Then check if `.gitignore` is needed. If the project has `node_modules/`, `__pycache__/`, `.venv/`, `.env`, or similar — offer to create a `.gitignore`. Common template:

```
node_modules/
__pycache__/
.venv/
venv/
.env
*.pyc
.DS_Store
```

Then stage and commit:
```bash
git add -A
git commit -m "Initial commit"
```

---

### Step 2b — Stage and commit pending changes

```bash
git add -A
git status   # confirm what will be committed
git commit -m "<describe the changes>"
```

Use a descriptive commit message based on what files changed.

---

### Step 3 — Check gh authentication

```bash
gh auth status 2>&1
```

- If output contains `Logged in as` → skip to **Step 4**
- If output contains `not logged in` → run:

```bash
gh auth login --web -h github.com
```

Walk the user through the interactive prompts:
1. Protocol: **HTTPS**
2. Authenticate Git with credentials: **Yes**
3. Copy the one-time code shown, press Enter to open the browser, paste the code on GitHub

---

### Step 4 — Check for existing remote

```bash
git remote -v
```

- If a remote named `origin` exists → skip to **Step 5** (just push)
- If no remote → go to **Step 4a** (create repo)

---

### Step 4a — Create GitHub repository and push

First, determine the repo name and visibility:
- Default repo name: `basename "$PWD"`
- Default visibility: **private** — use `--public` only if the user explicitly specified it in their request

```bash
gh repo create <repo-name> --private --description "<short description>" \
  --source=. --remote=origin --push
```

For a public repo:
```bash
gh repo create <repo-name> --public --source=. --remote=origin --push
```

This creates the repo, adds `origin` remote, and pushes in one step.

---

### Step 5 — Push (remote already exists)

```bash
git push
```

If the branch has no upstream yet:
```bash
git push --set-upstream origin $(git branch --show-current)
```

---

## What to report after completion

Tell the user:
1. The GitHub URL of the repository (from `gh repo view --json url -q .url` or from the output of `gh repo create`)
2. How many commits were pushed (`git log --oneline | wc -l`)
3. Current branch name

---

## Edge cases

| Situation | Action |
|-----------|--------|
| `gh` not installed | Run `sudo apt install gh` or `sudo snap install gh` |
| Branch is `master` not `main` | Push as-is; mention user can rename with `git branch -m main` |
| Push rejected (non-fast-forward) | Show `git log origin/<branch>..HEAD` and ask whether to force-push or merge |
| Repo already exists on GitHub | Skip creation, add remote manually: `git remote add origin https://github.com/<user>/<repo>.git`, then push |
| Binary files or large files | Warn if any file > 50 MB (GitHub limit is 100 MB; LFS recommended above 50 MB) |

---

## Dependencies

- `git` — version control
- `gh` — GitHub CLI: `sudo apt install gh` or `sudo snap install gh`
- Active internet connection
- A GitHub account (free tier is sufficient)
