# Model comparison evidence

Kept for the WWW paper submission: the raw outputs behind the choice of
extraction model.

Moved here out of `subjects/` and `dist/` on 2026-09-05 —
the pipeline treats everything under `subjects/` as a real subject, so these
were contributing 170 person entities to Mode 2's search seeds and hijacking
name lookups (`Tuomo Suntola` resolved to `suntola_test_g` rather than
`suntola`). Nothing here is deleted or altered; it is only out of the
pipeline's path.

*The paper briefs also live in this folder but are gitignored — they are
writing artifacts, not repository content. See the note in `.gitignore`.*

## What this is

**Six extraction models, 9 runs per document, 18 runs total** -- not nine models.
Three of the six (`a`, `c`, `d`) were run twice, as `a2`/`c2`/`d2`, to check
run-to-run stability. Each `subjects/<name>_test_<suffix>/` is one run's output
for the **same** source document, so the runs are directly comparable:

| Source subject | Document |
|---|---|
| `suntola_test_*` | Puurunen 2014, *A Short History of Atomic Layer Deposition: Tuomo Suntola's Atomic Layer Epitaxy* (doi:10.1002/cvde.201402012) |
| `aleskovskii_test_*` | the Aleskovskii source PDF under `data/` |

`dist/` holds the rendered HTML for the runs that were built.

## ⚠ The model mapping is not recorded anywhere

**This needs filling in before the paper can cite any of it.** Nothing on disk
identifies which model produced which suffix — not `subject.json`, not
`sources.json`, not `pipeline_log.txt` (these runs were invoked by hand via
`build_site.py`, not through `run_pipeline.py`, so they never reached that
log). The suffix→model mapping currently exists only in the chat history of
the session that produced them.

| Model | Runs | Identified? | Provider |
|---|---|---|---|
| A | `a`, `a2` | **no** | KISSKI |
| C | `c`, `c2` | **no** | KISSKI |
| D | `d`, `d2` | **no** | KISSKI |
| E | `e` | **no** | KISSKI |
| G | `g` | **no** | KISSKI |
| — | `fable` | yes: `claude-fable-5.1` | OpenRouter |

**Five of the six models are unidentified, including the one that was
selected.** `qwen3.5-397b-a17b` is one of A, C, D, E or G and nothing on disk
says which.

Two further gaps, for anyone tempted to treat this as a complete comparison:
the lettering **skips `b` and `f`**, so two runs were probably made and not
kept; and only **8 of the 18 runs were rendered** to `dist/`, so that folder is
not a full set either.

All 18 ran on **2026-09-04**, in two phases -- `a`/`c`/`d`/`fable` between 12:39
and 14:24, then `a2`/`c2`/`d2`/`e`/`g` between 16:03 and 16:57. That ordering is
an independent check on any reconstruction of the mapping.

**The selected model was `qwen3.5-397b-a17b` (KISSKI)** — chosen as the only
candidate with zero factual hallucinations across repeated runs. See
`PIPELINE_GUIDE.md` for the standing configuration. Which suffix corresponds
to it is part of what needs recording above.

### What this evidence can and cannot support

**Can:** that six LLMs were compared on the same two documents, three of them
with repeat runs; that the selected model was the only one with zero factual
hallucinations; and that the two largest outputs were rejected for inventing
content, so more extraction was worse extraction.

**Cannot:** any table, chart or sentence that names which model produced which
row -- including the winner's own row. Until the mapping is recovered or the
comparison is re-run with it recorded, nothing here is citable per-model.

A separate, clean variance study of the selected model lives in
`variability/` -- see its README. It does not recover this mapping; it measures
run-to-run spread for `qwen3.5-397b-a17b` alone.

## Output sizes

Counts only — size is not quality, and the actual selection was made on
factual accuracy (hallucination checks against the source), not volume. The
two largest here are the ones that were *rejected* for inventing content.

| run | entities | events | relations | sources |
|------------------------|---------:|-------:|----------:|--------:|
| aleskovskii_test_a     |       10 |     19 |        10 |       1 |
| aleskovskii_test_a2    |       11 |     23 |        12 |       1 |
| aleskovskii_test_c     |       15 |     18 |        15 |       1 |
| aleskovskii_test_c2    |        9 |     15 |         9 |       1 |
| aleskovskii_test_d     |       10 |     17 |        11 |       1 |
| aleskovskii_test_d2    |       21 |     19 |        11 |       1 |
| aleskovskii_test_e     |        6 |      7 |         4 |       1 |
| aleskovskii_test_fable |       70 |     74 |        71 |       1 |
| aleskovskii_test_g     |       55 |     60 |        56 |       1 |
| suntola_test_a         |       35 |     26 |        21 |       1 |
| suntola_test_a2        |       25 |     30 |        14 |       1 |
| suntola_test_c         |       35 |     28 |        20 |       1 |
| suntola_test_c2        |       46 |     29 |        18 |       1 |
| suntola_test_d         |       19 |     22 |        14 |       1 |
| suntola_test_d2        |       37 |     18 |        32 |       1 |
| suntola_test_e         |       13 |     16 |         7 |       1 |
| suntola_test_fable     |      123 |     77 |        90 |       1 |
| suntola_test_g         |       91 |     61 |        74 |       1 |

## Reproducing a run

```
python scripts/build_site.py <slug> --pdf <source.pdf> --name "<Full Name>" --model <model>
```

Credentials come from `BIOGRAPH_*` environment variables; never pass a key on
the command line (it lands in shell history and in `run_subprocess`'s log).
