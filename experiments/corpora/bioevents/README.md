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

**The paper is CC-BY-NC-4.0**, stated in the proceedings footer printed on the PDF itself:
"European Language Resources Association (ELRA), licensed under CC-BY-NC-4.0".

The ACL Anthology's landing page shows its generic banner -- "Materials published in or
after 2016 are licensed on a Creative Commons Attribution 4.0 International License" --
which is **not** what this paper carries. The ELRA footer is specific and wins. The
non-commercial clause matters; do not cite this as CC BY.

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

## One row is one ANNOTATION, not one sentence

The single most important fact about this file. **654 of the 1,488 rows repeat a sentence
that is already present**, carrying a different trigger in a different column. Q3187801
sentence 14 appears twice with identical text: once as `STATE 'role'` with its location and
time arguments, once as `STATE 'leading'`. In all 417 repeated groups the text is
byte-identical.

So the adapter groups rows by `(author, sent_id)` and emits each sentence **once**, with the
union of every row's annotations. Appending per row instead concatenates the corpus to
exactly twice its real size -- 262,821 characters against 131,204 -- and hands the model
visibly repeated prose.

A repeated `(label, surface)` pair within one sentence is kept only as many times as that
string actually occurs there, and the nth repeat is mapped to the nth occurrence. 415 pairs
repeat; in 166 the surface occurs more than once, and 11 of those are scorable labels
(`EVENT 'published'` twice, `ARGx-LOC 'Philadelphia'` twice) where both are real
annotations at real positions.

## What the adapter builds

| | |
|---|---:|
| rows in the CSV | 1,488 |
| unique (author, sent_id) | 834 |
| documents built | **757** |
| sentences | 834 |
| characters total | 131,204 |
| document length | min 20, **median 147**, max 939 |
| documents containing a date | **410 of 757 (54%)** |

Trigger counts as built: `EVENT` 849 · `STATE` 618 · `ASP-EVENT` 83 · `REP-EVENT` 39 (1,589).
Role counts as built: `WRITER-ARG0` 853 · `ARGx-ORG` 570 · `ARGx-LOC` 460 · `ARGM-TIME` 431 ·
`WRITER-ARGx` 355 (2,669).

Every one of those 4,258 annotations reproduces its own surface from its recorded offsets,
and every one sits inside an annotated sentence span. Three annotations name a string that
is not in their sentence at all; they are dropped and counted in
`meta.unlocatable_annotations`, never matched to something nearby.

**The released CSV holds fewer annotations than the paper describes.** Table 2 of the paper
counts `EVENT` 894, `STATE` 695, `ASP-EVENT` 114, `REP-EVENT` 101, against 849 / 618 / 83 /
39 built here. Part is the one-cell-per-class format, part is the repeat collapsing above.
`REP-EVENT` loses the most, 101 down to 39. Recall against this file therefore uses a
denominator smaller than the annotation effort the paper reports, and that belongs beside
any number computed from it.


## There is no published baseline to compare against

The paper is a guidelines-and-resource paper. No benchmark results are reported.
It includes five tables reproting inter-annotator agreement, corpus counts, the most frequent
events/states, a PropBank argument distribution, and recurring link structures. 

An available quantitative anchor is the **human agreement ceiling**, Table 1, averaged over the
six annotator pairings:

| class | IAA (F) |
|---|---:|
| writer-ARG0 | 0.91 |
| ARGM-TIME | 0.91 |
| writer-ARGx | 0.90 |
| **EVENT** | **0.83** |
| ARGx-ORG | 0.81 |
| ARGx-LOC | 0.75 |
| **STATE** | **0.67** |

Two things in it are worth noticing: **STATE has the lowest
agreement of any class**, so the class this schema refuses to represent is also the one
human annotators agree on least; and **ARGx-LOC ranges from 0.38 to 0.91 across pairings**,
so its average of 0.75 hides a class that annotators were not reliably consistent about.

## Two things to know before running it

**Gate-off only.** The corpus is biographies of writers, and the scope gate refuses
writers 0/5 (`experiments/docs/scope-gate-boundary.md`). A gate-on run would be 0.00 by
construction, for reasons that have nothing to do with extraction. Pass `--gate-off`.

**757 documents is 757 extraction calls**, and the median document is ~220 characters.
`--min-triggers` trades coverage for budget; `--limit` caps the run.
