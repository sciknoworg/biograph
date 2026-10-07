# Benchmark 3 — WikiLifeTrajectory: provenance

The corpus is **not redistributed here**. This folder records where it comes from and what
it carries. The data beside this README is gitignored.

## Source

| | |
|---|---|
| paper | *Paths of A Million People: Extracting Life Trajectories from Wikipedia* |
| authors | Ying Zhang, Xiaofeng Li, Zhaoyang Liu, Haipeng Zhang |
| venue | ICWSM 2025 |
| DOI | 10.1609/icwsm.v19i1.35930 |
| arXiv | https://arxiv.org/abs/2406.00032 |
| repository | https://github.com/ZhangDataLab/COSMOS |
| file used | `data/regular.pkl` |

## Licence — unresolved

**The repository states no licence and contains no LICENSE file.** The paper's terms do not
cover the annotations; "publicly downloadable" is not "licensed for redistribution."

The corpus is Wikipedia-derived, so **CC BY-SA 4.0 applies upstream**, which means
share-alike would attach to any derived artifact published from it.

What this project does: **uses it, cites it, does not redistribute it.** The adapter never
downloads anything and reads a local copy via `--data-root`. **Settle the licence with the
authors before publishing any artifact derived from these annotations.**

## Obtaining it

```bash
mkdir -p experiments/corpora/wikilife
curl -L -o experiments/corpora/wikilife/regular.pkl \
  https://raw.githubusercontent.com/ZhangDataLab/COSMOS/main/data/regular.pkl
```

`data/` also holds `representative_train.pkl` (6,004 rows) and `representative_test.pkl`
(2,574). **Those are deliberately not used.** They are the candidate-triplet classification
set: each row is a triplet a generator already produced from a sentence, labelled true or
false, for training and testing a binary classifier. That is not the task this pipeline
performs, and its negatives exist only to support it.

*The release is a pandas pickle, which executes code on load. Before first use the opcodes
were disassembled: the only constructors referenced are `pandas`, `numpy` and `builtins` —
no `os`, `subprocess` or `eval`.*

## What is in it

`regular.pkl` is **274 manually annotated positive trajectory facts over ten complete
Wikipedia biographies**. Every row is `label=True` and `source=manual`; the partition
contains no negatives.

Each row carries `raw_label` = `[person, time, location, True, 'manual']`, the sentences
that evidence it, the containing `paragraph`, and `sample_source` — the biography's title.

| biography | gold facts | characters | unanchorable times |
|---|---:|---:|---:|
| Charles de Gaulle | 57 | 88,469 | 15 |
| Andrzej Grzegorczyk | 44 | 51,350 | 0 |
| Qian Songyan | 42 | 15,711 | 9 |
| Warith Deen Mohammed | 34 | 18,507 | 0 |
| Imran Khan | 28 | 33,483 | 1 |
| Steve Rothman | 24 | 13,395 | 0 |
| Robert Bloch | 19 | 31,183 | 1 |
| Homero Aridjis | 12 | 8,696 | 0 |
| Stillman Witt | 9 | 6,996 | 0 |
| Terunofuji Haruo | 5 | 9,659 | 1 |
| **total** | **274** | **277,449** | **27** |

**These are the only full-length documents in the whole evaluation suite.** Median 17,109
characters against 147 for BiographicalEvents and 131 for Biographical, and within an order
of magnitude of this project's own corpus median of 35,305.

## Three properties that shape the adapter

**Documents are rebuilt from the release, not fetched.** Each row carries its `paragraph`,
and the 94 distinct paragraphs reassemble into ten documents. Fetching the live article
would be closer to "the complete page", but the annotation is from 2024 and an article
edited since could silently drop gold facts, turning drift into apparent recall failure.
Rebuilding is reproducible and guarantees every gold fact's evidence is present. The cost:
paragraphs holding no trajectory fact are absent, so the input has fewer distractors than a
real page. Disclosed as `rebuilt_from_paragraphs`.

**The gold person is often not the subject.** Charles de Gaulle's 57 facts name him 39
times across four surface forms — `de Gaulle`, `De Gaulle`, `Charles de Gaulle`, `he` — and
name eighteen other people including Churchill and Eisenhower. Matching is against any
extracted person, on the longest significant word, with bare pronouns resolved to the
document subject.

**Time is heterogeneous, and 27 facts are unanchorable.** Of 274 gold times: 118 bare
years, 63 full dates, 44 month-year, 13 year ranges, and 27 carrying no year at all — `13
June`, `six months`, `the following year`, `70 years old`, `five`. No system can place
those on a timeline, so they are reported as `unanchorable_time` and excluded from the
denominator rather than scored as misses.

## Recall only — precision is not measurable

**Every gold fact is positive.** An extracted fact absent from gold may be a true fact the
annotators did not mark — their unit is the trajectory, not the life — so counting it as a
false positive would punish the extractor for reading more of the document than the
annotation covers. Unmatched extractions are reported as `unmatched_predictions`, never as
errors.

## There is a published number, and it is not a baseline

The paper reports roughly **82.1% trajectory recall** for COSMOS on this same `regular`
partition, and 85.95 F1 on the `representative` test.

Neither is a bar this run clears or misses. **COSMOS classifies candidate triplets that a
generator has already produced from a sentence**: the person, the time and the location are
all handed to it and it decides true or false. This pipeline receives a whole biography and
must find the people, the dates and the places, and decide which belong together. Their
recall is over candidates presented; this recall is over facts nobody pointed at.

Recorded in the adapter as `reference_cosmos_regular_recall`, deliberately outside
`published_baseline` so no report can render it as a bar.

## Before running it

**Gate-off only.** The population is a French general, a Polish logician, a Chinese painter,
a cricketer-politician, a sumo wrestler and an American congressman — the inclusion criteria
refuse all of it. Pass `--gate-off`.

Ten documents, so ten extraction calls, but they are long: 277,449 characters in total
against 43,674 for the 220-document BiographicalEvents run.
