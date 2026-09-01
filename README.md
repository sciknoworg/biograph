# biograph

Turns a biographical source paper into an explorable knowledge graph +
timeline: dated, cited events connecting people, places, organizations,
and artifacts — rendered as a single self-contained HTML page (network
graph, map, timeline).

Full docs: **[biograph.readthedocs.io](https://biograph.readthedocs.io/)**

## Requirements

Python 3.8+, the `jsonschema` package, a browser.

## Install

```bash
pip install jsonschema --break-system-packages
```

## Build & view

```bash
python3 scripts/build_site.py <subject>   # e.g. suntola, the shipped example
python3 scripts/build_site.py --all       # every subject under subjects/
```

Open `dist/<subject>.html` — self-contained, no server needed.

## Add a subject

There is no automated pipeline here — no PDF parser, no LLM call baked
into the code. A subject's data is hand-authored: someone (or an AI
assistant, working manually) reads the source paper and writes four JSON
files — `entities.json`, `events.json`, `relations.json`, `sources.json`
— under `subjects/<slug>/`, following
[`extraction/EXTRACTION_GUIDE.md`](extraction/EXTRACTION_GUIDE.md) and
validated against [`schema/`](schema/) at build time. That guide is what
keeps different extractions consistent with each other, in place of a
script.

## Structure

```
schema/         JSON Schema data model (entities, events, relations, sources)
subjects/<slug>/ One subject's hand-authored data (extraction output)
extraction/     Guide for authoring a new subject's data
frontend/       template.html — D3 explorer; reads subject JSON only
scripts/        build_site.py — validates and builds dist/<slug>.html
dist/           Generated, self-contained HTML output
data/           Source PDFs
docs/           Full documentation source (MkDocs + Material)
```
