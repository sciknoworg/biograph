# Tech stack

Biograph is deliberately low-tech: no server, no database, no JavaScript
framework or build step. The output is a single static HTML file per
subject. Two small Python scripts do everything else — `scripts/build_site.py`
(draft from a PDF, then validate and build) and `scripts/find_portraits.py`
(attach verified photos) — see [Usage Guide](usage.md) for the commands.
This page is about *how* each stage works and why it's built that way.

## 1. Extraction: PDF in, cited JSON out

| Piece | What it does |
|---|---|
| [`pypdf`](https://pypi.org/project/pypdf/) (Python) | Extracts text from the source PDF, inserting a `[pdf page N]` marker at every page break so the model can cite a real page even when the PDF has no visible page numbers. |
| [`openai`](https://pypi.org/project/openai/) (Python SDK) | The HTTP client, used generically against whatever OpenAI-compatible chat-completions endpoint you point it at. It's the de facto standard request/response shape for chat models, not an OpenAI-specific integration — OpenRouter, KISSKI, and most other model gateways speak it. There's no built-in option for OpenAI's own hosted API; base URL, model, and key are all chosen at runtime (prompted, flags, or `BIOGRAPH_*` env vars), never hardcoded. |
| `scripts/build_site.py --pdf` | Orchestrates the steps below, then hands off to stage 2 (validate + build) through the exact same functions a hand-written subject goes through — no separate code path. |

**Schema-embedded prompting.** The system prompt doesn't describe the
data model in prose — it embeds `schema/*.schema.json` verbatim (via
`json.dumps`), so the model sees the exact field names, enums, and
`required` lists a build will check it against. This is what keeps the
prompt from drifting out of sync with the schema as the model evolves:
change a schema file and the next extraction run picks it up
automatically, with no prompt text to remember to update.

**Provenance and terseness are prompt rules, not just schema
constraints.** The `RULES` block appended to every prompt spells out two
things explicitly: every event and relation citation needs a page number
(`sources[].page` — where in the text this came from — is a required
schema field, so a citation without one fails validation outright, not
just a style suggestion), and labels/summaries must be terse and
scannable ("Moved to Texas Instruments", not a paragraph) with fuller
detail reserved for an optional one-sentence `description`.

**Continuation across the token limit.** A reply that's cut off
mid-JSON at `--max-tokens` isn't an error: the script detects
`finish_reason == "length"`, sends the partial reply back as an
assistant turn with a "continue exactly where you left off" instruction,
and concatenates the pieces — up to 8 rounds — before parsing. JSON
strict mode (`response_format: json_object`) is used on the first
request only, since a mid-JSON fragment isn't valid JSON on its own and
would be rejected by strict mode on a continuation.

**Defensive parsing.** Model output is coerced, not trusted blindly:
a `subject` that comes back as a bare string, or `entities`/`events`
that come back as something other than a list, are reset to safe empty
defaults instead of crashing; a reply that's valid JSON but is itself a
JSON-encoded string (some models double-encode) is unwrapped one level.
A request that fails outright (bad model name, provider error) exits
with the provider's own error text and a hint, rather than a raw
traceback.

## 2. Validation & build: JSON in, one HTML file out

| Piece | What it does |
|---|---|
| JSON | The storage format for everything: four files per subject (`entities.json`, `events.json`, `relations.json`, `sources.json`) plus a `subject.json` manifest — human-readable and hand-editable, whether or not extraction produced the first draft. |
| [JSON Schema](https://json-schema.org/) (draft 2020-12) | Defines the shape and controlled vocabularies for entities, events, relations, dates, and sources — see [Data model reference](data-model.md). `page` is a required field on every source citation, so provenance is enforced structurally, not just by convention. |
| [`jsonschema`](https://pypi.org/project/jsonschema/) (Python), `Draft202012Validator` + `RefResolver` | Validates every subject file against its schema, then a second pass checks referential integrity by hand — every `participants[].entity_id`, `location`, `source_id`, and `event_id` referenced must actually exist in that subject's files, which JSON Schema alone can't express. |
| `scripts/build_site.py` | Sorts events by date, inlines the subject's data plus the shared, pre-converted world-map GeoJSON directly into `frontend/template.html` as `<script type="application/json">` blocks, and writes `dist/<slug>.html`. |

A validation failure lists every error and writes nothing — a subject
either builds clean or doesn't build at all, so a broken reference can
never silently ship as an `undefined` node. See [Usage Guide](usage.md)
for a worked failure-and-fix example.

## 3. Portrait verification: entity in, licensed photo out

| Piece | What it does |
|---|---|
| [Wikidata](https://www.wikidata.org/) action API (stdlib `urllib`, no extra dependency) | `wbsearchentities` to find candidates by name, `wbgetentities` to pull each candidate's birth date (P569), Commons image (P18), and description. |
| [Wikimedia Commons](https://commons.wikimedia.org/) action API (stdlib `urllib`) | `imageinfo`/`extmetadata` to resolve a candidate's image file to its license, license URL, and artist — a photo is never attached if Commons can't report a license for it. |
| `scripts/find_portraits.py` | Two-tier identity verification, reusing `build_site.py`'s provider/model/key prompts rather than duplicating them (see below), then writes verified `portrait` objects into `entities.json` and triggers a rebuild. |

**Mechanical tier first, LLM only if needed.** A candidate whose
Wikidata birth year matches a `birth` event already in this subject's
own `events.json` is `birth_year_verified` — no LLM call at all, since a
coincidence at that specificity is vanishingly unlikely. Only when no
birth-year match is available (or more than one same-named candidate
shares it) does the script batch those cases to an LLM, which judges
whether a candidate's Wikidata description is specific enough to rule
out a namesake (`description_verified`). The *script* computes which
tier applies from whether a birth year was involved — the model is
asked for a pick and a one-sentence reason, never for a self-reported
confidence level. See [Data Accuracy & Provenance § Portraits](data-accuracy.md#portraits)
for the full rule.

**Resilient by design.** Every Wikidata/Commons lookup is wrapped
individually, so one network hiccup or an unresolvable license skips
just that one person with a printed reason — a restrictive network
costs you that person's photo, not the whole run.

No LLM call, and no network call at all, is required to use Biograph —
extraction and portrait-finding are both optional accelerants over
hand-written JSON, never a dependency of the viewer or the build.

## Frontend: JSON in, an explorable page out

| Piece | What it does |
|---|---|
| [D3.js v7](https://d3js.org/) (via CDN) | Force-directed layout for the network graph, zoom/pan behavior for the timeline, D3-geo (`geoNaturalEarth1` + `geoPath`) for the map projection. |
| Vanilla JavaScript | One IIFE per page, no framework, no bundler. Everything — data binding, selection state, the three views — is plain D3 + DOM. |
| Plain CSS, custom-property design tokens | A validated, colorblind-safe categorical palette (see [Data Accuracy & Provenance](data-accuracy.md)) defined once as CSS variables and referenced by role throughout. |
| Embedded JSON | The subject's graph data and the world map's GeoJSON are inlined directly into the page as `<script type="application/json">` blocks at build time — no runtime fetch. |

The three views (network graph, map, milestones/timeline) share one
in-memory selection state: clicking a person in the graph highlights
their slice of the timeline and vice versa, all without a framework's
state-management layer. The result has exactly one external dependency
at runtime — the D3 CDN script tag — so a built page can be opened
offline, emailed, or dropped anywhere and still work.

## Development-time tools

These were used to build and verify the Suntola example and the
frontend itself, but nothing here ships in the final output:

| Tool | Used for |
|---|---|
| Wikidata & Wikimedia Commons APIs (manual lookup) | Sourcing place coordinates (`attributes.lat`/`lng`) — portraits are now `find_portraits.py`'s job, but coordinates are still verified by hand the same way; see [Data Accuracy & Provenance](data-accuracy.md). |
| [Playwright](https://playwright.dev/) + headless Chromium | Screenshot-based visual QA during frontend development. |
| Git / GitHub | Version control for the whole repository. |
| [MkDocs](https://www.mkdocs.org/) + [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) | This documentation site. |

## Why this stack

The choices all point the same direction: minimize what has to run to
view a biography. A subject's page should open by double-clicking a
file, not by standing up a server — so no framework, no build pipeline,
no backend. The data layer mirrors that: JSON files a person can read
and hand-edit, validated by a schema rather than enforced by an
application, so the "database" is just files under version control. The
same discipline extends to extraction and portraits: an LLM or a Wikidata
lookup can produce a faster first draft, but every fact still has to
clear the same schema-enforced provenance and referential-integrity
checks a hand-written subject would, and nothing about viewing or
building a subject ever depends on either being available.
