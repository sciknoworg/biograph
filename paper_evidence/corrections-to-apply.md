# Corrections to apply to the existing draft

The current draft was written from an earlier version of the briefs. Six claims in it are
now wrong. Attach this alongside the briefs and the paper, and apply these as edits.

Every figure below is re-derived at commit `3fd799a` (2026-10-02), backed by 53 assertions
over the repository and the run artifacts.

---

## 1. Quotes are mandatory, not optional

**Delete any sentence saying `quote` is optional, or "only for pivotal events, not every
one".** Quotes have been required for all new extraction output since 2026-09-06, enforced
in the schema, in the prompt, and by a pre-write check that raises.

**If the draft explains citation reach (97.6%) as a consequence of optional quotes, replace
that explanation.** All 162 quoteless citations are in two document folders — the two
founding subjects, which predate the requirement. 258 of 260 documents are at 100%.

## 2. The grounding sequence is two corrections, not four

**Delete the chain `21.2% → 11.9% → 9.9% → 2.6%`.** The denominator changes mid-chain, and
`9.9%` is not re-derivable from any saved artifact.

Replace with two independent corrections:

- Over all 233 subjects: the tool reports **21.2% not verbatim** (1,382 of 6,516 quotes);
  the 5-word shingle split gives **11.9% flagged** (773).
- Post-exclusion, of 213 flagged quotes: 70 recover on whitespace or case, 4 are
  unresolvable, **139 are absent in any form — 2.6% of 5,394**.

2.6% remains an **upper bound**, not a measurement.

## 3. Corpus volume is not current-prompt output

**This is the one that must be added, not just corrected.** Every one of the 233 subjects
was extracted before the completeness rules landed (`a155c27`, 2026-09-29), and no commit
has touched `subjects/` since. The current prompt yields **1.8–3.6× more entities** on the
same documents.

So: entity, event and relation counts describe the earlier prompt. Say so wherever a count
appears near the completeness multiplier. Subject counts, document counts, domain
composition, the access table, geocoding, portraits and every grounding figure are
unaffected.

## 4. Completeness governance is the organising finding

If the draft treats the completeness rules as a prompt refinement, reframe. The result is
that a prompt governs **exactly** the properties it states — five governed properties at
100% with zero variation across 40 runs — and has **no** influence on properties it leaves
unstated, where person count varies at CV 28.6–62.1%.

And the counterweight, which must appear with it: stating the rule **raised recall and did
not improve consistency.** On Aleskovskii it made consistency four times worse
(entity CV 13.6% → 48.8%). No difference reaches significance at n=5.

## 5. B5's coverage gaps are two legacy documents

If the draft says the 13 event/relation types below 95% citation reach reflect weak
provenance or low-n commercial types, that is wrong. They are the types those same two
founding documents happen to be dense in.

## 6. Smaller figure corrections

| in the draft | correct |
|---|---|
| 137 self-checks | **138** |
| basemap 436 KB, 89% of a page | **426 KB, ~87%** |
| 115 pages total 116 MB | **115 MB** |
| graph isolation 41.2% → 23.8% | **41.2% → ~24%** (the decimal was never real) |
| 35 runs | **40 runs, 9 conditions** |

---

## Qualifiers that must survive editing

Each marks a claim the evidence specifically fails to license. Do not soften any into
"may", and do not write past one.

- **2.6% is an upper bound.** Five subjects whose quotes all fail, while 80–100% of their
  entity names are present, carry 35% of the flagged quotes — document mismatch, not
  invention.
- **No difference in the completeness result is significant at n=5.** F(4,4) needs ≈9.6;
  the largest ratio observed is 5.0. The direction is reportable; the multipliers are not
  precise.
- **A single extraction is a draw, not a score.** Temperature 0 is not determinism: the
  served model is a mixture-of-experts whose routing depends on request batching.
- **A gate-on run measures the admission policy, not the extractor.** The two conditions
  are reported separately and never averaged.
- **The corpus is not representative** of the history of science. Four filters shape it,
  including an inverse bias against fame — Einstein, Curie, Darwin, Newton, Faraday and six
  others are all absent.
