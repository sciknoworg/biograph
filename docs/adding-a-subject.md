# Usage Guide: Adding a New Subject

This is the repeatable process for turning a new biographical source (a
paper, an oral history, an archive) into a new `subjects/<slug>/` folder.
Follow it in order — each step depends on the one before. The live
version of this checklist lives in `extraction/EXTRACTION_GUIDE.md`.

!!! tip "Faster path: let an LLM draft it"
    ```bash
    pip install -r extraction/requirements.txt
    python3 scripts/build_site.py <slug> --pdf data/<paper>.pdf
    ```
    Prompts for a provider (OpenRouter, or any other
    OpenAI-compatible base URL — e.g. KISSKI), then a model name, then an
    API key — or skip the prompts with `--base-url`/`--model`/`--api-key`
    or the matching `BIOGRAPH_*` env vars. No model is hardcoded; type
    whatever your provider currently offers. If a reply is cut off before
    it finishes, it automatically continues the request rather than
    failing. Runs through this exact process and writes the result. Still
    a first-pass draft — step 7 below still applies to it. Full flag
    reference: [Usage Guide § Drafting a new subject](usage.md#1-drafting-a-new-subject-with-pdf).

!!! tip "Read the data model first"
    Before extracting anything, read
    [Data model reference](data-model.md) — in particular what counts as
    an "event" and the fuzzy-date chronology mechanism. Extraction is only
    consistent if it follows that model exactly: don't improvise a new
    event type or relation type mid-extraction. If nothing in the
    controlled vocabulary fits, use `"other"` for events, or see
    [Extending & Contributing](extending.md) for how to propose a new
    vocabulary value.

## 0. Read the whole source once, straight through

Before extracting anything, read the paper end to end to get the arc of
the story. Note in passing: who are the recurring people, places,
organizations, and named things (inventions, patents, products, books)?
This becomes the seed list for the next step.

## 1. Draft `entities.json`

One entry per distinct person, place, organization, or artifact that will
be referenced by at least one event or relation. Don't create an entity
for something mentioned exactly once with no dateable connection to
anything else, unless it will anchor a relation or event.

```json
{
  "id": "v_b_aleskovskii",
  "entity_type": "person",
  "name": "Valentin Borisovich Aleskovskii",
  "summary": "Soviet chemist who independently discovered molecular layering, the Soviet-side counterpart to Suntola's Atomic Layer Epitaxy.",
  "subtype": "researcher"
}
```

- `id`: snake_case, derived from the name (`v_b_aleskovskii`, not `person_1`).
- `summary`: static facts only — no dates, no "in 1974...". If a sentence
  has a "when," it belongs in an event instead.
- **Keep it terse.** One sentence a domain expert could scan and
  immediately place the entity — not a paragraph.
- Watch for id collisions between a place and an organization that share
  a name (e.g. a company town) — suffix one (`_city` / `_oy`) if needed,
  the way `subjects/suntola/entities.json` distinguishes `lohja_city`
  (place) from `lohja_oy` (organization).

## 2. Draft `sources.json`

At minimum, one entry for the source paper itself:

```json
{
  "id": "malygin2015",
  "title": "Aleskovskii and the molecular layering method",
  "authors": ["A. A. Malygin"],
  "year": 2015,
  "publication": "Some Journal",
  "file": "data/malygin2015.pdf"
}
```

Add more entries only if the paper itself cites another primary source
you're drawing directly from (an autobiography, an interview transcript).

## 3. Draft `events.json`

Walk the source again, this time pulling out every dateable occurrence
that meets the four requirements from
[Data model reference](data-model.md#what-counts-as-an-event) (a date,
however fuzzy; a type; at least one participant; at least one source
citation).

```json
{
  "id": "aleskovskii_molecular_layering",
  "event_type": "invention",
  "label": "Aleskovskii formulates molecular layering",
  "description": "Aleskovskii and Kol'tsov proposed the molecular layering method for surface synthesis of solid compounds.",
  "date": { "display": "1965", "precision": "year", "sort_start": "1965-01-01", "sort_end": "1965-12-31" },
  "location": "leningrad",
  "participants": [
    { "entity_id": "v_b_aleskovskii", "role": "inventor" },
    { "entity_id": "molecular_layering", "role": "invention" }
  ],
  "sources": [
    { "source_id": "malygin2015", "page": 4, "quote": "the molecular layering method was first proposed in 1965" }
  ]
}
```

Practical rules:

- **Every event date must trace to something the text actually says.** If
  the text says "in the early 1970s," `date.display` is `"early 1970s"`
  with `precision: "decade"` — not a guessed exact year.
- **`sources[].page` is required, on every event, not just pivotal
  ones.** This is the provenance: exactly where in the text a reader can
  go to check the claim. It's the PDF's *printed* page number, not the
  PDF viewer's page index, so citations match what a human reader sees;
  fall back to the nearest `[pdf page N]` marker if the source has none
  printed.
- **Quote sparingly** — `sources[].quote` is optional, reserved for the
  load-bearing sentence of a genuinely pivotal event (the invention
  moment, the first public disclosure), not added to every citation.
- **Keep `label` terse and scannable** — an expert should read it alone
  and know what happened ("Moved to Texas Instruments"), not a full
  sentence. Put any extra context in `description`, at most one tight
  sentence, and only if `label` doesn't already say it.
- **Don't split one sentence into five events.** A paragraph describing
  one coherent episode is one event with a fuller description.
- **Capture connective-tissue events too** — an organization founded,
  sold, or renamed; a collaborator's milestone that later matters to the
  subject — not just the subject's own life events. These are what make
  the graph interesting to explore, and what a future
  [cross-subject bridge](#8-once-both-subjects-exist-cross-subject-bridges)
  connects to.

## 4. Draft `relations.json`

For each event that implies a durable fact about the connection between
two entities (an employment, an invention, a founding, a visit), add a
corresponding relation with `event_id` pointing back to it:

```json
{
  "id": "aleskovskii_invented_molecular_layering",
  "source": "v_b_aleskovskii",
  "type": "invented",
  "target": "molecular_layering",
  "event_id": "aleskovskii_molecular_layering",
  "sources": [{ "source_id": "malygin2015", "page": 4 }]
}
```

Then add any relations the source states as a fact *without* a specific
dateable event behind it (e.g. "they remained close collaborators for the
rest of their lives") — these stand alone, with no `event_id`.

Keep relations directed per the vocabulary's defined reading direction —
e.g. `worked_at` always reads person → organization, never the reverse.
See [Data model reference](data-model.md#relations) for the full list.

## 5. Write `subject.json`

```json
{
  "slug": "aleskovskii",
  "name": "V. B. Aleskovskii",
  "summary": "Discoverer of molecular layering — from Malygin (2015)"
}
```

## 6. Validate and build

```bash
pip install jsonschema --break-system-packages   # once
python3 scripts/build_site.py aleskovskii
```

The build validates every file against the schemas *and* checks
referential integrity before writing `dist/aleskovskii.html`. Fix every
reported error — see [Usage Guide](usage.md#example-a-referential-integrity-failure-and-its-fix)
for a worked example of diagnosing one.

## 7. Open the built page and sanity-check it

Click through a handful of entities and events. Things to look for: nodes
with no connections at all (probably a relation is missing), events
clustered at implausible dates (probably a `sort_start`/`sort_end` typo),
and any name that renders as `undefined` (a broken id reference).

## 8. Once both subjects exist: cross-subject bridges

Create `subjects/_bridges/<a>-<b>.json` — an array of relation objects
using the same shape as `relation.schema.json`, except `source`/`target`
are qualified as `"<slug>:<entity_id>"`:

```json
[
  {
    "id": "suntola_met_aleskovskii_leningrad",
    "source": "suntola:tuomo_suntola",
    "target": "aleskovskii:v_b_aleskovskii",
    "type": "met",
    "event_id": "suntola:suntola_visits_leningrad",
    "sources": [{ "source_id": "suntola:puurunen2014", "page": 341 }]
  }
]
```

This keeps each subject file self-contained while still letting a later
combined view draw the edges between them. The Puurunen paper already
documents one such link — Suntola's 1990 visit to Leningrad to meet
Aleskovskii (`subjects/suntola/events.json#suntola_visits_leningrad`) —
so `aleskovskii-suntola.json` is the first bridge file this project will
need once `subjects/aleskovskii/` exists.
