# Run-to-run convergence of one extraction model, held constant

**10 documents x 2 temperatures x 5 runs = 100 runs.** One prompt, one model, nothing
varying but the sampling and two deliberate axes.

## The design

| axis | values |
|---|---|
| document | a **short** and a **long** one in each of the five domains with the most subjects |
| temperature | **0.0** and **0.2** -- greedy decoding against the setting the pipeline ships with |
| runs | **5** per document per temperature |
| model, prompt, token budget | **fixed** |

| domain | short | long |
|---|---|---|
| physics | `dalembert` 3.7k | `helmert` 88k |
| life_sciences_and_medicine | `pacini` 2.6k | `g_borelli` 87k |
| chemistry | `vigneaud` 5.1k | `djerassi` 83k |
| materials_science | `ito_2` 2.0k | `hooke` 83k |
| mathematics_and_computation | `bellman` 4.4k | `galton` 86k |

**Length is the axis worth paying for.** WikiBio showed output volume is least stable on
the longest documents -- between two runs its two longest moved -54% and -65% while recall
moved 0.025 -- and this measures that directly with a repeat design instead of inferring
it. The long end stops near 88,000 characters because that is the longest length this
project has *demonstrated* fits a 64,000-token reply (de Gaulle, 88,469, in benchmark 3).
The corpus holds documents to 200,000 and they were deliberately not chosen: at twice a
proven length a failure costs the run and says nothing about variability.

**Temperature 0.0 is not determinism.** The served model is a mixture-of-experts whose
routing depends on request batching, so greedy decoding still varies between runs -- which
is why it gets five runs rather than one.

## What the earlier runs were, and where they went

An earlier set of 61 runs is in `archive-2026-10/`, with a README explaining what still
stands in it. In short: it was not designed, it accumulated across **seven prompt
versions** over two documents, so "40 runs, 9 conditions" described nine accidents. Its
§1 result -- governed properties at 100%, ungoverned ones at 13.6-48.8% CV -- does not
depend on the design being balanced and is still citable. Comparisons between its
conditions are not.

Suntola and Aleskovskii, the two documents it used, remain selectable here with
`--document` but are out of the default set: they are the project's founding documents,
hand-extracted before the automated path existed, and including one would give materials
science three documents.

## Why this is a separate study

The comparison in `../README.md` asked *which model*. This asks *do repeated extractions of
one document converge* — a different question, and the one the paper needs before it reports
any single extraction as a result. A single run is one sample, not a score.

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
| **validated** (exit 0) | a run that fails schema validation is a different outcome from a small one |
| **quotes verbatim / checked** | the grounding check, per run — whether faithfulness itself varies |
| **entity names present / checked** | the second grounding measure |
| wall seconds | cost variance |

`../README.md` says it plainly: *size is not quality*, and its two largest outputs were the
rejected ones. So spread in counts is the least interesting number here. **Spread in the
grounding rate is the interesting one** — if faithfulness is stable across runs while counts
move, that is a much stronger claim about the method than any single run's numbers.

## Isolation

Runs execute in a **hash-verified throwaway sandbox**, never in the repository.
`build_site.py` derives its root from its own `__file__`, so running in place would write these
runs as fake subjects into `subjects/` — exactly the accident `../README.md` records, where 170 test
entities began hijacking the pipeline's name resolution. The sandbox's core is hashed before
the study and re-verified after; a divergence exits 2.

Between runs the sandbox subject is deleted, because reading a subject merges every document
folder under it — a leftover would union two runs into one graph.

## Invocation

```bash
python paper_evidence/variability/run_variability.py --dry-run     # plan, no model call
python paper_evidence/variability/run_variability.py --runs 5
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
  suntola/run_01 .. run_05
  aleskovskii/run_01 .. run_05
```

Each `run_NN/` holds that run's `entities.json`, `events.json`, `relations.json`,
`sources.json` and `subject.json`. **Nothing about which model produced a run is encoded in
its folder name** — that lives only in `manifest.json`, keyed by document and run number.

## Sample size

**5 runs per document.** Enough to show whether spread exists and roughly how wide it is;
**not** enough for a confidence interval, and the write-up should report range and median
rather than a mean with error bars. Runs are additive — re-running the script continues the
numbering, so the study can be extended later without redoing anything.

## Status

Suntola: 5 of 5 recorded, extraction core verified unchanged against the repository.
Aleskovskii: running.
