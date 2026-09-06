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

Accepts a PDF, or a `.txt` of already-extracted text (`--text`, same
thing under a clearer name). Drafts a dated, cited biography against this
repo's own `schema/` (so it can't drift from the data model): every event
and relation must cite the page it came from **and quote the sentence
that states it**, verbatim. The same call judges whether the document
fits this project's scope at all (a biographical/historical essay, not
just any paper mentioning the person); if not, nothing is written and the
source is deleted (`--keep-rejected` to keep it).

A subject is a **person**; each document about them gets its own folder
named by its citation key:

```
subjects/suntola/
  subject.json              the person: canonical name + slug
  puurunen_2014/            one document's extraction
    entities.json           people, places, organizations, artifacts
    events.json             dated occurrences, each cited — the timeline
    relations.json          durable links (worked_at, invented, ...)
    sources.json            the document, for citation
  aris_2019/                a second account of the same life
```

Two papers about one person are two accounts, kept whole and separate.
They are reconciled when the subject is *read*, so a bad merge is a
rendering bug you re-run rather than extraction you've destroyed.

Every quote is then checked back against the source, and anything not
found verbatim is reported — a mechanical hallucination check, no second
LLM call:

```bash
python3 scripts/build_site.py <slug> --check-grounding
```

Treat the output as a first-pass draft, not ground truth: review it
against the source before trusting it.
[`extraction/EXTRACTION_GUIDE.md`](extraction/EXTRACTION_GUIDE.md) is the
checklist the script follows, and what to check a draft against.

The source's **extracted text** is archived to `data/<slug>.txt` — that
is what the model actually read and what `--check-grounding` verifies
against, at roughly 3% of a PDF's size. The PDF is not kept
(`--keep-source-pdf` to keep it) and neither is committed; `sources.json`
holds the citation needed to fetch the original again. See
[`data/README.md`](data/README.md).

## 2. Build the timeline visualization

```bash
pip install jsonschema --break-system-packages
python3 scripts/build_site.py <slug>       # step 1 already ran this once
python3 scripts/build_site.py --all        # or rebuild every subject
```

Reads every document folder under the subject, merges them into one
graph, validates against `schema/` (structure and referential integrity),
and inlines the result into `frontend/template.html` — writing
`dist/<slug>.html`, a single self-contained page (network graph, map,
timeline). Open it directly in a browser, no server needed. Re-run after
hand-editing any `subjects/<slug>/<doc>/*.json`.

On merge, entities sharing an id are the same thing and their aliases are
unioned; events and relations are never merged, since two papers
describing one episode are two accounts, not one claim.

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
schema/          JSON Schema data model (entities, events, relations, sources)
subjects/<slug>/ One person. subject.json + one folder per source document
                 (extraction output — by hand or by build_site.py, reviewed
                 either way)
extraction/      Guide for authoring a subject's data by hand + its own
                 requirements.txt (openai, pypdf — not needed just to view)
frontend/        template.html — D3 explorer; reads subject JSON only
scripts/         build_site.py — the whole knowledge-graph pipeline: with
                 --pdf/--text, LLM-drafts a subject from a document; either
                 way validates and builds dist/<slug>.html. Also
                 --check-grounding, the hallucination check.
                 find_portraits.py — attaches verified Wikidata/Commons photos.
dist/            Generated, self-contained HTML output
data/            Archived source text (gitignored — see data/README.md;
                 citations live in each subject's sources.json)
docs/            Full documentation source (MkDocs + Material)
```

## License

MIT (see [`LICENSE`](LICENSE)) — covering this repository's own work: the
schemas, the scripts, the frontend, and the extracted knowledge-graph JSON
under `subjects/`.

It does not extend to the source documents those subjects are drawn from.
Each paper stays under its own publisher's or author's terms, which is why
`data/*.pdf` and `data/*.txt` are gitignored rather than published — a
license chosen here cannot grant rights over someone else's work. What is
shared instead is the citation: every source is fully described in its
subject's `sources.json`, with a DOI wherever one exists. See
[`data/README.md`](data/README.md).
