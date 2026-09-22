# Benchmark 5 — Grounding

Does the extractor cite text that is actually there?

The only one of the five with no external corpus, no licence question and no model call.
The gold is the source document itself; the check is a string search. Every
`sources[].quote` must occur verbatim in the text the model read, and every entity name
must appear in it too.

## Why it earns a slot

Benchmarks 1–4 ask whether the extracted graph agrees with someone else's annotations.
**None of them asks whether it agrees with the document.** An extraction can score well on
a relation benchmark while citing a quotation nobody wrote, and that failure is invisible
to every other metric here.

It is also the failure that matters most for a corpus meant to be cited. A wrong relation
is an error; a fabricated quotation is a different kind of thing.

## What it is not

This audits the corpus that already exists. There is no train/test split and nothing is
predicted about unseen data. The generalization claim rests on benchmarks 1 and 2 — this
one rests on nothing but the corpus's own honesty, which is exactly what it is for.

## Read the fabrication rate, not the verbatim rate

The two failure modes are not the same finding and are never added together:

| score | meaning |
|---|---|
| `quote_fabrication_rate` | under half the quote's 5-word shingles appear in the source — **the hallucination number** |
| `quote_misquotation_rate` | most of it is present but not verbatim — over PDF-extracted text, usually a curly quotation mark, a ligature or a line-break hyphen |
| `quote_verbatim_rate` | the two combined; useful, but not a hallucination measure |

`check_grounding` already draws this distinction by shingle overlap. This adapter tallies
it from the checker's own issue lines rather than recomputing it.

The gap is large and it matters. Measured over Wikipedia plain text (the scope probe), the
verbatim rate was 99.5%. Over the PDF-derived corpus it is far lower — and almost all of
the difference is misquotation, not invention.

## The check is never reimplemented here

`build_site.py --check-grounding` already does it, including the details that make it
fair:

- whitespace and hyphenation are flattened first, because PDF extraction introduces both
- an elided quote (`... [...] ...`) is split on the ellipsis and each fragment checked
  separately, rather than being reported as fabricated
- entity names match on their longest word, so a document writing "J. B. Goodenough"
  satisfies a graph entity named "John B. Goodenough"
- overlap is measured in 5-word shingles, so "off by one word" and "invented outright" are
  separable

Reimplementing any of that would produce a second, subtly different checker and a number
that does not describe the shipped tool. This adapter shells out and parses, like the rest
of the harness.

## Reach is part of the result

`quote` is optional in the schema — "only for pivotal events, not every one" — so the
check cannot reach a citation carrying only a page number. `citation_reach` is reported
beside the rates, because a perfect verbatim rate over 18% of citations is not the same
claim as one over 98%.

## No sandbox, deliberately

The other benchmarks need one because `build_site.py` writes into `subjects/` as a side
effect of extraction. `--check-grounding` writes nothing at all, and `subjects/` is the
*subject* of this measurement rather than somewhere to put its output. The core's SHA-256
and the git commit are still recorded, so the report still says exactly which checker
produced the numbers.

## Running

```bash
python -m experiments.harness.cli --benchmark grounding
python -m experiments.harness.cli --benchmark grounding --limit 20
```

No `--data-root`, no API key, no network. Roughly one subprocess per subject.

Benchmarks 1–4 get the same figures for their own runs through `Runner.check_grounding`,
which shells out to the same checker; `score()` here aggregates those reports too, so a
benchmark run and the corpus audit are on the same footing.

## Measured over the corpus, 2026-09-22

233 subjects, 19 excluded (see below), 5,394 quotes checked.

| | |
|---|---:|
| quotes verbatim | **85.9%** |
| misquoted (present, not verbatim) | 10.2% |
| flagged NOT IN SOURCE by the checker | 4.0% |
| of those, recovered by ignoring whitespace or case | 70 of 213 |
| **not in the document in any form** | **2.6%** |
| entity names present | **98.3%** |
| citation reach | 97.6% |

Read the 2.6% as the fabrication rate. Getting to it took four corrections, each of which
would have supported a different and wronger claim: the raw summary line says 21.2% "not
verbatim"; splitting fabrication from misquotation gives 11.9%; the whitespace diagnostic
gives 9.9% (the model sometimes emits a quote with its spacing destroyed,
`'developedbyEmilvonBehringandShibasaburoKitasatoin1890'`); and excluding the subjects
whose source text was overwritten gives 2.6%.

## 19 subjects are excluded, because of a staging bug

Source text is staged as `data/<slug>.txt` -- keyed by the **subject**, not the document.
When a subject gains a second document, the first one's text is overwritten, and both
`sources.json` files still point at that single path. Every quote from the losing document
is then checked against a paper it never came from.

`berthollet` is the clean case: `sztejnberg_2020` and `weller_1999` both cite
`data/berthollet.txt`, which holds only the Weller paper. "He graduated from the Turin
University in 1770" is almost certainly verbatim in a document that is no longer on disk.

**19 subjects, 41 documents.** They are excluded from every rate and counted in
`attrition.subjects_excluded_source_overwritten`, because scoring a quote against text
that is not there measures the staging layout and nothing else. This is a provenance bug
in the pipeline, not an extraction failure, and the affected quotes are unverifiable
rather than wrong.

Fixing it forward means staging per document (`data/<slug>__<citation_key>.txt`). Recovering
the lost text is a separate question; the manifest records DOI, URL and provider for each
source.

## One caveat in the shipped behaviour

`--check-grounding` concatenates **every** source file belonging to a subject before
searching, so a quote from one document is checked against that subject's whole corpus.
That is slightly more permissive than per-document checking. It is the shipped behaviour
and is reused as-is rather than being quietly tightened here.
