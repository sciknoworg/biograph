# Biograph data model

This defines the scaffolding for turning a biographical source (a paper, an
oral history, an archive) into a small, queryable knowledge graph + timeline.
It is deliberately narrow: four JSON files per subject, each validated
against a JSON Schema in this folder. The goal is a model tight enough that
two different people extracting from the same paper would produce
essentially the same data.

## The four files (per subject, under `subjects/<slug>/`)

- `entities.json` — the nouns: people, places, organizations, and named
  "artifacts" (inventions, patents, products, publications, companies-as-
  things-founded). Everything an event or relation can point to.
- `events.json` — the things that happened. See "What counts as an event"
  below.
- `relations.json` — simple typed edges between two entities (`visited`,
  `worked_at`, `lived_in`, ...). Some relations are just a durable summary
  of an event (e.g. an `employment_start` event implies a `worked_at`
  relation); others stand alone when the source states a fact without a
  datable event behind it (e.g. "they were lifelong friends").
- `sources.json` — the source document(s) this subject's data was
  extracted from. Every event and relation cites at least one source here.

A subject is self-contained: nothing in `subjects/suntola/` refers to an id
in `subjects/aleskovskii/`. Cross-subject connections (the whole reason for
having two biographies) get their own bridge file once both subjects exist:
`subjects/_bridges/<a>-<b>.json`, using the same relation shape but with
entity ids qualified as `subject:id` (e.g. `suntola:tuomo_suntola`).

## What counts as an "event"

An event is a **dateable occurrence**, not a fact or a description. The
test: could you point to roughly *when* it happened, even fuzzily? If the
source only tells you a static fact with no timeframe ("Suntola was
interested in eastern philosophy"), it is not an event — it's either
dropped, or captured as a note on the entity.

Every event must have:

1. **A date**, however imprecise (a specific day, a month, a year, a
   decade, or a `circa` guess) — never "undated."
2. **A type**, drawn from the controlled vocabulary in `event.schema.json`
   (`event_type`). If nothing fits, use `"other"` and explain in the
   description rather than inventing a new type ad hoc.
3. **At least one participant** — the entity or entities the event is
   about. A "company founded" event participates the founder(s) and the
   organization founded (with `roles` distinguishing them).
4. **At least one source citation** — `source_id` and a `page` are both
   required: provenance means a reader can turn to exactly where in the
   text this came from. A short supporting `quote` is optional, reserved
   for pivotal events rather than added everywhere. No event is entered on
   inference or general knowledge; if the paper doesn't say it, it doesn't
   go in.

Events are the join between the graph and the timeline: the timeline is
just `events.json` sorted by date; the graph is `entities.json` +
`relations.json`, and relations may (optionally) point back to the event
that established them via `event_id`, so clicking a graph edge can jump to
its moment in the timeline and vice versa.

## Chronology mechanism

Biographical sources rarely give clean ISO dates ("in the early 1970s",
"by the end of 1973", "1963"). Rather than fake precision, every event
date is an object with:

- `display` — the human-readable string as it should be shown ("1963",
  "August–September 1974", "c. 1958", "early 1970s").
- `precision` — one of `day | month | year | decade | circa | range`.
- `sort_start` / `sort_end` — ISO `YYYY-MM-DD` bounds used **only** for
  sorting and for drawing a point-vs-span on the timeline; they are the
  earliest/latest the event could plausibly be, not an implied exact date.
  For a single fuzzy point, `sort_start == sort_end`.

This keeps ordering well-defined (sort by `sort_start`, break ties by
`sort_end`) without ever putting a false-precision date in front of a
reader. A `range`-precision event (e.g. "worked at Lohja, 1974–1987")
renders as a bar on the timeline instead of a point.

## Entities

`entity_type` is one of `person | place | organization | artifact`.
`artifact` covers inventions, patents, products, publications, and other
named things-that-aren't-people-places-or-orgs (e.g. "Atomic Layer
Epitaxy", "the 1974 ALE patent", "Humicap sensor"). Keeping these as
entities (not just event descriptions) lets the graph show, e.g., one
invention connected to every person who worked on it and every event in
its history.

**Coordinates for the map view**: a `place` entity that should appear on
the frontend's map view carries `attributes.lat` / `attributes.lng`
(decimal degrees) and, for provenance, `attributes.wikidata_qid`. Get
these from Wikidata's P625 (coordinate location) the same way as a
portrait (see "Portraits" below) — verify the candidate is the right
place (country/description match) before trusting its coordinates. A
`place` entity without `lat`/`lng` simply doesn't appear on the map; it
still works everywhere else (graph, timeline).

## Relations

A relation is `{ source, type, target }` plus optional time bounds
(`start`/`end`, same fuzzy-date shape as events, precision-only, no
`display`/sort split needed since relations aren't independently plotted)
and source citations. `type` is drawn from the controlled vocabulary in
`relation.schema.json`. Relations are directed; the vocabulary defines the
reading direction (e.g. `worked_at`: person → organization) — and
`scripts/build_site.py`'s `RELATION_DIRECTIONS` table enforces it at
build time, checking that `source`/`target` actually have the expected
`entity_type` for that relation `type`, not just that the ids resolve.
Keep that table in sync with this vocabulary the same way as
`event_type` (see "Extending the vocabularies" below).

## IDs

All ids are lowercase `snake_case`, unique within their file's type and
stable once assigned (other files reference them). Prefer human-legible
ids (`tuomo_suntola`, `ale_1974_patent`) over generated hashes — this data
is meant to be hand-editable.

## Portraits

A `person` entity may carry an optional `portrait` — a photo, hotlinked (not
embedded) from its source, so the file stays small and the credit stays
live and checkable. Never add one from an image search or by eyeballing a
"looks about right" photo. The required procedure:

1. Find the candidate's Wikidata item (`wbsearchentities`, or a web search
   for `"<name>" wikidata`).
2. Verify identity before trusting anything else about that item:
   - **`birth_year_verified`**: this subject's own `events.json` already
     has a `birth` event for the person, and the Wikidata item's P569
     matches it. Strongest signal — a coincidence at this specificity is
     very unlikely.
   - **`description_verified`**: no birth event to check against, but the
     Wikidata description/occupation is specific enough that it couldn't
     plausibly be a namesake (e.g. "Japanese physicist (1926–2018)" for a
     Japanese physicist the source discusses in that era — not just
     "researcher" or "academic", which are too generic to rule out a
     different person entirely).
   - Anything weaker (name matches but the description is generic, or
     contradicts known facts like nationality/era) is **not verified** —
     leave the entity without a portrait rather than guessing. A wrong
     photo is worse than none.
3. Only if verified, and the item has a P18 image: resolve the actual file
   and its license via the Commons API
   (`action=query&prop=imageinfo&iiprop=url|extmetadata`), not by
   guessing a filename. Use the **Special:FilePath** stable link
   (`https://commons.wikimedia.org/wiki/Special:FilePath/<file>?width=200`)
   as `portrait.image_url` so it keeps resolving even if the underlying
   file is renamed, and record the Commons file page as `source_url` so a
   reader can check the license and original themselves.
4. Fetching Wikidata/Commons requires a real browser context (fetch calls
   from a sandboxed shell are typically blocked) — use whatever browser
   tooling is available, not raw `curl`.

## Extending the vocabularies

`event_type` and relation `type` are closed enums on purpose — that's what
keeps extraction consistent. To add a value, edit the schema file and add
one line to this README's list rather than letting free-text types
accumulate across subjects. For a new relation `type`, also add its
`(source_types, target_types)` entry to `RELATION_DIRECTIONS` in
`scripts/build_site.py` — a type missing from that table silently skips
the direction check instead of enforcing it.

For where these vocabularies do (and don't) already exist in authoritative
semantic-web ontologies — CIDOC-CRM, schema.org, PROV-O, and others — see
[Ontology alignment](../docs/ontology-alignment.md).
