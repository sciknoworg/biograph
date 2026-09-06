# Defining a domain

This collection is not tied to any one science. What it covers is decided by a
**domain taxonomy** — a JSON file naming the fields, subfields and pioneers of
some discipline, plus a `_meta` block saying, in prose, what counts as being in
that discipline.

Point the pipeline at a different taxonomy and it collects a different science.
Nothing in the code names a field.

## Why the taxonomy carries the scope rule

Scope is judged twice, and both judgements must agree or the collection wastes
its effort:

- **Discovery** decides whose name is worth searching for.
- **Extraction** decides, having read the whole document, whether this person
  belongs in the collection at all.

If the first is chemistry and the second is materials science, every chemist
found is then rejected. So the domain statement lives in one place — the
taxonomy — and is read by both. `_meta.domain` becomes requirement 4 of the
extraction scope rules (`build_site.py --scope-domain`); `_meta.name` goes into
the prompts that grow the taxonomy and file new people into it.

The other three requirements — English, one central figure, substantial enough
to build a dated timeline — are properties of a *biographical document* and
hold for any field, so they are fixed in code.

## File shape

```json
{
  "_meta": {
    "name": "chemistry",
    "domain": "Include a person only when a historically significant part of ...
               Reject anyone whose significance lies outside that: ..."
  },
  "Organic Chemistry": {
    "Synthetic Methodology": ["Robert Burns Woodward", "Elias James Corey"],
    "Stereochemistry":       ["Jacobus Henricus van 't Hoff", "Vladimir Prelog"]
  },
  "Analytical Chemistry": {
    "Chromatography and Separation Science": ["Mikhail Tsvet", "Archer John Porter Martin"]
  }
}
```

Two levels below `_meta`: **field → subfield → names**. Keys beginning with `_`
are metadata and are never treated as fields. A taxonomy with no `_meta` falls
back to the built-in default domain (materials science), which is what the
earliest subjects in this collection were judged against.

## Writing `_meta.domain`

This one string does the most work in the whole system. It is handed verbatim to
a model as the test for whether a person belongs. It should:

1. **State positively** what a person's significant contribution must be *to*,
   naming concrete areas rather than gesturing at the field. "Chemical synthesis,
   reaction mechanisms, catalysis, analytical separation…" beats "chemistry".
2. **Then reject explicitly.** Write `Reject anyone whose significance lies
   outside that:` and list the neighbouring fields most easily confused with
   yours. This half matters more than the first: without it, anyone adjacent
   drifts in.
3. **Address a judge, not a reader.** It is an instruction, not a description.
4. **Draw the boundary you actually want.** A chemistry taxonomy that excludes
   "materials science without a central chemical contribution" will pass over
   metallurgists; one that doesn't will collect them. Neither is wrong — but
   decide, because this sentence is the decision.

Judgement is made from *what the document says the person's work was*, never
from what the model happens to know about the name.

## Choosing fields and names

- **8–12 fields, 3–6 subfields each, 2–3 names per subfield** is a good seed. It
  does not need to be complete: the pipeline surveys for new subfields itself
  once the existing names are exhausted, and one collection grew from 49 to 500
  subfields unaided.
- **Every name must be someone a biographical or retrospective essay plausibly
  exists about** — a Nobel laureate, a named-reaction originator, a founder of a
  discipline. The pipeline can only find what has actually been written. A
  significant scientist nobody has written a retrospective about will yield
  nothing, however deserving.
- **Overlap between domains is fine.** People are merged by identity, not by
  taxonomy, so a physical chemist reachable from two taxonomies produces one
  subject with two source documents, not two subjects.

## Generator prompt

A taxonomy of this shape is tedious to write by hand and well suited to a
language model. The template below is the reusable form: fill the three
placeholders, paste it into any capable model, and save the result as
`<domain>_taxonomy.json`. Everything outside the placeholders is invariant and
should not be edited — those rules are what make the output loadable and the
scope statement usable.

````text
Produce a JSON taxonomy of the history of {{FIELD}}, for a project that builds
biographical knowledge graphs of individual scientists and engineers from
retrospective essays, obituaries, memorial articles and historical papers
written about them.

Output ONLY the JSON object. No markdown fences, no commentary.

Exact shape -- a "_meta" block, then two levels of nesting:

{
  "_meta": {
    "name": "{{SHORT_NAME}}",
    "domain": "<one paragraph, written as instructions to a judge>"
  },
  "<Field>": {
    "<Subfield>": ["Pioneer One", "Pioneer Two", "Pioneer Three"]
  }
}

Rules for "_meta.domain" -- the single most important string in the file. It is
given verbatim to a model as the test for whether a document about a person
belongs in this collection.
  - Open by stating positively what a historically significant part of the
    person's contribution must be TO, naming concrete areas of {{FIELD}} rather
    than gesturing at the field as a whole.
  - Then write "Reject anyone whose significance lies outside that:" and list the
    neighbouring fields most easily confused with this one -- at minimum
    {{NEIGHBOURS_TO_EXCLUDE}}, plus any others you judge necessary. This half
    matters more than the first: without it, everyone adjacent drifts in.
  - Address a judge, not a reader. It is an instruction, not a description.
  - Be decisive. Every vague clause admits noise for the lifetime of the
    collection.

Rules for the fields and subfields:
  - 8 to 12 top-level fields, spanning the history of {{FIELD}} from its origins
    to the present.
  - 3 to 6 subfields under each. Each must be a genuinely distinct,
    well-established area, not a rewording of another subfield.
  - 2 to 3 names per subfield. Every name must be a real, historically notable,
    prolific contributor to THAT subfield -- someone a biographical or
    retrospective essay plausibly exists about: a major prize winner, the
    originator of a named method or device, the founder of a discipline or
    school. Do not include minor figures. Do not invent people.
  - Prefer people with substantial published biographical literature, since this
    collection can only find what has actually been written about someone.
  - Spell each name as it most commonly appears in the literature.
  - Do not repeat a person across subfields; place them where their reputation
    principally lies.
````

Three placeholders:

| Placeholder | What goes in it | Example |
|---|---|---|
| `{{FIELD}}` | The discipline, as you would say it aloud | `mechanical engineering, including its historical roots in machines, engines and manufacture` |
| `{{SHORT_NAME}}` | Lowercase name for prompts and log lines | `mechanical engineering` |
| `{{NEIGHBOURS_TO_EXCLUDE}}` | The confusable neighbours, as a hint | `physics without an engineering contribution; materials science; civil and structural engineering; electrical engineering; mathematics` |

Check the result before running it — a malformed file is refused at load, but a
thin one merely wastes a run:

```
python -c "import json;d=json.load(open('mechanical_taxonomy.json',encoding='utf-8'));f={k:v for k,v in d.items() if not k.startswith('_')};print('fields',len(f),'subfields',sum(len(v) for v in f.values()),'names',sum(len(n) for v in f.values() for n in v.values()),'domain chars',len(d.get('_meta',{}).get('domain','')))"
```

Expect roughly 8-12 fields, 30-60 subfields, 100-180 names, and a domain string
of 800 characters or more. A domain much shorter than that has almost certainly
skipped the reject-explicitly half.

## Running it

Each domain keeps its own taxonomy and its own state file; subjects from all of
them accumulate in the same `subjects/` directory, since the point is one graph.

Domains are run **one at a time**. Beyond the taxonomy and state, the working
files — candidate lists, staged documents, the scope-verdict scratch file — are
shared and fixed, so two simultaneous runs would read each other's intermediate
results.

## A note on what this cannot fix

A domain is only as collectable as its retrospective literature is reachable.
Where the biographies of a field's pioneers sit behind paywalls, the taxonomy
will look healthy and the collection will stay empty — and the gap says
something about the field's publishing culture rather than about its history.
