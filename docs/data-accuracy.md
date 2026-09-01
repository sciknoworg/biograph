# Data Accuracy & Provenance

Biograph has no automated fact-checker that re-reads a source PDF and
cross-verifies every claim. Accuracy instead comes from several layers of
discipline stacked together — this page documents each one, and is honest
about where the layers stop.

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
for a worked example of the build catching a broken reference. Closed
vocabularies for `entity_type`, `event_type`, and relation `type` (see
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
credit stays live and checkable. The required procedure, before adding
one:

1. Find the candidate's Wikidata item (`wbsearchentities`, or a web
   search for `"<name>" wikidata`).
2. **Verify identity** before trusting anything else about that item.
   `portrait.confidence` records which tier was cleared:
    - **`birth_year_verified`** — this subject's own `events.json`
      already has a `birth` event for the person, and the Wikidata item's
      P569 (date of birth) matches it. The strongest signal: a
      coincidence at this specificity is very unlikely.
    - **`description_verified`** — no birth event to check against, but
      the Wikidata description/occupation is specific enough that it
      couldn't plausibly be a namesake (e.g. "Japanese physicist
      (1926–2018)" for a Japanese physicist the source discusses in that
      era — not just "researcher," which is too generic to rule out a
      different person).
    - Anything weaker — a name match with a generic description, or one
      that contradicts a known fact like nationality or era — is **not
      verified**. `confidence: "unverified"` must never actually be used
      to add a portrait; the entity is left without one instead. A wrong
      photo is worse than none.
3. Only if verified, and the Wikidata item has a P18 image: resolve the
   actual file and its license via the Commons API
   (`action=query&prop=imageinfo&iiprop=url|extmetadata`), never by
   guessing a filename. The stable **Special:FilePath** link
   (`https://commons.wikimedia.org/wiki/Special:FilePath/<file>?width=200`)
   becomes `portrait.image_url`, so it keeps resolving even if the
   underlying file is renamed; the Commons file page becomes
   `portrait.source_url`, so a reader can check the license and original
   themselves.
4. Fetching Wikidata/Commons data requires a real browser context — a
   sandboxed shell's `fetch`/`curl` calls to those hosts are typically
   blocked. Use whatever browser tooling is available, not raw `curl`.

The Suntola example has three verified portraits (Tuomo Suntola, Jun-ichi
Nishizawa, Markku Leskelä), each carrying its `wikidata_qid`, `license`,
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
