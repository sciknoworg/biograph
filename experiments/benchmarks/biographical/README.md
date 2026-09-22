# Benchmark 1 — Biographical (Plum et al., SIGIR 2022)

Sentence-level biographical relation extraction over Wikipedia/Wikidata. Label space:
`birthdate`, `birthplace`, `deathdate`, `deathplace`, `occupation`, `ofParent`,
`educatedAt`, `hasChild`, `sibling`, `other`.

This is the benchmark that carries the paper's generalization claim. PMOA-TTS asks
whether the pipeline survives a different **genre**; this one asks whether it survives a
different **population** — writers, politicians, athletes and artists rather than
scientists and engineers, with the extractor, prompt and schema unchanged.

## Status

The adapter is complete and tested. **No data has been downloaded**, because the licence
is unresolved (see below), so it has never been run against the real corpus. Every number
it can produce today comes from synthetic rows or from projecting biograph's own existing
subjects.

## Licence — resolve before downloading

The repository is GPL-3.0, but **the data licence is not stated** and the corpus is
distributed via Google Drive. It is Wikipedia-derived, so CC BY-SA applies upstream.
Nothing here downloads anything: `load()` reads a local copy via `--data-root`.

## It must be run in both conditions

The scope gate refuses this population. That is measured, not assumed: eight Wikipedia
biographies of named people, identical in source, format and length, varying only the
subject's field, split **0/5** for literature, art, sport, music and politics against
**2/2** for aviation and nursing/statistics, with computing as a passing control
(`experiments/docs/scope-gate-boundary.md`).

A refused document produces no graph at all, so a gate-on run of this benchmark scores
0.00 for reasons that have nothing to do with extraction quality. Run both:

```bash
# the admission policy: how much of a general biography corpus is refused
python -m experiments.harness.cli --benchmark biographical --data-root <dir> --limit 50

# the extractor: what it does on the documents the gate refuses
python -m experiments.harness.cli --benchmark biographical --data-root <dir> --limit 50 --gate-off
```

They are two rows in the results table and are **never averaged together**.

## The four awkward joins, and what this adapter does about each

**1. Sentence-level gold, document-level extractor.** Biographical annotates single
sentences; biograph reads a document about one person. A lone sentence has no
biographical arc, and one extraction per row would cost a model call per annotation. So
the input adapter **groups by person**: every sentence about one subject becomes one
pseudo-document, extracted once, and that person's whole gold set is scored against it.

This is the most consequential choice in the adapter and is disclosed in
`BenchmarkDoc.transform` as `grouped_by_person`. It cuts both ways — more context per
decision, but the model must now attribute each fact to the right person among everyone
the sentences mention. **It also means these figures are not comparable to the paper's
sentence-level numbers**, which is why `published_baseline` is empty rather than filled
with numbers measured under a different setting.

**2. The dated labels are not relations in biograph.** `birthdate` and `deathdate` live
in `events.json` as `event_type` birth/death carrying a `FuzzyDate`, so they are read
from there. `birthplace`/`deathplace` have two routes — the `born_in`/`died_in` relation,
and the birth/death event's own `location` — and the adapter takes their **union**,
deduplicated, since a gold sentence states the fact once and either route finding it is a
hit.

Dates are scored by **interval containment**, not string equality: a year-precision
prediction against a day-precision gold is right to the precision the source offered.
The median predicted interval width is reported alongside, so a containment rate achieved
by predicting a decade is visibly not the same result as one achieved by predicting a day.

**3. `family_of` collapses three labels.** `ofParent`, `hasChild` and `sibling` are one
relation type in the schema. The subtype survives in the free-text `note` for 35% of
corpus instances ("Father", "youngest son"), and direction is recovered relative to which
end of the relation the subject sits on. Reported as combined family recall over all of
it, with per-subtype figures over the note-bearing subset only, labelled as such. Every
collapse is recorded in `Prediction.lossy`.

**4. `occupation` has no typed home.** `entity.subtype` is free text — the literal string
`'researcher'` for 1,393 of 1,975 corpus person entities — and `entity.summary` is prose.
Neither is a controlled slot, so `occupation` is reported `not_applicable` and **excluded
from every macro-average**. Scoring it 0 would understate the pipeline for a label it was
never asked to produce; scoring it at all would claim a capability the data model lacks.

## Reading the file format

The release is not in hand, so `load()` **sniffs the header** against `COLUMN_ALIASES`
rather than assuming column names, and refuses with the header it actually saw if it
cannot resolve all four fields. It does not guess: a silently mis-read column produces a
plausible, wrong results table, which is worse than an error.

Add the real column name to `COLUMN_ALIASES` when the release arrives.

## Four bugs the corpus itself caught

The adapter was developed against biograph's own 233 subjects, which is the only real
extraction data available before the licence is resolved. That found four defects that
synthetic rows would not have:

| bug | what it did |
|---|---|
| `location` read as a name | it is an **entity id** per `schema/event.schema.json`; Turing's birthplace came out blank |
| participation read as subjecthood | gave Fritz Haber a death date of 1 May 1915 — **Clara Immerwahr's** — because he appears in that event |
| both birthplace routes emitted | Suntola predicted `Tampere, Finland` twice, the spare one scoring as a false positive |
| dangling target ids emitted as `""` | a relation pointing at an id with no entity behind it manufactured an empty prediction |

All four are locked in by `experiments/tests.py`
(`test_biographical_projection`), which needs no model and no network.
