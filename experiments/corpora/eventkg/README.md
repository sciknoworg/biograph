# Benchmark 5 — EventKG biographical timelines: provenance

The corpus is **not redistributed here**. This folder records where it comes from and what
it carries. The data beside this README is gitignored.

## Source

| | |
|---|---|
| paper | *EventKG — the Hub of Event Knowledge on the Web — and Biographical Timeline Generation* |
| authors | Gottschalk & Demidova |
| venue | Semantic Web 10(6), 2019 |
| benchmark | http://eventkg.l3s.uni-hannover.de/timelines.html |
| file used | `benchmark.tsv` (one file, nine columns) |
| follow-up | EventKG+BT, ESWC 2020 Satellite Events (arXiv:2012.06306) |

## Licence — split, and only half is usable

**The two halves of this benchmark have different licence positions, and that decides what
can be run.**

`wikipedia_score` was derived from **English Wikipedia abstracts**, which are CC BY-SA 4.0
and freely fetchable. **This is the half this benchmark scores.**

`biography_score` was derived from **Thefamouspeople.com and Biography.com** article texts.
Those are third-party copyrighted, the benchmark does not redistribute them, and scraping
them is both a licence and a terms-of-service problem. **That half cannot be scored**, and
is read only to report how much of the benchmark is unreachable.

The relevance judgements themselves carry no stated licence. Used and cited, not
redistributed.

## Obtaining it — two steps

The benchmark ships relevance judgements over knowledge-graph relations and **no text at
all**, so the documents have to be assembled separately.

**1. The gold.** One file. Check the size before and after — it covers 2,760 people and
their full candidate relation pools, so it is large.

```bash
mkdir -p experiments/corpora/eventkg
curl -L -o experiments/corpora/eventkg/benchmark.tsv \
  http://eventkg.l3s.uni-hannover.de/timelines/benchmark.tsv
```

**2. The documents.** Fetched from the Wikipedia API, one lead section per person, pinned to
a revision. Free, no model calls, writes only under `--data-root`.

```bash
python -m experiments.benchmarks.eventkg.fetch_abstracts \
  --data-root experiments/corpora/eventkg --limit 50
```

Omit `--limit` only deliberately: the benchmark has 2,760 people and each one costs a model
call at run time.

## What is in it

One row per **candidate** relation, nine tab-separated columns:

```
entity_label  entity_id  property  connected_entity_label  connected_entity_id
start_date  end_date  biography_score  wikipedia_score

Rachel_Weisz  entity_817926  .../P1346  Academy_Award_for_Best_Supporting_Actress
entity_5589621  2005-01-01  2005-12-31  0.0  1.0
```

The two score columns are **binary relevance judgements** (`0.0` / `1.0`) from the two
biographical sources the authors aligned against. **Positives are a fraction of a percent
of rows**; the rest is the distractor pool their classifier had to reject — Barack Obama has
2,608 temporal relations in EventKG and roughly twelve belong on his timeline.

| | |
|---|---:|
| timeline entities (persons) | **2,760** |
| relevant relations, biography half | 37,638 (13.64 per entity) |
| relevant relations, Wikipedia half | **33,106** (12.00 per entity) |
| person types | actor 28%, musician 16%, athlete 6%, politician 10%, writer 11% |

**The site's field documentation is wrong about two column names.** It documents
`bio_score` and `wiki_score`; the file ships `biography_score` and `wikipedia_score`. The
adapter checks the header and refuses a file that does not match the released format, rather
than loading no gold and reporting zero recall.

## Why the abstracts are pinned to a 2019 revision

The judgements were made against Wikipedia as it stood when the paper was written. Scoring
against today's article would charge seven years of editing to the extractor: an abstract
rewritten since could have dropped a fact the gold says is in it. `fetch_abstracts.py`
resolves each title to its **last revision at or before `--cutoff`** (default `2019-05-21`,
the paper's arXiv submission date) and stores that revision's lead section, recording the
revision id in `abstracts/revisions.tsv`. Disclosed as `revision_pinned`.

**Only the lead section.** The authors built this half from *abstracts*, and `section=0` is
Wikipedia's own definition of one. Fetching whole articles would hand the extractor text the
gold was never aligned against.

## Four things the gold's construction forced

**The same fact arrives under several properties.** Rachel Weisz in *The Whistleblower* is
three rows — YAGO `actedIn`, DBpedia `starring`, Wikidata `P161` — each labelled separately.
Gold is deduplicated on `(connected_entity_id, start_date, end_date)`; the property set is
kept on the fact and both denominators are reported.

**A large share of rows are `wikipedia:link`, which carries no relation type** — only that
two entities are linked and co-temporal. The typed rows are no better behaved: the property
vocabulary spans Wikidata P-numbers, DBpedia ontology terms and YAGO resources, much of it
not biographical (`P170` creator, `P127` owned-by, `P136` genre). **Relation type is named
not-applicable.**

**The dates are knowledge-graph validity intervals, and often belong to the connected entity
rather than to anything that happened to the person.** A `wikipedia:link` row joining
Delacroix to `Vincent_van_Gogh` carries 1853–1890 — van Gogh's lifespan. A row joining
Rachel Weisz to `World_War_II` carries the war's span, labelled relevant because her family
fled it. Date agreement is computed **only** where the connected entity is an EventKG event
or the property is in `DATED_PROPERTIES`; everything else is scored by name alone and
counted in `date_semantics_unusable`.

**Some gold rows have no label.** `connected_entity_label` is `-` for entities EventKG holds
without an English Wikipedia title — and one of them carries Rachel Weisz's birth, as an
unlabelled entity dated `1970-03-07`. Excluded from name matching and reported as
`unlabelled_gold`.

## What is measured

Recall, in two tiers, mirroring B2's and B4's trigger anchoring:

| tier | requirement |
|---|---|
| **strong** | the connected entity is named by an extracted item **and** an extracted event's interval overlaps the gold interval |
| **weak** | the connected entity is named anywhere in the extracted graph |

**Relations carry no date in biograph's schema** — dates live on events — so only an event
can reach the strong tier. A relation or entity match is weak by construction. That is a
property of the data model, not of this benchmark, and it is why the tiers are reported
separately rather than summed.

**No precision**, but the distractor pool is reported. The `0.0` rows are not false: they
are relations EventKG holds which the abstract does not mention. An extraction landing on
one is either a fact the rule-based alignment missed or a fact imported from outside the
document, and this benchmark cannot tell those apart. Reported as `distractor_hit_rate`, a
diagnostic rather than an error count.

## Why this benchmark exists beside the others

**It is the closest published work to this project, and it runs in the opposite direction.**
EventKG+BT is handed a knowledge graph and selects which of a person's temporal relations
belong on a timeline, using features computed *from the graph* — entity types, Wikipedia
link counts, property frequency. **Its model never reads a biography.** biograph is handed a
biography and must produce the graph.

So its gold is reusable and its task is not. Nothing here reproduces their metric, and
their published figures are deliberately outside `published_baseline`.

**What it adds that nothing else in the suite does:**

- **A general population.** Actors, musicians, athletes, politicians and writers, rather
  than the single narrow population each other corpus covers.
- **Negative judgements.** ~99% of rows are relations the knowledge graph holds that the
  abstract never states. No other benchmark here has a distractor set, which makes this the
  only measurement of how often the pipeline imports knowledge from outside the document.
- **Typed, interval-dated relations** on a general population.

**What it cannot measure:** precision, relation type, and length — the abstracts are a few
thousand characters, so this is a breadth-of-population instrument, not a length one. B3 and
B4 remain the length experiments.

## Before running it

**Relaxed inclusion only.** The population is general biography, which the inclusion
criteria exclude. Pass `--relax-inclusion`.

**The gold is distant supervision.** An annotated sentence was mapped to a temporal relation
if both happened on exactly the same date, or if they shared both entities and time. The
authors say so plainly: manual relevance judgements were unfeasible at this scale. Recall
against it measures agreement with a rule, not with human judgement — report it as such.
