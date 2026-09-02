# biograph

Turns a biographical source paper into an explorable knowledge graph +
timeline: dated, cited events connecting people, places, organizations,
and artifacts — rendered as a single self-contained HTML page (network
graph, map, timeline).

Full docs: **[biograph.readthedocs.io](https://biograph.readthedocs.io/)**

## Requirements

Python 3.8+, a browser.

A worked example ships in `subjects/suntola/`, so you can skip straight
to [step 2](#2-build-the-timeline-visualization) and build/open it
without an API key.

## 1. Extract a biography from a PDF

```bash
pip install -r extraction/requirements.txt
python3 scripts/build_site.py <slug> --pdf data/<paper>.pdf
```

Prompts you for a provider (OpenRouter, or paste any other
OpenAI-compatible base URL — e.g. KISSKI), then a model name, then an API
key — or skip the prompts with `--base-url`/`--model`/`--api-key` (or the
matching `BIOGRAPH_*` env vars) for scripted use. No model is hardcoded,
since lineups change; type whatever your provider currently offers.

Reads the PDF and drafts a dated, cited biography against this repo's own
`schema/` (so it can't drift from the data model) — every event and
relation is required to cite the page it came from. Writes
`subjects/<slug>/`:

| File | Contents |
|---|---|
| `subject.json` | Identity: slug, name, one-line summary. |
| `entities.json` | People, places, organizations, artifacts mentioned. |
| `events.json` | Dated occurrences, each cited to a source page — the timeline's raw material. |
| `relations.json` | Durable connections between entities (`worked_at`, `invented`, ...). |
| `sources.json` | The source paper(s), for citation. |

Treat the output as a first-pass draft, not ground truth: review it
against the PDF, by hand, before trusting it — same as any extraction.
[`extraction/EXTRACTION_GUIDE.md`](extraction/EXTRACTION_GUIDE.md) is the
checklist the script follows and what to check the draft against (also
useful for extracting or correcting a subject by hand instead).

The PDF itself isn't committed to this repo — only its citation (title,
authors, DOI, ...) and the page-level provenance drawn from it are. See
[`data/README.md`](data/README.md).

## 2. Build the timeline visualization

```bash
pip install jsonschema --break-system-packages
python3 scripts/build_site.py <slug>       # step 1 already ran this once
python3 scripts/build_site.py --all        # or rebuild every subject
```

Validates the five files above against `schema/` (structure and
referential integrity) and inlines them into `frontend/template.html`,
writing `dist/<slug>.html` — a single self-contained page (network graph,
map, timeline). Open it directly in a browser, no server needed. Re-run
this any time after hand-editing `subjects/<slug>/*.json`.

## 3. Find portraits

```bash
python3 scripts/find_portraits.py <slug>
```

For each person without a photo, searches Wikidata and — only if
identity is confirmed (an exact birth-year match to this subject's own
data, or an LLM judging the description specific enough to rule out a
namesake) — attaches a licensed photo from Wikimedia Commons to
`entities.json` and rebuilds `dist/<slug>.html`. A wrong photo is worse
than none, so anything short of that is left blank rather than guessed.
Full explanation: [Data Accuracy & Provenance § Portraits](https://biograph.readthedocs.io/en/latest/data-accuracy/#portraits).

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
data/           Source PDFs (gitignored, not committed -- see data/README.md;
                citations live in each subject's sources.json)
docs/           Full documentation source (MkDocs + Material)
```
