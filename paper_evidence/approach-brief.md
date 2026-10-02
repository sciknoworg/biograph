# biograph — condensed technical brief for the WWW paper's Approach section

Self-contained context for drafting. Every figure re-derived at commit `41440f5` (2026-10-02)
from the repository and the run artifacts, not recalled. Numbers carry their denominators;
nothing is rounded up. Where a figure must not be cited, it says so.

---

**Approach is split across two briefs.** This one covers the data model, the two mechanical
checks and the scope gate — what the system does with one document. `pipeline-brief.md` covers
how documents are found: the discovery loop, its two seeding modes, the prominence gate and the
plateau stopping rule. Read together they are the whole method.

> ## Read this before citing any corpus number
>
> **The shipped corpus predates the current extraction prompt.** The completeness rules in §4
> landed at `a155c27` (2026-09-29) and **no commit has touched `subjects/` since** — so all 233
> subjects were extracted under a prompt that did not ask for completeness. Re-running the same
> two documents under the current prompt yields **1.8–3.6× more entities**
> (`findings-brief.md` §2).
>
> Everything in §3 (the data model), §5 (the grounding check's design), §6 (the scope gate) and
> §7 (the checks' numbers over the corpus as it exists) is current and citable. **Corpus
> *volume* — entity, event and relation counts — describes output from the earlier prompt and
> must be labelled as such.** See §9.

## 1. What the system is

A pipeline that turns biographical documents about scientists and engineers into a validated
knowledge graph, **one LLM call per document**, with every factual claim carrying a verifiable
citation into the source text.

Input: a PDF or plain text. Output: four JSON files per document, schema-validated, plus a
rendered single-file HTML page (graph / timeline / map views).

The contribution is not extraction quality in the abstract. It is that **the extractor's output
is mechanically checkable against its own sources**, that this check finds things no downstream
benchmark can see, and that the prompt's governance of its own output can be measured property
by property (§2).

## 2. The organising finding: a prompt governs exactly what it states

This is the frame the rest of the brief hangs on, and it is new since the earlier drafts.

Across **40 repeat extractions** of two documents by one model in 9 conditions, every property
the prompt states held at **100% with zero variation between draws** — events carrying a date,
citations carrying a page, citations carrying a quote, events with ≥1 participant, id pattern
conformance. Every property the prompt left unstated varied widely: entity count CV
13.6–48.8%, **person count CV 28.6–62.1%**.

The schema governs the **shape** of an item. Nothing governed **how many items there should
be** — and selection is where all the non-determinism lived. Full evidence, with the claims it
does and does not support, is in `findings-brief.md` §1.

The design consequence, implemented at `a155c27`, is §4: completeness was moved from an
unstated expectation into a stated rule with a mechanical check beside it, in the same register
as the shape rules. That is the Approach-level story — **not** "we improved the prompt", but
"the properties a prompt governs and the properties it does not are separable, measurable, and
the boundary moves when you state a rule."

## 3. Data model

Five JSON Schemas (draft 2020-12), embedded **verbatim** into the extraction prompt so the
prompt cannot drift from the validator:

| file | holds |
|---|---|
| `entity.schema.json` | **4** entity types: `person`, `place`, `organization`, `artifact` |
| `event.schema.json` | **22** event types (`birth`, `death`, `education`, `invention`, `patent_filed`, `publication`, `award`, …) |
| `relation.schema.json` | **27** relation types (`born_in`, `worked_at`, `invented`, `supervised_by`, `family_of`, …) |
| `date.schema.json` | **8** fuzzy-date precisions (below) |
| `source.schema.json` | the document, for citation |

**The output contract is seven top-level keys**, not four: `scope`, `subject`, `entities`,
`events`, `relations`, `sources`, `related_fields`. Two are infrastructure rather than data and
both earn their place:

- **`scope`** is `{"fits": <bool>, "reason": "<one sentence>", "subject_name": "<the person the
  document is principally about, or null>"}`. `subject_name` is load-bearing in the pipeline:
  documents are reached by searching for someone who may only be *mentioned* in them, so a
  Rotblat biography surfaced by searching "Harold Kroto" is filed under Rotblat because the
  extraction says who the document is actually about.
- **`related_fields`** is a best-effort list of adjacent subfields the document discusses as
  context. Not schema-validated; it feeds the discovery loop's taxonomy growth
  (`pipeline-brief.md` §3).

Load-bearing design decisions, each worth a sentence in the Approach:

- **Events are dateable occurrences, not states.** "An event is a dateable occurrence, not a
  fact or a description." Every event must carry a date, however imprecise; none may be
  undated. An ontological commitment with measurable consequences (`harness-brief.md` §6, B2).
- **Dates are intervals, not points.** 8 precisions (`day`, `month`, `season`, `year`, `decade`,
  `century`, `circa`, `range`), each stored with `sort_start`/`sort_end`. A year-precision date
  is an interval covering that year. Corpus distribution over 3,714 events: year 2,448 · day
  538 · month 299 · range 235 · decade 78 · circa 78 · season 36 · century 2.
- **Relations have fixed reading direction.** `worked_at` requires a `person` source and an
  `organization` target, enforced for all 27 types at validation — not merely that the ids
  resolve. The directions and meanings are rendered into the prompt from the same table the
  validator uses, and `extraction_schemas()` raises if the vocabulary, the directions and the
  meanings ever disagree.
- **Merge on read, never on write.** Each document's extraction is stored whole in its own
  folder, `subjects/<domain>/<slug>/<citation-key>/`. Two papers about one person are two
  accounts, not one claim. Entities merge by id (aliases unioned) at render time; **events and
  relations are never merged** — deciding that two accounts of an episode are one claim is
  exactly the judgement that should not be made silently. Both survive, each with its own
  citations, so a disagreement between sources is visible and attributable.
- **Provenance is mandatory at two levels.** Every event and relation citation must carry a
  `page`, **and every citation must carry a nonempty `quote`** — see §4.

## 4. What the prompt requires, and what changed

Two requirements in the current prompt are stricter than earlier drafts of this brief described.
Both matter for how the checks in §5 and §6 should be characterised.

### 4.1 Quotes are mandatory, not optional

Earlier drafts said `quote` was optional — "only for pivotal events, not every one". **That is
no longer true and has not been since `36d289b` (2026-09-06).** The current prompt:

> EVERY citation needs `sources[].quote`: the exact span of the document that states this fact,
> copied character-for-character […] This is checked mechanically against the source afterwards
> […] so a quote you cannot copy exactly is a fact you should not be stating. If you cannot
> point at the words, leave the fact out.

Enforced in three places, not one: `extraction_schemas()` adds `quote` to the citation
`required` list with `minLength: 1` and a `\S` pattern for new output; `check_extraction_quotes()`
raises before anything is written; the stored schemas still accept legacy citations without
quotes so older data remains loadable.

**This changes how citation reach must be reported.** 6,516 of 6,678 citations carry a quote
(97.6%). The 162 that do not are **entirely** in two document folders —
`suntola/puurunen2014` (83) and `aleskovskii/malygin_2015_cvd_essay` (79) — the two founding
subjects, extracted before the requirement existed. **258 of 260 documents are at 100%.** So
the correct statement is *"two legacy documents predate the requirement"*, never *"quotes are
optional, so some citations are outside the check"*.

### 4.2 Completeness is now stated and checked

Added at `a155c27`. Two rules, in the same imperative register as the shape rules:

> COMPLETENESS IS PART OF CORRECTNESS, and it is checked. Every rule above says what a fact must
> carry to be admissible; not one of them licenses leaving a fact out. […] Do not stop when the
> output feels long enough, do not keep only the highlights, and never drop a qualifying fact
> for brevity — a shorter extraction is not a better one. Two extractions of this document
> should differ in wording, never in which facts they contain.

> EVERY person, place, organization and artifact named inside a quote you cite must have its own
> `entities[]` object. Quoting "Suntola and Antson filed the patent" asserts that this document
> says something about Antson, so Antson is an entity with an id. […] The way out is never to
> quote a shorter span to dodge a name: if the sentence that states your fact names someone,
> define them.

The second rule is the one that admits a check, and that is why it is phrased that way.

## 5. Two mechanical checks

Both run after extraction, before validation. Both are **reported, not enforced**: extraction is
a first-pass draft, and a hard gate would discard good work over PDF artefacts. The caller
decides what to do with the numbers.

### 5.1 Grounding — does what was asserted appear in the document?

Every `sources[].quote` must occur in the source text the model actually read, and every entity
name must appear in it too.

**Why mechanical rather than a second LLM call.** An LLM asked to grade its own output shares
the priors that produced it. "Does this string occur in this document" cannot be talked into
agreeing. This is the central design argument.

**Normalisation is exactly the noise PDF extraction introduces, and nothing else.** Both sides
are lowercased and normalised for curly→straight quotes, en/em dashes→hyphen, soft hyphens
removed, typographic ligatures expanded (`ﬁ`→`fi`), whitespace collapsed. **Word characters are
left untouched**, so a quote naming a date or person the document never mentions still fails.
That asymmetry is the point.

**Elided quotes are not penalised.** A quote may legitimately abridge with `...` or `[...]`. It
is split on the ellipsis and each fragment longer than 12 characters must occur independently;
they need not be contiguous.

**Misquotation and fabrication are separated, by 5-word shingle overlap** — the fraction of the
quote's 5-word windows present in the source. One substituted word breaks only the windows
spanning it, so a copy error keeps nearly all windows while a composed sentence shares almost
none. Threshold 0.5: below is `NOT IN SOURCE`, above is `misquoted`. **Reporting these
identically would make the whole check ignorable**; that sentence is the justification for the
threshold.

**Entity names match on their longest word** (usually a surname), across the primary name and
all aliases. A document writing "J. B. Goodenough" therefore satisfies a graph entity named
"John B. Goodenough"; a missing surname means the entity came from the model's memory rather
than the page. Checking the full primary string would flag correct entity resolution as
invention.

### 5.2 Completeness — was everything quoted also defined?

`check_completeness()` asks the inverse question, and it is the newer half of the argument:
**does every name the extraction QUOTES resolve to an entity it DEFINED?**

The design point is why this needs no gold annotation. Completeness *against the source* would
require the source annotated, which nothing here has. Completeness against the extraction's own
citations requires nothing extra: **a quote is a span the model chose to assert, so a name
inside one is a name it has already committed to.** If it never defined that name as an entity,
the extraction contradicts itself — and self-contradiction is checkable for free.

**Reported as the heuristic it is.** It matches capitalised multi-word runs, so it flags field
names ("Analytical Chemistry") alongside real misses ("Jorma Antson", "Vaisala Oy"); roughly
half of what it reports is worth acting on. Like the grounding check it reports rather than
blocks — a hard gate on something this rough would cost more good extractions than it saved.

**Precision had three mechanical checks and completeness had none.** That asymmetry, not the
check's own accuracy, is the finding.

## 6. The scope gate, and the ablation that separates it from the extractor

A genre precondition sits in the prompt on every call: the document must be a "biographical or
historical retrospective essay" following a specific person's life "intertwined with a specific
technology's development", by a historian or domain scientist, long enough to extract dated
life events from. A `fits: false` verdict writes nothing at all.

**Where its boundary sits — controlled measurement.** 8 English Wikipedia biographies of named
people, identical in source, format and length (12,000 chars), varying **only** the subject's
field:

| field | verdict |
|---|---|
| literature (Woolf), art (Kahlo), sport (Owens), music (Ellington), politics (Churchill) | refused **0/5** |
| aviation (Earhart), nursing/statistics (Nightingale) | admitted **2/2** |
| computing (Turing) — positive control | admitted **1/1** |

All five refusals cite the *same* clause and **none** cites the named-subject clause. So the
gate asks "is this the biography of a technology, told through a person?", not "is this a
biography?". Nightingale's admission shows the boundary tracks whether the life *produced
something*, not whether that something is a machine.

**The ablation (`--ignore-scope`).** The verdict is still requested and still recorded; only its
power to stop the run is removed. One prompt sentence is swapped and the default path is
byte-identical. The swapped-out sentence is the reason downstream filtering could not substitute:

> If `scope.fits` is false, return `subject` as `{}` and `entities`, `events`, `relations`,
> `sources` and `related_fields` as `[]`.

A refused document comes back empty **by instruction**, so there is nothing downstream to
filter. The replacement sentence tells the model to record the verdict and extract in full
regardless, and the written verdict carries `gate_enforced` so a reader can always tell an
admitted document from one the gate would have refused.

Gate-off over the same 8 documents: **8/8 produce a graph, the verdict itself unchanged at 3
admitted**, and the five refused documents extract at the quality of the admitted ones —
**277/278 quotes verbatim (99.6%), 5/5 validating**. **The genre precondition was the only
obstacle.** This yields paired data: what the gate would have said, and what the extractor
produced anyway.

A related earlier finding: clinical case reports (PMOA-TTS) are refused **9/9**, invariant
across three input framings, for an additional and more structural reason — they are
de-identified by construction and so have no named subject at all.

*A second, stricter layer (`--strict-scope`) adds four requirements and is passed only by the
automated pipeline, never by the benchmark harness. See `pipeline-brief.md` §5.*

## 7. The grounding audit over the corpus

233 subjects; 19 excluded for the staging bug in §7.1.

| | post-exclusion (214 subjects) | all 233 subjects |
|---|---:|---:|
| quotes checked | **5,394** | 6,516 |
| verbatim | **85.9%** | 78.8% |
| misquoted (present, not verbatim) | 10.2% | 9.3% |
| flagged `NOT IN SOURCE` by the checker | 3.9% (213) | 11.9% (773) |
| **absent in any form — the fabrication rate** | **2.6%** (139) | — |
| entity names present | **98.3%** (4,591) | 95.7% (5,409) |

**Reaching 2.6% took two independent corrections, and they must not be presented as one ladder.**
Earlier drafts of this brief chained four percentages (21.2% → 11.9% → 9.9% → 2.6%); the
denominator changes between step 2 and step 4, and the 9.9% intermediate was never re-derivable
from a saved artifact. Report the two corrections separately instead — both are exact:

**Correction A — separating fabrication from misquotation.** Over all 233 subjects, the tool's
own summary line reports **21.2% not verbatim** (1,382 of 6,516). Applying the 5-word shingle
split, **11.9%** (773) are flagged `NOT IN SOURCE` and the remaining 9.3% are present but not
verbatim. A paper citing 21.2% as a hallucination rate would be overstating by roughly 1.8×.

**Correction B — the whitespace diagnostic, on the flagged set.** Of the 213 quotes flagged
post-exclusion: **69 match once whitespace is ignored**, 1 more once case is too, 4 could not be
resolved, and **139 are absent in any form** — 2.6% of 5,394. The recovered ones are the model
emitting a quote with its spacing destroyed, e.g.
`'developedbyEmilvonBehringandShibasaburoKitasatoin1890'`, which can match nothing although its
content is plainly in the document.

The diagnostic starts from the checker's own verdicts rather than recomputing them, so it can
only ever *reduce* the fabrication count. An earlier version that recomputed independently
scored 61.6% verbatim against the checker's 78.8%, because it lacked the ellipsis and
hyphenation handling — an upper bound wearing a measurement's clothes. It was discarded, not
reported.

**A numeric coincidence to guard against.** The report's `subjects_with_an_unverified_quote`
field is **139**, and the count of quotes absent in any form is **also 139**. They are unrelated:
139 of 214 scored subjects contain at least one unverified quote; 139 of 5,394 quotes are absent.
Do not let one number do both jobs in a sentence.

Per-domain spread after exclusion is tight: 81.1% (physics) to 95.5% (computer science),
n=202–1,345. *(An earlier reading showed life sciences at 66.6%; that was entirely the
overwritten-source artefact and does not survive the exclusion. Do not cite the spread as
tracking PDF quality.)*

### 7.1 What the check found: a silent provenance bug

Source text was staged as `data/<slug>.txt` — keyed by the **subject**, while document folders
have always been keyed by the **document**. A subject's second document therefore overwrote the
first one's text while both `sources.json` files kept pointing at that one path, so every quote
from the losing document was afterwards checked against a paper it had never come from.

**19 subjects, 41 documents.** Example: `berthollet` has two documents, `sztejnberg_2020` and
`weller_1999`, both citing `data/berthollet.txt`, which holds only the Weller paper.

This is the strongest available argument for the grounding check earning its place: **the
failure was silent, it looked exactly like hallucination, and no relation-level benchmark could
have surfaced it** — none of them ever compares the graph to the document. **A quarter of the
apparent hallucination rate was a filename.** Fixed forward at `aa60af1`
(`data/<slug>__<citation-key>.txt`), so a document's folder and the text it was extracted from
are now identifiable as a pair; the historical 41 remain flagged as attrition rather than
silently scored.

## 8. Benchmark harness — the integrity mechanism

Summarised here; `harness-brief.md` is the full version.

`experiments/` scores the pipeline against five external benchmarks. Everything is an adapter
*around* `build_site.py`'s CLI; the harness imports nothing from it and only shells out.

**"We did not modify the extraction core" is mechanical, not editorial.** Every run copies
`build_site.py`, the five schemas and `frontend/` into a throwaway sandbox, records the SHA-256
of each file plus the git commit, and **re-verifies every hash after the run**. A divergence
exits 2. The sandbox is necessary because `build_site.py` derives its root from its own
`__file__`, so running benchmarks in place would write fake people into the corpus — an accident
that already happened once (170 test entities hijacked name resolution).

**Three fields carry the methodological honesty**, and they are worth naming in the paper:
`Prediction.unmapped` (extracted items with no expression in a benchmark's label space, with a
reason — taxonomy loss as a per-run number rather than a limitations sentence);
`Prediction.lossy` (projections that succeeded while losing something nameable);
`ScoreReport.not_applicable` (benchmark labels the schema *cannot* represent, named and excluded
from macro-averages).

| benchmark | adapter | data | result |
|---|---|---|---|
| 1. Biographical (SIGIR 2022) | built, tested | **licence unresolved** | **NOT YET RUN** |
| 2. BiographicalEvents (ISA 2022) | built, tested | **licence unresolved** | **NOT YET RUN** |
| 3. PMOA-TTS | built | in hand | refuses 9/9; published baseline unreproducible |
| 4. TLEX | not built | — | — |
| 5. Grounding | built | none needed | **run — §7** |

## 9. Corpus, and the prompt boundary

**233 subjects, 260 documents, 9 domains: 5,545 entities, 3,714 events, 2,941 relations.**
Entity types: person 1,975 · organization 1,663 · artifact 1,058 · place 849.

physics 60 · chemistry 44 · life sciences & medicine 43 · materials science 33 ·
mathematics & computation 24 · engineering 11 · computer science 9 · earth & space 8 ·
agriculture & food technology 1.

Secondary coverage: **800 of 849 place entities geocoded (94.2%)** against Wikidata P625 with
the QID recorded; **150 person entities carry portraits across 137 subjects**, 145 verified by
exact birth-year match and only 5 by model judgement.

**The boundary, stated plainly for the paper.** These counts describe output from the prompt as
it stood before `a155c27`. The current prompt, on the same two documents, produces 1.8–3.6× more
entities. Three ways to handle this, in descending order of what they cost:

1. **State it** — report corpus volume as produced under the earlier prompt, and report the
   multiplier from `findings-brief.md` §2 as a separately measured effect. No new runs.
2. **Re-draw a sample** — re-extract *k* subjects under the current prompt and report the
   distribution shift with a confidence interval. Bounded cost, quantifies the gap.
3. **Re-run the corpus** — 260 documents of extraction. Removes the caveat entirely.

Option 1 is defensible and costs nothing. What is **not** defensible is reporting the corpus
counts and the completeness multiplier in the same section without saying they come from
different prompts.

## 10. Must not be claimed

- **Corpus volume as current-prompt output.** §9.
- **A chained four-step grounding sequence.** Two independent corrections, §7.
- **`quote` as optional**, or citation reach below 100% as a schema property. §4.1.
- **PMOA-TTS's published 0.80 recall / 0.95 concordance.** The clinician-curated gold is in
  neither the HuggingFace release nor the repo. Not reproducible by anyone. A reproducible
  substitute exists: the two released LLM annotators scored against each other (recall 0.82 /
  concordance 0.85 with the Levenshtein matcher at n=40).
- **B1 and B2 published baselines.** Deliberately left empty in both adapters. B1's paper is
  sentence-level where this groups by person; B2's is a token-level sequence labeller *trained on
  that corpus* where this is zero-shot and document-level. Not the same tasks.
- **Any generalization claim from a gate-on run** of a general-biography corpus. It measures the
  admission policy, not the extractor.
- **The per-domain grounding spread as a PDF-quality effect.** §7.
- **That the completeness rules improved consistency.** They raised recall and did not;
  `findings-brief.md` §2.

## 11. Model and reproducibility

Extraction model: `qwen3.5-397b-a17b` via an OpenAI-compatible endpoint
(`chat-ai.academiccloud.de`), `max_tokens` 32,000 with automatic continuation when a reply is
cut off.

**Temperature is 0.2 by default and now exposed as `--temperature`.** It was exposed because the
variability study measured what the default costs: extraction has a right answer — the facts the
document states — so spread between draws is error rather than useful diversity.

**Temperature 0 must not be described as deterministic.** The served model is a
mixture-of-experts whose routing depends on how requests are batched, and a reasoning trace can
diverge early and change how thorough an extraction is. Greedy decoding narrows the spread; it
does not close it. **A single run is a draw, not a score.** The harness supports `--repeats k`
and caches by `(text, model, core hash, repeat, condition)`.

Only one of six models attempted can perform this task at all; `findings-brief.md` §5 has the
failure taxonomy. One failure worth a footnote: a verification call budgeted at 300 tokens
returned `finish_reason: length` with empty content on **all 62 invocations**, because reasoning
tokens are charged against the same budget — and empty content was indistinguishable from a
considered "no match". **A reply that never arrived is not evidence.**
