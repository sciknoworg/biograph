# Benchmark 2 — Biographical Events: provenance

The corpus is **not redistributed here**. This folder records where it comes from and what
it carries, so a reproduction can obtain the same file and a reader can check the licence
without taking either on trust. The data that lands beside this README is gitignored.

## Source

| | |
|---|---|
| paper | *Guidelines and a Corpus for Extracting Biographical Events* |
| authors | Stranisci, Mensa, Diakite, Radicioni, Damiano |
| venue | ISA-18 @ LREC 2022 |
| ACL Anthology | https://aclanthology.org/2022.isa-1.3/ |
| arXiv | https://arxiv.org/abs/2206.03547 |
| repository | https://github.com/marcostranisci/bio-srl *(the paper cites `marcostranisci/biographicalEvents`, which redirects here)* |
| file | `biographical_events_corpus.csv`, repository root |

## Licence

**The paper is CC BY 4.0**, stated by the ACL Anthology: "Materials published in or after
2016 are licensed on a Creative Commons Attribution 4.0 International License."

**The corpus declares no licence of its own.** There is no `LICENSE` file in the
repository and no licensing statement in the paper. It is published openly, and it is
derived from English Wikipedia, which is CC BY-SA 4.0 upstream.

What this project does about that: **uses it, cites it, does not redistribute it.** The
adapter never downloads anything; it reads a local copy via `--data-root`. If a derived
artifact of this corpus is ever published, the CC BY-SA share-alike question has to be
settled first, and it has not been.

## Obtaining it

```bash
mkdir -p experiments/corpora/bioevents
curl -L -o experiments/corpora/bioevents/biographical_events_corpus.csv \
  https://raw.githubusercontent.com/marcostranisci/bio-srl/main/biographical_events_corpus.csv
```

## What is in it

1,488 annotated sentences over **757 distinct subjects** — roughly two sentences per
person — drawn from English Wikipedia biographies of underrepresented writers.

One row is one sentence. The annotation columns hold the **span text**, not an IOB tag:

```
author,sent_id,text,ARGx-LOC,STATE,TIME,WRITER-ARG0,REP-EVENT,EVENT,ARGx-ORG,ASP-EVENT,WRITER-ARGx,lemma
Q1064470,11,"...he dropped out of...  (Charles Fuller)",,,,he,,drop,,,,drop
```

`author` is the person the biography is **about**, not the annotator. Every `text` ends
with the subject's name in parentheses (1,486 of 1,488 rows); the adapter strips it and
uses it as the document name.

Trigger counts: `EVENT` 861 · `STATE` 627 · `ASP-EVENT` 85 · `REP-EVENT` 42.
Role counts: `WRITER-ARG0` 1,089 · `ARGx-ORG` 601 · `ARGx-LOC` 505 · `ARGM-TIME` 481 ·
`WRITER-ARGx` 388.

4,679 of 4,682 annotations (99.9%) are locatable verbatim in their own sentence; the three
that are not are dropped and counted in `meta.unlocatable_annotations`, never matched to
something nearby.

## Two things to know before running it

**Gate-off only.** The corpus is biographies of writers, and the scope gate refuses
writers 0/5 (`experiments/docs/scope-gate-boundary.md`). A gate-on run would be 0.00 by
construction, for reasons that have nothing to do with extraction. Pass `--gate-off`.

**757 documents is 757 extraction calls**, and the median document is ~220 characters.
`--min-triggers` trades coverage for budget; `--limit` caps the run.
