#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "yt-dlp>=2025.1.1",
# ]
# ///
"""Instagram Reels -> transcripts with the LOCAL whisper.cpp (free, no API keys).

Commands:
  reel   URL                    one reel -> Markdown (caption + transcript) on stdout
  batch  LINKS --name USER      many reels from a links file, polite and resumable
  status DIR                    progress of a batch folder
  build  DIR                    rebuild index.csv and ALL_TRANSCRIPTS.md

Instagram does not give the list of a profile's reels without login, so the list is
collected in the user's own browser (scripts/collect_links.js) and passed as LINKS.
Each reel is then fetched anonymously by yt-dlp (audio only, deleted afterwards) and
transcribed by whisper.cpp already installed at ~/tools/whisper.cpp.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

HOME = Path.home()
DEFAULT_OUT = HOME / "instagram_transcripts"
WHISPER_CLI = Path(os.environ.get("IG_WHISPER_CLI", HOME / "tools/whisper.cpp/build/bin/whisper-cli"))
MODELS_DIR = Path(os.environ.get("IG_WHISPER_MODELS", HOME / "tools/whisper.cpp/models"))
PARAGRAPH_SECONDS = 30            # reels are short: one [mm:ss] paragraph per ~30 s
BACKOFF_MINUTES = (30, 60, 120)   # waits after a block before giving up
MAX_ERROR_ATTEMPTS = 3
FINAL = {"done", "no_audio", "no_speech", "unavailable", "skipped"}
SHORTCODE_RE = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]{5,})")

BLOCK_MARKERS = ("login", "log in", "rate-limit", "rate limit", "please wait", "429",
                 "401", "checkpoint", "challenge", "cookies")
UNAVAILABLE_MARKERS = ("not available", "404", "private", "removed", "unavailable")
# whisper "phantom" lines produced on music / silence (common in RU/UK/EN)
HALLUCINATIONS = re.compile(
    r"(субтитры (сделал|создавал|подогнал)|редактор субтитров|продолжение следует|"
    r"спасибо за просмотр|подписывайтесь на канал|dimatorzok|thanks for watching|"
    r"♪)|^\s*[\[(*].*[\])*]\s*$", re.I)  # also whole-line [Music], (смех), *outro music*


class Blocked(Exception):
    """Instagram refused anonymous access (login wall / rate limit)."""


class Unavailable(Exception):
    pass


# ---------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def shortcode(url: str) -> str | None:
    m = SHORTCODE_RE.search(url)
    return m.group(1) if m else None


def reel_url(code: str) -> str:
    return f"https://www.instagram.com/reel/{code}/"


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def resolve_model(name: str) -> Path:
    p = Path(name).expanduser()
    if not p.exists():
        p = MODELS_DIR / f"ggml-{name}.bin"
    if not p.exists():
        avail = sorted(x.stem.removeprefix("ggml-") for x in MODELS_DIR.glob("ggml-*.bin"))
        sys.exit(f"whisper model '{name}' not found; available in {MODELS_DIR}: {avail}")
    return p


def check_tools() -> None:
    if not WHISPER_CLI.exists():
        sys.exit(f"whisper.cpp not found at {WHISPER_CLI} (set IG_WHISPER_CLI)")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")


# ------------------------------------------------------------ download + ASR

def fetch_audio(url: str, workdir: Path, cookies: str | None) -> tuple[dict, Path]:
    """One page request + media download. Returns (info, media_path)."""
    opts = {"format": "ba/b", "outtmpl": str(workdir / "%(id)s.%(ext)s"),
            "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            "retries": 2, "socket_timeout": 30}
    if cookies:
        opts["cookiefile"] = str(Path(cookies).expanduser())
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as e:
        msg = str(e).lower()
        if any(m in msg for m in BLOCK_MARKERS):
            raise Blocked(str(e)[:200])
        if any(m in msg for m in UNAVAILABLE_MARKERS):
            raise Unavailable(str(e)[:200])
        raise
    if info.get("_type") == "playlist":  # carousel post: take the first video
        entries = [x for x in info.get("entries") or [] if x]
        if not entries:
            raise Unavailable("post has no video")
        info = {**entries[0], "description": info.get("description") or entries[0].get("description")}
    files = [p for p in workdir.iterdir() if p.is_file() and not p.name.endswith((".part", ".wav", ".json"))]
    if not files:
        raise Unavailable("nothing downloaded")
    return info, files[0]


def has_audio(media: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", str(media)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def transcribe(media: Path, model: Path, lang: str, threads: int) -> dict:
    wav = media.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(media), "-vn",
                    "-ac", "1", "-ar", "16000", str(wav)], check=True)
    base = media.with_suffix("")
    r = subprocess.run([str(WHISPER_CLI), "-m", str(model), "-l", lang, "-t", str(threads),
                        "-oj", "-of", str(base), "-np", "-f", str(wav)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"whisper-cli failed: {r.stderr.strip()[-300:]}")
    data = json.loads(Path(f"{base}.json").read_text(encoding="utf-8", errors="replace"))
    segs = []
    for s in data.get("transcription", []):
        text = s.get("text", "").strip()
        if text and not HALLUCINATIONS.search(text):
            segs.append((s["offsets"]["from"] / 1000.0, text))
    return {"lang": (data.get("result") or {}).get("language", lang), "segments": segs}


def to_paragraphs(segments) -> str:
    out, cur, start = [], [], None
    for t, text in segments:
        if start is None:
            start = t
        cur.append(text)
        if t - start >= PARAGRAPH_SECONDS and text.rstrip().endswith((".", "!", "?", "…")):
            out.append(f"[{fmt_ts(start)}] " + " ".join(cur))
            cur, start = [], None
    if cur:
        out.append(f"[{fmt_ts(start or 0)}] " + " ".join(cur))
    return "\n\n".join(out)


def meta_of(info: dict) -> dict:
    ts = info.get("timestamp")
    return {"user": info.get("channel") or info.get("uploader_id") or info.get("uploader") or "",
            "author": info.get("uploader") or "",
            "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else "",
            "timestamp": ts, "duration": round(info.get("duration") or 0) or None,
            "likes": info.get("like_count"), "comments": info.get("comment_count"),
            "views": info.get("view_count"), "caption": (info.get("description") or "").strip()}


def render_markdown(code: str, meta: dict, tr: dict | None, status: str = "done") -> str:
    stats = ", ".join(f"{k}: {meta[k]}" for k in ("duration", "views", "likes", "comments") if meta.get(k))
    head = (f"# @{meta['user']} — {meta['date'] or 'no date'} — {code}\n\n"
            f"- URL: {reel_url(code)}\n- Author: {meta['author']}\n"
            + (f"- Stats: {stats}\n" if stats else "")
            + (f"- Language: {tr['lang']} (whisper.cpp)\n" if tr else f"- Transcript: {status}\n"))
    cap = meta["caption"] or "(no caption)"
    body = f"\n## Caption\n\n{cap}\n"
    if tr:
        body += f"\n## Transcript\n\n{to_paragraphs(tr['segments']) or '(no speech recognised)'}\n"
    return head + body


def process_reel(url: str, args, model: Path, match: re.Pattern | None = None) -> tuple[str, dict, dict | None, str]:
    code = shortcode(url) or url
    with tempfile.TemporaryDirectory(prefix="igtr_") as tmp:
        info, media = fetch_audio(reel_url(code) if shortcode(url) else url, Path(tmp), args.cookies)
        meta = meta_of(info)
        if not meta["duration"]:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(media)], capture_output=True, text=True)
            meta["duration"] = round(float(r.stdout.strip() or 0)) or None
        if match and not match.search(meta["caption"]):
            return code, meta, None, "skipped"
        if not has_audio(media):
            return code, meta, None, "no_audio"
        tr = transcribe(media, model, args.lang, args.threads)
        if args.keep_media:
            dst = Path(args.keep_media).expanduser()
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(media, dst / media.name)
    status = "done" if tr["segments"] else "no_speech"
    return code, meta, tr, status


# ---------------------------------------------------------------- commands

def cmd_reel(args) -> int:
    check_tools()
    model = resolve_model(args.model)
    try:
        code, meta, tr, status = process_reel(args.url, args, model)
    except Blocked as e:
        print(f"Instagram blocked anonymous access: {e}\nRetry later, or pass --cookies.", file=sys.stderr)
        return 3
    except Unavailable as e:
        print(f"Reel unavailable: {e}", file=sys.stderr)
        return 2
    md = render_markdown(code, meta, tr, status)
    if args.out:
        write_atomic(Path(args.out).expanduser(), md)
        print(f"saved: {args.out} ({status})", file=sys.stderr)
    else:
        sys.stdout.write(md)
    return 0 if status == "done" else 2


def read_links(path: Path) -> list[str]:
    """Shortcodes in file order (txt with URLs anywhere, or JSON list); de-duplicated."""
    text = path.read_text(encoding="utf-8")
    codes = [m.group(1) for m in SHORTCODE_RE.finditer(text)]
    return list(dict.fromkeys(codes))


def cmd_batch(args) -> int:
    check_tools()
    model = resolve_model(args.model)
    out_dir = Path(args.out).expanduser() / re.sub(r"[^\w.-]+", "_", args.name.lstrip("@"))
    (out_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    pid_file = out_dir / "run.pid"
    if pid_file.exists() and pid_alive(int(pid_file.read_text() or 0)):
        log(f"another run is already active for this folder (pid {pid_file.read_text()})")
        return 1
    pid_file.write_text(str(os.getpid()))
    match = re.compile(args.match, re.I) if args.match else None
    try:
        listing = load_json(out_dir / "reels.json", {"user": args.name, "reels": []})
        known = set(listing["reels"])
        new = [c for c in read_links(Path(args.links).expanduser()) if c not in known]
        listing["reels"] += new  # keep first-seen order, append new links
        listing["updated"] = datetime.now().isoformat(timespec="seconds")
        write_atomic(out_dir / "reels.json", json.dumps(listing, ensure_ascii=False, indent=1))

        state_path = out_dir / "state.json"
        state = load_json(state_path, {})

        def needs(c: str) -> bool:
            s = state.get(c, {})
            if s.get("status") == "skipped" and (not match or match.search(s.get("caption", ""))):
                return True  # filter changed or removed: reconsider
            return s.get("status") not in FINAL and s.get("attempts", 0) < MAX_ERROR_ATTEMPTS

        todo = [c for c in listing["reels"] if needs(c)]
        if args.limit:
            todo = todo[:args.limit]
        log(f"@{args.name}: {len(listing['reels'])} reels ({len(new)} new), {len(todo)} to process"
            f" -> {out_dir} | model {model.name}")
        consecutive_errors = 0
        for i, code in enumerate(todo, 1):
            if i > 1:
                if (i - 1) % args.batch == 0:
                    pause = random.uniform(args.batch_pause_min, args.batch_pause_max) * 60
                    log(f"  batch pause {pause / 60:.0f} min")
                    time.sleep(pause)
                else:
                    time.sleep(random.uniform(args.min_delay, args.max_delay))
            prev = state.get(code, {})
            for attempt in range(len(BACKOFF_MINUTES) + 1):
                try:
                    _, meta, tr, status = process_reel(reel_url(code), args, model, match)
                    write_atomic(out_dir / "transcripts" / f"{code}.md", render_markdown(code, meta, tr, status))
                    entry = {"status": status, **{k: meta[k] for k in
                             ("date", "timestamp", "duration", "views", "likes", "caption")},
                             "lang": tr["lang"] if tr else "",
                             "words": sum(len(t.split()) for _, t in tr["segments"]) if tr else 0}
                    consecutive_errors = 0
                    break
                except Unavailable as e:
                    entry = {"status": "unavailable", "error": str(e)[:200]}
                    break
                except Blocked as e:
                    if attempt == len(BACKOFF_MINUTES):
                        log(f"STOP: still blocked after backoff ({e}). Progress saved; rerun later.")
                        build(out_dir)
                        return 3
                    wait = BACKOFF_MINUTES[attempt] * 60 * random.uniform(1.0, 1.2)
                    log(f"  BLOCKED ({str(e)[:80]}); backing off {wait / 60:.0f} min")
                    time.sleep(wait)
                except Exception as e:
                    consecutive_errors += 1
                    entry = {"status": "error", "error": f"{type(e).__name__}: {e}"[:300],
                             "attempts": prev.get("attempts", 0) + 1}
                    break
            entry["updated"] = datetime.now().isoformat(timespec="seconds")
            state[code] = {**prev, **entry}
            write_atomic(state_path, json.dumps(state, ensure_ascii=False, indent=1))
            log(f"[{i}/{len(todo)}] {code} {entry['status']} {entry.get('date', '')}"
                f" {entry.get('lang', '')} {entry.get('words', '')} {entry.get('error', '')}".rstrip())
            if consecutive_errors >= 5:
                log("STOP: 5 errors in a row (block or Instagram change). Rerun later.")
                build(out_dir)
                return 3
        build(out_dir)
        log("finished")
        print_status(out_dir)
        return 0
    finally:
        pid_file.unlink(missing_ok=True)


def build(out_dir: Path) -> None:
    """index.csv + ALL_TRANSCRIPTS.md, oldest reel first."""
    listing = load_json(out_dir / "reels.json", {"reels": []})
    state = load_json(out_dir / "state.json", {})
    codes = sorted(listing["reels"], key=lambda c: state.get(c, {}).get("timestamp") or 9e12)
    with open(out_dir / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n", "code", "date", "url", "duration_s", "views", "likes", "status", "lang",
                    "words", "caption_start"])
        for n, c in enumerate(codes, 1):
            s = state.get(c, {})
            w.writerow([n, c, s.get("date", ""), reel_url(c), s.get("duration") or "", s.get("views") or "",
                        s.get("likes") or "", s.get("status", "pending"), s.get("lang", ""),
                        s.get("words", ""), " ".join((s.get("caption") or "").split())[:120]])
    parts = [f"# @{listing.get('user', '')}: all reel transcripts\n\nOldest reel first.\n"]
    for c in codes:
        p = out_dir / "transcripts" / f"{c}.md"
        if p.exists() and state.get(c, {}).get("status") == "done":
            parts.append(p.read_text(encoding="utf-8").replace("# ", "## ", 1)
                         .replace("\n## Caption", "\n### Caption").replace("\n## Transcript", "\n### Transcript"))
    write_atomic(out_dir / "ALL_TRANSCRIPTS.md", "\n---\n\n".join(parts))


def print_status(out_dir: Path) -> None:
    listing = load_json(out_dir / "reels.json", {"reels": []})
    state = load_json(out_dir / "state.json", {})
    counts: dict[str, int] = {}
    for c in listing["reels"]:
        st = state.get(c, {}).get("status", "pending")
        counts[st] = counts.get(st, 0) + 1
    pid_file = out_dir / "run.pid"
    pid = int(pid_file.read_text() or 0) if pid_file.exists() else 0
    running = pid not in (0, os.getpid()) and pid_alive(pid)
    words = sum(s.get("words", 0) or 0 for s in state.values())
    print(f"@{listing.get('user', out_dir.name)}: {len(listing['reels'])} reels | "
          + ", ".join(f"{k}={n}" for k, n in sorted(counts.items()))
          + f" | {words} words | {'RUNNING' if running else 'not running'}")
    print(f"folder: {out_dir}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="medium", help="whisper.cpp model: small|medium|<path> (default medium)")
    p.add_argument("--lang", default="auto", help="spoken language, e.g. ru, uk, en (default auto)")
    p.add_argument("--threads", type=int, default=min(8, os.cpu_count() or 4))
    p.add_argument("--cookies", help="Netscape cookies.txt (opt-in, only a secondary account)")
    p.add_argument("--keep-media", metavar="DIR", help="also keep downloaded media files in DIR")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("reel", help="one reel -> Markdown on stdout")
    r.add_argument("url")
    r.add_argument("-o", "--out")
    r.set_defaults(func=cmd_reel)

    b = sub.add_parser("batch", help="many reels from a links file, resumable")
    b.add_argument("links", help="file with reel URLs (txt/json from collect_links.js)")
    b.add_argument("--name", required=True, help="profile username, used for the folder name")
    b.add_argument("-o", "--out", default=str(DEFAULT_OUT))
    b.add_argument("--match", help="regex on the caption: transcribe only matching reels")
    b.add_argument("--limit", type=int)
    b.add_argument("--min-delay", type=float, default=20)
    b.add_argument("--max-delay", type=float, default=60)
    b.add_argument("--batch", type=int, default=20)
    b.add_argument("--batch-pause-min", type=float, default=5)
    b.add_argument("--batch-pause-max", type=float, default=10)
    b.set_defaults(func=cmd_batch)

    s = sub.add_parser("status", help="progress of a batch folder")
    s.add_argument("dir")
    s.set_defaults(func=lambda a: (print_status(Path(a.dir).expanduser()), 0)[1])
    bl = sub.add_parser("build", help="rebuild index.csv and ALL_TRANSCRIPTS.md")
    bl.add_argument("dir")
    bl.set_defaults(func=lambda a: (build(Path(a.dir).expanduser()), print_status(Path(a.dir).expanduser()), 0)[2])

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
