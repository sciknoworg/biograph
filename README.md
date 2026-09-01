# biograph

A small scaffolding for turning a biographical source paper into an
explorable knowledge graph + chronological timeline: a graph of people,
places, organizations, and inventions, connected by simple typed relations
and grounded in dated, cited events.

Full documentation (usage guide, data model reference, frontend architecture, provenance discipline) lives under `docs/` and builds with [MkDocs](https://www.mkdocs.org/) + Material — see `mkdocs.yml`, or read it live at **[biograph.readthedocs.io](https://biograph.readthedocs.io/)**.

## Run it in one line

```bash
pip install jsonschema --break-system-packages && python3 scripts/build_site.py suntola
```

Then open `dist/suntola.html` in any browser — it's a single self-contained
file, no server needed.

## Two separate steps: extraction, then visualization

The project is deliberately split into two independent halves that don't
share code:

**1. Extraction — turning a source paper into data.** This is a manual,
guided process, not a script: you read a biography paper and hand-write
four JSON files (`entities.json`, `events.json`, `relations.json`,
`sources.json`) describing what it says, following
[`extraction/EXTRACTION_GUIDE.md`](extraction/EXTRACTION_GUIDE.md) step by
step. There is nothing to "run" here — the output is just data, checked
against `schema/` for structure and against itself for referential
integrity at build time.

**2. Visualization — turning that data into an explorable page.** This
*is* code, and it's the one-liner above:
[`scripts/build_site.py`](scripts/build_site.py) validates a subject's
JSON and inlines it into [`frontend/template.html`](frontend/template.html)
(a single-file D3 graph + map + timeline explorer) to produce
`dist/<slug>.html`. The frontend has no idea where the data came from —
it only ever reads the four JSON files, so any subject that passes
validation renders, regardless of how it was extracted.

Because these two halves don't share code, you can redo an extraction
by hand, fix a typo in a JSON file directly, or swap in a subject
extracted differently, and the visualization step doesn't change at all.

## Layout

```
schema/         JSON Schema + README defining entities, events, relations,
                sources, and — most importantly — what counts as an "event"
                and how fuzzy/uncertain dates are handled for chronology.
subjects/<slug>/ One biographical subject's data: entities.json, events.json,
                relations.json, sources.json, subject.json. (The output of
                extraction — see step 1 above.)
extraction/     Guide for extracting a new subject from a source paper.
                No code — a manual process.
frontend/       template.html — the single-file D3 graph+timeline explorer.
                No knowledge of extraction; only reads subject JSON.
scripts/        build_site.py — validates a subject's data and inlines it
                into the template to produce a standalone HTML file.
dist/           Generated output (dist/<slug>.html) — self-contained,
                double-click to open, no server needed.
data/           Source PDFs.
docs/           Full documentation source (MkDocs + Material) — see above.
```

## Quick start (with detail)

```bash
pip install jsonschema --break-system-packages   # once, for validation
python3 scripts/build_site.py suntola            # or --all, to build every subject
```

Open `dist/suntola.html` in a browser. Click any person/place/org/invention
to see its connections and its slice of the timeline; click any timeline
event to see its participants; drag to zoom/pan the timeline; scroll/drag
to pan and zoom the graph; use the legend to toggle entity types on/off.
For everything else — adding a new subject, the full data model, the
frontend's Map/Milestones views — see the [docs](https://biograph.readthedocs.io/).

## Status

- `subjects/suntola/` — first-pass extraction from Puurunen (2014), *A
  Short History of Atomic Layer Deposition: Tuomo Suntola's Atomic Layer
  Epitaxy*. 67 entities, 42 events, 50 relations. Treat this as a draft to
  review against the source, not ground truth — see
  `extraction/EXTRACTION_GUIDE.md` for how it was built and how to extend
  or correct it.
- `subjects/aleskovskii/` — not yet started. The Malygin (2015) paper in
  `data/` covers V. B. Aleskovskii's independent discovery of "molecular
  layering," the Soviet-side counterpart to Suntola's ALE. Once it exists,
  a cross-subject bridge file connects the two (they already documented
  meeting each other in 1990 — see
  `subjects/suntola/events.json#suntola_visits_leningrad`).
