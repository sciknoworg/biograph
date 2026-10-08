# Benchmark 4 — WikiBio: provenance

The corpus is **not redistributed here**. This folder records where it comes from and what
it carries. The data beside this README is gitignored.

## Source

| | |
|---|---|
| paper | *WikiBio: a Semantic Resource for the Intersectional Analysis of Biographical Events* |
| authors | Stranisci, Damiano, Mensa, Patti, Radicioni, Caselli |
| venue | ACL 2023, pp. 12370–12384 |
| DOI | 10.18653/v1/2023.acl-long.691 |
| repository | https://github.com/marcostranisci/WikiBio |
| files used | `corpus/*_annotation_tokens.csv`, 20 files |

Same first author as Benchmark 2 (BiographicalEvents), and the same annotation philosophy —
which is exactly why the pair is worth running.

## Licence — unresolved for the data

**The ACL paper is CC BY 4.0. That does not cover a separately released annotation set.**
The repository states no licence and has no LICENSE file.

Wikipedia-derived, so **CC BY-SA 4.0 applies upstream**, and share-alike would attach to any
derived artifact published from it.

Used and cited, not redistributed. **Settle this with the authors before publishing
anything built from these annotations.**

## Obtaining it

```bash
mkdir -p experiments/corpora/wikibio
for n in 8091 8092 8093 8094 8095 8096 8097 8098 8099 8100 \
         8104 8105 8106 8107 8108 8109 8110 8111 8112 8113; do
  curl -L -o experiments/corpora/wikibio/$n.csv \
    https://raw.githubusercontent.com/marcostranisci/WikiBio/master/corpus/${n}_annotation_tokens.csv
done
```

## What is in it

20 complete English Wikipedia biographies of African and African-American writers born
1928–1945. One row per token, in document order.

```
_id,label,id,token,sentence
Q560307_150,ENTITY,0J9UonOFjU,Donald,0
Q560307_151,ENTITY,0J9UonOFjU,James,0
Q560307_154,EVENT-GR,LTmqarsZNg,was,0
```

The `id` column groups multi-token spans — `Donald`, `James`, `Woods`, `CBE` are four rows
of one annotation.

| | |
|---|---:|
| documents | **20** |
| tokens | 75,088 |
| characters as built | **389,546** |
| document length | min 10,384, **median 16,688**, max 41,418 |
| sentences | ~2,720 |
| **gold EVENT spans (scored)** | **3,282** |
| ENTITY spans (target person) | 2,231 |
| EVENT-GR + EVENT-MOD (read, not scored) | 417 |

These figures match the paper exactly — 75,088 tokens, 2,985 `ENTITY` tokens, 3,290 `EVENT`
tokens. **This is the only corpus in the suite whose release matches its paper's numbers.**

## Three things the format forced

**The `_id` column is not the subject's QID.** All twenty files carry the prefix `Q560307`
— Donald Woods, who is the subject of file 8091 alone. It is an annotation-project
identifier baked into every file and identifies nothing. The subject is recovered from the
first `ENTITY` span instead, which yields `Ada Aharoni`, `Lewis Nkosi`, `Ngũgĩ wa Thiong'o`
correctly.

**Tokens are detokenised, not space-joined.** Joining with spaces produces `anti -
apartheid`, `( 15 December 1933 )` and `activist .` — prose no biography ever contained,
handed to a model asked to read a biography. Spacing is reconstructed and every gold offset
is computed against the text actually produced, so an annotation always lands on the token
it names. All 3,282 trigger offsets reproduce their own surface. Disclosed as `detokenised`.

**Only `EVENT` is scored.** `EVENT-GR` (light and grammatical verbs) and `EVENT-MOD`
(modality) annotate *how* an event is expressed rather than that one occurred, and the
paper's own corpus figure of 3,290 event mentions is the `EVENT` column alone.

## Why this benchmark exists beside BiographicalEvents

**It is B2's task at the right document length.** Same trigger-anchored event recall, but
**16,688 characters per document against 147**, and **3,282 gold events against 1,589**.
That is a controlled comparison available nowhere else: the same extractor, on the same kind
of annotation, at two document lengths differing by roughly 100×.

It also removes the other confound. B2 lost 46% of its corpus to the schema's requirement
that every event carry a date. **This gold annotates no dates at all**, so what is measured
is purely whether the extractor noticed the life episode.

## What it cannot measure

`EVENT` is **untyped**. All 22 biograph event types collapse onto it, so type accuracy is
unmeasurable in either direction and every projected event is recorded in `lossy` for that
reason.

**Precision is not comparable to a sentence-level figure.** The annotation covers events
associated with the biography's *target person*; an event about anyone else in the document
is correct extraction with no gold to match.

## There is a published figure, and it is a different split

The paper reports DistilBERT event detection at about **0.859 F1** — but over the 1,691
event-bearing **target sentences**, split 564/563/564. That is a sentence-level split of a
document-level corpus. Target-entity detection is separately reported at about **0.808 F1**
over a document split of 5 train / 5 dev / 10 test biographies.

This pipeline receives a whole 16,688-character biography and is scored over every gold
event in it, so neither figure is the bar it clears or misses. Both are recorded in the
adapter as `reference_event_f1_sentence_split` and `reference_entity_f1_document_split`,
deliberately outside `published_baseline`.

*The repository's corpus README states that selected biographies had lengths "higher than
200.000 tokens", which is incompatible with the paper's own figure of ~3,754 tokens per
document and with the files themselves. Treat that README line as erroneous.*

## Before running it

**Relaxed inclusion only.** The population is writers, which the inclusion criteria exclude
0/5 in a controlled probe. Pass `--relax-inclusion`.

20 documents, 389,546 characters. Comparable in total size to WikiLifeTrajectory's ten
(277,449), so expect a similar run cost.
