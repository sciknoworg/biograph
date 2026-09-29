# biograph — condensed technical brief for the WWW paper's Approach section

Self-contained context for drafting. Everything here is measured at commit `aa60af1`
(2026-09-29) unless marked **NOT YET RUN**. Numbers carry their denominators; nothing is
rounded up. Where a figure must not be cited, it says so.

---

**Approach is split across two briefs.** This one covers the data model, the grounding check
and the scope gate — what the system does with one document. `pipeline-brief.md` covers how
documents are found: the discovery loop, its two seeding modes, the prominence gate and the
plateau stopping rule. Read together they are the whole method.

## 1. What the system is

A pipeline that turns biographical documents about scientists and engineers into a
validated knowledge graph, one LLM call per document, with every factual claim carrying a
verifiable citation into the source text.

Input: a PDF or plain text. Output: four JSON files per document, schema-validated, plus a
rendered single-file HTML page (graph / timeline / map views).

The contribution is not extraction quality in the abstract. It is that **the extractor's
output is mechanically checkable against its own sources**, and that this check finds
things no downstream benchmark can see.

## 2. Data model

Five JSON Schemas (draft 2020-12), embedded **verbatim** into the extraction prompt so the
prompt cannot drift from the validator:

| file | holds |
|---|---|
| `entity.schema.json` | 4 entity types: `person`, `place`, `organization`, `artifact` |
| `event.schema.json` | **22** event types (`birth`, `death`, `education`, `invention`, `patent_filed`, `publication`, `award`, …) |
| `relation.schema.json` | **27** relation types (`born_in`, `worked_at`, `invented`, `supervised_by`, `family_of`, …) |
| `date.schema.json` | fuzzy dates (below) |
| `source.schema.json` | the document, for citation |

Load-bearing design decisions, each worth a sentence in the Approach:

- **Events are dateable occurrences, not states.** "An event is a dateable occurrence, not
  a fact or a description." Every event must carry a date, however imprecise; none may be
  undated. This is an ontological commitment with measurable consequences (§6).
- **Dates are intervals, not points.** 8 precisions (`day`, `month`, `season`, `year`,
  `decade`, `century`, `circa`, `range`), each stored with `sort_start`/`sort_end`. A
  year-precision date is an interval covering that year. Corpus distribution: year 2,448 /
  day 538 / month 299 / range 235 / decade 78 / circa 78 / season 36 / century 2.
- **Relations have fixed reading direction.** `worked_at` requires a `person` source and an
  `organization` target, enforced for all 27 types at validation — not merely that the ids
  resolve.
- **Merge on read, never on write.** Each document's extraction is stored whole in its own
  folder, `subjects/<domain>/<slug>/<citation-key>/`. Two papers about one person are two
  accounts, not one claim. Entities merge by id (aliases unioned) only at render time;
  events and relations are never merged. Rationale: a bad reconciliation becomes a
  rendering bug you re-run, never lost extraction.
- **Provenance is mandatory at the citation level.** Every event and relation source
  citation must carry a `page`, not just a `source_id`. `quote` is *optional* — "only for
  pivotal events, not every one" — which bounds the grounding check's reach (§3).

## 3. The grounding check — the paper's focus

**What it does.** After extraction, before validation: every `sources[].quote` must occur
in the source text the model actually read, and every entity name must appear in it too.

**Why it is mechanical rather than a second LLM call.** An LLM asked to grade its own
output shares the priors that produced it. "Does this string occur in this document"
cannot be talked into agreeing. This is the central design argument.

**Normalisation — exactly the noise PDF extraction introduces, and nothing else.** Before
comparison, both sides are lowercased and normalised for: curly→straight quotes, en/em
dashes→hyphen, soft hyphens removed, typographic ligatures expanded (`ﬁ`→`fi`), whitespace
collapsed. Word characters are left untouched, so a quote naming a date or person the
document never mentions still fails. That asymmetry is the point.

**Elided quotes are not penalised.** A quote may legitimately abridge with `...` or
`[...]`. It is split on the ellipsis and each fragment longer than 12 characters must occur
independently; they need not be contiguous.

**Misquotation and fabrication are separated, by 5-word shingle overlap.** The fraction of
the quote's 5-word windows present in the source. One substituted word breaks only the
windows spanning it, so a copy-error keeps nearly all windows; a composed sentence shares
almost none. Threshold 0.5: below is `NOT IN SOURCE`, above is `misquoted`. **Reporting
these identically would make the whole check ignorable** — that sentence is the
justification for the threshold.

**Entity names match on their longest word** (usually a surname), across the primary name
and all recorded aliases. A document writing "J. B. Goodenough" therefore satisfies a graph
entity named "John B. Goodenough"; a missing surname means the entity came from the model's
memory rather than the page. Checking only the full primary string would flag correct entity
resolution as invention.

**Reported, not enforced.** Extraction is a first-pass draft a human reviews; a strict gate
would discard good work over PDF artefacts. The caller decides what to do with the numbers.

### Measured over the corpus (233 subjects, 5,394 quotes, 19 subjects excluded)

| | |
|---|---:|
| quotes verbatim | **85.9%** |
| misquoted (present, not verbatim) | 10.2% |
| flagged `NOT IN SOURCE` by the checker | 4.0% (213) |
| of those, recovered by ignoring whitespace or case | 70 of 213 |
| **absent in any form — the fabrication rate** | **2.6%** (139) |
| entity names present | **98.3%** (4,591 checked) |
| citation reach (citations carrying a quote) | 97.6% (6,516 of 6,678) |

**Getting to 2.6% required four corrections, and the sequence is itself a result.** Each
intermediate number would have supported a different and wronger claim:

1. **21.2%** — what the tool's own summary line reports as "not verbatim".
2. **11.9%** — after separating fabrication from misquotation.
3. **9.9%** — after a diagnostic on the flagged set: the model sometimes emits a quote with
   its whitespace destroyed (`'developedbyEmilvonBehringandShibasaburoKitasatoin1890'`),
   which can match nothing though its content is plainly in the document. 69 of 213.
4. **2.6%** — after excluding 19 subjects whose source text no longer existed (§3.1).

The diagnostic starts from the checker's own verdicts rather than recomputing them, so it
can only ever *reduce* the fabrication count. An earlier version that recomputed
independently scored 61.6% verbatim against the checker's 78.8%, because it lacked the
ellipsis and hyphenation handling — an upper bound wearing a measurement's clothes. It was
discarded, not reported.

Per-domain spread after exclusion is tight: 81.1% (physics) to 95.5% (computer science),
n=202–1,345. *(An earlier reading showed life sciences at 66.6%; that was entirely the
overwritten-source artefact and does not survive the exclusion. Do not cite the spread as
tracking PDF quality.)*

### 3.1 What the check found: a silent provenance bug

Source text was staged as `data/<slug>.txt` — keyed by the **subject**, while document
folders have always been keyed by the **document**. A subject's second document therefore
overwrote the first one's text while both `sources.json` files kept pointing at that one
path, so every quote from the losing document was afterwards checked against a paper it had
never come from.

**19 subjects, 41 documents.** Example: `berthollet` has two documents, `sztejnberg_2020`
and `weller_1999`, both citing `data/berthollet.txt`, which holds only the Weller paper.

This is the strongest available argument for the grounding check earning its place: **the
failure was silent, it looked exactly like hallucination, and no relation-level benchmark
could have surfaced it** — none of them ever compares the graph to the document. A quarter
of the apparent hallucination rate was a filename. Fixed forward at `aa60af1`
(`data/<slug>__<citation-key>.txt`); the historical 41 remain flagged as attrition rather
than silently scored.

## 4. The scope gate, and the ablation that separates it from the extractor

A genre precondition sits in the extraction prompt on every call: the document must be a
"biographical or historical retrospective essay following a specific person's life
intertwined with a specific technology's development". A `fits: false` verdict writes
nothing at all.

**Where its boundary sits — controlled measurement.** 8 English Wikipedia biographies of
named people, identical in source, format and length (12,000 chars), varying **only** the
subject's field:

| field | verdict |
|---|---|
| literature (Woolf), art (Kahlo), sport (Owens), music (Ellington), politics (Churchill) | refused **0/5** |
| aviation (Earhart), nursing/statistics (Nightingale) | admitted **2/2** |
| computing (Turing) — positive control | admitted **1/1** |

All five refusals cite the *same* clause and **none** cites the named-subject clause. So
the gate asks "is this the biography of a technology, told through a person?", not "is this
a biography?". Nightingale's admission shows the boundary tracks whether the life *produced
something*, not whether that something is a machine.

**The ablation (`--ignore-scope`).** The verdict is still requested and still recorded; only
its power to stop the run is removed. One prompt sentence is swapped and the default path is
byte-identical. Ignoring the verdict downstream would not have worked: the prompt tells the
model that when `fits` is false the other keys "may be left empty", so a refused document
comes back empty by instruction.

Gate-off over the same 8 documents: **8/8 produce a graph, the verdict itself unchanged**,
and the five refused documents extract at the quality of the admitted ones — 277/278 quotes
verbatim (99.6%), 5/5 validating. **The genre precondition was the only obstacle.** This
yields paired data: what the gate would have said, and what the extractor produced anyway.

A related earlier finding: clinical case reports (PMOA-TTS) are refused **9/9**, invariant
across three input framings, for an additional and more structural reason — they are
de-identified by construction and so have no named subject at all.

## 5. Benchmark harness — the integrity mechanism

`experiments/` scores the pipeline against five external benchmarks. Everything is an
adapter *around* `build_site.py`'s CLI; the harness imports nothing from it and only shells
out.

**"We did not modify the extraction core" is mechanical, not editorial.** Every run copies
`build_site.py`, the five schemas and `frontend/` into a throwaway sandbox, records the
SHA-256 of each file plus the git commit, and **re-verifies every hash after the run**. A
divergence exits 2. The sandbox is necessary because `build_site.py` derives its root from
its own `__file__`, so running benchmarks in place would write fake people into the corpus —
an accident that already happened once (170 test entities hijacked name resolution).

**Three fields carry the methodological honesty**, and they are worth naming in the paper:

- `Prediction.unmapped` — every extracted item with no expression in a benchmark's label
  space, with a reason. Taxonomy loss becomes a per-run number, not a limitations sentence.
- `Prediction.lossy` — projections that succeeded while losing something nameable (a
  three-way collapse onto `family_of`; a year standing in for an hour-resolution timestamp).
- `ScoreReport.not_applicable` — benchmark labels the schema *cannot* represent, named and
  **excluded from macro-averages**. Scoring them 0 would understate the pipeline for a label
  it was never asked to produce; scoring them at all would claim a capability the data model
  lacks.

### Adapter status

| benchmark | adapter | data | result |
|---|---|---|---|
| 1. Biographical (SIGIR 2022) | built, tested | **licence unresolved** | **NOT YET RUN** |
| 2. BiographicalEvents (ISA 2022) | built, tested | **licence unresolved** | **NOT YET RUN** |
| 3. PMOA-TTS | built | in hand | refuses 9/9; published baseline unreproducible |
| 4. TLEX | not built | — | — |
| 5. Grounding | built | none needed | **run — §3** |

Benchmark-specific mismatches already characterised (useful for a Limitations or Approach
subsection):

- **B1** is *sentence-level*; the adapter groups sentences **by person** into one
  pseudo-document, disclosed in `transform`. These figures will therefore **not** be
  comparable to the paper's sentence-level numbers. `occupation` has no typed home in the
  schema (`entity.subtype` is free text, `'researcher'` for 1,393 of 1,975 person entities)
  and is reported N/A.
- **B2**'s label space is ISO-TimeML (`EVENT`, `STATE`, `ASP-EVENT`, `REP-EVENT`) plus
  writer-centric SemAF roles. All 22 event types collapse onto one label, so **type
  accuracy is not measurable in either direction** and scoring is trigger-anchored, with a
  two-tier anchor (label+quote, then quote alone, counted separately). `STATE` is an
  **unreachable ceiling by design** — a state is not a dateable occurrence — reported as a
  measured number and excluded from the macro.

## 6. Corpus

233 subjects, 260 documents, 9 domains: 5,545 entities, 3,714 events, 2,941 relations.

physics 60 · chemistry 44 · life sciences & medicine 43 · materials science 33 ·
mathematics & computation 24 · engineering 11 · computer science 9 · earth & space 8 ·
agriculture & food technology 1.

Secondary coverage: 800 of 849 place entities geocoded (94.2%) against Wikidata P625 with
the QID recorded; 148 person entities carry portraits verified by exact birth-year match or
an LLM identity judgement.

## 7. Access findings — the "message to publishers" thread

Of 4,292 documents the pipeline attempted: **1,395 obtained (33%)**, 1,746
`failed_permanent` (40.7%), 451 no URL, 437 transient failure, 257 duplicate.

By provider, refusals with ≥10 attempts — Wiley **0 obtained / 297 refused** (all 403),
OUP 0/137 (all 403), Springer 1/128 (HTML interstitial), IOP 11/105, MDPI 0/103 (403),
ScienceDirect 0/76 (403), NCBI 0/70, Nature 0/65, ACS 0/56, T&F 1/56. CORE 96/182.

The careful framing established earlier: these documents are **open to a human and closed
to a machine**. Also measured: `confirmed open access` count in cycle 1 predicts domain
yield monotonically (298→43 subjects, 117→24, 114→11, 87→8, 74→1; two probe domains at
17→0 and 3→0).

## 8. Must not be claimed

- **PMOA-TTS's published 0.80 recall / 0.95 concordance.** The clinician-curated gold behind
  it is in neither the HuggingFace release nor the repo. Not reproducible by anyone. A
  reproducible substitute exists: scoring the two released LLM annotators against each other
  (recall 0.82 / concordance 0.85 with the Levenshtein matcher at n=40).
- **B1 and B2 published baselines.** Deliberately left empty in both adapters. B1's paper is
  sentence-level where this groups by person; B2's is a token-level sequence labeller
  *trained on that corpus* where this is zero-shot and document-level. Not the same tasks.
- **Any generalization claim from a gate-on run** of a general-biography corpus. It measures
  the admission policy, not the extractor.
- **The per-domain grounding spread as a PDF-quality effect** (see §3).

## 9. Model and reproducibility

Extraction model: `qwen3.5-397b-a17b` via an OpenAI-compatible endpoint
(`chat-ai.academiccloud.de`), temperature 0.2, `max_tokens` 32,000 with automatic
continuation when a reply is cut off. Because sampling is non-deterministic, a single run is
a draw rather than a score; the harness supports `--repeats k` and caches by
`(text, model, core hash, repeat, condition)`.

One reasoning-model failure worth a footnote: a verification call budgeted at 300 tokens
returned `finish_reason: length` with empty content on **all 62 invocations**, because
reasoning tokens are charged against the same budget — and empty content was
indistinguishable from a considered "no match". A reply that never arrived is not evidence.
