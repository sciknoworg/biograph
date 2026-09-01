# Usage Guide: Building & Validating a Subject

The tool surface is two scripts, both run from the repository root:
`scripts/build_site.py` (validate and build a subject that already has
data — covered on this page) and `scripts/extract_subject.py` (draft a
*new* subject from a PDF using an LLM — covered below, and in full in
[Adding a new subject](adding-a-subject.md)).

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

## Drafting a new subject with `extract_subject.py`

Everything above assumes `subjects/<slug>/` already has data. To draft
one from a PDF instead of writing it by hand, see
[Adding a new subject](adding-a-subject.md) for the full walkthrough —
this section is the command/flag reference.

```bash
pip install -r extraction/requirements.txt
python3 scripts/extract_subject.py data/<paper>.pdf <slug> [options]
```

| Flag | Default | What it does |
|---|---|---|
| `--name` | slug, title-cased | Display name for `subject.json`. |
| `--model` | *(prompted)* | Model name, exactly as your provider lists it. `BIOGRAPH_MODEL` skips the prompt. No default is hardcoded — model lineups move too fast for a baked-in one to stay current. |
| `--base-url` | *(prompted)* | Provider's API base URL. The prompt offers OpenAI and OpenRouter by name, or "Other" to paste any OpenAI-compatible URL (e.g. KISSKI). `BIOGRAPH_BASE_URL` skips the prompt. |
| `--api-key` | *(prompted, hidden input)* | `BIOGRAPH_API_KEY` or `OPENAI_API_KEY` also skip the prompt. |
| `--max-chars` | `180000` | Truncates the extracted PDF text beyond this many characters, for very long sources. |
| `--max-tokens` | `32000` | Reply budget per request. If the model hits this mid-subject, the script automatically asks it to continue and stitches the pieces together (up to 8 rounds) rather than failing — see below. |
| `--no-build` | off | Write and validate `subjects/<slug>/`, but skip building `dist/<slug>.html`. |

### What it does, in order

1. **Reads** the PDF with `pypdf`, inserting a `[pdf page N]` marker at
   each page break so the model can cite real page numbers.
2. **Builds the prompt** by embedding `schema/*.schema.json` verbatim —
   the model sees the exact field names and enums, not a paraphrase, so
   the prompt can't drift out of sync with the data model.
3. **Asks the model** for a single JSON object with five keys (`subject`,
   `entities`, `events`, `relations`, `sources`). If a reply is cut off
   at the `--max-tokens` limit before finishing, it automatically sends
   the partial reply back and asks the model to continue exactly where
   it left off, repeating until the reply finishes or it's asked to
   continue 8 times in a row (at which point it stops and tells you to
   try a smaller `--max-chars` or a larger `--max-tokens`).
4. **Writes** `subjects/<slug>/{subject,entities,events,relations,sources}.json`,
   forcing the source's `file` field to point at the actual PDF (copied
   into `data/<slug>.pdf` if it wasn't already under `data/`) rather than
   trusting whatever path the model guessed.
5. **Validates and builds**, reusing `build_site.validate_subject()` and
   `build_site.build()` directly rather than duplicating that logic — a
   validation failure is reported exactly like a hand-written subject's
   would be (see above), pointing at `subjects/<slug>/*.json` to fix.

### Treat the result as a first-pass draft

Same caveat as manual extraction, because it's doing the same job: an
LLM can misdate an event, mis-cite a page, or miss a fact the source
states in passing. Validation catches *structural* problems (a broken
reference, a wrong enum value) — it can't catch a wrong date or a
misattributed quote. Review the draft against the PDF before trusting
it; see [Sanity-checking a build](#sanity-checking-a-build) above and
[Data Accuracy & Provenance](data-accuracy.md).
