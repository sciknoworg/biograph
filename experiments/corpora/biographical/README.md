# Benchmark 1 — Biographical: provenance

The corpus is **not redistributed here**. This folder records where it comes from and what
it carries. The data beside this README is gitignored.

## Source

| | |
|---|---|
| paper | *Biographical: A Semi-Supervised Relation Extraction Dataset* |
| authors | Plum, Ranasinghe, Jones, Orăsan, Mitkov |
| venue | SIGIR 2022 |
| DOI | https://doi.org/10.1145/3477495.3531742 |
| arXiv | https://arxiv.org/abs/2205.00806 |
| dataset | https://huggingface.co/datasets/plumaj/biographical |
| file used | `en/m2_gold.tsv` |

The project page cited in the paper (`plumaj.github.io/biographical`) redirects to
`ajplum.com/biographical`, which did not respond in October 2026. The HuggingFace release
is the live location, pointed to by the first author.

## Licence

**CC BY-SA 4.0**, stated by the first author in correspondence (October 2026).

Cite it as the author's statement, not the repository's: the HuggingFace card's
"Licensing and Citation" section is an unfilled template placeholder. Worth asking them to
fill it in, since that is what a reviewer will check. The corpus is Wikipedia-derived,
which is CC BY-SA 4.0 upstream as well, so **share-alike applies to derived artifacts** --
settle that before publishing anything built from it.

## Obtaining it

```bash
mkdir -p experiments/corpora/biographical
curl -L -o experiments/corpora/biographical/m2_gold.tsv \
  https://huggingface.co/datasets/plumaj/biographical/resolve/main/en/m2_gold.tsv
```

### The nine English files, and why only one is used

| file | size | what it is |
|---|---:|---|
| **`m2_gold.tsv`** | **678 KB** | **human-annotated gold. The only file used.** |
| `m2_train.tsv` / `m2_test.tsv` | 59 / 7 MB | `normal` processing, distant supervision |
| `m2_coref_train/test.tsv` | 70 / 9 MB | with automatic coreference resolution |
| `m2_skip_train/test.tsv` | 34 / 4 MB | first sentence of each article skipped |
| `m2_comb_train/test.tsv` | 145 / 20 MB | the three combined, deduplicated |

The train/test files are **automatically aligned, not human-checked**. Their label noise is
measurable from the gold file itself: `relation` (the automatic label) and `ANNOTATION` (the
human one) disagree on 578 of 2,900 rows, 20%.

This pipeline is zero-shot, so there is nothing to train on, and evaluating against
distant-supervision labels would measure agreement with a signal already known to be 20%
wrong. `m2_gold.tsv` is also what the paper's own models are evaluated on, so using it
keeps the evaluation set shared even though the task is not.

## What the paper reports, and why it is not a bar this run clears

The paper trains BERT-base on each distant-supervision set and evaluates **on this same
gold file**. So the evaluation set is shared -- the difference is the task.

**Their task is 10-way classification over a pair someone already found.** The model is
handed a sentence with `<e1>` and `<e2>` marked and picks one label, including `other`.
**This pipeline is handed raw text with no pair**, and must find the entities, decide which
are related, and type the relation. Recall there is over pairs presented; recall here is
over facts nobody pointed at.

Table 5, BERT trained on `normal`, evaluated on gold -- macro **P 0.90 / R 0.73 / F1 0.76**
(coref 0.78, skip 0.74, all 0.78):

| relation | P | R | F1 |
|---|---:|---:|---:|
| birthdate | 1.00 | 0.99 | 1.00 |
| deathdate | 1.00 | 0.95 | 0.97 |
| occupation | 1.00 | 0.99 | 1.00 |
| educatedAt | 0.98 | 0.87 | 0.92 |
| birthplace | 0.85 | 0.77 | 0.81 |
| ofParent | 0.92 | 0.54 | 0.66 |
| deathplace | 0.73 | 0.53 | 0.62 |
| sibling | 0.92 | 0.45 | 0.57 |
| hasChild | 0.96 | 0.36 | 0.42 |
| other | 0.38 | 0.95 | 0.54 |

Table 4 scores the **matching algorithm itself** against the same gold, macro F1 **0.83**.
That is the more honest of the two references: a label the distant supervision got wrong is
a label the classifier was taught wrong, so 0.83 is the ceiling 0.76 was trained toward.

Both are recorded in the adapter as `reference_classifier` and
`reference_matching_macro_f1`, deliberately kept **out** of `published_baseline` so no
report renders them as a bar this run cleared or missed.

## What is in it

2,900 rows over 2,748 Wikipedia pages, in three annotation variants (`set` = `m` 995,
`c` 906, `s` 999; only 13 sentence strings repeat across them, so all three are used).

```
sentence                                        relation  P1 P2 ANNOTATION wp_id
<e1>Emily Seebohm</e1>, OAM ( born 5 June 1992 ) occupation e1 e2 occupation 16844751
is an Australian ... <e2>swimmer</e2>.
```

**The two arguments are `<e1>`/`<e2>` spans inside the sentence, not columns**, and `P1`
names which one is the subject -- `e1` in 2,473 rows and `e2` in 427. Reading `e1` as the
subject always would invert one row in seven, because a sentence can introduce the date
before the person.

**`ANNOTATION` is the gold label; `relation` is the distant-supervision guess.** They
disagree on **578 of 2,900 rows (20%)**, and not symmetrically: annotators reclassified
heavily toward `Other` (808 against 295). Scoring against `relation` would measure
agreement with a signal already known to be noisy.

## What the adapter builds

| | |
|---|---:|
| documents (Wikipedia pages) | **2,748** |
| median document length | 141 characters |
| median sentences per document | **1** |
| gold facts | 2,844 |
| facts in scored labels | **1,826** |
| documents with ≥1 scored fact | 1,800 |
| rows unusable | **0** |

Gold by label: `other` 785 · `birthdate` 296 · `deathdate` 286 · `birthplace` 282 ·
`educatedAt` 266 · `occupation` 233 · `ofParent` 216 · `sibling` 203 · `hasChild` 173 ·
`deathplace` 104.

Release label names are mapped explicitly: `bplace_name`→`birthplace`,
`dplace_name`→`deathplace`, `parent`→`ofParent`, `child`→`hasChild`, `Other`→`other`.
An unmapped gold label is counted, never silently dropped -- it would otherwise score as a
permanent miss while the run looked healthy.

**Grouping is by `wp_id`, not by subject string.** The subject strings are surface forms,
so grouping on them merges different people: the most frequent are `Lee`, `Adams` and
`Johnson`. A page id is one person by construction. 37 pages carry two name variants of
that one person (`Thomas Wyatt` / `Wyatt`); the longest is used as the document name.

## Two things to know before running it

**Gate-off only.** The population is writers, politicians and athletes, which the scope
gate refuses 0/5 in a controlled probe. A gate-on run is 0.00 by construction.

**`occupation` is reported not-applicable.** `entity.subtype` is free text -- the literal
string `'researcher'` for 1,393 of 1,975 person entities -- and `entity.summary` is prose.
Neither is a controlled slot, so it is excluded from the macro average rather than scored
zero. That removes 233 of the 2,844 gold facts from scoring.
