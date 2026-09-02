# Extracting a new subject from a source paper

This is the repeatable process for turning a new biographical source (e.g.
the Malygin paper on Aleskovskii) into a subject folder under `subjects/`.
Follow it in order — each step depends on the one before.

> **Faster path:** `python3 scripts/build_site.py <slug> --pdf <pdf>` runs
> an LLM through exactly this process and writes the result for you (see
> the repo README). This document is what it follows internally, and what
> to check its draft against — step 8 below still applies to its output.

## 0. Read `schema/README.md` first

It defines what counts as an event, the chronology mechanism (fuzzy dates
with `sort_start`/`sort_end`), and the controlled vocabularies. Extraction
is only consistent if it follows that model exactly — don't improvise a
new event type or relation type mid-extraction; if nothing in the enum
fits, either use `other` (events) or open a discussion about extending the
vocabulary (see schema/README.md § "Extending the vocabularies") rather
than inventing a value that will fail schema validation.

## 1. Read the whole source once, straight through

Before extracting anything, read the paper end to end to get the arc of
the story. Note in passing: who are the recurring people, places,
organizations, and named things (inventions/patents/products/books)? This
becomes the seed list for step 2.

## 2. Draft `subjects/<slug>/entities.json`

One entry per distinct person, place, organization, or artifact that will
be referenced by at least one event or relation. Don't create an entity
for something mentioned exactly once with no dateable connection to
anything else (a passing name in a photo caption with nothing else known)
unless it will anchor a relation or event.

- `id`: snake_case, derived from the name (`v_b_aleskovskii`, not `person_1`).
- `entity_type`: `person | place | organization | artifact`.
- `summary`: one terse sentence, static facts only — no dates, no
  "in 1974 ...". If a sentence has a "when," it belongs in an event
  instead, not here. A domain expert should be able to scan it and
  immediately place the entity — not a paragraph.
- Watch for id collisions between a place and an organization that share a
  name (e.g. a company town) — suffix one (`_city` / `_oy`) if needed.

## 3. Draft `subjects/<slug>/sources.json`

At minimum, one entry for the source paper itself (id, title, authors,
year, publication, `file` pointing at the PDF under `data/`). Add more
entries if the paper itself cites another primary source you're drawing
directly from (e.g. an autobiography, an interview transcript).

## 4. Draft `subjects/<slug>/events.json`

Walk the source again, this time pulling out every dateable occurrence
that meets the four requirements in schema/README.md (date, type,
participants, source citation). Practical rules:

- **Every event date must trace to something the text actually says.**
  If the text says "in the early 1970s," the event's `date.display` is
  `"early 1970s"` with `precision: "decade"` — not a guessed exact year.
- **`sources[].page` is required, on every event, not just pivotal
  ones.** This is the provenance: exactly where in the text a reader can
  go to check the claim — the PDF's printed page number (bottom of page),
  not the PDF viewer's page index, so citations match what a human reader
  sees; fall back to the nearest `[pdf page N]` marker if unprinted.
- **Quote sparingly** — `sources[].quote` is optional, reserved for the
  load-bearing sentence of a genuinely pivotal event (the actual
  invention moment, the first public disclosure), not added everywhere.
- **Keep `label` terse and scannable** — an expert should read it alone
  and know what happened ("Moved to Texas Instruments"), not a full
  sentence. Put extra context in `description`, at most one tight
  sentence, only if `label` doesn't already say it.
- **Don't split one sentence into five events.** A paragraph describing
  one coherent episode (e.g. "the first successful reactor run") is one
  event with a fuller description, not one event per clause.
- **Do capture the connective tissue events**, not just the subject's own
  milestones: when an organization is founded, sold, or renamed; when a
  collaborator does something that later matters to the subject. These are
  what make the graph interesting to explore, and what a future
  cross-subject bridge (§ below) will connect to.

## 5. Draft `subjects/<slug>/relations.json`

For each event that implies a durable fact about the connection between
two entities (an employment, an invention, a founding, a visit), add a
corresponding relation with `event_id` pointing back to it. Then add any
relations the source states as a fact *without* a specific dateable event
behind it (e.g. "they remained close collaborators for the rest of their
lives") — these stand alone, no `event_id`.

Keep relations directed per the vocabulary's defined reading direction
(see schema/README.md § Relations) — e.g. `worked_at` always reads
person → organization, never the reverse. This is build-enforced, not
just a convention: get it backwards and step 7 rejects it with exactly
which `entity_type` it expected.

## 6. Write `subjects/<slug>/subject.json`

```json
{ "slug": "<slug>", "name": "<display name>", "summary": "<one line, shown in the page header>" }
```

## 7. Validate and build

```
pip install jsonschema --break-system-packages   # once
python3 scripts/build_site.py <slug>
```

The build script validates every file against the schemas *and* checks
referential integrity (every `entity_id`, `location`, `source_id`, and
`event_id` referenced actually exists) before writing
`dist/<slug>.html`. Fix every reported error — don't hand-wave past a
validation failure by deleting the offending field.

## 8. Open `dist/<slug>.html` and sanity-check it

Click through a handful of entities and events. Things to look for: nodes
with no connections at all (probably a relation is missing), events
clustered at implausible dates (probably a `sort_start`/`sort_end` typo),
and any name that renders as `undefined` (a broken id reference that
somehow passed validation, e.g. a stale copy of the schema).

## 9. Once both subjects exist: cross-subject bridges

Create `subjects/_bridges/<a>-<b>.json` — an array of relation objects
using the same shape as `relation.schema.json`, except `source`/`target`
are qualified as `"<slug>:<entity_id>"` (e.g. `"suntola:tuomo_suntola"`,
`"aleskovskii:v_b_aleskovskii"`). This keeps each subject file
self-contained while still letting a later "combined view" draw the edges
between them (e.g. the Puurunen paper already documents one: Suntola's
1990 visit to Leningrad to meet Aleskovskii — see
`subjects/suntola/events.json#suntola_visits_leningrad`).
