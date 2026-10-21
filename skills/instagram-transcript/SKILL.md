---
name: instagram-transcript
description: |
  Gets transcripts of Instagram Reels for free: no API keys, no paid services. Audio is
  fetched anonymously with yt-dlp and transcribed by a LOCAL whisper.cpp
  (default ~/tools/whisper.cpp; never install another Whisper). Works for one reel
  ("what is this reel about?") or for all reels of a profile (bulk, slow and polite,
  runs in the background, resumable); the list of reels is collected in the user's own
  browser with a JS snippet, because Instagram does not list profiles without login.
  Use when the user sends an instagram.com/reel/ or /p/ link and asks what it is about,
  to summarize or transcribe it; or asks to download/transcribe all reels of an
  Instagram author for later analysis.
  Triggers: "о чём этот рилс", "транскрипт рилса", "что в этом ролике инстаграм",
  "скачай все ролики из инстаграма", "все рилсы автора", "транскрипты инстаграм",
  "проанализируй инстаграм-блогера", "instagram transcript", "transcribe this reel",
  "all reels of this profile".
---

# Instagram Reels transcripts

Script: `scripts/ig_transcript.py` (self-contained `uv` script, only dependency
`yt-dlp`, installs itself). Requires `uv`, `ffmpeg` and an existing
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) build:
`~/tools/whisper.cpp/build/bin/whisper-cli`, models in `~/tools/whisper.cpp/models/`
(`ggml-medium.bin` default, `ggml-small.bin` faster). Other locations: set
`IG_WHISPER_CLI` and `IG_WHISPER_MODELS`. Do NOT install faster-whisper,
openai-whisper or download new models unless the user explicitly asks.

```bash
IG=~/.claude/skills/instagram-transcript/scripts/ig_transcript.py
```

Global options go BEFORE the subcommand: `--model small|medium|<path>`,
`--lang ru|uk|en|auto` (default auto), `--threads N` (default 8),
`--cookies FILE`, `--keep-media DIR`.

## Mode 1: one reel

```bash
$IG reel "<instagram reel url>"            # Markdown: author, date, stats, caption, transcript
$IG reel "<url>" -o /path/file.md
```

~20 s per reel on CPU. Exit codes: `2` no audio / no speech / unavailable (caption is still
printed: many reels are music + on-screen text, then the caption is the content),
`3` Instagram blocked anonymous access (retry in an hour).
Then answer in the user's language: gist, key points with `[mm:ss]`, practical takeaways.

## Mode 2: all reels of a profile

**Step 1. Collect links in the user's browser** (the only step that needs login; it is
ordinary browsing, so no account risk). Tell the user:
1. Open `https://www.instagram.com/<username>/reels/` while logged in.
2. F12 → Console (Chrome may require typing `allow pasting` first).
3. Paste the contents of `~/.claude/skills/instagram-transcript/scripts/collect_links.js`
   (print it with `cat` or point to the path), Enter, leave the tab alone.
4. It scrolls to the end and saves `~/Downloads/<username>_reels.txt`.
For a very large profile it can be re-run; links are merged, duplicates ignored.
Any text with reel URLs also works as input (copied links, a JSON export).

**Step 2. Launch the batch detached** (survives the end of the session):
```bash
mkdir -p ~/instagram_transcripts
setsid nohup $IG batch ~/Downloads/<username>_reels.txt --name <username> \
  >> ~/instagram_transcripts/<username>.log 2>&1 < /dev/null &
```
After ~15 s read the log: first line shows reel count and the folder;
`<folder>/run.pid` holds the worker PID. Start a background waiter (`run_in_background`):
`while kill -0 <PID> 2>/dev/null; do sleep 300; done; tail -5 <log>`.
Tell the user: folder, number of reels, ETA, how to check progress, that the session can be closed.

Polite by design: one page request per reel, random 20-60 s pause, 5-10 min pause every
20 reels, on a login wall backoff 30/60/120 min then a clean stop (exit 3; rerun later,
progress is kept). Rough time **~1.5 min per reel** (200 reels ≈ 5 h).
Do not lower delays or run two batches in parallel unless the user explicitly asks.

Options: `--match REGEX` (transcribe only reels whose caption matches; others become
`skipped` and are reconsidered when run without/with another filter), `--limit N`,
`--min-delay/--max-delay`, `--batch`, `--batch-pause-min/-max`, `-o` base folder.
`--cookies` (Netscape cookies.txt) only if anonymous access is blocked persistently and
only with a secondary account: it puts that account at risk. Never cookies of the main one.

Progress: `$IG status ~/instagram_transcripts/<username>`; `$IG build <dir>` rebuilds files.

Result in `~/instagram_transcripts/<username>/`:
- `transcripts/<code>.md` — one file per reel (caption + transcript);
- `index.csv` — n, code, date, url, duration, views, likes, status, lang, words, caption_start (oldest first);
- `ALL_TRANSCRIPTS.md` — all `done` reels, oldest first;
- `reels.json`, `state.json` — links and resume state.
Statuses: `done`, `no_audio`, `no_speech`, `unavailable`, `skipped` are final;
`error` is retried on the next run (up to 3 times).

## Analysing a profile by topic

Reels are short (100-300 words), so even 300 reels fit in ~60-90k words. Workflow:
1. Pick relevant reels: `index.csv` captions + `grep -il` over `transcripts/` with topic
   keywords in the author's language (word stems catch all inflections, e.g. for job
   search in Russian: резюме, собеседован, вакан, оффер, зарплат).
   Don't trust captions alone: talking reels often have hashtag-only captions.
2. Under ~40 relevant reels: read them directly. More: split into batches and give each
   batch to a subagent (`model: sonnet`) with the same extraction brief, then merge.
3. Synthesis: recurring techniques, concrete scripts/templates, frequency of each
   advice, contradictions, and what applies to the user's situation, with reel links.
Write the analysis to a Markdown file in the user's working folder, not only to chat.

Whisper caveats: medium model handles RU/UK/EN well, names and English terms inside
Russian speech may be garbled — check against the caption. Phantom lines on music
("Субтитры сделал...", `[Музыка]`) are filtered automatically.
