# Benchmark 2 — Biographical Events (ISA 2022, arXiv:2206.03547)

Token-level ISO-TimeML annotation over biographies: event classes `EVENT`, `STATE`,
`ASP-EVENT`, `REP-EVENT` on trigger tokens, plus writer-centric SemAF roles
(`writer-ARG0`, `writer-ARGx`, `ARGx-LOC`, `ARGx-ORG`, `ARGM-TIME`).

This is the most structurally mismatched of the five benchmarks, and the mismatches are
the finding rather than an obstacle to it.

## Status

Adapter complete, 23 self-checks passing, **no data downloaded** — the licence is not
stated in the paper and not declared in the repository. `load()` reads a local copy via
`--data-root`.

## Type is not measurable, in either direction

All 22 biograph event types collapse onto TimeML's single `EVENT` class, and TimeML's four
classes have no counterpart in biograph's vocabulary. So this adapter **never compares a
type to a type**. Scoring is *trigger-anchored*: a gold trigger is recalled if some
extracted event is anchored at it. Gold triggers are bucketed by class afterwards to report
recall per class, but the match itself is type-agnostic.

Inventing a correspondence to produce a type-accuracy number would be the one genuinely
dishonest move available here, so the coverage matrix says `partial` for every row and the
scorer reports what it can actually measure.

## Anchoring needs two tiers

biograph produces no token offsets. It does produce, for every event, a verbatim
`sources[].quote` (grounding-checked at 99.5% across the corpus) and a short `label`.
Locating the quote in the document gives a character span.

A span alone is not enough. Turing's **Born** and **Died** events cite the *same* quote —
`"Alan Turing OBE FRS (23 June 1912 – 7 June 1954)"` — so span containment alone would let
either event answer for either trigger. Hence:

| tier | meaning |
|---|---|
| `label+quote` | the trigger token appears in the event's label **and** falls inside one of its quote spans — the strong anchor |
| `quote` | the trigger falls inside a quote span with no label support — weak, and **counted separately** |

Matching is **one-to-one**: a gold trigger is answered by at most one event, and an event
answers at most one trigger. Without that, one sentence-length quote would claim every
trigger in its sentence and recall would be meaningless.

`anchored_by_quote_only` is reported in every run, so a reader can see how much of recall
rests on the weaker anchor.

## `STATE` is an unreachable ceiling, by design

> "An event is a dateable occurrence, not a fact or a description" — `schema/README.md`

A TimeML `STATE` is precisely a fact or a description. biograph drops them deliberately, so
`STATE` recall should be near zero. It is **reported as a measured number** and **excluded
from `macro_recall`**, because averaging in a class the schema refuses to represent would
score an ontological choice as though it were an error rate.

This is the cleanest result the benchmark can give: a quantified statement of what the data
model chose not to model.

## Precision is scoped to annotated text

The corpus annotates some sentences; biograph extracts from the whole document. An
extracted event anchored outside any annotated sentence has no gold that could confirm or
deny it, so counting it as a false positive would punish the extractor for reading text the
annotators did not label.

Those are reported as `unscorable_span` and excluded from precision. Only events overlapping
an annotated sentence are scored.

## Roles

`ARGx-LOC` and `ARGx-ORG` are filled from `relations.json` via `RELATION_ROLE`, which is
taken straight from `harness/coverage.py`'s `BIOEVENTS` cells so the two cannot drift apart.
`ARGM-TIME` comes from each event's own date display. Roles are scored by span overlap and
reported separately from triggers.

`writer-ARG0` / `writer-ARGx` are `not_applicable`: they model the biography's *author*, a
perspective the schema does not represent at all.

## No published baseline

`published_baseline` is deliberately empty. The paper's figures are token-level sequence
labelling by a model **trained on this corpus**; this adapter anchors a **zero-shot,
document-level** extractor's events to the same triggers. These are not the same task, and
printing the two side by side would imply a comparison that does not hold.

## Running

```bash
# the admission policy
python -m experiments.harness.cli --benchmark bioevents --data-root <dir> --limit 25

# the extractor, on documents the gate refuses
python -m experiments.harness.cli --benchmark bioevents --data-root <dir> --limit 25 --gate-off
```

As with Benchmark 1, this is a general-biography population, so a gate-on run will mostly
measure refusals. Both conditions are reported; they are never averaged.

## Format

`load()` accepts CoNLL/IOB (blank-line-separated sentences, token first and tag last) and
JSON/JSONL carrying `tokens[]` + `labels[]`, or `tokens[]` of objects. Column names are
sniffed against `COLUMN_ALIASES` and the loader **refuses with the header it actually saw**
rather than guessing. IOB runs (`B-EVENT I-EVENT I-EVENT`) merge into one annotation.

Offsets are computed while the text is assembled, so they index the string the model
actually receives — not the original file.
