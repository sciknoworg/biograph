# Benchmark 3 — PMOA-TTS

> Weiss et al., *PMOA-TTS: Introducing the PubMed Open Access Textual Time Series
> Corpus* (arXiv:2505.20323), and the relative-timeline framework it evaluates
> (arXiv:2504.12350). Reference implementation: `jcweiss2/pmoa_tts`.

Single document → `(event, time)` tuples. The same architecture shape as biograph, an
entirely different subject matter — which makes it the closest generalization test of
the five, and the reason it was built first: **its metric never compares categories**,
so this adapter exercises the whole input/output path with no taxonomy mapping to debug
at the same time. Anything that breaks here is plumbing.

## The metric, as published

Reimplemented in `score.py` from the authors' R and Python code, not re-invented. Each
function names the reference file it follows.

| | |
|---|---|
| embeddings | `pritamdeka/S-PubMedBert-MS-MARCO`, mean-pooled, L2-normalized (`distance_helper.py`) |
| distance | cosine **distance** — `pairwise_distances(metric='cosine')` |
| match | `error.rate < 0.1` (`compare_with_manual.R`) |
| pairing | `recursive_match()` — greedy, one-to-one |
| event recall | matched gold events / gold events |
| concordance | `1 - Cindex(pred, Surv(time, uncensored))` over matched pairs |
| AULTC | area under the empirical CDF of `log(1 + |Δt|)`, unmatched charged `max+1` |
| published | O1-preview: recall 0.80, concordance 0.95; Llama-3.3-70B median c 0.96 |

Worth stating plainly: both papers say "cosine similarity threshold of 0.1", which read
as a *similarity* would match almost any two clinical findings. The code settles it —
`distance_helper.py` computes a cosine **distance** and the R filter keeps
`error.rate < threshold`. `--matcher lev` offers the reference's own non-embedding
fallback (normalized Levenshtein at 0.6) so the scorer runs without torch.

## The two transformations, and why they are disclosed

Both are recorded in `BenchmarkDoc.transform`, surfaced by `--dry-run`, and printed in
every `ScoreReport`.

**Framing** (`--framing none|minimal|biographical`). `SCOPE_DEFINITION` is in the prompt
on every call, with or without `--strict-scope`, and asks for a biographical essay about
a life intertwined with a technology's development. A clinical case report is a
single-person life narrative but not that, and a `fits: false` verdict writes nothing at
all. The adapter does not try to defeat the gate — it offers three framings and the
runner records the verdict for every document.

> **Measured, 2026-09-17: 9 of 9 refused, invariant to framing.** See
> [the pilot writeup](../../docs/pmoa-tts-scope-pilot.md). The refusals name two
> blockers, and the structural one is that case reports have **no named subject** —
> de-identification is a property of the genre, so no framing can supply one without
> fabricating it. Benchmark 3 as specified measures the admission policy, not the
> extraction engine, and returns 0.00 on every metric.

**Anchor** (`--no-anchor` to disable). Every event needs an ISO date; case reports carry
relative times only, and PMOA-TTS timestamps them in hours from presentation. With no
absolute date in the text, a faithful extractor should produce *nothing* — the rules
forbid inventing one. So the input adapter can prepend one line stating the presentation
date, adding no clinical content, and the output adapter converts the resulting dates
back to hours. The difference between anchored and unanchored measures how much of the
difficulty here is the date requirement rather than the extraction.

## The resolution floor

biograph's finest precision is one **day**; PMOA-TTS's is one **hour**. Events placed on
the same day are tied in the prediction even when the gold orders them hours apart. Ties
score 0.5 (Harrell's convention) and `tied_pair_rate` reports how many comparable pairs
were affected — because a concordance depressed by the schema's resolution floor is a
different finding from one depressed by wrong ordering, and the table has to tell them
apart.

Imprecise dates project to the **midpoint** of `[sort_start, sort_end]`, not the start:
a `range` or `decade` date asserts only that the event falls inside its bounds, and
taking the earliest would bias every imprecise event toward the past. Each one is
recorded in `Prediction.lossy`.

## What the release actually contains

Checked against the files, not the paper. Two things differ from what the paper implies,
and both change the experiment.

**There is no document text, in any split.** The fields are `pmc_id`, `case_report_id`,
`textual_timeseries`, `demographics`, `diagnoses`, `death_info`. So the input side has to
be rebuilt from PubMed Central by `case_report_id` — `pmc.py` does that, reproducing the
authors' own boundary from `make_tts/get_pmoa_body.sh`:

```sh
awk '/==== Body/{a=1;next}/==== Ref/{a=0}a'
```

Body only: no title, no abstract, no references. Feeding biograph the abstract as well
would hand it a summary of the whole case and inflate recall against timelines that were
never extracted from one. Articles outside the OA subset are counted as `no_oa_text`
attrition, never substituted.

**There are no human reference timelines.** `case_study_100` is manually reviewed for
*single-case validity* — 88 of 100 candidates confirmed to be single-patient reports —
not for timeline correctness. Its `textual_timeseries` is LLaMA 3.3 output like every
other split. The clinician-curated set behind the published **0.80 recall / 0.95
concordance** is in neither the HuggingFace release nor the GitHub repo, which ships the
evaluation code and expects you to point it at your own manual directory.

So a run against this corpus measures **agreement with a published LLM annotation**, not
accuracy against human gold, and it is **not comparable to the published numbers**. The
paper must say so.

### The reference band that *can* be reproduced

Both released annotators — LLaMA 3.3 and DeepSeek-R1 — cover the same 24,746 cases.
Scoring one against the other with this same metric gives the band a competent system
lands in, using only released data and no model calls:

```bash
python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --ceiling
```

They disagree substantially — 17 vs 28 events on the same case, and on timestamps
(−72 h vs −24 h for the same symptom onset). Report biograph against this band, not
against 0.80/0.95.

## Two structural recall floors, measured not excused

**Demographics are annotated as events.** `'53 years old' | 0`, `'male' | 0` head most
gold timelines. These are attributes, not dateable occurrences, and biograph will never
emit them — `schema/README.md` is explicit that "an event is a dateable occurrence, not a
fact or a description". Measured over all 88 cases in `case_study_100`: **156 of 4,862
gold rows (3.2%)**. Real, bounded, and reported as `diagnostic_attribute_share_of_gold`
rather than guessed at — it is not the main story, and the paper should not imply it is.

**Granularity.** Gold timelines carry a median of 52 events per case (max 138). biograph's
own corpus averages ~14 events per subject. The two systems are not aiming at the same
resolution, and recall will reflect that before any extraction quality is measured.

## Corpus

Not vendored — **CC BY-NC-SA 4.0** (non-commercial, share-alike). Downloaded locally for
testing and gitignored. Case report text comes separately from PMC Open Access under each
article's own licence.

```bash
mkdir -p experiments/corpora/pmoa_tts
for f in case_study_100 case_study_25k_L33 case_study_25k_DSR1; do
  curl -sL -o experiments/corpora/pmoa_tts/$f.parquet \
    https://huggingface.co/datasets/snoroozi/pmoa-tts/resolve/main/data/$f-00000-of-00001.parquet
done
```

## Run

```bash
python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --ceiling
python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --limit 3 --dry-run
python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --limit 25 --framing minimal
python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --limit 25 --framing none
```
