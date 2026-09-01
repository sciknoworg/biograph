# Extending & Contributing

## Extending the controlled vocabularies

`event_type` and relation `type` are closed enums **on purpose** — that's
what keeps extraction consistent across subjects (see
[Data model reference](data-model.md)). To add a value:

1. Edit the enum in the relevant schema file (`schema/event.schema.json`
   for `event_type`, `schema/relation.schema.json` for relation `type`).
2. Add one line documenting it to `schema/README.md`'s vocabulary list.
3. Re-run `python3 scripts/build_site.py --all` to confirm nothing else
   breaks.

Don't let free-text types accumulate across subjects instead — if
`"other"` is showing up often for a recognizable pattern, that's the
signal to add a real vocabulary value rather than keep reaching for the
catch-all.

## Adding a second (and third...) subject

See [Adding a new subject](adding-a-subject.md) for the full, step-by-step
extraction process. The repository's second planned subject,
`subjects/aleskovskii/` (from the Malygin 2015 paper on V. B. Aleskovskii,
the Soviet-side counterpart to Suntola's independent discovery), hasn't
been started yet — it's the natural next example to work through the
process on.

## Cross-subject bridges

Once two or more subjects exist, `subjects/_bridges/<a>-<b>.json` connects
them — an array of relation objects using the same shape as
`relation.schema.json`, with entity ids qualified as `"<slug>:<entity_id>"`.
See [Adding a new subject § 8](adding-a-subject.md#8-once-both-subjects-exist-cross-subject-bridges)
for the format and a concrete example (Suntola's documented 1990 visit to
meet Aleskovskii in Leningrad).

A **combined view** that renders a bridge file's edges alongside two (or
more) subjects' own graphs doesn't exist yet in the frontend — today,
`frontend/template.html` renders exactly one subject per page. That's the
natural next frontend extension once bridge files exist to render.

## Other directions this project could grow

None of these exist yet; they're natural next steps given the current
architecture:

- **A subject index page** — a small landing page listing every built
  `dist/<slug>.html`, generated alongside `--all`.
- **Interoperability with external vocabularies** — the relation and
  event types here were built bottom-up from what two source papers
  actually say (see [Data Accuracy & Provenance](data-accuracy.md)), not
  mapped to a formal standard like CIDOC-CRM or Wikidata's property IDs.
  Since the vocabulary is closed and enumerated, adding an optional
  `wikidata_property` (or similar) field to each enum value's schema
  documentation would be a mechanical addition, not a redesign.
- **Automated re-verification** — a script that re-checks every
  `sources[].quote` against the actual source PDF text, to catch
  transcription drift over time.

## Reporting an issue or proposing a change

This is a small, file-based project — issues, corrections, and pull
requests go through the GitHub repository at
[sciknoworg/biograph](https://github.com/sciknoworg/biograph). If you spot
a factual error in the Suntola extraction specifically, the most useful
report is the entity/event/relation id plus what the source actually
says, since every claim should be traceable to a specific cited page.
