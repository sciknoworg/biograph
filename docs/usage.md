# Usage Guide: Building & Validating a Subject

The entire tool surface is one script, `scripts/build_site.py`, run from
the repository root.

## Command reference

```bash
python3 scripts/build_site.py <slug>     # build one subject
python3 scripts/build_site.py --all      # build every subject under subjects/
```

`<slug>` is the directory name under `subjects/` — for the shipped
example, that's `suntola` (i.e. `subjects/suntola/`).

## What a build does, in order

1. **Loads** `subjects/<slug>/{subject,entities,events,relations,sources}.json`.
2. **Validates** each file against its schema in `schema/` (entity, event,
   relation, source — dates are validated inline via `$ref`), using
   [`jsonschema`](https://pypi.org/project/jsonschema/)'s
   `Draft202012Validator`.
3. **Checks referential integrity** — every event's `participants[].entity_id`
   and `location`, every relation's `source`/`target`/`event_id`, and
   every `sources[].source_id` (on both events and relations) must point
   to something that actually exists in this subject's files.
4. **Sorts** events by `date.sort_start` (ties broken by `sort_end`).
5. **Inlines** the subject's data — plus the shared, pre-converted world
   map GeoJSON — into `frontend/template.html`, producing
   `dist/<slug>.html`.

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

## Example: a clean build

```console
$ python3 scripts/build_site.py suntola
Building 'suntola'...
  67 entities, 42 events, 50 relations
  -> dist/suntola.html
```

## Example: a referential-integrity failure and its fix

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

## Building without `jsonschema` installed

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

## Sanity-checking a build

After a successful build, open `dist/<slug>.html` and look for:

- Nodes with **no connections at all** — usually means a relation is
  missing.
- Events clustered at an **implausible date** — usually a
  `sort_start`/`sort_end` typo.
- Any name rendering as **`undefined`** — a broken id reference that
  somehow passed validation (e.g. a stale copy of a schema file).

## Next: adding your own subject

This page covers building an *existing* subject's data. To extract a new
biography from a source paper and turn it into a new `subjects/<slug>/`
folder, see [Adding a new subject](adding-a-subject.md).
