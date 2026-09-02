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
python3 scripts/build_site.py <slug> --pdf data/<paper>.pdf
```

Prompts you for a provider (OpenAI, OpenRouter, or paste any other
OpenAI-compatible base URL — e.g. KISSKI), then a model name, then an API
key — or skip the prompts with `--base-url`/`--model`/`--api-key` (or the
matching `BIOGRAPH_*` env vars) for scripted use. No model is hardcoded,
since lineups change; type whatever your provider currently offers. It
then drafts the four subject JSON files against this repo's own
`schema/`, validates the result, and builds `dist/<slug>.html` — one
command, PDF in, graph out.

Treat the output as a first-pass draft, not ground truth: review it
against the PDF, by hand, before trusting it — same as any extraction.
[`extraction/EXTRACTION_GUIDE.md`](extraction/EXTRACTION_GUIDE.md) is the
checklist the script follows and what to check the draft against (also
useful for extracting or correcting a subject by hand instead).

## Find portraits

```bash
python3 scripts/find_portraits.py <slug>
```

For each person without a photo, searches Wikidata and — only if
identity is confirmed (an exact birth-year match to this subject's own
data, or an LLM judging the description specific enough to rule out a
namesake) — attaches a licensed photo from Wikimedia Commons. A wrong
photo is worse than none, so anything short of that is left blank rather
than guessed. Full explanation: [Data Accuracy & Provenance § Portraits](https://biograph.readthedocs.io/en/latest/data-accuracy/#portraits).

## Structure

```
schema/         JSON Schema data model (entities, events, relations, sources)
subjects/<slug>/ One subject's data (extraction output — by hand or by
                build_site.py --pdf, reviewed either way)
extraction/     Guide for authoring a new subject's data + its own
                requirements.txt (openai, pypdf — not needed just to view)
frontend/       template.html — D3 explorer; reads subject JSON only
scripts/        build_site.py — the whole knowledge-graph pipeline: with
                --pdf, LLM-drafts a subject from a PDF; either way,
                validates and builds dist/<slug>.html.
                find_portraits.py — attaches verified Wikidata/Commons photos.
dist/           Generated, self-contained HTML output
data/           Source PDFs
docs/           Full documentation source (MkDocs + Material)
```
