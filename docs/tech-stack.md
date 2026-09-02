# Tech stack

Biograph is deliberately low-tech: no server, no database, no JavaScript
framework or build step. The output is a single static HTML file per
subject, built by a small Python script from validated JSON.

## Frontend

| Piece | What it does |
|---|---|
| [D3.js v7](https://d3js.org/) (via CDN) | Force-directed layout for the network graph, zoom/pan behavior for the timeline, D3-geo (`geoNaturalEarth1` + `geoPath`) for the map projection. |
| Vanilla JavaScript | One IIFE per page, no framework, no bundler. Everything — data binding, selection state, the three views — is plain D3 + DOM. |
| Plain CSS, custom-property design tokens | A validated light color palette (see [Data Accuracy & Provenance](data-accuracy.md)) defined once as CSS variables and referenced by role throughout. |
| Embedded JSON | The subject's graph data and the world map's GeoJSON are inlined directly into the page as `<script type="application/json">` blocks at build time — no runtime fetch. |

The result has exactly one external dependency at runtime — the D3 CDN
script tag — so a built page can be opened offline, emailed, or dropped
anywhere and still work.

## Data & build

| Piece | What it does |
|---|---|
| JSON | The storage format for everything: four files per subject (`entities.json`, `events.json`, `relations.json`, `sources.json`) plus a `subject.json` manifest. |
| [JSON Schema](https://json-schema.org/) (draft 2020-12) | Defines the shape and controlled vocabularies for entities, events, relations, dates, and sources — see [Data model reference](data-model.md). |
| [`jsonschema`](https://pypi.org/project/jsonschema/) (Python) | Validates every subject file against its schema and checks referential integrity before a build is allowed to succeed. |
| `scripts/build_site.py` | The build script: validates, then inlines the subject's data (and the shared world map) into `frontend/template.html` to produce `dist/<slug>.html`. |

There is no framework here either — the build script is a few hundred
lines of plain Python, run from the command line. See
[Usage Guide](usage.md) for the exact commands.

## Extraction (optional)

Only needed to draft a *new* subject from a PDF — not to view or build
one that already exists, which is why these live in their own
`extraction/requirements.txt` rather than the root one.

| Piece | What it does |
|---|---|
| [`pypdf`](https://pypi.org/project/pypdf/) (Python) | Extracts page-numbered text from the source PDF (`[pdf page N]` markers, so the model can cite real pages). |
| [`openai`](https://pypi.org/project/openai/) (Python SDK) | Talks to whatever OpenAI-compatible chat-completions endpoint you point it at — OpenAI, OpenRouter, KISSKI, or any other gateway speaking the same API. Base URL, model, and key are all chosen at runtime, never hardcoded. |
| `scripts/build_site.py --pdf` | Reads the PDF, embeds `schema/*.schema.json` directly in the prompt (so it can't drift from the data model), asks the model to draft the four subject JSON files, auto-continues a reply that gets cut off at the token limit, then validates and builds `dist/<slug>.html` through the exact same code path a hand-written subject goes through. |
| [Wikidata](https://www.wikidata.org/) & [Wikimedia Commons](https://commons.wikimedia.org/) APIs (stdlib `urllib`, no extra dependency) | Looked up by `scripts/find_portraits.py` — see below — to find and verify a person's photo. |
| `scripts/find_portraits.py` | The second script: for each `person` entity without a portrait, searches Wikidata, and — only if identity is confirmed, either by an exact birth-year match to this subject's own `events.json` or, failing that, an LLM judging the Wikidata description specific enough to rule out a namesake — attaches a Commons photo with its license and source. Reuses `build_site.py`'s provider/model prompts rather than duplicating them. Never guesses; see [Data Accuracy & Provenance § Portraits](data-accuracy.md#portraits). |

No LLM call is required to use Biograph at all — it's the fast path for
producing a first draft, not a dependency of the viewer or the build. See
[Adding a new subject](adding-a-subject.md) for the full walkthrough.

## Development-time tools

These were used to build and verify the Suntola example and the frontend
itself, but nothing here ships in the final output:

| Tool | Used for |
|---|---|
| Wikidata & Wikimedia Commons APIs (manual lookup) | Sourcing place coordinates (`attributes.lat`/`lng`) — portraits are now `find_portraits.py`'s job (above), but coordinates are still verified by hand the same way; see [Data Accuracy & Provenance](data-accuracy.md). |
| [Playwright](https://playwright.dev/) + headless Chromium | Screenshot-based visual QA during frontend development. |
| Git / GitHub | Version control for the whole repository. |
| [MkDocs](https://www.mkdocs.org/) + [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) | This documentation site. |

## Why this stack

The choices all point the same direction: minimize what has to run to
view a biography. A subject's page should open by double-clicking a file,
not by standing up a server — so no framework, no build pipeline, no
backend. The data layer mirrors that: JSON files a person can read and
hand-edit, validated by a schema rather than enforced by an application,
so the "database" is just files under version control.
