# Findings — condensed brief for the WWW paper's Results

Five results, with the evidence behind each and the claims each does **not** support.
Self-contained; assumes no access to the repository. Every figure re-derived at commit
`bc0e799` (2026-10-01) from `paper_evidence/variability/manifest.json` and
`experiments/runs/`, not recalled.

Companion to `approach-brief.md`, `pipeline-brief.md`, `harness-brief.md`,
`corpus-and-access-brief.md` and `frontend-brief.md`, which describe the system. This one
is only about what was measured.

---

## 1. Constraints are obeyed exactly where they are stated, and nowhere else

**The headline result.** Across **40 repeat extractions** of two documents by one model
(`qwen3.5-397b-a17b`), spanning 9 conditions (2 documents × 2 temperatures × 4 prompt
versions), every property the prompt governs held at **100%, with zero variation between
draws**:

| governed property | every condition |
|---|---|
| events carrying a date | **100%** |
| citations carrying a page number | **100%** |
| citations carrying a verbatim quote | **100%** |
| events with ≥1 participant | **100%** |
| ids matching `^[a-z][a-z0-9_]*$` | **100%** |

Every property the prompt leaves unspecified varied widely across the same draws:

| ungoverned property | spread (CV across draws, by condition) |
|---|---|
| entity count | **13.6% – 48.8%** |
| event count | 6.5% – 34.3% |
| relation count | 6.2% – 38.3% |
| **person count** | **28.6% – 62.1%** |

The schema governs the **shape** of an item; nothing governed **how many items there should
be**. Selection — which mentions deserve an entity, which occurrences deserve an event — was
never stated, and all the non-determinism lives there.

Concretely: one draw of a paper that names six colleagues produced **a single person entity**
while still quoting the others by name, and the same document produced **15 to 104 entities**
across draws.

**Why this is the interesting framing.** It is not "the extractor is unreliable". It is that a
schema embedded in a prompt is obeyed with perfect fidelity on every dimension it addresses,
and has no influence at all on the dimensions it does not. Person count is the worst case, which
fits: deciding whether a colleague mentioned once "is an entity" is the purest selection
judgement in the task.

**Does not support:** that temperature causes this. Greedy decoding (temperature 0) did not
reduce the spread — see §2.

---

## 2. Stating the missing rule raised recall and did not improve consistency

Completeness rules were added to the prompt in the same register as the existing shape rules
("a shorter extraction is not a better one"; "every person named inside a quote you cite must
have its own entity"). Measured on both documents at temperature 0, 5 draws per condition:

| | entities (median) | verbatim rate (median) |
|---|---|---|
| suntola, before | 25 | 89% |
| **suntola, after** | **89 (3.6×)** | **65%** |
| aleskovskii, before | 14.5 | 83% |
| **aleskovskii, after** | **26 (1.8×)** | **72%** |

**Recall rose on both documents. Consistency did not improve, and on the second document it
got markedly worse:**

| CV across draws | suntola before → after | aleskovskii before → after |
|---|---|---|
| entities | 34.3% → 36.4% | **13.6% → 48.8%** |
| events | 21.1% → 12.9% | **6.5% → 27.3%** |
| relations | 14.6% → 6.2% | 13.8% → 14.2% |

Suntola alone suggested the rules stabilised output; the second document reversed that. **The
rules are a recall intervention, not a consistency fix**, and the paper must not claim
otherwise.

**The fidelity cost is misquotation, not fabrication.** Splitting the verbatim drop by the
checker's own 5-word-shingle threshold:

| | quotes | fabricated | misquoted |
|---|---:|---:|---:|
| suntola before | 168 | 2 (1.2%) | 18 (10.7%) |
| suntola after | 248 | **1 (0.4%)** | 74 (29.8%) |
| aleskovskii before | 321 | 2 (0.6%) | 46 (14.3%) |
| aleskovskii after | 230 | 4 (1.7%) | 44 (19.1%) |

Fabrication stayed at or below 1.7% throughout and fell on one document. The system quotes more
material and copies it less exactly; it does not invent more.

**Does not support:** that the trade is free. It costs 11–24 points of verbatim rate.

---

## 3. Grounding audit of the shipped corpus: 2.6% of quotes are absent in any form

233 subjects, **5,394 quotes checked**, 19 subjects excluded (see below):

| | |
|---|---:|
| quotes verbatim | **85.9%** |
| misquoted (present, not verbatim) | 10.2% |
| **absent in any form — the fabrication rate** | **2.6%** |
| entity names present in the source | **98.3%** (4,591 checked) |
| citation reach (citations carrying a quote) | 97.6% |

**Reaching 2.6% took four corrections, and the sequence is itself the argument for the check.**
Each intermediate number would have supported a different and wronger claim: the tool's summary
line reports **21.2%** "not verbatim"; separating fabrication from misquotation gives **11.9%**;
a diagnostic on the flagged set gives **9.9%** (the model sometimes emits a quote with its
whitespace destroyed, e.g. `'developedbyEmilvonBehringandShibasaburoKitasatoin1890'`); and
excluding subjects whose source text no longer existed gives **2.6%**.

**The check found a silent provenance bug.** Source text was staged as `data/<slug>.txt`, keyed
by subject while document folders are keyed by document, so a subject's second document
overwrote the first one's text while both still pointed at that path. **19 subjects, 41
documents** had their quotes checked against papers they never came from. The failure was
silent, looked exactly like hallucination, and **no relation-level benchmark could have
surfaced it** — none of them ever compares the graph to the document. A quarter of the apparent
hallucination rate was a filename.

**Does not support:** 2.6% as a precise fabrication measurement. Five subjects whose quotes all
fail while 80–100% of their entity names are present carry 35% of the flagged quotes; those are
document-mismatch rather than invention, so 2.6% is an **upper bound**.

---

## 4. The scope gate admits only technology-biography, and it is the only obstacle

Eight English Wikipedia biographies of named people, identical in source, format and length
(12,000 characters), varying **only** the subject's field:

| field | verdict |
|---|---|
| literature, art, sport, music, politics | refused **0/5** |
| aviation, nursing/statistics | admitted **2/2** |
| computing (positive control) | admitted **1/1** |

All five refusals cite the *same* clause — "not a person whose life was intertwined with a
specific technology's development" — and **none** cites the named-subject clause. So the gate
asks "is this the biography of a technology, told through a person?", not "is this a
biography?". Clinical case reports (PMOA-TTS) are refused **9/9**, invariant to three input
framings, for an additional and more structural reason: they are de-identified by construction.

**The ablation.** `--ignore-scope` records the verdict but does not enforce it, swapping one
prompt sentence. Over the same 8 documents: **8/8 produce a graph, the verdict itself
unchanged**, and the five refused documents extract at the quality of the admitted ones —
**277/278 quotes verbatim (99.6%), 5/5 validating**. The genre precondition was the only
obstacle.

**Does not support:** any generalization claim from a gate-on run of a general-biography
corpus. Gate-on measures the admission policy; gate-off measures the extractor. They are
reported as two conditions and never averaged.

---

## 5. Most models cannot perform this task, and they fail in distinguishable ways

Six models attempted the extraction. Usable draws:

| model | attempts | usable | failure |
|---|---:|---:|---|
| `qwen3.5-397b-a17b` | 40 | **40** | — |
| `claude-fable-5.1` | 9 | **1** | 8 were provider budget, not capability |
| `meta-llama-3.1-8b-instruct` | 1 | 1 | produced output but **violated the enums** (invented `entity_type: "event"`, `event_type: "presentation"`) |
| `mistral-medium-3.5-128b` | 5 | **0** | 3 returned valid **empty** JSON, 2 timed out |
| `qwen3.8-27b` | 5+1 | **0** | timed out at 2400s; later attempts were provider budget |
| `glm-5.3-flash` | 1 | **0** | timed out at 3600s |

A separate provider probe — same endpoint, a **generic** 16k-token structured-output task with
generated prompts — found **11 of 14 models complete it correctly**. So the endpoint is healthy
and the difficulty is specific to this task, not to long output in general. The probe also
separated the causes: reasoning tokens consumed `max_tokens` before any content
(`qwen3.8-27b`: 0 content characters, 28,781 reasoning characters), a 20,080-token context
limit, a model returning `finish_reason: tool_calls` with no content, and one taking 903s on a
one-sentence prompt against 146s on one 400× larger.

**The useful claim:** schema-constrained extraction at this output length is not portable across
models. Three failure modes — too slow, cannot hold a closed vocabulary, and **vacuously
compliant** (valid empty JSON that satisfies every constraint trivially) — each need a different
response, and the third is the one that looks like success.

**Does not support:** a model *quality* comparison. No two models were measured under one
prompt with enough draws, and `claude-fable-5.1`'s single draw — 110 entities, **211/215 quotes
verbatim (98%)** — is both the best result observed and n=1 on a prompt version nothing else
used.

---

## Sample sizes and what they bear

- §1: 40 runs, 9 conditions, one model. Strong.
- §2: 5 draws per condition, two documents. Direction is unambiguous (3.6× is not noise); the
  multipliers are not precise, and **no difference here reaches significance** — F(4,4) needs
  ≈9.6 and the largest variance ratio observed is 5.0.
- §3: full corpus, 5,394 quotes. Strong, with the upper-bound caveat.
- §4: 8 documents, 1 draw each, with a positive control. The separation is perfect (0/5, 2/2,
  1/1), which is what makes n=1 per document tolerable.
- §5: counts of attempts, not a controlled comparison.

Extraction samples at temperature 0.2 by default; §1, §2 and §4's ablation were run at
temperature 0. A single run is a draw, not a score.
