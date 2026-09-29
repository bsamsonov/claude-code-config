# Research subagent protocol (economy mode)

Instructions for a (Sonnet) subagent assigned one or several related sections. The main
agent passes a reference to this file instead of duplicating the protocol in every
prompt (saving input tokens on every spawn).

The subagent receives: a list of sections (1-3 related ones), and for each — the topic,
concrete questions and the path to the output file `<NN_section.md>`.

---

## START — do this first

For every assigned section check `<path>/.work/<NN_section>/state.json`:

- **EXISTS** → a restart after an interruption.
  Read `state.json` → take `sections_remaining`.
  Read the already written `<NN_section.md>` — the finished H2s are there.
  Continue from the first section in `sections_remaining`.
- **DOES NOT EXIST** → a new run.
  Derive the H2 sections from the questions in the prompt (1 question = 1 H2).
  Create `state.json` and initialise the output file:
  ```bash
  mkdir -p "<path>/.work/<NN_section>"
  cat > "<path>/.work/<NN_section>/state.json" << 'EOF'
  {"section":"<NN_section>","status":"in_progress",
   "sections_done":[],"sections_remaining":["h2_1","h2_2"],
   "last_updated":"<ISO timestamp>"}
  EOF
  printf -- "**Status:** In progress\n\n" > "<path>/<NN_section.md>"
  ```

---

## LOOP — for every H2 section

a. **Smart fetch (quality rule):**
   1. WebSearch (1-2 queries) on the section topic → a list of candidates with snippets.
   2. From the snippets **select the 1-3 best sources** (official documentation, recent
      articles from the last 1-2 years, detailed write-ups) — don't fetch blindly.
   3. WebFetch the selected URLs with a **narrow extraction request**: ask for exactly the
      facts/numbers/details on the section topic, not a dump of the whole page.
   Snippets are for *selecting*, not a substitute for reading the sources — the depth of
   the section must not suffer.
b. Write the H2 section and append it to the output file right away (1 Bash call):
   ```bash
   cat >> "<path>/<NN_section.md>" << 'EOF'
   ## Section title
   <content>
   EOF
   ```
c. Update `state.json` (1 Bash call, overwrite without Read):
   ```bash
   cat > "<path>/.work/<NN_section>/state.json" << 'EOF'
   {"section":"<NN_section>","status":"in_progress",
    "sections_done":["h2_1"],"sections_remaining":["h2_2"],
    "last_updated":"<ISO timestamp>"}
   EOF
   ```
d. Move on to the next H2.

With several assigned sections — after finishing one, move to the next with the same
loop. Context accumulated on a related topic improves coherence; but if the context is
clearly bloated (>2-3 sections), finish and return control to the main agent.

---

## FINISH — for every section

1. Append `## Sources` to the output file (`bash cat >>`).
2. Replace the status (1 Bash call):
   ```bash
   sed -i 's/\*\*Status:\*\* In progress/**Status:** Done/' "<path>/<NN_section.md>"
   ```
3. Mark the section done:
   ```bash
   cat > "<path>/.work/<NN_section>/state.json" << 'EOF'
   {"section":"<NN_section>","status":"done","last_updated":"<ISO timestamp>"}
   EOF
   ```

---

## RETURN TO THE MAIN AGENT — a rich extract (quality rule)

The full text of the sections is **already on disk** — don't retell it in the answer.
Return a structured ~300-500-word extract per section:

```
### <NN_section> — extract
- Key facts and numbers: ...
- Contradictions between sources / disputed points: ...
- Strong conclusions: ...
- What remained open / was not found: ...
- Best sources (2-3 URLs): ...
```

This extract is the material for the final synthesis. It must be rich enough for the
main agent to synthesise conclusions **without re-reading the full section**; if it
turns out to be insufficient on some topic, the main agent may read the full
`<NN_section.md>` via Read.

---

## State-keeping rules (resume)

- First action — check `.work/<NN_section>/state.json`.
- Checkpoint after every H2: append the H2 to the markdown + overwrite `state.json` (no Read).
- Content is written into the output markdown as you go, not synthesised at the end.
- `state.json` is always overwritten entirely via `cat >`.
- A minimal thinking budget is fine (comparing sources, resolving discrepancies), but no
  extended reasoning — this is Sonnet work, not Opus.
