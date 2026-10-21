#!/usr/bin/env python3
"""
cc_cost.py — approximate token and $ spend of Claude Code, from its own logs.

Parses the JSONL transcripts in ~/.claude/projects (Claude Code writes them
itself, one record per model response, subagents/Task included). Nothing to
instrument, and the accounting itself costs zero tokens.

Counts the 4 token kinds with the right cache multipliers, plus server tools
(web_search / web_fetch). Prices are indicative — edit PRICING for your plan.
The $ figure is the API-price equivalent, useful even on a subscription to see
where the budget goes.

Accounting details:
  - one API response is written to the JSONL as 2-8 lines (one per content
    block: thinking / text / tool_use), each with a copy of the same usage.
    Records are deduplicated by message.id, keeping the line with the largest
    output_tokens — summing all copies would overstate spend roughly 2x;
  - thinking tokens (usage.output_tokens_details.thinking_tokens) are part of
    output and billed as output; shown separately in --by-model / --by-effort;
  - a project is the top-level folder in ~/.claude/projects, so subagent
    transcripts (<project>/<session>/subagents/agent-*.jsonl) count towards the
    project that spawned them. Projects with subagents get two gray subrows:
    main sessions vs subagents, with their share of the project's $;
  - project names are printed as the real working directory (the transcript's
    `cwd`), relative to $CC_COST_PROJECTS_ROOT (default ~/projects), else ~/...;
    --project still matches a substring of the encoded folder name;
  - external `claude -p --output-format json --no-session-persistence` runs
    (CI, review pipelines) write no transcript. Point CC_COST_EXTRA_GLOBS
    (':'-separated globs) at their result JSON logs and they are counted too:
    in the project summary, TOTAL and --by-model, not in --by-effort /
    --by-skill / --top. A log whose session_id also has a transcript is skipped.

Columns: RUNS = main sessions + subagent runs + external runs (the subrows show
each kind); PROMPTS = real user prompts in the main thread (no tool results,
slash commands or meta records).

Usage:
  python3 cc_cost.py                     # all time, summary by project
  python3 cc_cost.py --since 7d          # last 7 days (30m / 24h / 2w also work)
  python3 cc_cost.py --project tmp       # only projects whose path contains 'tmp'
  python3 cc_cost.py --by-model          # breakdown by model family
  python3 cc_cost.py --by-skill          # breakdown by subagent / skill
  python3 cc_cost.py --by-effort         # effort x model, plus sessions by effort
  python3 cc_cost.py --skill deep-research   # one skill's spend, by project
  python3 cc_cost.py --top 10            # the 10 most expensive sessions
"""
from __future__ import annotations
import json, sys, glob, os, re, time, argparse
from datetime import datetime
from collections import defaultdict, Counter

# $ per 1M tokens: (input, output, cache read). Cache writes are multipliers
# of the input rate. As of 2026-10, platform.claude.com/docs/en/about-claude/pricing.
# The key is a price group; a model is matched by a substring of its ID.
PRICING = {
    "fable-5.1": (10.0, 50.0, 0.25),  # Fable 5.1 / Mythos 5.1 (cache read 0.025x)
    "fable":     (10.0, 50.0, 1.00),  # Fable 5 / Mythos 5
    "opus-5.5":  (4.0,  20.0, 0.20),  # Opus 5.5 (cache read 0.05x)
    "opus":      (5.0,  25.0, 0.50),  # Opus 4.5 ... 5
    "opus-4.1":  (15.0, 75.0, 1.50),  # Opus 4 / 4.1
    "sonnet-5":  (2.0,  10.0, 0.20),  # Sonnet 5 / 5.5
    "sonnet":    (3.0,  15.0, 0.30),  # Sonnet 4 ... 4.6
    "haiku-5.5": (0.10,  0.50, 0.01), # Haiku 5.5 (prompts up to 100K; above: $0.50/$2.50)
    "haiku":     (1.0,   5.0, 0.10),  # Haiku 4.5
}
MODEL_RULES = [  # (model ID substring, PRICING key), most specific first
    ("fable-5-1", "fable-5.1"), ("mythos-5-1", "fable-5.1"),
    ("fable", "fable"), ("mythos", "fable"),
    ("opus-5-5", "opus-5.5"),
    ("opus-4-1", "opus-4.1"), ("opus-4-2025", "opus-4.1"),  # Opus 4.1 / Opus 4
    ("opus", "opus"),
    ("sonnet-5", "sonnet-5"), ("sonnet", "sonnet"),
    ("haiku-5-5", "haiku-5.5"), ("haiku", "haiku"),
]
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.0
# Server tools ($ per request), approximately:
WEB_SEARCH_PER_REQ = 10.0 / 1000      # ~$10 per 1000 searches
WEB_FETCH_PER_REQ  = 0.0              # usually billed as context tokens only

# Result logs of external `claude -p --output-format json` runs (no transcript).
EXTRA_GLOBS = [g for g in os.environ.get("CC_COST_EXTRA_GLOBS", "").split(":") if g.strip()]
# Project names are shown relative to this folder.
PROJECTS_ROOT = os.path.expanduser(os.environ.get("CC_COST_PROJECTS_ROOT", "~/projects"))

def ext_usage(fam: str, mu: dict) -> dict:
    """modelUsage of one model from a result log -> a dict shaped like message.usage.
    The 5m/1h cache-write split is recovered from costUSD (Claude Code's exact price):
    cost = base + w*pin*(1.25 + 0.75*r1), where r1 is the 1h share."""
    pin, pout, pcr = PRICING[fam]
    i, o = mu.get("inputTokens", 0), mu.get("outputTokens", 0)
    r, w = mu.get("cacheReadInputTokens", 0), mu.get("cacheCreationInputTokens", 0)
    ws = mu.get("webSearchRequests", 0)
    r1 = 0.0
    if w and pin and mu.get("costUSD") is not None:
        base = i*pin + o*pout + r*pcr + ws*WEB_SEARCH_PER_REQ*1e6
        r1 = min(1.0, max(0.0, ((mu["costUSD"]*1e6 - base)/(w*pin) - CACHE_WRITE_5M)
                               / (CACHE_WRITE_1H - CACHE_WRITE_5M)))
    cw1 = round(w*r1)
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": r,
            "cache_creation": {"ephemeral_5m_input_tokens": w - cw1, "ephemeral_1h_input_tokens": cw1},
            "output_tokens_details": {"thinking_tokens": mu.get("thinkingTokens", 0)},
            "server_tool_use": {"web_search_requests": ws}}

def is_user_prompt(o) -> bool:
    """A real user message in the main thread (not a tool_result, meta record,
    slash command or compact summary)."""
    if o.get("type") != "user" or o.get("isSidechain") or o.get("isMeta") \
       or o.get("isCompactSummary"): return False
    ct = (o.get("message") or {}).get("content")
    if isinstance(ct, str): return bool(ct.strip()) and not ct.lstrip().startswith("<")
    if isinstance(ct, list):
        types = {b.get("type") for b in ct if isinstance(b, dict)}
        return "tool_result" not in types and bool(types & {"text", "image"})
    return False

def model_family(m: str) -> str:
    """Model ID -> PRICING key (price group)."""
    m = (m or "").lower()
    for sub, key in MODEL_RULES:
        if sub in m: return key
    return "sonnet"  # default

def parse_since(s: str | None) -> float:
    if not s: return 0.0
    unit = s[-1]; n = float(s[:-1])
    mult = {"m":60, "h":3600, "d":86400, "w":604800}[unit]
    return time.time() - n*mult

def record_epoch(ts: str) -> float:
    """Record ISO 8601 timestamp (e.g. '2026-07-23T19:05:32.752Z') -> epoch (UTC).
    None/garbage -> 0 (the record is kept, the filter just does not apply)."""
    if not ts: return 0.0
    if ts.endswith("Z"): ts = ts[:-1] + "+00:00"
    try: return datetime.fromisoformat(ts).timestamp()
    except ValueError: return 0.0

class Acc:
    __slots__=("inp","out","think","cw5","cw1","cr","web_s","web_f","calls")
    def __init__(s): s.inp=s.out=s.think=s.cw5=s.cw1=s.cr=s.web_s=s.web_f=s.calls=0
    def add(s,u):
        s.inp += u.get("input_tokens",0)
        s.out += u.get("output_tokens",0)
        s.think += (u.get("output_tokens_details") or {}).get("thinking_tokens",0) or 0
        s.cr  += u.get("cache_read_input_tokens",0)
        cc = u.get("cache_creation") or {}
        cw5 = cc.get("ephemeral_5m_input_tokens")
        cw1 = cc.get("ephemeral_1h_input_tokens")
        if cw5 is None and cw1 is None:
            # old format: a single field, counted as 5m
            s.cw5 += u.get("cache_creation_input_tokens",0)
        else:
            s.cw5 += cw5 or 0; s.cw1 += cw1 or 0
        st = u.get("server_tool_use") or {}
        s.web_s += st.get("web_search_requests",0)
        s.web_f += st.get("web_fetch_requests",0)
        s.calls += 1
    def cost(s, fam):
        pin,pout,pcr = PRICING[fam]
        return ((s.inp*pin + s.out*pout
                 + s.cw5*pin*CACHE_WRITE_5M + s.cw1*pin*CACHE_WRITE_1H
                 + s.cr*pcr)/1e6
                + s.web_s*WEB_SEARCH_PER_REQ + s.web_f*WEB_FETCH_PER_REQ)
    @property
    def tokens(s): return s.inp+s.out+s.cw5+s.cw1+s.cr

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="window: N + m/h/d/w (minutes/hours/days/weeks), e.g. 30m, 2h, 7d")
    ap.add_argument("--project", help="substring of the encoded project folder name")
    ap.add_argument("--by-model", action="store_true")
    ap.add_argument("--by-skill", action="store_true",
                    help="breakdown by subagent / skill (attributionSkill)")
    ap.add_argument("--by-effort", action="store_true",
                    help="effort x model, plus sessions grouped by their effort")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--skill", help="count only records of this skill/subagent "
                    "(substring; special: 'subagents' = any sidechain). "
                    "The project table then shows its spend by project")
    a = ap.parse_args()
    since = parse_since(a.since)
    root = os.path.expanduser("~/.claude/projects")

    by_proj = defaultdict(lambda: defaultdict(Acc))   # proj -> fam -> Acc
    # proj -> main sessions / subagents / external claude -p -> fam -> Acc
    by_part = defaultdict(lambda: {"main": defaultdict(Acc), "sub": defaultdict(Acc),
                                   "ext": defaultdict(Acc)})
    by_file = defaultdict(lambda: [None,0.0,""])      # file -> [fam->Acc, cost, proj]
    grand   = defaultdict(Acc)                         # fam -> Acc
    by_skill = defaultdict(lambda: defaultdict(Acc))  # skill -> fam -> Acc
    skill_files = defaultdict(set)   # skill -> transcripts (sessions / subagent runs) it appears in
    by_effort = defaultdict(lambda: defaultdict(Acc)) # effort -> fam -> Acc
    # sessionId -> {"acc": fam->Acc (subagents included), "eff": Counter of
    #               main-thread effort per call, "prompts": int}
    sessions = defaultdict(lambda: {"acc": defaultdict(Acc), "eff": Counter(), "prompts": 0})

    prompts_by_proj = Counter()    # user prompts per project (main thread)
    main_runs_by_proj = Counter()  # main sessions (<sessionId>.jsonl files) per project
    sub_runs_by_proj = Counter()   # subagent runs (agent-*.jsonl files) per project
    proj_cwd = {}      # encoded project name -> real cwd (for display)
    seen_ids = set()   # message.ids already counted (in case of repeats across files)
    dup_lines = 0      # duplicate lines dropped
    for fp in glob.glob(os.path.join(root,"**","*.jsonl"), recursive=True):
        # project = first folder of the path relative to root (subagents live
        # deeper: <project>/<session>/subagents/agent-*.jsonl)
        proj = os.path.relpath(fp, root).split(os.sep)[0]
        if a.project and a.project not in proj: continue
        # Coarse filter by file mtime: the last record is <= mtime, so an older
        # file has nothing fresh. Only an optimisation — mtime can be shifted by
        # rsync/touch, so records are still filtered by their own timestamps.
        if since and os.path.getmtime(fp) < since: continue
        facc = defaultdict(Acc)
        is_sub_file = os.sep + "subagents" + os.sep in fp
        # One API response = several lines with a copy of the same usage and the
        # same message.id. Count it ONCE, keeping the line with the largest
        # output_tokens (earlier lines may carry an intermediate value).
        uniq = {}  # message.id -> (usage, fam, skill, effort, sessionId, sidechain)
        for lineno, line in enumerate(open(fp, errors="ignore")):
            try: o=json.loads(line)
            except: continue
            if proj not in proj_cwd and not is_sub_file and o.get("cwd"):
                proj_cwd[proj] = o["cwd"]
            msg = o.get("message")
            if not isinstance(msg,dict): continue
            if is_user_prompt(o) and not a.skill:
                ts = record_epoch(o.get("timestamp"))
                if not (since and ts and ts < since):
                    sessions[o.get("sessionId") or fp]["prompts"] += 1
                    prompts_by_proj[proj] += 1
            u = msg.get("usage")
            if not u: continue
            # authoritative filter by the record's own timestamp
            if since:
                ts = record_epoch(o.get("timestamp"))
                if ts and ts < since: continue
            if a.skill:
                sk = o.get("attributionSkill")
                if a.skill == "subagents":
                    if not o.get("isSidechain"): continue
                elif not (sk and a.skill in sk): continue
            fam = model_family(msg.get("model"))
            # attribution to a subagent/skill; (main) = the main thread
            skill = o.get("attributionSkill") or ("(sidechain)" if o.get("isSidechain") else "(main)")
            key = msg.get("id") or o.get("requestId") or (fp, lineno)
            effort = o.get("perTurnEffort") or o.get("effort") or "(none)"
            if key in uniq:
                dup_lines += 1
                if (uniq[key][0].get("output_tokens",0) or 0) > (u.get("output_tokens",0) or 0):
                    continue
            sid = o.get("sessionId") or fp
            uniq[key] = (u, fam, skill, effort, sid, bool(o.get("isSidechain")))
        for key, (u, fam, skill, effort, sid, side) in uniq.items():
            if key in seen_ids: dup_lines += 1; continue  # same response in another file
            seen_ids.add(key)
            facc[fam].add(u); by_proj[proj][fam].add(u); grand[fam].add(u)
            by_skill[skill][fam].add(u); skill_files[skill].add(fp)
            by_effort[effort][fam].add(u)
            sessions[sid]["acc"][fam].add(u)
            by_part[proj]["sub" if (side or is_sub_file) else "main"][fam].add(u)
            if not side: sessions[sid]["eff"][effort] += 1
        if facc and is_sub_file: sub_runs_by_proj[proj] += 1
        elif facc: main_runs_by_proj[proj] += 1
        if facc:
            c = sum(acc.cost(f) for f,acc in facc.items())
            by_file[fp] = [facc, c, proj]

    # External `claude -p --output-format json` runs (no transcript)
    ext_runs = 0
    ext_runs_by_proj = Counter()
    if not a.skill:
        ext_files = set()
        for g in EXTRA_GLOBS:
            ext_files.update(glob.glob(os.path.expanduser(g.strip()), recursive=True))
        for fp in sorted(ext_files):
            if since and os.path.getmtime(fp) < since: continue
            try: d = json.load(open(fp))
            except Exception: continue
            if not isinstance(d, dict) or d.get("type") != "result" or not d.get("modelUsage"): continue
            if d.get("session_id") and d["session_id"] in sessions:
                continue                            # already counted via its transcript
            # project = the repo holding a .review/ folder, else the log's folder
            sep_review = os.sep + ".review" + os.sep
            repo = fp.split(sep_review)[0] if sep_review in fp else os.path.dirname(fp)
            proj = re.sub(r"[^A-Za-z0-9]", "-", repo)   # how Claude Code encodes a project path
            proj_cwd.setdefault(proj, repo)
            if a.project and a.project not in proj: continue
            ext_runs += 1; ext_runs_by_proj[proj] += 1
            for model, mu in d["modelUsage"].items():
                fam = model_family(model); u = ext_usage(fam, mu)
                by_proj[proj][fam].add(u); grand[fam].add(u); by_part[proj]["ext"][fam].add(u)

    def fmt(acc_map):
        vals = acc_map.values()
        return (sum(x.inp for x in vals), sum(x.out for x in vals),
                sum(x.cw5+x.cw1 for x in vals), sum(x.cr for x in vals),
                sum(x.tokens for x in vals),
                sum(x.cost(f) for f,x in acc_map.items()))

    home = os.path.expanduser("~")
    enc_projects = re.sub(r"[^A-Za-z0-9]", "-", PROJECTS_ROOT) + "-"
    enc_home = re.sub(r"[^A-Za-z0-9]", "-", home) + "-"

    def pname(proj, width=38):
        """Readable project name: the path relative to PROJECTS_ROOT, else ~/...
        Without a cwd in the transcript, strip the encoded prefix instead."""
        cwd = proj_cwd.get(proj)
        if cwd:
            if cwd == PROJECTS_ROOT or cwd.startswith(PROJECTS_ROOT + os.sep):
                name = os.path.relpath(cwd, PROJECTS_ROOT)
            elif cwd == home or cwd.startswith(home + os.sep):
                name = "~/" + os.path.relpath(cwd, home) if cwd != home else "~"
            else:
                name = cwd
        elif proj.startswith(enc_projects): name = proj[len(enc_projects):]
        elif proj.startswith(enc_home):     name = "~/" + proj[len(enc_home):]
        else: name = proj
        if len(name) <= width: return name
        parts = name.split("/")
        if len(parts) > 2:                      # first/…/last
            short = parts[0] + "/…/" + parts[-1]
            if len(short) <= width: return short
        if len(parts[-1]) <= width: return parts[-1]   # last folder only
        return "…" + name[-(width-1):]

    def h(n):  # compact numbers: 1.2M / 345K
        if n>=1e6: return f"{n/1e6:.1f}M"
        if n>=1e3: return f"{n/1e3:.0f}K"
        return str(n)

    # subrows are gray — only on a TTY and without NO_COLOR
    use_color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    GRAY, RESET = ("\033[90m", "\033[0m") if use_color else ("", "")

    def print_parts(parts, total_cost, ext_n=0, sub_n=0, main_n=0, prompts=0):
        """Subrows main sessions / subagents / external claude -p, with their share
        of the row above."""
        present = [(p_, l_) for p_, l_ in (("main", "main sessions"), ("sub", "subagents"),
                                           ("ext", "external claude -p")) if parts[p_]]
        for k, (part, label) in enumerate(present):
            mark = "└" if k == len(present) - 1 else "├"
            i,o,w,r,tok,cost = fmt(parts[part])
            pct = 100*cost/total_cost if total_cost else 0
            lab = f"  {mark} {label} {pct:.0f}%"
            runs = {"main": main_n, "sub": sub_n, "ext": ext_n}[part]
            pr = prompts if part == "main" else 0   # prompts exist only in the main thread
            line = f"{lab:<39}{runs or '-':>5}{pr or '-':>8}{h(i):>7}{h(o):>7}{h(w):>7}{h(r):>7}{h(tok):>7}{cost:>8.2f}"
            print(f"{GRAY}{line}{RESET}")

    # --- Summary by project ---
    hdr=f"{'PROJECT':<39}{'RUNS':>5}{'PROMPTS':>8}{'IN':>7}{'OUT':>7}{'cWRITE':>7}{'cREAD':>7}{'TOKENS':>7}{'COST$':>8}"
    print(hdr); print("-"*len(hdr))
    rows = sorted(by_proj.items(), key=lambda kv: -sum(x.cost(f) for f,x in kv[1].items()))
    gi=go=gw=gr=gt=gc=0
    for proj, fams in rows:
        i,o,w,r,tok,cost = fmt(fams)
        gi+=i; go+=o; gw+=w; gr+=r; gt+=tok; gc+=cost
        runs = main_runs_by_proj[proj] + sub_runs_by_proj[proj] + ext_runs_by_proj[proj]
        print(f"{pname(proj):<39}{runs or '-':>5}{prompts_by_proj[proj] or '-':>8}{h(i):>7}{h(o):>7}{h(w):>7}{h(r):>7}{h(tok):>7}{cost:>8.2f}")
        if by_part[proj]["sub"] or by_part[proj]["ext"]:   # split only if there is something to split
            print_parts(by_part[proj], cost, ext_runs_by_proj[proj], sub_runs_by_proj[proj],
                        main_runs_by_proj[proj], prompts_by_proj[proj])
    print("-"*len(hdr))
    runs = sum(main_runs_by_proj.values()) + sum(sub_runs_by_proj.values()) + ext_runs
    print(f"{'TOTAL':<39}{runs or '-':>5}{sum(prompts_by_proj.values()) or '-':>8}{h(gi):>7}{h(go):>7}{h(gw):>7}{h(gr):>7}{h(gt):>7}{gc:>8.2f}")
    tot_parts = {"main": defaultdict(Acc), "sub": defaultdict(Acc), "ext": defaultdict(Acc)}
    for parts in by_part.values():
        for part in ("main", "sub", "ext"):
            for fam, x in parts[part].items():
                t = tot_parts[part][fam]
                for f in Acc.__slots__: setattr(t, f, getattr(t, f) + getattr(x, f))
    if tot_parts["sub"] or tot_parts["ext"]: print_parts(tot_parts, gc, ext_runs, sum(sub_runs_by_proj.values()),
                                                          sum(main_runs_by_proj.values()),
                                                          sum(prompts_by_proj.values()))
    if dup_lines:
        print(f"{GRAY}({dup_lines:,} duplicate lines of the same API responses skipped){RESET}")

    if a.by_skill:
        sh=f"\n{'SKILL / SUBAGENT':<34}{'RUNS':>6}{'IN':>8}{'OUT':>8}{'cWRITE':>8}{'cREAD':>8}{'TOKENS':>9}{'COST$':>10}"
        print(sh); print("-"*(len(sh)-1))
        srows = sorted(by_skill.items(), key=lambda kv:-sum(x.cost(f) for f,x in kv[1].items()))
        for skill, fams in srows:
            i,o,w,r,tok,cost = fmt(fams)
            print(f"{skill[:33]:<34}{len(skill_files[skill]) or '-':>6}{h(i):>8}{h(o):>8}{h(w):>8}{h(r):>8}{h(tok):>9}{cost:>10.2f}")

    if a.by_model:
        print("\nBy model:")
        for fam,acc in sorted(grand.items(), key=lambda kv:-kv[1].cost(kv[0])):
            print(f"  {fam:<10} {acc.tokens:>14,} tok  ${acc.cost(fam):>9.2f}  "
                  f"(in={acc.inp:,} out={acc.out:,} cacheW={acc.cw5+acc.cw1:,} "
                  f"cacheR={acc.cr:,} calls={acc.calls} think={acc.think:,})")
        ws = sum(x.web_s for x in grand.values()); wf=sum(x.web_f for x in grand.values())
        if ws or wf: print(f"  server tools: web_search={ws} web_fetch={wf}")

    if a.by_effort:
        # (1/2) effort x model — compare rows of the SAME model
        eh=(f"\n{'EFFORT':<9}{'MODEL':<11}{'CALLS':>7}{'OUT':>8}{'THINK':>8}{'cWRITE':>8}"
            f"{'cREAD':>8}{'COST$':>10}{'out/req':>9}{'think/req':>10}{'$/req':>8}")
        print(eh); print("-"*(len(eh)-1))
        rows = [(eff, fam, acc) for eff, fams in by_effort.items() for fam, acc in fams.items()
                if acc.calls]
        for eff, fam, x in sorted(rows, key=lambda r: (r[1], -r[2].cost(r[1]))):
            n = x.calls; c = x.cost(fam)
            print(f"{eff[:8]:<9}{fam[:10]:<11}{n:>7}{h(x.out):>8}{h(x.think):>8}"
                  f"{h(x.cw5+x.cw1):>8}{h(x.cr):>8}{c:>10.2f}{x.out/n:>9.0f}"
                  f"{x.think/n:>10.0f}{c/n:>8.3f}")

        # (2/2) sessions by the prevailing effort of their main thread
        groups = defaultdict(lambda: {"n":0, "prompts":0, "calls":0, "cost":0.0, "costs":[]})
        for sid, S in sessions.items():
            cost = sum(x.cost(f) for f, x in S["acc"].items())
            calls = sum(x.calls for x in S["acc"].values())
            if not calls: continue
            tot = sum(S["eff"].values())
            if tot:
                top, k = S["eff"].most_common(1)[0]
                eff = top if k >= 0.9*tot else "mixed"
            else:
                eff = "(none)"
            g = groups[eff]
            g["n"] += 1; g["prompts"] += S["prompts"]; g["calls"] += calls
            g["cost"] += cost; g["costs"].append(cost)
        sh=(f"\n{'SESSIONS by effort':<19}{'SESS':>6}{'PROMPTS':>9}{'CALLS':>7}{'COST$':>10}"
            f"{'$/sess':>9}{'median':>9}{'$/prompt':>10}{'calls/pr':>10}")
        print(sh); print("-"*(len(sh)-1))
        for eff, g in sorted(groups.items(), key=lambda kv: -kv[1]["cost"]):
            cs = sorted(g["costs"]); med = cs[len(cs)//2] if len(cs)%2 else (cs[len(cs)//2-1]+cs[len(cs)//2])/2
            pr = g["prompts"]
            print(f"{eff[:18]:<19}{g['n']:>6}{pr:>9}{g['calls']:>7}{g['cost']:>10.2f}"
                  f"{g['cost']/g['n']:>9.2f}{med:>9.2f}"
                  f"{(g['cost']/pr if pr else 0):>10.3f}{(g['calls']/pr if pr else 0):>10.1f}")
        print("  session effort = the prevailing one (>=90% of main-thread calls), else mixed;\n"
              "  a session's cost includes its subagents.")

    if a.top:
        print(f"\nTop {a.top} sessions by cost:")
        for fp,(facc,c,proj) in sorted(by_file.items(), key=lambda kv:-kv[1][1])[:a.top]:
            print(f"  ${c:>8.2f}  {pname(proj, 30):<32} {os.path.basename(fp)[:8]}")


if __name__=="__main__":
    main()
