# Usage Guide

The tool surface is two scripts, both run from the repository root, used
in this order: `scripts/build_site.py` (draft a subject from a PDF with
`--pdf`, and either way validate + build it) and `scripts/find_portraits.py`
(attach verified Wikidata/Commons photos, once a subject has data).

## 1. Drafting a new subject with `--pdf`

```bash
pip install -r extraction/requirements.txt
python3 scripts/build_site.py <slug> --pdf data/<paper>.pdf [options]
python3 scripts/build_site.py <slug> --text data/<paper>.txt [options]
```

See [Adding a new subject](adding-a-subject.md) for the full walkthrough
of what a good draft looks like; this section is the command/flag
reference. `<slug>` becomes the directory name under `subjects/`.

| Flag | Default | What it does |
|---|---|---|
| `--name` | slug, title-cased | Display name for `subject.json`. |
| `--model` | *(prompted)* | Model name, exactly as your provider lists it. `BIOGRAPH_MODEL` skips the prompt. No default is hardcoded — model lineups move too fast for a baked-in one to stay current. |
| `--base-url` | *(prompted)* | Provider's API base URL. The prompt offers OpenRouter by name, or "Other" to paste any OpenAI-compatible URL (e.g. KISSKI). `BIOGRAPH_BASE_URL` skips the prompt. |
| `--api-key` | *(prompted, hidden input)* | `BIOGRAPH_API_KEY` also skips the prompt. |
| `--max-chars` | `180000` | Truncates the extracted PDF text beyond this many characters, for very long sources. |
| `--max-tokens` | `32000` | Reply budget per request. If the model hits this mid-subject, the script automatically asks it to continue and stitches the pieces together (up to 8 rounds) rather than failing — see below. |
| `--text` | — | Same as `--pdf`, named for clarity when the source is already-extracted text rather than a PDF. Pass one or the other, not both. |
| `--keep-rejected` | off | When the model judges the source out of scope (see step 3 below), the source passed via `--pdf`/`--text` is deleted automatically. Pass this to leave it in place instead. |
| `--keep-source-pdf` | off | Also archive the original PDF beside the extracted text. Off by default: the text is what the model read and what `--check-grounding` verifies against, at ~3% of the size, and `sources.json` already carries the citation needed to fetch the original again. |

### What it does, in order

1. **Reads** the PDF with `pypdf`, inserting a `[pdf page N]` marker at
   each page break so the model can cite real page numbers.
2. **Builds the prompt** by embedding `schema/*.schema.json` verbatim —
   the model sees the exact field names, enums, and provenance/terseness
   requirements, not a paraphrase, so the prompt can't drift out of sync
   with the data model.
3. **Asks the model** for a single JSON object with six keys: `scope`
   (`{"fits": <bool>, "reason": "<one sentence>"}`, judging whether the
   document is even a biographical/historical retrospective essay in
   this project's sense — see `SCOPE_DEFINITION` in
   `scripts/build_site.py`) plus the usual `subject`, `entities`,
   `events`, `relations`, `sources`. If `scope.fits` comes back `false`,
   nothing is written under `subjects/`: the PDF passed via `--pdf` is
   deleted (unless `--keep-rejected`) and the script exits, printing the
   model's reason. A missing or malformed `scope` (an older prompt, a
   model that ignored the instruction) is treated as unknown, not as a
   rejection — extraction proceeds rather than guessing. If a reply is
   cut off at the `--max-tokens` limit before finishing, it automatically
   sends the partial reply back and asks the model to continue exactly
   where it left off, repeating until the reply finishes or it's asked to
   continue 8 times in a row (at which point it stops and tells you to
   try a smaller `--max-chars` or a larger `--max-tokens`).
4. **Checks grounding** — every `sources[].quote` is searched for in the
   source text, and every entity name too. Anything not found verbatim is
   reported, separating a misquote from something not in the document at
   all. See [Data Accuracy § Grounding](data-accuracy.md#2-grounding-the-hallucination-check).

5. **Writes** the document's four files into
   `subjects/<domain>/<slug>/<citation-key>/`, where the citation key is the
   source's own `sources[0].id` (e.g. `puurunen_2014`), and
   `subject.json` into `subjects/<domain>/<slug>/` above them:

   ```
   subjects/materials_science/suntola/
     subject.json              canonical name + slug — the person
     puurunen_2014/
       entities.json           people, places, organizations, artifacts
       events.json             dated occurrences, each cited — the timeline
       relations.json          durable links (worked_at, invented, ...)
       sources.json            the document, for citation
   ```

   A second paper about the same person lands beside the first rather
   than overwriting it. The source's `file` field is forced to point at
   the archived extracted text (`data/<slug>.txt`) rather than whatever
   path the model guessed; that text isn't committed — see
   `data/README.md`.

6. **Validates and builds** — the exact same `validate_subject()`/`build()`
   used for a hand-written subject (see below), no separate code path — a
   validation failure is reported exactly like a hand-written subject's
   would be, pointing at `subjects/<domain>/<slug>/*.json` to fix.

### Treat the result as a first-pass draft

An LLM can misdate an event, mis-cite a page, or miss a fact the source
states in passing. Validation catches *structural* problems (a broken
reference, a wrong enum value, a missing page citation) — it can't catch
a wrong date or a misattributed quote. Review the draft against the PDF
before trusting it; see [Sanity-checking a build](#sanity-checking-a-build)
below and [Data Accuracy & Provenance](data-accuracy.md).

## 2. Building & validating

```bash
python3 scripts/build_site.py <slug>     # build one subject
python3 scripts/build_site.py --all      # build every subject under subjects/
python3 scripts/build_site.py <slug> --check-grounding   # audit against the source
```

Everything in this section assumes the subject's folder already has data —
either just drafted (step 1) or written by hand. For the shipped example
that's `suntola` (i.e. `subjects/suntola/`), which needs no API key to
build.

### What a build does, in order

1. **Loads** `subjects/<slug>/subject.json` plus every document folder
   beneath it, merging them into one graph: entities sharing an id are the
   same thing and their `aliases` are unioned, while events and relations
   are never merged — two papers describing one episode are two accounts,
   not one claim, and an id colliding across documents is prefixed with
   its document key.
2. **Validates** each file against its schema in `schema/` (entity, event,
   relation, source — dates are validated inline via `$ref`), using
   [`jsonschema`](https://pypi.org/project/jsonschema/)'s
   `Draft202012Validator`. This includes provenance: every event and
   relation source citation must carry a `page` number, not just a
   `source_id`.
3. **Checks referential integrity** — every event's `participants[].entity_id`
   and `location`, every relation's `source`/`target`/`event_id`, and
   every `sources[].source_id` (on both events and relations) must point
   to something that actually exists in this subject's files. For
   relations, this also checks the vocabulary's fixed reading direction —
   a `worked_at` relation's `source` must actually be a `person` entity
   and its `target` an `organization`, for all 27 relation types, not
   just that the ids resolve. A relation that fails this check, or whose
   `source`/`target` names an entity that doesn't exist, is **set aside
   rather than fatal** — see "Set-aside relations" below.
4. **Sorts** events by `date.sort_start` (ties broken by `sort_end`).
5. **Inlines** the subject's data — plus the shared, pre-converted world
   map GeoJSON — into `frontend/template.html`, producing
   `dist/<slug>.html`: a single self-contained page (network graph, map,
   timeline). Open it directly in a browser, no server needed.

If step 2 or 3 finds a problem, the build **fails loudly** and lists every
error before writing anything:

```
Validation failed for subject 'suntola':
  event suntola_born: 'date' is a required property
  event humicap_developed: unknown source 'puurunen2015'
  relation ulf_strom_employed: unknown target entity 'finlux_oy'
```

Fix every reported error — don't work around a validation failure by
deleting the offending field. See
[Data Accuracy & Provenance](data-accuracy.md) for why this check exists.

### Example: a clean build

```console
$ python3 scripts/build_site.py suntola
Building 'suntola'...
  67 entities, 42 events, 50 relations
  -> dist/suntola.html
```

### Example: a referential-integrity failure and its fix

Say you add a new event that cites a source id that doesn't exist yet:

```json
{
  "id": "new_patent_filed",
  "event_type": "patent_filed",
  "label": "New patent filed",
  "date": { "display": "1985", "precision": "year", "sort_start": "1985-01-01", "sort_end": "1985-12-31" },
  "participants": [{ "entity_id": "tuomo_suntola", "role": "inventor" }],
  "sources": [{ "source_id": "puurunen_2015", "page": 12 }]
}
```

If `sources.json` only has an entry with id `puurunen2014`, the build
stops with:

```
Validation failed for subject 'suntola':
  event new_patent_filed: unknown source 'puurunen_2015'
```

The fix is either to correct the typo (`puurunen2014`) or to add the
missing entry to `sources.json` — never to remove the citation to make
the error go away, since every event requires at least one source (see
[Data model reference](data-model.md#events)).

### Example: a reversed relation direction and its fix

Say a relation gets written backwards — `worked_at` with the organization
as `source` instead of the person:

```json
{
  "id": "suntola_worked_at_instrumentarium",
  "source": "instrumentarium",
  "type": "worked_at",
  "target": "tuomo_suntola",
  "sources": [{ "source_id": "puurunen2014", "page": 20 }]
}
```

Both ids exist, so referential integrity alone wouldn't catch this — but
the build does, because `worked_at` requires a `person` source and an
`organization` target:

```
  (1 relation(s) set aside -- unexpected entity_type for the relation type; the rest of the extraction is kept)
    suntola_worked_at_instrumentarium: 'worked_at' expects source entity_type person, but 'instrumentarium' is 'organization'
    -> parked in subjects/suntola/puurunen2014/relations.rejected.json
```

The fix is to swap `source` and `target` — never to change the relation's
`type` to something that happens to accept the wrong direction just to
silence the error.

### Set-aside relations

A relation whose ends resolve to real entities but carry an unexpected
`entity_type`, or which points at an entity that was never defined, is
**dropped from the build and written to
`subjects/<slug>/<doc>/relations.rejected.json`** — with the reason and its
full source citation — instead of failing the whole subject.

This is reported, not enforced, for the same reason as the grounding check:
it is a first-pass draft either way, and a hard gate threw away far more than
it protected. Measured across this project's automated runs, **23 complete
extractions were discarded over 26 offending relations** — roughly one bad
edge each, costing about 20 entities, 15 events and 12 relations every time.

Nothing is lost. A set-aside relation is often a *variant reading* rather than
an error — "employed by" a person (an apprentice and his master) is real
history that the vocabulary simply didn't allow — so the parked file doubles as
evidence for which `RELATION_DIRECTIONS` entries are too narrow. Review it, fix
the entity's type or the relation's direction, and rebuild.

Events are treated the same way, narrowly. An event is set aside into
`events.rejected.json` when a required list came back **empty** — it names nobody,
or cites nothing, so it can be neither rendered nor verified. A participant or a
`location` naming an entity nobody defined is simply dropped, keeping the event:
the reference points at nothing, so removing it corrupts nothing, and one dangling
name should not sink a thirty-event extraction. An event left with no participants
at all then joins the set-aside path.

What remains fatal is corruption that would make the rest untrustworthy: a
malformed date, a missing source citation, a schema violation in an entity or
source. The rule throughout is that a leaf may be removed and the whole kept, but
nothing is silently repaired.

### Building without `jsonschema` installed

If the package isn't installed, the build still runs but skips validation
entirely:

```console
$ python3 scripts/build_site.py suntola
Building 'suntola'...
  (jsonschema not installed — skipping schema validation; pip install jsonschema to enable it)
  67 entities, 42 events, 50 relations
  -> dist/suntola.html
```

This is convenient for a quick local preview, but **always validate
before committing** — an unvalidated build can silently ship broken
references (e.g. a node that renders as `undefined`).

### Sanity-checking a build

After a successful build, open `dist/<slug>.html` and look for:

- Nodes with **no connections at all** — usually means a relation is
  missing.
- Events clustered at an **implausible date** — usually a
  `sort_start`/`sort_end` typo.
- Any name rendering as **`undefined`** — a broken id reference that
  somehow passed validation (e.g. a stale copy of a schema file).

## 3. Finding portraits with `find_portraits.py`

```bash
python3 scripts/find_portraits.py <slug> [options]
```

Full explanation of what it does and why: [Data Accuracy & Provenance §
Portraits](data-accuracy.md#portraits). Flags:

| Flag | Default | What it does |
|---|---|---|
| `--force` | off | Re-check entities that already have a portrait, instead of skipping them. |
| `--no-llm` | off | Birth-year matches only — never makes an LLM call, so no API key is needed at all. |
| `--no-build` | off | Skip rebuilding `dist/<slug>.html` afterward (only runs if a portrait was actually attached). |
| `--model`, `--base-url`, `--api-key` | *(prompted, only if needed)* | Same as `build_site.py --pdf`. Only asked for the first time a `description_verified` judgment call actually comes up — never if every match resolves by exact birth year, or `--no-llm` is passed. |

Run it any time after a subject has data — right after drafting it with
`build_site.py --pdf`, or later, or repeatedly with `--force`. Output:
attaches a verified `portrait` object to the matched entries in
`entities.json`, and rebuilds `dist/<slug>.html`.

```bash
python3 scripts/build_site.py aleskovskii --pdf data/malygin2015.pdf
python3 scripts/find_portraits.py aleskovskii
```

Every Wikidata/Commons lookup fails independently and prints why (a
network error, no match, no image, an unresolvable license) rather than
stopping the whole run — so a restrictive network only costs you that one
person's photo, not the rest.
