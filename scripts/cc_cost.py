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

Usage:
  python3 cc_cost.py                     # all time, summary by project
  python3 cc_cost.py --since 7d          # last 7 days (1d / 24h / 2w also work)
  python3 cc_cost.py --project tmp       # only projects whose path contains 'tmp'
  python3 cc_cost.py --by-model          # breakdown by model family
  python3 cc_cost.py --by-skill          # breakdown by subagent / skill
  python3 cc_cost.py --skill deep-research   # one skill's spend, by project
  python3 cc_cost.py --top 10            # the 10 most expensive sessions
"""
from __future__ import annotations
import json, sys, glob, os, time, argparse
from datetime import datetime
from collections import defaultdict

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
    "haiku":     (1.0,   5.0, 0.10),  # Haiku 4.5
}
MODEL_RULES = [  # (model ID substring, PRICING key), most specific first
    ("fable-5-1", "fable-5.1"), ("mythos-5-1", "fable-5.1"),
    ("fable", "fable"), ("mythos", "fable"),
    ("opus-5-5", "opus-5.5"),
    ("opus-4-1", "opus-4.1"), ("opus-4-2025", "opus-4.1"),  # Opus 4.1 / Opus 4
    ("opus", "opus"),
    ("sonnet-5", "sonnet-5"), ("sonnet", "sonnet"),
    ("haiku", "haiku"),
]
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.0
# Server tools ($ per request), approximately:
WEB_SEARCH_PER_REQ = 10.0 / 1000      # ~$10 per 1000 searches
WEB_FETCH_PER_REQ  = 0.0              # usually billed as context tokens only

def model_family(m: str) -> str:
    """Model ID -> PRICING key (price group)."""
    m = (m or "").lower()
    for sub, key in MODEL_RULES:
        if sub in m: return key
    return "sonnet"  # default

def parse_since(s: str | None) -> float:
    if not s: return 0.0
    unit = s[-1]; n = float(s[:-1])
    mult = {"d":86400, "h":3600, "w":604800}[unit]
    return time.time() - n*mult

def record_epoch(ts: str) -> float:
    """Record ISO 8601 timestamp (e.g. '2026-07-23T19:05:32.752Z') -> epoch (UTC).
    None/garbage -> 0 (the record is kept, the filter does not apply)."""
    if not ts: return 0.0
    if ts.endswith("Z"): ts = ts[:-1] + "+00:00"
    try: return datetime.fromisoformat(ts).timestamp()
    except ValueError: return 0.0

class Acc:
    __slots__=("inp","out","cw5","cw1","cr","web_s","web_f","calls")
    def __init__(s): s.inp=s.out=s.cw5=s.cw1=s.cr=s.web_s=s.web_f=s.calls=0
    def add(s,u):
        s.inp += u.get("input_tokens",0)
        s.out += u.get("output_tokens",0)
        s.cr  += u.get("cache_read_input_tokens",0)
        cc = u.get("cache_creation") or {}
        cw5 = cc.get("ephemeral_5m_input_tokens")
        cw1 = cc.get("ephemeral_1h_input_tokens")
        if cw5 is None and cw1 is None:
            # old format: everything in one field, count it as 5m
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
    ap.add_argument("--since"); ap.add_argument("--project")
    ap.add_argument("--by-model", action="store_true")
    ap.add_argument("--by-skill", action="store_true",
                    help="breakdown by subagent/skill (attributionSkill)")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--skill", help="count only records of this skill/subagent "
                    "(substring; special value 'subagents' = any sidechain). "
                    "The project table then shows its spend per project")
    a = ap.parse_args()
    since = parse_since(a.since)
    root = os.path.expanduser("~/.claude/projects")

    by_proj = defaultdict(lambda: defaultdict(Acc))   # proj -> fam -> Acc
    by_file = defaultdict(lambda: [None,0.0,""])      # file -> [fam_acc dict, cost, proj]
    grand   = defaultdict(Acc)                         # fam -> Acc
    by_skill = defaultdict(lambda: defaultdict(Acc))  # skill -> fam -> Acc

    for fp in glob.glob(os.path.join(root,"**","*.jsonl"), recursive=True):
        proj = os.path.basename(os.path.dirname(fp))
        if a.project and a.project not in proj: continue
        # Coarse filter by file mtime: the last record is <= mtime, so if
        # mtime < since the file has no fresh records at all.
        # This is only an optimisation — mtime can be shifted (rsync/touch),
        # so for mtime >= since every record is still filtered by timestamp.
        if since and os.path.getmtime(fp) < since: continue
        facc = defaultdict(Acc)
        for line in open(fp, errors="ignore"):
            try: o=json.loads(line)
            except: continue
            msg = o.get("message")
            if not isinstance(msg,dict): continue
            u = msg.get("usage")
            if not u: continue
            # Exact filter by the record timestamp (authoritative).
            if since:
                ts = record_epoch(o.get("timestamp"))
                if ts and ts < since: continue
            if a.skill:
                sk = o.get("attributionSkill")
                if a.skill == "subagents":
                    if not o.get("isSidechain"): continue
                elif not (sk and a.skill in sk): continue
            fam = model_family(msg.get("model"))
            facc[fam].add(u); by_proj[proj][fam].add(u); grand[fam].add(u)
            # Attribution to a subagent/skill; (main) = the main thread, not a subagent.
            skill = o.get("attributionSkill") or ("(sidechain)" if o.get("isSidechain") else "(main)")
            by_skill[skill][fam].add(u)
        if facc:
            c = sum(acc.cost(f) for f,acc in facc.items())
            by_file[fp] = [facc, c, proj]

    def fmt(acc_map):
        vals = acc_map.values()
        return (sum(x.inp for x in vals), sum(x.out for x in vals),
                sum(x.cw5+x.cw1 for x in vals), sum(x.cr for x in vals),
                sum(x.tokens for x in vals),
                sum(x.cost(f) for f,x in acc_map.items()))

    def h(n):  # compact number format: 1.2M / 345K
        if n>=1e6: return f"{n/1e6:.1f}M"
        if n>=1e3: return f"{n/1e3:.0f}K"
        return str(n)

    # --- Summary by project ---
    hdr=f"{'PROJECT':<40}{'IN':>8}{'OUT':>8}{'cWRITE':>8}{'cREAD':>8}{'TOKENS':>9}{'COST$':>10}"
    print(hdr); print("-"*len(hdr))
    rows = sorted(by_proj.items(), key=lambda kv: -sum(x.cost(f) for f,x in kv[1].items()))
    gi=go=gw=gr=gt=gc=0
    for proj, fams in rows:
        i,o,w,r,tok,cost = fmt(fams)
        gi+=i; go+=o; gw+=w; gr+=r; gt+=tok; gc+=cost
        print(f"{proj[-39:]:<40}{h(i):>8}{h(o):>8}{h(w):>8}{h(r):>8}{h(tok):>9}{cost:>10.2f}")
    print("-"*len(hdr))
    print(f"{'TOTAL':<40}{h(gi):>8}{h(go):>8}{h(gw):>8}{h(gr):>8}{h(gt):>9}{gc:>10.2f}")

    if a.by_skill:
        sh=f"\n{'SKILL / SUBAGENT':<34}{'IN':>8}{'OUT':>8}{'cWRITE':>8}{'cREAD':>8}{'TOKENS':>9}{'COST$':>10}"
        print(sh); print("-"*(len(sh)-1))
        srows = sorted(by_skill.items(), key=lambda kv:-sum(x.cost(f) for f,x in kv[1].items()))
        for skill, fams in srows:
            i,o,w,r,tok,cost = fmt(fams)
            print(f"{skill[:33]:<34}{h(i):>8}{h(o):>8}{h(w):>8}{h(r):>8}{h(tok):>9}{cost:>10.2f}")

    if a.by_model:
        print("\nBy model:")
        for fam,acc in sorted(grand.items(), key=lambda kv:-kv[1].cost(kv[0])):
            print(f"  {fam:<10} {acc.tokens:>14,} tok  ${acc.cost(fam):>9.2f}  "
                  f"(in={acc.inp:,} out={acc.out:,} cacheW={acc.cw5+acc.cw1:,} "
                  f"cacheR={acc.cr:,} calls={acc.calls})")
        ws = sum(x.web_s for x in grand.values()); wf=sum(x.web_f for x in grand.values())
        if ws or wf: print(f"  server tools: web_search={ws} web_fetch={wf}")

    if a.top:
        print(f"\nTop {a.top} sessions by cost:")
        for fp,(facc,c,proj) in sorted(by_file.items(), key=lambda kv:-kv[1][1])[:a.top]:
            print(f"  ${c:>8.2f}  {proj[-30:]:<32} {os.path.basename(fp)[:8]}")

if __name__=="__main__":
    main()
