# Data Accuracy & Provenance

Biograph has no automated fact-checker that re-reads a source PDF and
cross-verifies every claim. Accuracy instead comes from several layers of
discipline stacked together — this page documents each one, and is honest
about where the layers stop.

That's true whether a subject's first draft was written by hand or by
[`scripts/build_site.py --pdf`](usage.md#1-drafting-a-new-subject-with-pdf)
(an LLM reading the PDF). That flag is a faster way to *produce* a
draft, not a different accuracy standard — the same layers below apply to
its output, starting with the fact that it can't skip schema validation
(layer 2) and ends the same way any extraction should: a human checking
the draft against the source (layer 5) before it's trusted.

## 1. Source-grounded extraction

Every event and relation is **required** to cite a source (`sources.json`
entry id, plus where possible a page number and a supporting quote) — see
the `sources` field in [Data model reference](data-model.md#events). If
the paper doesn't say it, it doesn't go in the graph. This is enforced
structurally: `event.schema.json` and `relation.schema.json` both require
a non-empty `sources` array (`minItems: 1`), so an uncited event or
relation fails validation and the build refuses to produce a page.

## 2. Schema validation at build time

`scripts/build_site.py` validates every subject file against its JSON
Schema before building anything, and separately checks **referential
integrity**: every event participant, every event's `location`, every
relation's `source`/`target`/`event_id`, and every `sources[].source_id`
must point to something that actually exists in that subject's files. See
[Usage Guide](usage.md#example-a-referential-integrity-failure-and-its-fix)
for a worked example of the build catching a broken reference.

The same pass also enforces each relation type's **fixed reading
direction** — `worked_at` always checks that `source` is a `person` and
`target` is an `organization`, never the reverse, for all 27 relation
types in `relation.schema.json`. This used to be convention only (stated
in the extraction prompt and `schema/README.md`, but not code-enforced);
a reversed or mistyped direction now fails the build with exactly which
entity_type was expected, the same way an unknown id does, instead of
building cleanly and only looking wrong once you inspect the graph.

Closed vocabularies for `entity_type`, `event_type`, and relation `type` (see
[Data model reference](data-model.md)) mean nothing free-text can drift
into an inconsistent category across subjects.

## 3. Honest uncertainty in dates

The [fuzzy-date chronology mechanism](data-model.md#chronology-fuzzy-dates)
exists specifically so an approximate date ("early 1970s") never gets
forced into a fake precise one. `sort_start`/`sort_end` are explicitly
documented as sort keys only, never an assertion of exactness. Events also
carry an optional `certainty` field (`certain` / `approximate` /
`disputed`) for cases where the source itself hedges or where sources
disagree.

## 4. Verified provenance for portraits and coordinates

Anything visual that could be flatly wrong — a person's photo, a place's
map coordinates — goes through an explicit verification step before it's
attached, rather than being added on a "looks about right" basis.

### Portraits

A `person` entity may carry an optional `portrait` (see
[Data model reference](data-model.md#entities)) — a photo, **hotlinked**
from Wikimedia Commons, not embedded, so the file stays small and the
credit stays live and checkable.

```bash
python3 scripts/find_portraits.py <slug>
```

[`scripts/find_portraits.py`](https://github.com/sciknoworg/biograph/blob/main/scripts/find_portraits.py)
automates the procedure below for every `person` entity without a
portrait, using the same rule it's always been: a wrong photo is worse
than none, so an entity is left without one rather than guessed at.

1. Search Wikidata for the person's name (and aliases).
2. **Verify identity** before trusting anything else about the match.
   `portrait.confidence` records which tier was cleared:
    - **`birth_year_verified`** — this subject's own `events.json`
      already has a `birth` event for the person, and it matches exactly
      one candidate's Wikidata P569 (date of birth). Purely mechanical —
      the script does this with no LLM call at all, the strongest signal
      since a coincidence at this specificity is very unlikely.
    - **`description_verified`** — no birth event to check against (or
      more than one same-named candidate shares that birth year), so an
      LLM judges whether a candidate's Wikidata description is specific
      enough that it couldn't plausibly be a namesake (e.g. "Japanese
      physicist (1926–2018)" for a Japanese physicist the source
      discusses in that era — not just "researcher," too generic to rule
      out a different person). This is the same judgment call a human
      would make reading the same two facts side by side; the script
      just asks the model to make it, using whatever provider/model was
      already configured for extraction (or prompting for one, the first
      time it's actually needed).
    - Anything weaker is **not verified**: the entity is left without a
      portrait. `confidence: "unverified"` is never actually written to a
      file — it's not a value that means "attach it anyway."
3. Only once verified, and only if that candidate has a Wikidata P18
   image: resolve the actual file and its license via the Commons API
   (`action=query&prop=imageinfo&iiprop=extmetadata`), never by guessing
   a filename — and never attach one if Commons can't report a license
   for it. The stable **Special:FilePath** link
   (`https://commons.wikimedia.org/wiki/Special:FilePath/<file>?width=200`)
   becomes `portrait.image_url`, so it keeps resolving even if the
   underlying file is renamed; the Commons file page becomes
   `portrait.source_url`, so a reader can check the license and original
   themselves.

Every Wikidata/Commons lookup is wrapped individually — a network hiccup
or an unreachable host (e.g. a restrictive proxy) skips just that one
person with a printed reason, rather than failing the whole run. Pass
`--no-llm` to disable the description-tier check entirely (birth-year
matches only, no API key ever needed), or `--force` to re-check people
who already have a portrait.

The Suntola example has three verified portraits (Tuomo Suntola —
`birth_year_verified`; Jun-ichi Nishizawa and Markku Leskelä — both
`description_verified`), each carrying its `wikidata_qid`, `license`,
and `source_url` for anyone to re-check.

### Place coordinates

A `place` entity that should appear on the [Map view](frontend-guide.md#map-view)
carries `attributes.lat` / `attributes.lng` (decimal degrees) and, for
provenance, `attributes.wikidata_qid`. These come from Wikidata's P625
(coordinate location), verified the same way as a portrait: confirm the
candidate is the right place (country/description match) before trusting
its coordinates. A `place` entity without `lat`/`lng` simply doesn't
appear on the map — it still works everywhere else (graph, timeline).

## 5. Human review, iterated

The Suntola extraction has been reviewed and corrected multiple times
against the source paper during development — a transcription typo
("Sentola" → "Suntola"), a duplicate entity id (a place and an
organization both wanting `lohja`), and a mislabeled timeline category
were all caught this way, not by an automated check. The `README.md`
status note for `subjects/suntola/` says it plainly: treat any first-pass
extraction as a **draft to review against the source, not ground truth**.
A second pair of eyes checking the JSON against the original PDF is a
reasonable sanity pass before treating any subject as authoritative — see
[Usage Guide](usage.md#sanity-checking-a-build) for what to look for.

## The color palette

Entity-type colors follow a categorical palette validated for
colorblind-safety: adjacent-pair CVD (color-vision-deficiency) Delta E
checked against both a hard gate and a normal-vision floor, run through a
palette validator rather than chosen by eye. In the shipped light theme:
person is blue (`#2a78d6`), place is aqua/green (`#1baf7a`), organization
is orange (`#eb6834`), artifact is violet (`#4a3aa7`), and the award/gold
accent (`#eda100`) is reserved for the Milestones/Publications lane. Color
never carries meaning alone in the frontend — every colored mark is
paired with a legend, a label, or both.
