# Archived: the variability runs made before the study was designed

Superseded on 2026-10-23. Kept because two results in the paper rest on it, and because
the reason it was superseded is itself worth recording.

## What is here

| | |
|---|---|
`manifest.json` | **61 runs** — every field each run recorded: model, temperature, commit, prompt fingerprint, core hashes, counts, grounding, wall time |
`suntola-runs/`, `aleskovskii-runs/` | the per-run extraction output, 2.1 MB, gitignored then and now |
`suntola-README.txt`, `aleskovskii-README.txt` | the source-document notes that sat beside those folders |

The 61 runs are two different experiments:

- **40 runs** of `qwen3.5-397b-a17b` — the variability study (`findings-brief.md` §1)
- **21 runs** across five other models — the model comparison (`findings-brief.md` §5):
  Fable 5.1 (9), Mistral Medium 3.5 (5), qwen3.8-27b (5), Llama 3.1 8B (1), GLM 5.3
  Flash (1)

## Why it was superseded

**It was not designed; it accumulated.** The 40 runs were taken at whatever commit the
prompt happened to be at while the prompt was still being written, then pooled. They span
**seven prompt versions** over **two documents** — and `a155c27` is the completeness-rules
commit, so some runs predate the current prompt and some follow it.

`summarise.py` groups on the prompt fingerprint and so never pooled two prompts into one
block. But the headline "40 runs, 9 conditions" described nine accidents rather than a
design, the cells held between 1 and 10 runs each, and only one temperature had a cell
with five runs in it. Nothing was wrong with the runs; the *design* was retrospective.

## What still stands, and should still be cited from here

The result in `findings-brief.md` §1 does not depend on the design being balanced, because
it is a statement about what varied and what did not **within** every condition:

- every property the prompt governs held at **100% with zero variation** — events carrying
  a date, citations carrying a page, citations carrying a quote, events with a
  participant, ids matching the pattern
- every property it leaves unstated varied widely — entity count CV **13.6–48.8%**, person
  count **28.6–62.1%**

The model comparison in §5 also stands: five of six models produced nothing usable, and
that is a count of attempts rather than a controlled comparison, which is how it is
reported.

**What should NOT be cited from here:** any comparison between conditions. The per-cell n
varies from 1 to 10, and no difference reaches significance — F(4,4) needs ≈9.6 and the
largest ratio observed is 5.0.

## What replaced it

`../run_variability.py`, rebuilt as a designed experiment: **ten documents** (a short and a
long one in each of the five domains with the most subjects), **two temperatures** (0.0 and
0.2, the second being what the pipeline ships with), **five runs each**, one prompt, one
model — 100 runs. Output nests under `runs/<model>/t<temperature>/<document>/` so a repeat
with another model stays separable.

The question it asks is narrower: hold everything constant and ask whether repeated
extractions of the same document converge.
