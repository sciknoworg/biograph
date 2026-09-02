# Usage Guide

The tool surface is two scripts, both run from the repository root, used
in this order: `scripts/build_site.py` (draft a subject from a PDF with
`--pdf`, and either way validate + build it) and `scripts/find_portraits.py`
(attach verified Wikidata/Commons photos, once a subject has data).

## 1. Drafting a new subject with `--pdf`

```bash
pip install -r extraction/requirements.txt
python3 scripts/build_site.py <slug> --pdf data/<paper>.pdf [options]
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

### What it does, in order

1. **Reads** the PDF with `pypdf`, inserting a `[pdf page N]` marker at
   each page break so the model can cite real page numbers.
2. **Builds the prompt** by embedding `schema/*.schema.json` verbatim —
   the model sees the exact field names, enums, and provenance/terseness
   requirements, not a paraphrase, so the prompt can't drift out of sync
   with the data model.
3. **Asks the model** for a single JSON object with five keys (`subject`,
   `entities`, `events`, `relations`, `sources`). If a reply is cut off
   at the `--max-tokens` limit before finishing, it automatically sends
   the partial reply back and asks the model to continue exactly where
   it left off, repeating until the reply finishes or it's asked to
   continue 8 times in a row (at which point it stops and tells you to
   try a smaller `--max-chars` or a larger `--max-tokens`).
4. **Writes** `subjects/<slug>/`, forcing the source's `file` field to
   point at the actual PDF (copied into `data/<slug>.pdf` if it wasn't
   already under `data/`) rather than trusting whatever path the model
   guessed:

   | File | Contents |
   |---|---|
   | `subject.json` | Identity: slug, name, one-line summary. |
   | `entities.json` | People, places, organizations, artifacts mentioned. |
   | `events.json` | Dated occurrences, each cited to a source page — the timeline's raw material. |
   | `relations.json` | Durable connections between entities (`worked_at`, `invented`, ...). |
   | `sources.json` | The source paper(s), for citation. |

   The PDF copied into `data/<slug>.pdf` isn't itself committed — see
   `data/README.md`.

5. **Validates and builds** — the exact same `validate_subject()`/`build()`
   used for a hand-written subject (see below), no separate code path — a
   validation failure is reported exactly like a hand-written subject's
   would be, pointing at `subjects/<slug>/*.json` to fix.

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
```

Everything in this section assumes `subjects/<slug>/` already has data —
either just drafted (step 1) or written by hand. For the shipped example
that's `suntola` (i.e. `subjects/suntola/`), which needs no API key to
build.

### What a build does, in order

1. **Loads** `subjects/<slug>/{subject,entities,events,relations,sources}.json`.
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
   just that the ids resolve.
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
Validation failed for subject 'suntola':
  relation suntola_worked_at_instrumentarium: 'worked_at' expects source entity_type person, but 'instrumentarium' is 'organization'
  relation suntola_worked_at_instrumentarium: 'worked_at' expects target entity_type organization, but 'tuomo_suntola' is 'person'
```

The fix is to swap `source` and `target` — never to change the relation's
`type` to something that happens to accept the wrong direction just to
silence the error.

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
