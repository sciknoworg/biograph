# Run-to-run variability of the selected extraction model

**10 runs per document × 2 documents = 20 runs** of `qwen3.5-397b-a17b` over the same two
sources the 2026-09-04 model comparison used.

## Why this is a separate study

The comparison in `../README.md` asked *which model*. This asks *how much does one model vary
between draws* — which is a different question, and the one the paper actually needs before it
reports any single extraction as a result. Extraction samples at **temperature 0.2**, so one
run is a draw, not a score.

It also does **not** recover the 2026-09-04 suffix→model mapping. That evidence stays
uncitable per-model; see `../README.md`. Using the same two documents means the two studies
become comparable if the mapping is ever recovered.

## The one thing this study does differently

**Every run records what produced it, before the next run starts.** `manifest.json` holds, per
run: model, `base_url`, temperature, git commit, the SHA-256 of all eight extraction-core
files, timestamp, wall time, exit code, whether it validated, output counts, and the grounding
numbers. The manifest is rewritten after each run rather than at the end, so an interrupted
study still has a complete record of what it did.

That is the entire lesson of the earlier comparison: 18 runs on disk, a defensible selection
criterion, and no way to say which row is which model.

## What is measured, and why counts are the weakest of it

| per run | why |
|---|---|
| entity / event / relation / source counts | cheap, and what `../README.md`'s existing table reports |
| **validated** (exit 0) | a draw that fails schema validation is a different outcome from a small one |
| **quotes verbatim / checked** | the grounding check, per draw — whether faithfulness itself varies |
| **entity names present / checked** | the second grounding measure |
| wall seconds | cost variance |

`../README.md` says it plainly: *size is not quality*, and its two largest outputs were the
rejected ones. So spread in counts is the least interesting number here. **Spread in the
grounding rate is the interesting one** — if faithfulness is stable across draws while counts
move, that is a much stronger claim about the method than any single run's numbers.

## Isolation

Runs execute in a **hash-verified throwaway sandbox**, never in the repository.
`build_site.py` derives its root from its own `__file__`, so running in place would write 20
fake subjects into `subjects/` — exactly the accident `../README.md` records, where 170 test
entities began hijacking the pipeline's name resolution. The sandbox's core is hashed before
the study and re-verified after; a divergence exits 2.

Between runs the sandbox subject is deleted, because reading a subject merges every document
folder under it — a leftover would union two draws into one graph.

## Invocation

```bash
python paper_evidence/variability/run_variability.py --dry-run     # plan, no model call
python paper_evidence/variability/run_variability.py --runs 10
python paper_evidence/variability/run_variability.py --runs 1 --document suntola
```

`--keep-rejected` is passed on every call: without it a scope refusal deletes the source PDF,
and these two PDFs are the project's own founding documents. `--strict-scope` is deliberately
**not** passed, matching how the 2026-09-04 runs were invoked. Credentials come from
`BIOGRAPH_MODEL` / `BIOGRAPH_BASE_URL` / `BIOGRAPH_API_KEY` and never reach a command line.

Runs are additive: the script reads `manifest.json`, continues numbering from what is already
recorded, and can be re-run to extend the study.

## Layout

```
variability/
  manifest.json          the mapping and every per-run measurement
  suntola/run_01 .. run_10
  aleskovskii/run_01 .. run_10
```

Each `run_NN/` holds that draw's `entities.json`, `events.json`, `relations.json`,
`sources.json` and `subject.json`. **Nothing about which model produced a run is encoded in
its folder name** — that lives only in `manifest.json`, keyed by document and run number.

## Status

Folders prepared, driver written and dry-run checked. **No runs recorded yet** —
`manifest.json` does not exist until the first run completes.
