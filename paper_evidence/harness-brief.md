# The benchmark harness — condensed brief for the WWW paper's Evaluation section

Companion to `approach-brief.md`. Self-contained: assumes no access to the repository. Every
figure re-derived at commit `41440f5` (2026-10-02). Every figure carries its denominator. What
has not been run says so.

---

## 1. The question the harness exists to answer

Five external benchmarks, none designed for this project, scored against the extraction pipeline
**exactly as it ships**. The claim under test is not "our extractor is good" but "this
extractor, unmodified, can be measured against work it was never built for, and the cost of
translating between its vocabulary and theirs can be stated as a number rather than a caveat."

Scale: **4,782 lines across `experiments/`, of which 809 are self-checks — 138 assertions in 25
test functions, none of which calls a model or touches the network.**

## 2. The integrity mechanism — the methodological selling point

"We did not modify the extraction core" is a claim a reviewer cannot verify by reading, so it is
made mechanical:

- Every run copies `build_site.py`, the five JSON Schemas and `frontend/` into a **throwaway
  sandbox**, records the **SHA-256 of each file plus the git commit** in `manifest.json`, and
  **re-verifies every hash after the run**. A divergence exits 2 — it fails the run, it is not a
  footnote.
- The harness **imports nothing** from the pipeline. It only ever shells out to the CLI.
- `git_dirty_core()` additionally reports whether any core file has uncommitted changes, because
  a paper cites a commit and a dirty file means the cited commit is not what ran.

The sandbox is not ceremony. `build_site.py` derives its root from its own `__file__`, so
`subjects/`, `data/` and `dist/` are always siblings of `scripts/` with no flag to redirect
them. Running benchmarks in place would write thousands of fake people into the corpus — an
accident that already happened once, when 170 test entities leaked into name resolution and
"Tuomo Suntola" began resolving to `suntola_test_g`.

Four of the 138 self-checks cover this directly, including one that tampers with the sandbox
copy and asserts that verification catches it.

**One deliberate exception.** Benchmark 5 runs without a sandbox, because `--check-grounding`
writes nothing and the corpus is the *subject* of that measurement rather than somewhere to put
its output. The core's SHA-256 and the commit are still recorded.

## 3. The adapter contract

Each benchmark implements four methods, and nothing benchmark-specific lives inside the pipeline:

```
native format → [load]    → .txt → [build_site.py --text] →
                  entities/events/relations/sources.json →
                [project] → the benchmark's label space → [score] → its own published metric
```

| method | role |
|---|---|
| `load(data_root, limit)` | **input adapter** — native format to text |
| `project(doc, extraction)` | **output adapter** — biograph's fixed vocabulary to their labels |
| `score(pairs)` | **scorer** — the benchmark's own published metric, not a new one |
| `coverage()` | that benchmark's column of the vocabulary coverage matrix |

**Three fields carry the honesty, and they are the part worth naming in the paper:**

- **`Prediction.unmapped`** — every extracted item with no expression in the target label space,
  recorded with a reason. Taxonomy loss becomes a measured per-run quantity instead of a
  sentence in a limitations section.
- **`Prediction.lossy`** — projections that succeeded while losing something nameable: a
  three-way kinship collapse onto `family_of`, a year-precision date standing in for an
  hour-resolution timestamp.
- **`ScoreReport.not_applicable`** — target labels the schema *cannot* represent, named and
  **excluded from every macro-average**. Scoring them 0 would understate the pipeline for a
  label it was never asked to produce; scoring them at all would claim a capability the data
  model lacks. Neither is defensible, so they are named.

## 4. How the pipeline is invoked — fixed once, for every benchmark

```
python <sandbox>/scripts/build_site.py <slug> --text <path> --name <name>
       --domain benchmark_<adapter> --keep-rejected --scope-out <path>
       --model $BIOGRAPH_MODEL --base-url $BIOGRAPH_BASE_URL   [--ignore-scope]
```

Each flag is a decision:

- **`--keep-rejected` is not optional.** Without it, a document the scope gate refuses has its
  input file deleted by the pipeline. A harness that eats its own corpus on rejection is not a
  harness.
- **`--strict-scope` is never passed.** Its four extra rules would reject short benchmark
  documents on length alone. Only the always-on genre precondition applies, which is what makes
  the gate-on / gate-off pair interpretable.
- **`--scope-out` is always passed**, for every document including refusals, because scope-gate
  attrition is a reported column in every results table. The verdict file also carries
  `gate_enforced`, so a reader can tell an admitted document from one the gate would have
  refused but was told to extract anyway.
- **The API key goes through the environment, never `argv`**, or it lands in shell history and in
  every log line echoing the command.

**Three CLI behaviours the harness handles explicitly, all of which would corrupt results if
ignored:**

1. `build()` runs *after* `extract()` and exits non-zero on validation failure — **after the JSON
   is already on disk**. So a non-zero exit means "the draft did not validate", not "no output".
   The runner reads the document folder either way and records `exit_code`. Conflating the two
   loses a real finding.
2. Extraction samples at **temperature 0.2** (now exposed as `--temperature`), so a single run is
   a draw, not a score. `--repeats k` is supported, and results cache on
   `(text, model, core hash, repeat, condition)`. **The `condition` component matters**: without
   it a gate-off run would silently serve a gate-on cached result and produce a perfectly
   plausible, entirely wrong ablation table.
3. **Temperature 0 is not determinism.** The served model is a mixture-of-experts whose routing
   depends on how requests are batched. A benchmark table must not be presented as reproducible
   to the item on the strength of a fixed temperature.

**Both of the pipeline's mechanical checks run on every benchmark document**, grounding and
completeness alike, because the harness invokes the shipped CLI rather than a reduced path. So a
benchmark run yields a grounding and completeness report per document alongside its own score —
available as a diagnostic column, and the reason B5 needs no separate corpus.

## 5. The vocabulary coverage matrix — a strong table for the paper

49 rows (22 event types + 27 relation types, **read from the schemas at import time**, so the
matrix cannot drift from what it describes) × 5 benchmark columns. Cell vocabulary:
`clean` / `partial` (information lost) / `residual` (no target label; scored only via a
catch-all) / `none` (not expressible) / `untyped` (metric is category-free).

| column | clean | partial | residual | none | untyped |
|---|---:|---:|---:|---:|---:|
| B1 Biographical | **5** | 3 | **41** | 0 | 0 |
| B2 BiographicalEvents | 0 | 32 | 0 | 17 | 0 |
| B3 PMOA-TTS | 0 | 0 | 0 | 27 | 22 |
| B4 TLEX | 0 | 0 | 0 | 27 | 22 |
| B5 Grounding *(measured)* | 0 | 13 | 0 | 0 | 36 |

**This table is itself a finding.** Against the closest-matched benchmark, only **5 of 49** types
are clean matches and **41 collapse into a catch-all `other` class**. The benchmarks are
narrower than the schema, not the reverse — which is the honest framing for why external scores
under-describe a richer data model, and why `unmapped` is reported per run.

### 5.1 B5's column, and a correction to how it was explained

B5's column is *measured rather than declared*: it reports, per type, the share of citations
carrying a quote (the grounding check's reach). **36 of 49 types clear 95%; 13 do not** —
`published` 220/233 (94%), `founded` 68/79 (86%), `company_sold` 8/11 (73%), `patent_filed`
10/14 (71%), `sold_to` 3/6 (50%), and others.

**Earlier drafts explained these gaps as "`quote` is optional in the schema", and that is wrong.**
Quotes have been mandatory for new output since `36d289b`; `approach-brief.md` §4.1 has the
enforcement. The real explanation is narrower and more interesting: **all 162 quoteless citations
in the corpus live in exactly two document folders** — `suntola/puurunen2014` (83) and
`aleskovskii/malygin_2015_cvd_essay` (79), the two founding subjects, extracted before the
requirement existed. **258 of 260 documents are at 100% reach.**

So the 13 sub-95% types are **not low-n commercial types with weak provenance**. They are the
types those two particular ALD/thin-film industrial histories happen to be dense in. The gap
tracks two legacy documents, not the schema and not the event vocabulary.

*Code note, not a paper claim: the adapter still emits the old "quote is optional" wording into
every report's notes, and the run directory named `grounding_newprompt` holds figures identical
to `grounding_corpus` — the corpus has not changed, so neither have the numbers. Both are
cosmetic, both are worth fixing before anyone reads a report straight out of the repository.*

## 6. The five benchmarks

### B1 — Biographical (Plum et al., SIGIR 2022) · **adapter built, NOT YET RUN**
Sentence-level relation extraction over Wikipedia/Wikidata. Labels: `birthdate`, `birthplace`,
`deathdate`, `deathplace`, `occupation`, `ofParent`, `educatedAt`, `hasChild`, `sibling`,
`other`. **Carries the generalization claim**: same extractor, different *population* (writers,
politicians, athletes rather than scientists).

Four joins, each disclosed:
- **Sentences are grouped by person** into one pseudo-document, disclosed in
  `BenchmarkDoc.transform`. A lone sentence has no biographical arc and one extraction per row
  would cost a model call per annotation. Consequence: these figures are **not comparable to the
  paper's sentence-level numbers**.
- `birthdate`/`deathdate` are **not relations** in this schema; they are read from the
  birth/death event's fuzzy date. `birthplace`/`deathplace` take the **union** of the
  `born_in`/`died_in` relation and the event's own `location`, deduplicated.
- Dates score by **interval containment**, not string equality, with the median interval width
  reported alongside — so a containment rate achieved by predicting a decade is visibly not one
  achieved by predicting a day.
- `occupation` is **`not_applicable`**: `entity.subtype` is free text (the literal string
  `'researcher'` for 1,393 of 1,975 person entities, 71%) and `entity.summary` is prose. A
  separate, clearly-labelled string-match diagnostic exists and is never folded into the F1.

*Licence: **unresolved.** Repository is GPL-3.0; the data licence is not stated and the corpus
ships via Google Drive. Nothing downloaded.*

### B2 — Biographical Events (ISA 2022, arXiv:2206.03547) · **adapter built, NOT YET RUN**
Token-level ISO-TimeML: classes `EVENT`, `STATE`, `ASP-EVENT`, `REP-EVENT` on trigger tokens,
plus writer-centric SemAF roles (`writer-ARG0`, `ARGx-LOC`, `ARGx-ORG`, `ARGM-TIME`).

- **Type is not measurable in either direction.** All 22 event types collapse onto TimeML's
  single `EVENT`; its four classes have no counterpart here. So no type is ever compared to a
  type. Scoring is **trigger-anchored**, and gold is bucketed by class only afterwards.
- **Anchoring needs two tiers**, because a span alone is ambiguous: the pipeline emits no token
  offsets, but every event carries a verbatim quote and a short label. Turing's *Born* and *Died*
  cite the **same quote**, so containment alone would let either event answer for either trigger.
  Strong tier requires the trigger token in the event's label **and** inside its quote span; weak
  tier is the span alone, **counted separately**. Matching is one-to-one in both directions.
- **`STATE` is an unreachable ceiling by design** — "an event is a dateable occurrence, not a
  fact or a description" — reported as a *measured* number and excluded from the macro.
  Averaging in a class the schema refuses to represent would score an ontological choice as an
  error rate. This is the cleanest result the benchmark can yield.
- `REP-EVENT` (reporting verbs) has no speech-act type here either; `ASP-EVENT` is partially
  recoverable, since `employment_start`/`employment_end` encode aspect in the type itself.
- **Precision is scoped to annotated text.** Events anchored outside any annotated sentence are
  `unscorable_span`, not false positives; otherwise the extractor is punished for reading text
  the annotators did not label.

*Licence: **unresolved** — stated in neither the paper nor the repository.*

### B3 — PMOA-TTS · **run; the result is architectural**
Clinical case reports; `(event, time)` tuples, time in hours from presentation; metric is
embedding-distance event recall plus temporal concordance and AULTC.

**Result: 9 of 9 documents refused, invariant across three input framings** (as published /
one-line genre header / framed as a medical biography). `subject_name` null every time; every
metric 0.00. The refusals name two independent blockers, and the structural one is that case
reports are **de-identified by construction** and so have no named subject, which the scope
definition requires. No input framing can supply one without fabricating it.

So this benchmark **measures the genre admission policy, not the extraction engine**, and reports
as `scope-gate attrition: 100% (9/9)`. That is a sharper architectural finding than a recall
number.

The release also ships **no document text** (rebuilt from PMC Open Access, matching the authors'
own body boundary) and **no human reference timelines**.

*Licence: CC BY-NC-SA 4.0 — non-commercial **and** share-alike; derived artifacts published with
the paper would inherit it. Downloaded locally, not redistributed.*

### B4 — TLEX (arXiv:2406.05265) · **NOT BUILT**
Consumes a TimeML temporal graph and returns exact timelines. The pipeline has no TLINKs, so an
adapter would derive interval relations from `sort_start`/`sort_end` — which makes the graph
**consistent by construction**, so TLEX's consistency check is trivially satisfied. The
informative output would be *indeterminacy*: how much of a timeline is genuinely unordered
because the source gave only a year. That is a property of **date precision, not event type**, so
the per-type column is uniform and the real table would be the precision one (year 2,448 of
3,714 events). Lowest value of the five, and the reason it is last.

### B5 — Grounding · **run; see `approach-brief.md` §7**
No external corpus, no licence question, no model call. Reuses the shipped `--check-grounding` by
shelling out; the check is never reimplemented. **85.9% of 5,394 quotes verbatim, 98.3% of 4,591
entity names present, 2.6% of quotes absent in any form**, 19 subjects excluded for a
source-staging bug it discovered.

**Report the two corrections separately, not as a four-step ladder.** Over all 233 subjects the
tool's summary line gives 21.2% not verbatim (1,382 of 6,516); the 5-word shingle split gives
11.9% flagged (773). Post-exclusion, of 213 flagged quotes, 70 recover on whitespace or case, 4
are unresolvable, and **139 are absent in any form (2.6% of 5,394)**. The denominator changes
between those two corrections, which is why chaining them was wrong. `approach-brief.md` §7 has
the full table.

## 7. What can be reported today

| result | status |
|---|---|
| Grounding audit over 233 subjects | **measured** |
| Scope-gate boundary, 8 controlled biographies (0/5 far, 2/2 adjacent, 1/1 control) | **measured** |
| `--ignore-scope` ablation, same 8 (8/8 produce a graph; 277/278 quotes verbatim) | **measured** |
| PMOA-TTS scope attrition, 9/9 refused across 3 framings | **measured** |
| Prompt governance, 40 runs in 9 conditions (`findings-brief.md` §1) | **measured** |
| Coverage matrix, 49 × 5 | **generated from the schemas** |
| B1 / B2 scores | **blocked on data licences** |
| B4 | not built |

Run artifacts, each with commit + core SHA-256: `grounding_corpus`, `grounding_newprompt`,
`scope_probe_professions`, `scope_probe_gate_off`, `pilot_none`, `pilot_minimal`,
`pilot_biographical`.

**The licence block is the critical path.** B1 and B2 are the only two benchmarks that would
carry a cross-population generalization claim, both adapters are built and tested, and both are
waiting on an email. Nothing else in this table unblocks the Evaluation section.

## 8. Must not be claimed

- **PMOA-TTS's published 0.80 recall / 0.95 concordance.** The clinician-curated gold behind it is
  in neither the HuggingFace release nor the repo — not reproducible by anyone. A reproducible
  substitute exists and should be used instead: the two released LLM annotators scored against
  each other, fully paired over 24,746 cases. At n=40: embedding matcher recall 0.931 /
  concordance 0.878 / AULTC 0.696; Levenshtein 0.824 / 0.852 / 0.613.
- **B1's and B2's published baselines.** Deliberately empty in both adapters. B1's is
  sentence-level where this groups by person; B2's is a token-level sequence labeller *trained on
  that corpus* where this is zero-shot and document-level.
- **Any generalization claim from a gate-on run** of a general-biography corpus: it measures the
  admission policy, not the extractor. B1 and B2 must be reported in **both** conditions, never
  averaged.
- **Type accuracy against B2**, in either direction.
- **B5's sub-95% types as a provenance weakness.** §5.1 — two legacy documents.
- **A single run as a score.** Temperature is 0.2, and temperature 0 is not determinism.
- **Benchmark results as describing the shipped corpus's prompt.** Any run made now uses the
  current prompt; the corpus does not. `approach-brief.md` §9.

## 9. Reproducibility surface

```bash
python -m experiments.tests                                   # 138 checks, no model, no network
python -m experiments.harness.coverage --out <file>           # regenerate the matrix
python -m experiments.harness.cli --benchmark <name> --data-root <dir> --dry-run
python -m experiments.harness.cli --benchmark grounding       # no data-root, no key
python -m experiments.harness.scope_probe --corpus <dir> [--gate-off]
```

`--dry-run` loads the corpus, builds the input text and prints what *would* be sent without
calling a model — how the input adapter and slug rules get checked before an API budget is spent
finding out.

Corpora are never vendored: each adapter reads a local copy via `--data-root`, and
`experiments/corpora/` ignores data while keeping the fetchers, because a corpus a paper cites
has to be rebuildable from the repository.

Both unresolved-licence adapters **sniff their input format** against an alias table and refuse
with the header they actually saw rather than guessing, since a silently mis-read column produces
a plausible, wrong results table — worse than an error.
