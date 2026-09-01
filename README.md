# biograph

A small scaffolding for turning a biographical source paper into an
explorable knowledge graph + chronological timeline: a graph of people,
places, organizations, and inventions, connected by simple typed relations
and grounded in dated, cited events.

Full documentation (usage guide, data model reference, frontend architecture, provenance discipline) lives under `docs/` and builds with [MkDocs](https://www.mkdocs.org/) + Material — see `mkdocs.yml`. Import this repo at readthedocs.org to host it there (a `.readthedocs.yaml` is already set up), or run `pip install -r docs/requirements.txt && mkdocs serve` to preview it locally.

## Layout

```
schema/         JSON Schema + README defining entities, events, relations,
                sources, and — most importantly — what counts as an "event"
                and how fuzzy/uncertain dates are handled for chronology.
subjects/<slug>/ One biographical subject's data: entities.json, events.json,
                relations.json, sources.json, subject.json.
extraction/     Guide for extracting a new subject from a source paper.
frontend/       template.html — the single-file D3 graph+timeline explorer.
scripts/        build_site.py — validates a subject's data and inlines it
                into the template to produce a standalone HTML file.
dist/           Generated output (dist/<slug>.html) — self-contained,
                double-click to open, no server needed.
data/           Source PDFs.
```

## Quick start

```
pip install jsonschema --break-system-packages   # once, for validation
python3 scripts/build_site.py suntola            # or --all
```

Open `dist/suntola.html` in a browser. Click any person/place/org/invention
to see its connections and its slice of the timeline; click any timeline
event to see its participants; drag to zoom/pan the timeline; scroll/drag
to pan and zoom the graph; use the legend to toggle entity types on/off.

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
