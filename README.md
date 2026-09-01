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

```bash
pip install -r extraction/requirements.txt
python3 scripts/extract_subject.py data/<paper>.pdf <slug>
```

Reads the PDF, asks an OpenAI-compatible LLM (OpenAI, OpenRouter, KISSKI,
etc. — set `--base-url`/`--model`/`--api-key` or the matching
`BIOGRAPH_*` env vars; prompts for the key if none is set) to draft the
four subject JSON files against this repo's own `schema/`, validates the
result, and builds `dist/<slug>.html` — one command, PDF in, graph out.

Treat the output as a first-pass draft, not ground truth: review it
against the PDF, by hand, before trusting it — same as any extraction.
[`extraction/EXTRACTION_GUIDE.md`](extraction/EXTRACTION_GUIDE.md) is the
checklist the script follows and what to check the draft against (also
useful for extracting or correcting a subject by hand instead).

## Structure

```
schema/         JSON Schema data model (entities, events, relations, sources)
subjects/<slug>/ One subject's hand-authored data (extraction output)
extraction/     Guide for authoring a new subject's data + its own
                requirements.txt (openai, pypdf — not needed just to view)
frontend/       template.html — D3 explorer; reads subject JSON only
scripts/        build_site.py — validates and builds dist/<slug>.html.
                extract_subject.py — LLM-drafts a new subject from a PDF.
dist/           Generated, self-contained HTML output
data/           Source PDFs
docs/           Full documentation source (MkDocs + Material)
```
