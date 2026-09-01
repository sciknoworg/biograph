# Biograph

Biograph turns a single biographical source — a paper, an oral history, an
archive — into a small, explorable knowledge graph that is also a
chronological timeline. Point it at one subject's structured data and it
builds a self-contained HTML page with three linked ways to explore that
person's life: a network graph, a world map, and a chronological
milestones reel.

It is deliberately narrow. Four JSON files per subject, each validated
against a JSON Schema, are enough to model a biography tightly: who and
what (entities), what happened and when (events), how things connect
(relations), and where every claim comes from (sources). The goal is a
model tight enough that two different people extracting from the same
paper would produce essentially the same data — see
[Data Accuracy & Provenance](data-accuracy.md) for how that discipline is
enforced.

## Why a graph *and* a timeline

Most biographical tools pick one: a family-tree-style graph, or a
timeline. Biograph treats them as two views of the same underlying data.
Every event is dated (however fuzzily) *and* connects the people, places,
organizations, and things involved in it. Click a person in the network
view and their slice of the timeline highlights; click an event on the
timeline and the graph highlights everyone who was there. The
[Map](frontend-guide.md#map-view) and
[Milestones](frontend-guide.md#milestones-view) views are two more lenses
on that same data — no separate content to maintain.

## Try it now

The repository ships one worked example: `subjects/suntola/`, extracted
from Puurunen (2014)'s history of Tuomo Suntola's invention of Atomic
Layer Epitaxy — 67 entities, 42 events, 50 relations. Build it and open it:

```bash
pip install jsonschema --break-system-packages
python3 scripts/build_site.py suntola
```

Then open `dist/suntola.html` directly in a browser — no server required.
See [Getting Started](getting-started.md) for the full walkthrough.

## What's in this documentation

- **[Tech stack](tech-stack.md)** — what Biograph is built from, front end
  and build side.
- **[Getting Started](getting-started.md)** — install the one dependency,
  build the example subject, open it.
- **[Usage Guide](usage.md)** — the build/validate CLI, and the full
  step-by-step process for [adding a new subject](adding-a-subject.md)
  from a source paper.
- **[Architecture](data-model.md)** — the [data model](data-model.md) (the
  four JSON files, the controlled vocabularies, the fuzzy-date chronology
  mechanism) and the [frontend](frontend-guide.md) (the three views, how
  selection state stays in sync across them).
- **[Data Accuracy & Provenance](data-accuracy.md)** — the citation
  discipline, schema validation, and the verification tiers used before
  any portrait or map coordinate is added.
- **[Extending & Contributing](extending.md)** — adding vocabulary values,
  cross-subject bridges, and where the project goes from here.
