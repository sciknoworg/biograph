# Architecture: Data Model Reference

A subject is a **person**. Each source document about them gets its own
folder beneath, named by that source's citation key, holding the four
JSON files validated against `schema/`. `subject.json` sits above them
and describes the person, not any one paper:

```
subjects/suntola/
  subject.json                  canonical name + slug
  puurunen_2014/                one document's extraction
    entities.json  events.json  relations.json  sources.json
  aris_2019/                    a second account of the same life
```

This page is the field-level reference; [Adding a new subject](adding-a-subject.md)
walks through producing them from a source paper.

### Several documents, one person

Each document folder is extracted independently and kept whole. Two
papers about the same person are two *accounts*, not one merged truth —
reconciling them (same human, different entity ids, one episode described
two ways) happens when the subject is **read**, so a wrong reconciliation
is a rendering bug you re-run rather than extraction you have destroyed.
Where two accounts disagree, both survive with their own citations, and
which document asserted what stays answerable.

On read: entities sharing an id are treated as the same thing and their
`aliases` unioned; **events and relations are never merged**, and an id
colliding across documents is prefixed with its document key.

`subject.json` carries exactly one canonical name for the person — the
fullest form seen — with every other form recorded in that person's
`aliases`, so one scientist never appears under several spellings.

A subject is self-contained: nothing in `subjects/suntola/` refers to an
id in `subjects/aleskovskii/`. Cross-subject connections get their own
[bridge file](adding-a-subject.md#8-once-both-subjects-exist-cross-subject-bridges),
with ids qualified as `subject:id` — subject-scoped, not document-scoped,
since a bridge connects two *people* and the document that mentioned the
link is already in that relation's own `sources[]`.

## What counts as an "event"

An event is a **dateable occurrence**, not a fact or a description. The
test: could you point to roughly *when* it happened, even fuzzily? If the
source only states a static fact with no timeframe ("Suntola was
interested in eastern philosophy"), it is not an event — it's either
dropped, or captured as a note on the entity's `summary`.

Every event must have, and `event.schema.json` enforces:

1. **A date**, however imprecise — never "undated." See
   [Chronology](#chronology-fuzzy-dates) below.
2. **A type**, drawn from the closed `event_type` vocabulary. If nothing
   fits, use `"other"` rather than inventing a value.
3. **At least one participant** — the entity or entities the event is
   about, each with a `role` (e.g. `"subject"`, `"employer"`,
   `"invention"`, `"awarding_body"`).
4. **At least one source citation** — `source_id` and `page` are both
   required: provenance means a reader can turn to exactly where in the
   text this came from — and a `quote`: the span of the document that
   states this fact, copied verbatim. Quotes are checked mechanically
   against the source afterwards (see
   [Data Accuracy § Grounding](data-accuracy.md#2-grounding-the-hallucination-check)), so a quote that cannot
   be copied exactly is a fact that should not be stated. No event is
   entered on inference or general knowledge.

Events are the join between the graph and the timeline: the timeline is
`events.json` sorted by date; the graph is `entities.json` +
`relations.json`, and a relation may optionally point back to the event
that established it via `event_id`.

## Chronology: fuzzy dates

Biographical sources rarely give clean ISO dates ("in the early 1970s",
"by the end of 1973", "1963"). Rather than fake precision, every date —
on an event, or on a relation's optional `start`/`end` bounds — is an
object (`date.schema.json`):

| Field | Meaning |
|---|---|
| `display` | The human-readable string as it should render: `"1963"`, `"August–September 1974"`, `"c. 1958"`, `"early 1970s"`. Required on events; optional on relation bounds. |
| `precision` | One of `day \| month \| year \| decade \| circa \| range`. |
| `sort_start` / `sort_end` | ISO `YYYY-MM-DD` bounds used **only** for sorting and for drawing a point vs. a span on the timeline — the earliest/latest the event could plausibly be, never an implied exact date. Equal for a single fuzzy point. |

This keeps ordering well-defined (sort by `sort_start`, ties broken by
`sort_end`) without ever putting a false-precision date in front of a
reader. A `range`-precision event (e.g. "worked at Lohja, 1974–1987")
renders as a bar on the timeline instead of a point.

## Entities

`entities.json` — the nouns: people, places, organizations, and named
"artifacts." `entity.schema.json` requires `id`, `entity_type`, and
`name`:

| Field | Notes |
|---|---|
| `entity_type` | `person \| place \| organization \| artifact`. `artifact` covers inventions, patents, products, publications, and companies-as-founded-things. |
| `aliases` | Other names/spellings this entity is referred to by in sources. |
| `summary` | One terse sentence, static facts only — no dates. A domain expert should be able to scan it and immediately place the entity. |
| `subtype` | Free text, e.g. person: `"researcher"`; place: `"city"`/`"country"`; organization: `"company"`/`"university"`/`"lab"`; artifact: `"invention"`/`"patent"`/`"product"`/`"publication"`/`"award"`. |
| `attributes` | Open `{}` for structured extras. Two conventions the frontend reads directly: a `place` entity carries `attributes.lat` / `attributes.lng` (decimal degrees) plus `attributes.wikidata_qid` for provenance, to appear on the [Map view](frontend-guide.md#map-view) — see [Data Accuracy & Provenance](data-accuracy.md#place-coordinates). |
| `portrait` | Optional, `person` only — a verified photo. See [Data Accuracy & Provenance](data-accuracy.md#portraits) for the required verification procedure before adding one. |

## Events

`events.json` — see [What counts as an "event"](#what-counts-as-an-event)
above for the model. `event.schema.json` fields:

| Field | Notes |
|---|---|
| `event_type` | Closed vocabulary of 22 values — see below. |
| `label` | Terse, scannable title an expert could read at a glance, e.g. `"Moved to Texas Instruments"` — not a full sentence. |
| `description` | Optional, at most 1 tight sentence, close to the source's own wording — only when `label` alone doesn't capture it. |
| `date` | The fuzzy-date object above. |
| `location` | Optional entity id of a `place`, if the source specifies where. Drives the [Map view](frontend-guide.md#map-view). |
| `participants` | Array of `{entity_id, role}`, minimum 1. |
| `certainty` | `certain` (default) \| `approximate` (source itself hedges) \| `disputed` (sources disagree). |
| `sources` | Array of `{source_id, page, quote}`, minimum 1. `page` locates the claim; `quote` is the document's own words for it, copied verbatim and checked against the source afterwards. |

**`event_type` values:** `birth`, `death`, `education`,
`employment_start`, `employment_end`, `role_change`, `invention`,
`patent_filed`, `patent_granted`, `publication`, `product_launch`,
`public_demonstration`, `conference`, `visit`, `meeting`, `relocation`,
`award`, `company_founded`, `company_sold`, `company_renamed`,
`retirement`, `other`.

## Relations

`relations.json` — simple typed, **directed** edges between two entities.
`relation.schema.json` fields:

| Field | Notes |
|---|---|
| `source` / `target` | Entity ids. Direction follows the vocabulary's defined reading — e.g. `worked_at` always reads person → organization — and the build enforces it: `source`/`target` must actually have the expected `entity_type` for that relation `type`, not just resolve to *some* entity. |
| `type` | Closed vocabulary of 27 values — see below. |
| `event_id` | Optional link back to the `events.json` entry that established this relation (e.g. an `employment_start` event implies a `worked_at` relation). |
| `start` / `end` | Optional fuzzy-date bounds (precision-only; no `display` needed since relations aren't independently plotted). |
| `note` | Free text. |
| `sources` | Array of `{source_id, page, quote}`, minimum 1. Same requirement as on events, and checked the same way. |

Some relations just durably summarize an event; others stand alone when
the source states a fact without a datable event behind it (e.g. "they
were lifelong friends").

Relations are directed, and each type fixes the `entity_type` of its two
ends (`worked_at`: person → organization). A couple of types accept two
kinds of target: `visited` and `lived_in` both take a `place` *or* an
`organization`, since a college or hospital is genuinely both a body and a
location. See `schema/README.md` for the full reasoning.

**`type` values:** `born_in`, `died_in`, `lived_in`, `visited`,
`relocated_to`, `worked_at`, `employed_by`, `founded`, `member_of`,
`supervised_by`, `mentored`, `collaborated_with`, `met`, `married_to`,
`family_of`, `studied_at`, `educated_by`, `invented`, `patented`,
`published`, `developed`, `awarded`, `licensed_to`, `acquired_by`,
`sold_to`, `renamed_to`, `corresponded_with`.

## Sources

`sources.json` — the source document(s) this subject's data was extracted
from. Every event and relation cites at least one entry here.
`source.schema.json` requires only `id` and `title`; `authors`, `year`,
`publication`, `file` (relative path under `data/`), `doi`, and `url` are
all optional. `file` points at the archived extracted text
(`data/<slug>.txt`) — what the model actually read, and what the
grounding check verifies against. Neither it nor the original PDF is
committed to the repo (`data/*.txt` and `data/*.pdf` are both gitignored)
— the citation fields here, especially `doi`, are the part that's actually
shared; see `data/README.md`.

## IDs

All ids are lowercase `snake_case`, unique within their file's type, and
stable once assigned — other files reference them. Prefer human-legible
ids (`tuomo_suntola`, `ale_1974_patent`) over generated hashes; this data
is meant to be hand-edited.

## Extending the vocabularies

`event_type` and relation `type` are closed enums **on purpose** — that's
what keeps extraction consistent across subjects. See
[Extending & Contributing](extending.md#extending-the-controlled-vocabularies)
for how to add a value.
